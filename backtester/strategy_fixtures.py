"""Closed-form synthetic futures paths.

Price paths are formulas, not samples. The recorded seed is part of the
experiment identity and does not perturb these version-1 paths. No market
data is read.
"""
from __future__ import annotations

from datetime import date, timedelta

from .data import Bar
from .sessions import local_at

CONTRACT = "NQH26"
SYMBOL = "NQ"
START = date(2026, 1, 5)
SEED = 9


def _bar(stamp, open_, high, low, close):
    return Bar(stamp, open_, high, low, close, 100, CONTRACT, SYMBOL,
               provider="SYNTHETIC", dataset="STEP7A_SYNTHETIC")


def _session(prices, *, day=START, clock="09:30"):
    start = local_at(day, clock)
    rows = []
    for index, price in enumerate(prices):
        if isinstance(price, tuple):
            rows.append(_bar(start + timedelta(minutes=index), *price))
        else:
            rows.append(_bar(start + timedelta(minutes=index), price, price, price, price))
    return tuple(rows)


def _describe(fixture_id, summary):
    return {"fixture_id": fixture_id, "seed": SEED, "summary": summary,
            "generator": "backtester.strategy_fixtures.fixture_bars",
            "path": "closed_form", "classification": "SYNTHETIC"}


FIXTURE_CATALOG = (
    _describe("trending", "Twelve one-minute bars rising by one NQ tick."),
    _describe("mean_reverting", "A six-bar alternating range, then a two-standard-deviation up close."),
    _describe("range_breakout", "Six bars pinned at 100, then a one-tick close above that range."),
    _describe("flat", "Eight unchanged 100-point bars."),
    _describe("missing_bar", "A one-minute in-session gap after a long signal."),
    _describe("market_closure", "A Monday RTH decision whose next bar is Tuesday."),
    _describe("adverse_costs", "The long round trip priced with spread and commission on the strategy."),
    _describe("long_round_trip", "Momentum long entered at 101 and exited at 100."),
    _describe("short_round_trip", "Momentum short entered at 100 and covered at 101."),
    _describe("reversal", "Momentum long closed into a short that is marked one point lower."),
    _describe("winner", "Momentum long entered at 103, marked down, then exited at 105."),
    _describe("exposure_rejection", "The long round-trip path used with a two-contract target."),
)


def fixture_bars(fixture_id):
    if fixture_id in {"long_round_trip", "adverse_costs", "exposure_rejection"}:
        return _session([100, 100, 100, 101, 101, 101, 101, 100])
    if fixture_id == "short_round_trip":
        return _session([101, 101, 101, 100, 100, 100, 100, 101])
    if fixture_id == "winner":
        return _session([100, 100, 100, 101, 103, 103, 101, 105])
    if fixture_id == "reversal":
        rising = [100, 100, 100, 101, 101, 101, 100]
        bars = list(_session(rising))
        bars.append(_bar(bars[-1].end, 100, 100, 99, 99))
        return tuple(bars)
    if fixture_id == "flat":
        return _session([100] * 8)
    if fixture_id == "trending":
        return _session([100 + 0.25 * index for index in range(12)])
    if fixture_id == "mean_reverting":
        # Prior six closes average 100.25 with standard deviation 0.25.
        # The seventh close, 100.75, is exactly two standard deviations above that mean.
        return _session([100, 100, 100, 100.5, 100.5, 100.5, 100.75, 100.5])
    if fixture_id == "range_breakout":
        return _session([100] * 6 + [100.25, 100.25])
    if fixture_id == "missing_bar":
        start = local_at(START, "09:30")
        prices = [100, 100, 100, 101, 101]
        stamps = [start + timedelta(minutes=index if index < 4 else index + 1) for index in range(5)]
        return tuple(_bar(stamp, price, price, price, price) for stamp, price in zip(stamps, prices))
    if fixture_id == "market_closure":
        monday = list(_session([100 + 0.25 * index for index in range(7)]))
        tuesday = _bar(local_at(date(2026, 1, 6), "09:30"), 101.5, 101.5, 101.5, 101.5)
        return tuple([*monday, tuesday])
    raise ValueError("Unknown synthetic fixture: " + fixture_id)
