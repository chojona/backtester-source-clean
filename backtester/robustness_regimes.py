"""Closed-form market regimes for robustness tests.

Prices are formulas of the bar index. The recorded seed does not move them.
No market data is read, and none of these paths retune a strategy.
"""
from __future__ import annotations

from datetime import date, timedelta

from .data import Bar
from .sessions import local_at


CONTRACT = "NQH26"
SYMBOL = "NQ"
START = date(2026, 1, 5)
CLOCK = "09:30"
SEED = 9
INTENDED_BARS = 12
BULLISH = tuple(100 + 0.25 * index for index in range(INTENDED_BARS))
BEARISH = tuple(103 - 0.25 * index for index in range(INTENDED_BARS))
SIDEWAYS = (100, 100, 100, 101, 101, 101, 100, 100, 100, 101, 101, 101)
EXPANSION = (100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.5, 101.5, 103.0, 105.5, 109.0, 113.5)
HIGH = (100.0, 108.0) * 6
LOW = (100.0,) * INTENDED_BARS


def _bar(stamp, open_, high, low, close):
    return Bar(stamp, open_, high, low, close, 100, CONTRACT, SYMBOL,
               provider="SYNTHETIC", dataset="STEP7A_SYNTHETIC")


def _flat(prices, omitted=()):
    start = local_at(START, CLOCK)
    rows = []
    for index, price in enumerate(prices):
        if index in omitted:
            continue
        rows.append(_bar(start + timedelta(minutes=index), price, price, price, price))
    return tuple(rows)


def _gaps(closes):
    start = local_at(START, CLOCK)
    rows = []
    for index, close in enumerate(closes):
        open_ = close if index == 0 else close - 0.5
        rows.append(_bar(start + timedelta(minutes=index), open_, max(open_, close), min(open_, close), close))
    return tuple(rows)


_BUILDERS = {
    "bullish_trend": lambda: _flat(BULLISH),
    "bearish_trend": lambda: _flat(BEARISH),
    "sideways": lambda: _flat(SIDEWAYS),
    "high_volatility": lambda: _flat(HIGH),
    "low_volatility": lambda: _flat(LOW),
    "volatility_expansion": lambda: _flat(EXPANSION),
    "price_gaps": lambda: _gaps(BULLISH),
    "missing_bars": lambda: _flat(BULLISH, omitted=(4,)),
}

REGIME_CATALOG = (
    {"regime_id": "bullish_trend", "label": "Bullish trend", "generated": True, "omitted_offsets": [],
     "summary": "Twelve closes rising by one NQ tick, open equal to close."},
    {"regime_id": "bearish_trend", "label": "Bearish trend", "generated": True, "omitted_offsets": [],
     "summary": "Twelve closes falling by one NQ tick from 103, open equal to close."},
    {"regime_id": "sideways", "label": "Sideways market", "generated": True, "omitted_offsets": [],
     "summary": "A bounded 100/101 range with three round trips and no drift regime."},
    {"regime_id": "high_volatility", "label": "High volatility", "generated": True, "omitted_offsets": [],
     "summary": "Closes alternate between 100 and 108."},
    {"regime_id": "low_volatility", "label": "Low volatility", "generated": True, "omitted_offsets": [],
     "summary": "Twelve unchanged 100-point closes."},
    {"regime_id": "volatility_expansion", "label": "Volatility expansion", "generated": True,
     "omitted_offsets": [],
     "summary": "Six quiet 100 closes, then a widening upward path."},
    {"regime_id": "price_gaps", "label": "Price gaps", "generated": True, "omitted_offsets": [],
     "summary": "Bullish closes with each later open half a point below that close."},
    {"regime_id": "missing_bars", "label": "Missing bars", "generated": True, "omitted_offsets": [4],
     "summary": "The bullish path with the 09:34 bar removed inside the same window."},
    {"regime_id": "exchange_halt", "label": "Exchange halt", "generated": False, "omitted_offsets": [],
     "summary": "Listed only. A halt calendar is not certified, so no result is generated."},
)


def regime_bars(regime_id):
    builder = _BUILDERS.get(regime_id)
    if builder is None:
        known = regime_id in {item["regime_id"] for item in REGIME_CATALOG}
        if known:
            raise ValueError(f"Regime {regime_id} has not been generated")
        raise ValueError("Unknown synthetic regime: " + regime_id)
    return builder()


def omitted_offsets(regime_id):
    for item in REGIME_CATALOG:
        if item["regime_id"] == regime_id:
            return tuple(item["omitted_offsets"])
    raise ValueError("Unknown synthetic regime: " + regime_id)
