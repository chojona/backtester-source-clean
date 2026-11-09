from __future__ import annotations

from collections import Counter, defaultdict
from fractions import Fraction
from typing import Iterable

from terminal.data import DataError

from .model import Bar, MAX_PRICE_ROWS, TICK_SIZE

METHODS = ('hlc3', 'uniform')
VOLUME_SCALE = 1_000_000


def row_index(tick: int, width: int) -> int:
    return tick // width


def row_bounds(index: int, width: int) -> dict:
    return {'low_tick': index * width, 'high_tick': (index + 1) * width - 1}


def price_span(first: int, last: int) -> range:
    if last - first + 1 > MAX_PRICE_ROWS:
        raise DataError(f'AMT price span exceeds {MAX_PRICE_ROWS} rows; increase row_ticks')
    return range(first, last + 1)


def weights(bars: Iterable[Bar], method: str, width: int) -> dict[int, Fraction]:
    """Uniform edge contributions and interior range updates, in exact units."""
    if method not in METHODS:
        raise DataError('Unknown OHLCV volume allocation')
    # Group equal denominators before summing the exact rational shares.
    changes = defaultdict(Counter)
    edges = defaultdict(Counter)
    first = last = None
    for bar in bars:
        if not bar.volume:
            continue
        if method == 'uniform':
            low, high = row_index(bar.low, width), row_index(bar.high, width)
        else:
            low = high = row_index(bar.typical_tick, width)
        first = low if first is None else min(low, first)
        last = high if last is None else max(high, last)
        price_span(first, last)
        if low == high:
            edges[low][1] += bar.volume
        else:
            ticks = bar.high - bar.low + 1
            edges[low][ticks] += bar.volume * ((low + 1) * width - bar.low)
            edges[high][ticks] += bar.volume * (bar.high - high * width + 1)
            if high > low + 1:
                changes[low + 1][ticks] += bar.volume * width
                changes[high][ticks] -= bar.volume * width
    if first is None:
        return {}
    running = Fraction()
    result = {}
    for index in price_span(first, last):
        running += sum(Fraction(value, ticks) for ticks, value in changes.get(index, {}).items() if value)
        result[index] = running + sum(Fraction(value, ticks) for ticks, value in edges.get(index, {}).items())
    return result


def value_area(rows: dict, width: int, fraction: Fraction) -> dict | None:
    if not rows:
        return None
    low, high = min(rows), max(rows)
    poc = min(rows, key=lambda index: (-rows[index], abs(2 * index - low - high), index))
    left = right = poc
    included = rows[poc]
    total = sum(rows.values())
    target = total * fraction
    while included < target:
        if left > low and (right == high or rows.get(left - 1, 0) >= rows.get(right + 1, 0)):
            left -= 1
            included += rows.get(left, 0)
        else:
            right += 1
            included += rows.get(right, 0)
    return {'poc': row_bounds(poc, width), 'val_tick': left * width,
            'vah_tick': (right + 1) * width - 1, 'included_fraction': float(included / total)}


def nodes(rows: dict, width: int, radius: int, prominence: float) -> dict:
    result = {'hvn': [], 'lvn': []}
    if len(rows) < 3:
        return result
    span = price_span(min(rows), max(rows))
    # Normalize for a scale-independent prominence threshold.
    peak = max(rows.values())
    values = [float(rows.get(index, 0) / peak) for index in span]
    smooth = []
    for i in range(len(values)):
        window = values[max(0, i - radius):i + radius + 1]
        smooth.append(sum(window) / len(window))
    smoothed_peak = max(smooth)
    threshold = smoothed_peak * prominence
    for i in range(1, len(smooth) - 1):
        before, current, after = smooth[i - 1:i + 2]
        for kind, distance in (('hvn', current - max(before, after)), ('lvn', min(before, after) - current)):
            if distance > 0 and distance >= threshold:
                result[kind].append({**row_bounds(span[i], width), 'relative_prominence': distance / smoothed_peak})
    return result


def serialized_rows(rows: dict[int, Fraction], width: int) -> list[dict]:
    scaled = {index: weight * VOLUME_SCALE for index, weight in rows.items()}
    floors = {index: int(value) for index, value in scaled.items()}
    remainder = int(sum(scaled.values())) - sum(floors.values())
    for index in sorted(scaled, key=lambda i: (floors[i] - scaled[i], i))[:remainder]:
        floors[index] += 1
    return [{**row_bounds(index, width), 'volume_units': units} for index, units in floors.items()]


def make_profile(bars, method, width, fraction, radius, prominence, sensitivity):
    rows = weights(bars, method, width)
    area = value_area(rows, width, fraction)
    comparison = None
    if sensitivity:
        other = 'uniform' if method == 'hlc3' else 'hlc3'
        alternate = value_area(weights(bars, other, width), width, fraction)
        comparison = {'method': other, 'value': alternate, 'delta_ticks': {
            'poc': alternate['poc']['low_tick'] - area['poc']['low_tick'],
            'vah': alternate['vah_tick'] - area['vah_tick'], 'val': alternate['val_tick'] - area['val_tick'],
        } if area and alternate else None}
    return {'classification': f'ohlcv_{method}_volume_estimate', 'method': method, 'tick_size': TICK_SIZE,
            'row_ticks': width, 'volume_scale': VOLUME_SCALE, 'total_volume': sum(bar.volume for bar in bars),
            'rows': serialized_rows(rows, width), 'value': area,
            'nodes': nodes(rows, width, radius, prominence), 'sensitivity': comparison}
