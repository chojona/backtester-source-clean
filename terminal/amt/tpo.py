from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from string import ascii_letters

from terminal.data import DataError

from .model import MINUTE, TICK_SIZE, elapsed_minutes, session_bounds
from .profile import price_span, row_bounds, row_index, value_area


def initial_balance(sample, cutoff, minutes):
    start, _ = session_bounds(sample.day, 'RTH')
    end = start + minutes * MINUTE
    elapsed = elapsed_minutes(start, end, cutoff)
    bars = [bar for bar in sample.bars if start <= bar.time < end and bar.time + MINUTE <= cutoff]
    return {'trading_date': sample.day.isoformat(), 'start': start, 'end': end,
            'high_tick': max((bar.high for bar in bars), default=None),
            'low_tick': min((bar.low for bar in bars), default=None),
            'observed_minutes': len(bars), 'elapsed_minutes': elapsed,
            'missing_elapsed_minutes': elapsed - len(bars),
            'developing': start <= cutoff < end, 'started': cutoff >= start,
            'complete': cutoff >= end and len(bars) == minutes}


def period_letter(index):
    labels = ascii_letters[26:] + ascii_letters[:26]
    value = ''
    while index >= 0:
        index, digit = divmod(index, len(labels))
        value = labels[digit] + value
        index -= 1
    return value


def merged_ranges(ranges):
    result = []
    for low, high in sorted(ranges):
        if result and low <= result[-1][1] + 1:
            result[-1][1] = max(result[-1][1], high)
        else:
            result.append([low, high])
    return result


def make_tpo(samples, cutoff, display, width, minutes, fraction: Fraction, representation, ib_minutes):
    counts = defaultdict(int)
    periods = []
    first = last = None
    represented_ranges = 0
    step = minutes * MINUTE
    for sample in samples:
        start, end = session_bounds(sample.day, display)
        by_period = defaultdict(list)
        for bar in sample.bars:
            if start <= bar.time < end and bar.time + MINUTE <= cutoff:
                by_period[(bar.time - start) // step].append((row_index(bar.low, width), row_index(bar.high, width)))
        period_start, index = start, 0
        recess = end - 45 * MINUTE
        while period_start < min(end, cutoff):
            period_end = min(end, period_start + step)
            expected = elapsed_minutes(period_start, period_end, cutoff)
            if display == 'Globex' and sample.ordinary_minutes == 1365:
                expected -= elapsed_minutes(max(period_start, recess), min(period_end, recess + 15 * MINUTE), cutoff)
            ranges = merged_ranges(by_period[index])
            period = {'trading_date': sample.day.isoformat(), 'index': index, 'start': period_start,
                      'end': period_end, 'observed_end': min(period_end, cutoff),
                      'partial': cutoff < period_end, 'observed_minutes': len(by_period[index]),
                      'elapsed_expected_minutes': expected,
                      'missing_elapsed_minutes': expected - len(by_period[index]),
                      'occupied_rows': sum(high - low + 1 for low, high in ranges)}
            if representation != 'none':
                represented_ranges += len(ranges)
                if represented_ranges > 24000:
                    raise DataError('TPO representation exceeds 24,000 intervals; shorten the scope or omit representation')
                period['ranges'] = [[low * width, (high + 1) * width - 1] for low, high in ranges]
                if representation == 'letters':
                    period['letter'] = period_letter(index)
            for low, high in ranges:
                counts[low] += 1
                counts[high + 1] -= 1
                first = low if first is None else min(first, low)
                last = high if last is None else max(last, high)
            periods.append(period)
            period_start, index = period_end, index + 1
    running, rows = 0, {}
    if first is not None:
        for index in price_span(first, last):
            running += counts[index]
            rows[index] = running
    return {'classification': 'ohlcv_bar_range_tpo_estimate', 'tick_size': TICK_SIZE,
            'row_ticks': width, 'period_minutes': minutes, 'representation': representation,
            'rows': [{**row_bounds(i, width), 'count': count} for i, count in rows.items()],
            'periods': periods, 'value': value_area(rows, width, fraction),
            'initial_balance': [initial_balance(sample, cutoff, ib_minutes) for sample in samples]}
