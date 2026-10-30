"""Offline, close-of-bar signal features and separately computed outcomes.

Inputs are raw, single-contract Bar observations. No adjusted retrospective prices,
execution fills, historical acquisition, or model fitting occur here.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime
from math import log, sqrt
from statistics import mean
from types import MappingProxyType
from typing import Mapping, Protocol

from .data import Bar, validate
from .features import VWAP


@dataclass(frozen=True)
class SignalConfig:
    momentum_windows: tuple[int, ...] = (3, 6)
    reversion_window: int = 6
    breakout_window: int = 6
    realized_vol_window: int = 6
    horizons: tuple[int, ...] = (1, 3, 6)

    def __post_init__(self):
        values = (*self.momentum_windows, self.reversion_window, self.breakout_window,
                  self.realized_vol_window, *self.horizons)
        if not self.momentum_windows or any(type(x) is not int or x < 1 for x in values):
            raise ValueError("Windows and horizons must be positive integers")
        if len(set(self.momentum_windows)) != len(self.momentum_windows) or len(set(self.horizons)) != len(self.horizons):
            raise ValueError("Duplicate windows or horizons")


@dataclass(frozen=True)
class FeatureRow:
    decision_at: datetime
    trading_date: date
    contract: str
    values: Mapping[str, float | None]


@dataclass(frozen=True)
class LabelRow:
    decision_at: datetime
    outcome_at: datetime | None
    horizon_bars: int
    forward_log_return: float | None
    censored_reason: str | None


class CausalFeature(Protocol):
    """Extension point: update may inspect only the current and earlier bars."""
    def update(self, bar: Bar, trading_date: date) -> dict[str, float | None]: ...


class SignalFeatures:
    def __init__(self, config: SignalConfig):
        self.config = config
        self.closes = deque(maxlen=max(*config.momentum_windows, config.reversion_window) + 1)
        self.returns = deque(maxlen=max(config.reversion_window, config.realized_vol_window))
        self.ranges = deque(maxlen=config.breakout_window)
        self.vwap = VWAP("typical")
        self.session = self.contract = None
        self.last_end = None

    def update(self, bar: Bar, trading_date: date) -> dict[str, float | None]:
        if self.session != trading_date or self.contract != bar.contract or (self.last_end and self.last_end != bar.timestamp):
            self.closes.clear()
            self.returns.clear()
            self.ranges.clear()
            self.vwap = VWAP("typical")
        prior_close = self.closes[-1] if self.closes else None
        prior_range = list(self.ranges)
        values = {}
        for window in self.config.momentum_windows:
            values[f"momentum_{window}"] = log(bar.close / self.closes[-window]) if len(self.closes) >= window else None
        current_return = log(bar.close / prior_close) if prior_close else None
        if current_return is not None:
            self.returns.append(current_return)
        rolling = list(self.returns)
        reversion_returns = rolling[-self.config.reversion_window:]
        values["rolling_return_mean"] = mean(reversion_returns) if len(reversion_returns) == self.config.reversion_window else None
        values["current_log_return"] = current_return
        vol_returns = rolling[-self.config.realized_vol_window:]
        values["realized_vol"] = (sqrt(mean(x * x for x in vol_returns))
                                  if len(vol_returns) == self.config.realized_vol_window else None)
        if len(self.closes) >= self.config.reversion_window:
            history = list(self.closes)[-self.config.reversion_window:]
            center = mean(history)
            sd = sqrt(mean((x - center) ** 2 for x in history))
            values["reversion_z"] = (bar.close - center) / sd if sd > 0 else None
        else:
            values["reversion_z"] = None
        if len(prior_range) == self.config.breakout_window:
            high = max(x[0] for x in prior_range)
            low = min(x[1] for x in prior_range)
            values["breakout"] = 1.0 if bar.close > high else -1.0 if bar.close < low else 0.0
            values["prior_range_high"] = high
            values["prior_range_low"] = low
        else:
            values.update(breakout=None, prior_range_high=None, prior_range_low=None)
        session_vwap = self.vwap.update(bar)
        values["session_vwap"] = session_vwap
        values["vwap_distance"] = bar.close / session_vwap - 1 if session_vwap else None
        self.closes.append(bar.close)
        self.ranges.append((bar.high, bar.low))
        self.session, self.contract, self.last_end = trading_date, bar.contract, bar.end
        return values


def _checked(bars, calendar):
    bars = tuple(bars)
    report = validate(bars, calendar)
    if len(report.contracts) != 1:
        raise ValueError("Signal research requires one contract")
    for previous, current in zip(bars, bars[1:]):
        if (calendar.classify(previous.timestamp).trading_date == calendar.classify(current.timestamp).trading_date
                and previous.end != current.timestamp):
            raise ValueError("Missing in-session bars")
    if any(b.coverage_state == "UNKNOWN" for b in bars):
        raise ValueError("Unknown provider coverage")
    return bars


def compute_features(bars, calendar, config=SignalConfig(), feature: CausalFeature | None = None):
    bars = _checked(bars, calendar)
    feature = feature or SignalFeatures(config)
    return tuple(FeatureRow(bar.end, calendar.classify(bar.timestamp).trading_date,
                            bar.contract, MappingProxyType(dict(feature.update(bar, calendar.classify(bar.timestamp).trading_date))))
                 for bar in bars)


def make_labels(bars, calendar, horizons=(1, 3, 6)):
    """Bar-close to future bar-close log returns; never supplied to feature code."""
    bars = _checked(bars, calendar)
    if not horizons or any(type(h) is not int or h < 1 for h in horizons):
        raise ValueError("Horizons must be positive integers")
    dates = [calendar.classify(b.timestamp).trading_date for b in bars]
    rows = []
    for i, bar in enumerate(bars):
        for h in horizons:
            end = i + h
            complete = end < len(bars) and dates[end] == dates[i] and bars[end].timestamp == bar.end + (h - 1) * bar.duration
            rows.append(LabelRow(bar.end, bars[end].end if complete else None, h,
                                 log(bars[end].close / bar.close) if complete else None,
                                 None if complete else "session_boundary_or_dataset_end"))
    return tuple(rows)
