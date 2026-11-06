"""Read-only queries against the sealed NQ OHLCV research v2 release."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

VERSION = 'nq-ohlcv-research-v2.0.0'
FRAMES = {'1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60, 'daily': 1440}
ET = ZoneInfo('America/New_York')


class DataError(ValueError):
    pass


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


class ResearchStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        seal = json.loads((self.root / 'SUCCESS.json').read_text())
        if seal['version'] != VERSION:
            raise DataError(f'Expected sealed {VERSION} release')
        self.hashes = {}
        for name in ('research.parquet', 'session-eligibility.parquet',
                     'selected-observations-with-flags.parquet', 'contract-rolls.parquet',
                     'summary.json', 'input-bindings.json'):
            expected = seal['outputs'][name]
            if digest(self.root / name) != expected:
                raise DataError(f'Source hash mismatch: {name}')
            self.hashes[name] = expected
        self.summary = json.loads((self.root / 'summary.json').read_text())
        if self.summary['version'] != VERSION:
            raise DataError('Summary version mismatch')
        # Only paths and manifest metadata are retained; OHLCV stays in Parquet.

    def query(self, sql: str, params=()):
        with duckdb.connect(':memory:') as con:
            con.execute("SET TimeZone='UTC'")
            for view, name in [('bars', 'research.parquet'), ('eligibility', 'session-eligibility.parquet'),
                               ('context', 'selected-observations-with-flags.parquet'), ('rolls', 'contract-rolls.parquet')]:
                path = str(self.root / name).replace("'", "''")
                con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet('{path}')")
            result = con.execute(sql, params)
            names = [d[0] for d in result.description]
            return [dict(zip(names, row)) for row in result.fetchall()]

    def provenance(self):
        return {'version': VERSION, 'verified': True, 'hashes': self.hashes,
                'summary': self.summary, 'strict_eligible': False,
                'availability': 'Retrospective QC eligibility; historical publication times are unproven.',
                'indicators': {'vwap': 'Cumulative HLC3 × volume / volume, reset at session open; OHLCV approximation.',
                               'opening_range': '09:30–10:00 America/New_York; developing until 10:00.',
                               'realized_volatility': '100 × sqrt(sum of squared consecutive 1m log returns); unannualized; gaps excluded.',
                               'aggregation': 'Session-open anchored; only observed bars closed by cutoff; partial buckets labeled.'}}

    def contracts(self):
        return self.query('''SELECT selected_contract AS contract, min(trading_date) AS first_session,
          max(trading_date) AS last_session, count(*) AS sessions FROM eligibility
          WHERE eligible_full_session IS TRUE GROUP BY selected_contract ORDER BY last_session DESC''')

    def sessions(self, contract: str | None, start: date | None, end: date | None, limit: int, offset: int):
        return self.query('''SELECT trading_date, selected_contract AS contract, ordinary_candidate_minutes AS minutes,
          prior_candidate_date, calendar_status, certified_complete, roll, warmup_14_ready
          FROM eligibility WHERE eligible_full_session IS TRUE
          AND (? IS NULL OR selected_contract = ?) AND (? IS NULL OR trading_date >= ?)
          AND (? IS NULL OR trading_date <= ?) ORDER BY trading_date DESC LIMIT ? OFFSET ?''',
          [contract, contract, str(start) if start else None, str(start) if start else None,
           str(end) if end else None, str(end) if end else None, limit, offset])

    def snapshot(self, contract: str, session: date, timeframe: str = '1m', cursor: int | None = None,
                 as_of: datetime | None = None, offset: int = 0, limit: int = 50):
        if timeframe not in FRAMES:
            raise DataError('Unsupported timeframe')
        if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
            raise DataError('as_of must include a timezone')
        meta = self.query('''SELECT * FROM eligibility WHERE trading_date=? AND selected_contract=?
                             AND eligible_full_session IS TRUE''', [session.isoformat(), contract])
        if len(meta) != 1:
            raise DataError('No eligible full session for this exact contract and date')
        bounds = self.query('''SELECT count(*) AS total, min(timestamp_utc) AS start, max(timestamp_utc) AS last
           FROM bars WHERE trading_date=? AND contract=? AND selected_contract=? AND eligible_full_session IS TRUE''',
           [session.isoformat(), contract, contract])[0]
        total = bounds['total']
        if total != meta[0]['ordinary_candidate_minutes']:
            raise DataError('Manifest and observed session counts disagree')
        if cursor is not None and not 0 <= cursor <= total:
            raise DataError('cursor outside session')
        rows = self.query('''SELECT timestamp_utc, open, high, low, close, volume FROM bars
          WHERE trading_date=? AND contract=? AND selected_contract=? AND eligible_full_session IS TRUE
          AND (? IS NULL OR CAST(timestamp_utc AS TIMESTAMPTZ) + INTERVAL 1 MINUTE <= ?)
          ORDER BY timestamp_utc LIMIT ?''', [session.isoformat(), contract, contract, as_of, as_of,
                                             cursor if cursor is not None else total])
        if len({r['timestamp_utc'] for r in rows}) != len(rows):
            raise DataError('Duplicate observed timestamps')
        cutoff = rows[-1]['timestamp_utc'] + timedelta(minutes=1) if rows else min(as_of, bounds['start']) if as_of else bounds['start']
        previous = self.query('''SELECT min(low) AS low, max(high) AS high, count(*) AS n
          FROM context WHERE trading_date=? AND contract=? AND selected_contract=?
          AND full_grid_observed IS TRUE AND boundary_unresolved IS FALSE
          AND CAST(timestamp_utc AS TIMESTAMPTZ) + INTERVAL 1 MINUTE <= ?''',
          [meta[0]['prior_candidate_date'], contract, contract, cutoff])[0]
        previous_meta = self.query('''SELECT ordinary_candidate_minutes FROM eligibility
          WHERE trading_date=? AND selected_contract=? AND full_grid_observed IS TRUE''',
          [meta[0]['prior_candidate_date'], contract])
        previous = ({'high': previous['high'], 'low': previous['low'], 'date': meta[0]['prior_candidate_date']}
                    if previous_meta and previous['n'] == previous_meta[0]['ordinary_candidate_minutes']
                    else {'high': None, 'low': None, 'date': None})
        pv = vol = rv = 0.0
        or_high = or_low = None
        buckets = {}
        prior = None
        anchor = int(bounds['start'].timestamp())
        span = FRAMES[timeframe] * 60
        for r in rows:
            stamp = r['timestamp_utc']
            t = int(stamp.timestamp())
            if prior and (stamp - prior['timestamp_utc']).total_seconds() == 60:
                rv += math.log(r['close'] / prior['close']) ** 2
            prior = r
            pv += ((r['high'] + r['low'] + r['close']) / 3) * r['volume']
            vol += r['volume']
            local = stamp.astimezone(ET)
            if local.date() == session and (9, 30) <= (local.hour, local.minute) < (10, 0):
                or_high = max(or_high, r['high']) if or_high is not None else r['high']
                or_low = min(or_low, r['low']) if or_low is not None else r['low']
            bucket = anchor + ((t - anchor) // span) * span
            if bucket not in buckets:
                buckets[bucket] = {'time': bucket, 'open': r['open'], 'high': r['high'], 'low': r['low'],
                                   'volume': 0, 'source_count': 0}
            b = buckets[bucket]
            b.update(high=max(b['high'], r['high']), low=min(b['low'], r['low']), close=r['close'],
                     volume=b['volume'] + r['volume'], source_count=b['source_count'] + 1,
                     vwap=pv / vol if vol else None, or_high=or_high, or_low=or_low,
                     available_at=t + 60)
        candles = list(buckets.values())
        for b in candles:
            # A final short session bucket is complete when the session is fully observed.
            b['partial'] = b['time'] + span > cutoff.timestamp() and len(rows) < total
        stats = {'open': rows[0]['open'] if rows else None,
                 'high': max((r['high'] for r in rows), default=None),
                 'low': min((r['low'] for r in rows), default=None),
                 'close': rows[-1]['close'] if rows else None,
                 'volume': int(vol), 'vwap': pv / vol if vol else None,
                 'realized_volatility': math.sqrt(rv) * 100, 'or_high': or_high, 'or_low': or_low,
                 'or_complete': cutoff.astimezone(ET) >= datetime.combine(session, datetime.min.time(), ET).replace(hour=10),
                 'or_range': or_high - or_low if or_high is not None else None}
        stats['range'] = stats['high'] - stats['low'] if rows else None
        stats['vwap_deviation'] = stats['close'] - stats['vwap'] if rows and vol else None
        return {'contract': contract, 'session': session.isoformat(), 'timeframe': timeframe,
                'cursor': len(rows), 'total_minutes': total, 'as_of': cutoff.isoformat(),
                'session_start': bounds['start'].isoformat(), 'session_end': (bounds['last'] + timedelta(minutes=1)).isoformat(),
                'bars': candles, 'stats': stats, 'previous': previous,
                'explorer': {'rows': candles[offset:offset + limit], 'total': len(candles), 'offset': offset, 'limit': limit},
                'eligibility': {'eligible_full_session': True, 'strict_eligible': False,
                                'calendar_status': meta[0]['calendar_status'], 'roll': meta[0]['roll'],
                                'warmup_14_ready': meta[0]['warmup_14_ready']}}
