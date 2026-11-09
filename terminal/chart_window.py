"""Session-aligned chart pages over the terminal's verified, read-only stores."""
from __future__ import annotations

import base64
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import hmac
import json
import re
import secrets

from .continuous import identity
from .data import DataError, ET, FRAMES, VERSION, aggregate_exact

MAX_CANDLES = 2500
_CURSOR_KEY = secrets.token_bytes(32)
_ROLL_FIELDS = ('roll_id', 'trading_date', 'decision_utc', 'old_contract', 'new_contract', 'policy_version')
_MINUTE = timedelta(minutes=1)


def series_identity(source, selected):
    continuous = selected is not source
    return {
        'release_id': identity(source.hashes),
        'build_id': selected.manifest['build_id'] if continuous else None,
        'artifact_id': identity(selected.manifest['outputs']) if continuous else None,
    }


def _encode(scope, day, direction):
    payload = json.dumps([scope, day, direction], separators=(',', ':')).encode()
    tag = hmac.digest(_CURSOR_KEY, payload, 'sha256')
    return base64.urlsafe_b64encode(tag + payload).decode().rstrip('=')


def _decode(token, scope):
    try:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', token):
            raise ValueError()
        raw = base64.urlsafe_b64decode(token + '=' * (-len(token) % 4))
        if base64.urlsafe_b64encode(raw).decode().rstrip('=') != token:
            raise ValueError()
        tag, payload = raw[:32], raw[32:]
        if not hmac.compare_digest(tag, hmac.digest(_CURSOR_KEY, payload, 'sha256')):
            raise ValueError()
        token_scope, day, direction = json.loads(payload)
        if token_scope != scope or direction not in ('older', 'newer'):
            raise ValueError()
        return date.fromisoformat(day), direction
    except (ValueError, TypeError) as exc:
        raise DataError('Invalid, stale, or mismatched chart cursor') from exc


def _select_sessions(source, selected, contract, anchor, direction, count, last_day):
    if selected is source:
        query = source.query
        table = 'eligibility'
        condition = 'selected_contract=? AND eligible_full_session IS TRUE'
        params = [contract]
        columns = 'trading_date, selected_contract, ordinary_candidate_minutes, prior_candidate_date'
    else:
        query = lambda sql, args: selected.query(contract, sql, args)
        table = 'sessions'
        condition = 'TRUE'
        params = []
        columns = 'trading_date, selected_contract, eligible_full_session, quality_flags, absent_candidate_minutes, observed_minutes'
    comparison, order = {
        'initial': ('<=', 'DESC'), 'older': ('<', 'DESC'), 'newer': ('>', 'ASC'),
    }[direction]
    return query(f'''WITH eligible AS (
        SELECT {columns} FROM {table} WHERE {condition} AND trading_date<=?
    ), edges AS (
        SELECT min(trading_date) AS first_day, max(trading_date) AS last_day FROM eligible
    )
    SELECT * FROM eligible CROSS JOIN edges WHERE trading_date {comparison} ?
    ORDER BY trading_date {order} LIMIT ?''', [*params, last_day, anchor.isoformat(), count])


def _exact_bars(source, contract, dates, frame, display, opening, deviations, cutoff):
    by_day = defaultdict(list)
    rows = source.query('''SELECT trading_date, timestamp_utc, open, high, low, close, volume
        FROM bars WHERE contract=? AND selected_contract=? AND eligible_full_session IS TRUE
        AND trading_date BETWEEN ? AND ? AND trading_date=ANY(?)
        AND CAST(timestamp_utc AS TIMESTAMPTZ) <= ?
        ORDER BY trading_date,timestamp_utc LIMIT ?''',
        [contract, contract, min(dates), max(dates), list(dates), cutoff - _MINUTE, len(dates)*1500+1])
    if len(rows) > len(dates)*1500:
        raise DataError('Chart window exceeded the source observation bound')
    for row in rows:
        by_day[row['trading_date']].append(row)
    candles, context = {}, {}
    for day, meta in dates.items():
        rows = by_day[day]
        expected = meta['ordinary_candidate_minutes']
        if cutoff.year == 9999 and len(rows) != expected:
            raise DataError('Manifest and observed session counts disagree')
        if len(rows) > expected or any(a['timestamp_utc'] >= b['timestamp_utc'] for a, b in zip(rows, rows[1:])):
            raise DataError('Invalid exact-contract session observations')
        if not rows:
            continue
        available_at = rows[-1]['timestamp_utc'] + _MINUTE
        bars, _, boundaries = aggregate_exact(
            rows, date.fromisoformat(day), rows[0]['timestamp_utc'], frame, display, opening, deviations,
            available_at, len(rows) < expected,
        )
        candles[day] = [dict(bar, trading_date=day, source_contract=contract) for bar in bars]
        context[day] = dict(
            cutoff=available_at, prior=meta['prior_candidate_date'],
            boundaries=[stamp for stamp in boundaries if stamp <= cutoff.timestamp()],
        )
    return candles, context


def _exact_context(source, contract, context, display):
    if not context:
        return {}
    days = list(context)
    priors = [row['prior'] for row in context.values()]
    cutoffs = [row['cutoff'] for row in context.values()]
    relevant = [prior for prior in priors if prior]
    result = {day: dict(boundaries=row['boundaries'], previous={'high': None, 'low': None, 'date': None})
              for day, row in context.items()}
    if not relevant:
        return result
    # Reconcile the prior session against the complete eligible grid even for RTH display.
    display_filter = ("hour(timezone('America/New_York',CAST(timestamp_utc AS TIMESTAMPTZ)))*60"
                      "+minute(timezone('America/New_York',CAST(timestamp_utc AS TIMESTAMPTZ))) BETWEEN 570 AND 959"
                      if display == 'RTH' else 'TRUE')
    rows = source.query(f'''WITH requested AS (
        SELECT unnest(?::VARCHAR[]) AS day, unnest(?::VARCHAR[]) AS prior,
               unnest(?::TIMESTAMPTZ[]) AS cutoff
    ), eligible_context AS (
        SELECT trading_date, timestamp_utc, low, high FROM context
        WHERE contract=? AND selected_contract=? AND full_grid_observed IS TRUE
        AND boundary_unresolved IS FALSE AND trading_date BETWEEN ? AND ? AND trading_date=ANY(?)
    )
    SELECT r.day, r.prior, min(c.low) FILTER (WHERE {display_filter}) AS low,
           max(c.high) FILTER (WHERE {display_filter}) AS high
    FROM requested r JOIN eligibility e ON e.trading_date=r.prior AND e.selected_contract=?
        AND e.full_grid_observed IS TRUE
    JOIN eligible_context c ON c.trading_date=r.prior
        AND CAST(c.timestamp_utc AS TIMESTAMPTZ)+INTERVAL 1 MINUTE<=r.cutoff
    GROUP BY r.day,r.prior,e.ordinary_candidate_minutes HAVING count(*)=e.ordinary_candidate_minutes''',
        [days, priors, cutoffs, contract, contract, min(relevant), max(relevant), relevant, contract])
    for row in rows:
        result[row['day']]['previous'] = {'high': row['high'], 'low': row['low'], 'date': row['prior']}
    return result


def chart_window(source, selected, contract, frame, display, opening, deviations, as_of, session,
                 cursor, sessions, start_sessions=None):
    if (session is None) == (cursor is None):
        raise DataError('Provide exactly one of session or cursor')
    if start_sessions is not None and (cursor is not None or start_sessions > sessions):
        raise DataError('start_sessions requires an initial session and cannot exceed sessions')
    adjusted = contract == 'NQ1! Adjusted'
    if as_of is not None:
        if as_of.utcoffset() is None:
            raise DataError('as_of must include a timezone')
        if adjusted:
            raise DataError('Retrospective adjusted prices are unavailable in replay/as_of')
        if not 1900 <= as_of.year <= 2200:
            raise DataError('as_of outside the supported chart dates')
        as_of = as_of.astimezone(timezone.utc)
    cutoff = as_of or datetime.max.replace(tzinfo=timezone.utc)
    local = as_of.astimezone(ET) if as_of else None
    last_day = (local.date() + timedelta(days=local.hour >= 18)).isoformat() if local else '9999-12-31'
    continuous = selected is not source
    series = series_identity(source, selected)
    cutoff_iso = as_of.isoformat() if as_of else None
    scope = identity([1, series, contract, frame, display, opening, deviations, cutoff_iso, sessions])
    anchor, direction = _decode(cursor, scope) if cursor is not None else (session, 'initial')
    count = min(start_sessions or sessions, 250 if continuous and frame == 'daily' else 20)
    candidates = _select_sessions(source, selected, contract, anchor, direction, count, last_day)
    empty_newer = not candidates and direction == 'initial' and bool(
        _select_sessions(source, selected, contract, anchor, 'newer', 1, last_day)
    )
    # Globex 1m counts are already known. Read one overshoot session at most.
    if frame == '1m' and display == 'Globex' and not as_of:
        estimated = 0
        for i, meta in enumerate(candidates):
            estimated += meta['observed_minutes' if continuous else 'ordinary_candidate_minutes']
            if estimated > MAX_CANDLES:
                candidates = candidates[:i+1]
                break
    dates = {meta['trading_date']: meta for meta in candidates}
    candles, context = {}, {}
    if dates and continuous:
        rows, _ = selected.chart_bars(
            contract, 'trading_date BETWEEN ? AND ? AND trading_date=ANY(?) AND CAST(timestamp_utc AS TIMESTAMPTZ)<=?',
            [min(dates), max(dates), list(dates), cutoff - _MINUTE], frame, display, opening, deviations,
            False, max_rows=len(dates) * (4 if frame == 'daily' else 1500),
        )
        for bar in rows:
            candles.setdefault(bar['trading_date'], []).append(bar)
    elif dates:
        candles, context = _exact_bars(source, contract, dates, frame, display, opening, deviations, cutoff)
    kept = []
    size = 0
    for day in dates:
        length = len(candles.get(day, ()))
        if length > MAX_CANDLES:
            raise DataError('A single session exceeds the chart candle bound')
        if size + length > MAX_CANDLES:
            break
        kept.append(day)
        size += length
    kept.sort()
    bars = sorted((bar for day in kept for bar in candles.get(day, ())), key=lambda bar: bar['time'])
    if any(a['time'] >= b['time'] for a, b in zip(bars, bars[1:])):
        raise DataError('Duplicate chart timestamps')
    gaps, rolls, gap_count = [], [], 0
    has_older = bool(kept and kept[0] > candidates[0]['first_day'])
    has_newer = empty_newer or bool(kept and kept[-1] < candidates[0]['last_day'])
    if kept and continuous:
        gaps, gap_count, rolls = selected.chart_metadata(contract, kept[0], kept[-1], cutoff, as_of is not None)
        if as_of:
            # Only elapsed intervals and roll decisions are visible at a cutoff.
            rolls = [{field: roll[field] for field in _ROLL_FIELDS} for roll in rolls]
            for bar in bars:
                bar.pop('eligible_full_session', None)
                end = datetime.fromisoformat(bar['trading_date']).replace(
                    hour=16 if display == 'RTH' else 17, tzinfo=ET)
                bar['partial'] = cutoff < end and bar['time'] + FRAMES[frame]*60 > cutoff.timestamp()
    return {
        'contract': contract, 'timeframe': frame, 'display': display,
        'opening_minutes': opening, 'deviations': deviations, 'as_of': cutoff_iso,
        'series': series, 'scope': scope, 'retrospective': adjusted,
        'provenance': {'version': VERSION, 'verified': True, 'strict_eligible': False,
                       'availability': 'Observation close is a replay convention. Historical publication is unproven.'},
        'session_dates': kept, 'bars': bars, 'gaps': gaps, 'rolls': rolls,
        'gap_count': gap_count, 'gaps_truncated': gap_count > len(gaps),
        'unavailable_sessions': [
            {k: dates[day][k] for k in ('trading_date', 'quality_flags', 'absent_candidate_minutes')}
            for day in kept if continuous and not as_of and not dates[day]['eligible_full_session']
        ],
        'session_context': _exact_context(source, contract, {day: context[day] for day in kept if day in context}, display),
        'has_older': has_older, 'has_newer': has_newer,
        'older_cursor': _encode(scope, kept[0], 'older') if has_older else None,
        'newer_cursor': _encode(scope, kept[-1] if kept else anchor.isoformat(), 'newer') if has_newer else None,
    }
