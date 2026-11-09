from __future__ import annotations

import math

from .model import MINUTE, TICK_SIZE


def make_vwap(samples, anchor, cutoff, deviations, points_from=None):
    """Accumulate weighted population moments over the entire requested scope."""
    previous = None
    weight = 0
    mean = m2 = 0.0
    points = []
    for sample in samples:
        for bar in sample.bars:
            available = bar.time + MINUTE
            if (anchor is not None and bar.time < anchor) or available > cutoff:
                continue
            if bar.volume:
                typical = (bar.low + bar.high + bar.close) * TICK_SIZE / 3
                weight += bar.volume
                delta = typical - mean
                mean += delta * (bar.volume / weight)
                m2 += bar.volume * delta * (typical - mean)
            sd = math.sqrt(max(0, m2 / weight)) if weight else None
            disconnected = previous is None or bar.time != previous + MINUTE
            if points_from is None or available >= points_from:
                points.append({'time': int(bar.time.timestamp()), 'available_at': int(available.timestamp()),
                               'trading_date': sample.day.isoformat(), 'break_before': disconnected,
                               'volume': weight, 'vwap': mean if weight else None, 'deviation': sd,
                               'upper': mean + deviations * sd if weight else None,
                               'lower': mean - deviations * sd if weight else None})
            previous = bar.time
    return {'classification': 'ohlcv_hlc3_weighted_vwap_estimate', 'anchor': anchor,
            'points_from': points_from, 'deviations': deviations, 'points': points}
