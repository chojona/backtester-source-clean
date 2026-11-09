"""Read the verified stores with bounded, parameterized AMT scopes."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from terminal.chart_window import series_identity
from terminal.continuous import identity
from terminal.data import DataError, VERSION as RELEASE_VERSION

from .model import (Bar, MAX_OBSERVATIONS, MINUTE, VERSION, elapsed_minutes,
                    local_stamp, price_tick, session_bounds, trading_date)

Scope = Literal['session', 'prior_session', 'range', 'week', 'prior_week', 'month', 'prior_month']


def month_start(day):
    return day.replace(day=1)


def scope_dates(scope, session, start, end):
    if scope == 'range':
        if start is None or end is None or not 0 <= (end - start).days < 31:
            raise DataError('Range needs ordered start and end dates, at most 31 calendar dates inclusive')
        return start, end
    if start is not None or end is not None:
        raise DataError('start and end apply only to range scope')
    if scope in ('week', 'prior_week'):
        monday = session - timedelta(days=session.weekday())
        return (monday, session) if scope == 'week' else (monday - timedelta(days=7), monday - timedelta(days=1))
    if scope in ('month', 'prior_month'):
        first = month_start(session)
        previous_end = first - timedelta(days=1)
        return (first, session) if scope == 'month' else (month_start(previous_end), previous_end)
    return session, session


@dataclass
class Sample:
    day: date
    bars: list[Bar]
    coverage: dict
    lineage: dict | None
    ordinary_minutes: int


class ObservationSource:
    def __init__(self, source, selected, contract, display, as_of, replay):
        self.source, self.selected = source, selected
        self.contract, self.display = contract, display
        self.continuous = selected is not source
        self.adjusted = contract == 'NQ1! Adjusted'
        if replay and as_of is None:
            raise DataError('Replay requires an explicit as_of cutoff')
        if self.adjusted and (as_of is not None or replay):
            raise DataError('Retrospective adjusted prices are unavailable in replay/as_of')
        if as_of is not None and (as_of.utcoffset() is None or not 1900 <= as_of.year <= 2200):
            raise DataError('as_of requires a timezone and a supported date')
        self.as_of = as_of.astimezone(timezone.utc) if as_of else None
        self.series = series_identity(source, selected)

    def query(self, sql, params):
        if self.continuous:
            return self.selected.query(self.contract, sql, params)
        return self.source.query(sql, params)

    def metadata(self, first, last):
        table = 'sessions' if self.continuous else 'eligibility'
        rows = self.query(f'''SELECT trading_date, selected_contract, eligible_full_session,
            ordinary_candidate_minutes, prior_candidate_date, calendar_status FROM {table}
            WHERE trading_date BETWEEN ? AND ? ORDER BY trading_date LIMIT 32''',
            [first.isoformat(), last.isoformat()])
        if len(rows) > 31 or len({row['trading_date'] for row in rows}) != len(rows):
            raise DataError('Invalid AMT session manifest membership')
        return rows

    def prior(self, session):
        if self.as_of and session > trading_date(self.as_of):
            return None
        rows = self.metadata(session, session)
        previous = rows[0]['prior_candidate_date'] if rows else None
        prior = date.fromisoformat(previous) if previous else None
        if prior is not None and prior >= session:
            raise DataError('AMT prior candidate must precede the selected trading date')
        return prior

    def gaps(self, first, last, cutoff):
        if not self.continuous or first > last:
            return {'intervals': [], 'interval_count': 0, 'truncated': False, 'available': self.continuous}
        intervals, count, rolls = self.selected.chart_metadata(self.contract, first.isoformat(), last.isoformat(),
                                                                cutoff, self.as_of is not None)
        # Retrospective roll overlap evidence belongs in the continuous quality API.
        fields = ('roll_id', 'trading_date', 'decision_utc', 'old_contract', 'new_contract', 'policy_version')
        return {'intervals': intervals, 'interval_count': count, 'truncated': count > len(intervals),
                'available': True, 'interval_basis': 'reviewed Globex intervals',
                'rolls': [{key: row[key] for key in fields} for row in rolls],
                'unresolved_roll_ids': [row['roll_id'] for row in rolls if not self.as_of
                                        and row['roll_id'] in self.selected.quality['unresolved_rolls']]}

    def load(self, first, last, cutoff, starts_at=None):
        last_elapsed = min(last, trading_date(cutoff))
        if first > last_elapsed:
            return []
        metadata = self.metadata(first, last_elapsed)
        eligible = [row['trading_date'] for row in metadata if row['eligible_full_session']
                    and (self.continuous or row['selected_contract'] == self.contract)]
        by_day = defaultdict(list)
        if eligible:
            lineage = ('source_contract, segment_id, roll_id, adjustment_offset, adjustment_status, '
                       + ('adjustment_block_id' if self.adjusted else 'NULL AS adjustment_block_id')
                       if self.continuous else 'contract AS source_contract, NULL AS segment_id, NULL AS roll_id, '
                       '0 AS adjustment_offset, NULL AS adjustment_block_id, \'unadjusted\' AS adjustment_status')
            predicate = 'contract=selected_contract' if self.continuous else 'contract=? AND selected_contract=?'
            params = [] if self.continuous else [self.contract, self.contract]
            rows = self.query(f'''SELECT trading_date, timestamp_utc, open, high, low, close, volume, {lineage}
                FROM bars WHERE trading_date BETWEEN ? AND ? AND trading_date=ANY(?)
                AND CAST(timestamp_utc AS TIMESTAMPTZ)<=? AND eligible_full_session IS TRUE
                AND boundary_unresolved IS FALSE AND {predicate}
                ORDER BY trading_date,timestamp_utc LIMIT ?''',
                [min(eligible), max(eligible), eligible, cutoff - MINUTE, *params, MAX_OBSERVATIONS + 1])
            if len(rows) > MAX_OBSERVATIONS:
                raise DataError('AMT observation limit exceeded')
            for row in rows:
                by_day[row['trading_date']].append(row)
        return [self.sample(meta, by_day[meta['trading_date']], cutoff, starts_at) for meta in metadata
                if session_bounds(date.fromisoformat(meta['trading_date']), self.display)[0] <= cutoff]

    def sample(self, meta, rows, cutoff, starts_at):
        day = date.fromisoformat(meta['trading_date'])
        start, end = session_bounds(day, self.display)
        globex_start, globex_end = session_bounds(day, 'Globex')
        ordinary = meta['ordinary_candidate_minutes']
        regime_known = ordinary in (1365, 1380)
        recess = (local_stamp(day, 16, 15), local_stamp(day, 16, 30))
        window_start = start
        if starts_at is not None and starts_at > start:
            # An off-minute anchor starts with the next minute's observation.
            window_start = starts_at.replace(second=0, microsecond=0)
            if starts_at > window_start:
                window_start += MINUTE
        expected = elapsed_minutes(window_start, end, cutoff)
        if self.display == 'Globex' and ordinary == 1365:
            expected -= elapsed_minutes(max(window_start, recess[0]), recess[1], cutoff)
        admitted = meta['eligible_full_session'] and (self.continuous or meta['selected_contract'] == self.contract)
        fields = ('source_contract', 'segment_id', 'roll_id', 'adjustment_offset', 'adjustment_status', 'adjustment_block_id')
        bars, lineage, previous = [], None, None
        for row in rows:
            stamp = row['timestamp_utc'].astimezone(timezone.utc)
            if (not globex_start <= stamp < globex_end or stamp + MINUTE > cutoff
                    or stamp.second or stamp.microsecond or previous is not None and previous >= stamp
                    or row['source_contract'] != meta['selected_contract']
                    or ordinary == 1365 and recess[0] <= stamp < recess[1]):
                raise DataError('Invalid AMT minute ordering, calendar or source identity')
            previous = stamp
            this_lineage = {key: row[key] for key in fields}
            if lineage is not None and lineage != this_lineage:
                raise DataError('AMT session crosses source coordinates')
            lineage = this_lineage
            low, high, close, open_ = (price_tick(row[key]) for key in ('low', 'high', 'close', 'open'))
            volume = row['volume']
            if not low <= min(close, open_) <= max(close, open_) <= high or type(volume) is not int or volume < 0:
                raise DataError('Invalid AMT source OHLCV')
            if window_start <= stamp < end:
                bars.append(Bar(stamp, low, high, close, volume))
        if cutoff >= globex_end and admitted and len(rows) != ordinary:
            raise DataError('AMT manifest and observed session counts disagree')
        complete = admitted and regime_known and cutoff >= end and len(bars) == expected > 0
        status = ('complete_observed_grid' if complete else 'incomplete' if cutoff >= end
                  else 'developing')
        # Do not disclose a retrospective exclusion decision for an active prefix.
        if not admitted and cutoff >= globex_end:
            status = 'excluded'
        coverage = {'trading_date': day.isoformat(), 'display_start': start, 'display_end': end,
                    'scope_start': min(end, window_start),
                    'elapsed_expected_minutes': expected if regime_known else None,
                    'observed_minutes': len(bars), 'status': status, 'calendar_status': meta['calendar_status'],
                    'complete': complete, 'developing': cutoff < end}
        return Sample(day, bars, coverage, lineage if bars else None, ordinary)

    def coordinate(self, samples):
        lineages = [sample.lineage for sample in samples if sample.lineage]
        if not lineages:
            return None
        if self.adjusted:
            blocks = {row['adjustment_block_id'] for row in lineages}
            if len(blocks) != 1 or None in blocks:
                raise DataError('AMT cannot aggregate across independent adjustment blocks')
            return {'mode': 'adjusted', 'adjustment_block_id': next(iter(blocks))}
        keys = {(row['source_contract'], row['segment_id']) for row in lineages}
        if len(keys) != 1:
            raise DataError('AMT cannot aggregate across Raw contracts or roll segments')
        contract, segment = next(iter(keys))
        return {'mode': 'raw' if self.continuous else 'exact', 'source_contract': contract, 'segment_id': segment}

    def envelope(self, scope, first, last, cutoff, samples, options):
        coordinate = self.coordinate(samples)
        files = (['adjusted.parquet' if self.adjusted else 'raw.parquet', 'session-eligibility.parquet',
                  'selected-gap-intervals.parquet', 'rollover-manifest.json', 'adjustment-manifest.json']
                 if self.continuous else ['research.parquet', 'session-eligibility.parquet'])
        hashes = self.selected.manifest['outputs'] if self.continuous else self.source.hashes
        return {
            'contract': self.contract, 'display': self.display, 'scope': scope,
            'start': first, 'end': last, 'methodology_version': VERSION, 'options': options,
            'request_id': identity([VERSION, self.series, self.contract, self.display, scope,
                                    first.isoformat(), last.isoformat(), cutoff.isoformat(),
                                    self.as_of is not None, options]),
            'source': {'series': self.series, 'release_version': RELEASE_VERSION, 'granularity': '1m',
                       'verified': True, 'files': {key: hashes[key] for key in files}, 'coordinate': coordinate,
                       'strict_eligible': False, 'execution_eligible': False, 'retrospective_prices': self.adjusted,
                       'admission': 'sealed retrospective full-session eligibility'},
            'cutoff': {'as_of': cutoff, 'basis': 'observation_close', 'publication_verified': False,
                       'explicit': self.as_of is not None},
            'coverage': {'sessions': [dict(sample.coverage, lineage=sample.lineage) for sample in samples],
                         'contributing_sessions': [sample.day.isoformat() for sample in samples if sample.bars],
                         'observed_minutes': sum(len(sample.bars) for sample in samples),
                         'status': ('no_declared_sessions' if not samples else 'observed'
                                    if any(sample.bars for sample in samples) else 'no_admitted_observations'),
                         'all_declared_sessions_complete': bool(samples) and all(s.coverage['complete'] for s in samples),
                         'quality': self.gaps(first, min(last, trading_date(cutoff)), cutoff)},
        }
