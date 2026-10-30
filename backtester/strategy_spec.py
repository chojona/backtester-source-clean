"""Versioned synthetic strategy specifications.

These records describe how a completed bar becomes a target position. They do
not search parameters and they do not read historical market data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from math import isfinite

from .instruments import INSTRUMENTS


FAMILIES = ("momentum_continuation", "mean_reversion", "breakout_continuation")
_FEATURE = {
    "momentum_continuation": "momentum_{window}",
    "mean_reversion": "reversion_z",
    "breakout_continuation": "breakout",
}


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    version: str
    family: str
    instrument_symbol: str
    contract: str
    quantity_unit: str
    feature_name: str
    window: int
    threshold: float
    decision_phase: str
    fill_rule: str
    flat_when_unavailable: bool
    contracts: int
    max_exposure: int
    max_position_size: int | None
    max_gross_notional: float | None
    max_trade_risk: float | None
    max_daily_loss: float | None
    max_session_loss: float | None
    max_buying_power_multiple: float | None
    spread_points: float
    slippage_points: float
    commission_per_contract: float
    initial_cash: float
    seed: int
    bar_duration_seconds: int
    dataset: str
    provider: str

    def __post_init__(self):
        if self.family not in FAMILIES or self.strategy_id not in FAMILIES:
            raise ValueError("Unknown predefined strategy family")
        if self.version != "1.0.0":
            raise ValueError("Unsupported strategy specification version")
        if self.quantity_unit != "contracts" or self.instrument_symbol not in INSTRUMENTS:
            raise ValueError("Only registered USD futures contracts are supported; shares and options are refused")
        if self.feature_name != _FEATURE[self.family].format(window=self.window):
            raise ValueError("Feature does not match the strategy family")
        if self.decision_phase != "completed_bar_close" or self.fill_rule != "next_eligible_open":
            raise ValueError("Decisions are completed-bar closes and fills are next eligible opens")
        if self.flat_when_unavailable is not True:
            raise ValueError("Unavailable features must flatten")
        if type(self.window) is not int or self.window < 1:
            raise ValueError("Feature window must be a positive integer")
        if type(self.contracts) is not int or self.contracts < 1:
            raise ValueError("Position size must be a positive integer number of contracts")
        if type(self.max_exposure) is not int or self.max_exposure < 1:
            raise ValueError("Maximum exposure must be a positive integer")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("Seed must be a nonnegative integer")
        if self.provider != "SYNTHETIC" or self.dataset != "STEP7A_SYNTHETIC":
            raise ValueError("Strategy laboratory accepts only synthetic bars")
        if self.bar_duration_seconds != 60:
            raise ValueError("Version 1.0.0 uses one-minute bars")
        if not isfinite(self.threshold) or self.threshold < 0:
            raise ValueError("Threshold must be finite and nonnegative")
        if not isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("Initial cash must be positive and finite")
        for value in (self.spread_points, self.slippage_points, self.commission_per_contract):
            if not isfinite(value) or value < 0:
                raise ValueError("Transaction costs must be finite and nonnegative")
        for value in (self.max_gross_notional, self.max_trade_risk, self.max_daily_loss,
                      self.max_session_loss, self.max_buying_power_multiple):
            if value is not None and (not isfinite(value) or value <= 0):
                raise ValueError("Risk limits must be positive and finite")
        if self.max_position_size is not None and (type(self.max_position_size) is not int or self.max_position_size < 1):
            raise ValueError("Maximum position size must be a positive integer")

    def to_dict(self):
        return asdict(self)


def _spec(family, *, window, threshold):
    return StrategySpec(
        strategy_id=family, version="1.0.0", family=family, instrument_symbol="NQ",
        contract="NQH26", quantity_unit="contracts",
        feature_name=_FEATURE[family].format(window=window), window=window, threshold=threshold,
        decision_phase="completed_bar_close", fill_rule="next_eligible_open",
        flat_when_unavailable=True, contracts=1, max_exposure=1, max_position_size=None,
        max_gross_notional=None, max_trade_risk=None, max_daily_loss=None,
        max_session_loss=None, max_buying_power_multiple=None, spread_points=0.0,
        slippage_points=0.0, commission_per_contract=0.0, initial_cash=100_000.0,
        seed=9, bar_duration_seconds=60, dataset="STEP7A_SYNTHETIC", provider="SYNTHETIC")


def predefined():
    """The three fixed strategies. Parameters are declared, not searched."""
    return (
        _spec("momentum_continuation", window=3, threshold=0.0),
        _spec("mean_reversion", window=6, threshold=1.0),
        _spec("breakout_continuation", window=6, threshold=0.0),
    )


def spec_for(strategy_id, **overrides):
    base = {item.strategy_id: item for item in predefined()}
    if strategy_id not in base:
        raise ValueError("Unknown predefined strategy")
    known = {item.name for item in fields(StrategySpec)}
    unknown = set(overrides) - known
    if unknown:
        raise ValueError("Unknown strategy field: " + ",".join(sorted(unknown)))
    if "feature_name" not in overrides and ("family" in overrides or "window" in overrides):
        family = overrides.get("family", base[strategy_id].family)
        window = overrides.get("window", base[strategy_id].window)
        overrides = {**overrides, "feature_name": _FEATURE[family].format(window=window)}
    return replace(base[strategy_id], **overrides)
