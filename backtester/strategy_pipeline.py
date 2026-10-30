"""Point-in-time path from a completed bar to a Step 7B futures fill.

Feature values come from the causal signal engine. Forward labels are not
imported. A decision is stamped at the completed bar's end and can fill only
on a later bar.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from .data import validate
from .instruments import instrument
from .signal_research import SignalConfig, SignalFeatures
from .strategy_analytics import build_metrics
from .strategy_spec import StrategySpec
from .synthetic_execution import Config, InstrumentSpec, Target, simulate


def _decide(spec, value):
    if value is None:
        return 0, "feature_unavailable"
    if spec.family == "mean_reversion":
        if value > spec.threshold:
            return -spec.contracts, "signal_short"
        if value < -spec.threshold:
            return spec.contracts, "signal_long"
        return 0, "signal_flat"
    if value > spec.threshold:
        return spec.contracts, "signal_long"
    if value < -spec.threshold:
        return -spec.contracts, "signal_short"
    return 0, "signal_flat"


def _canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
                      default=lambda value: value.isoformat() if isinstance(value, datetime) else value)


def canonical_digest(payload):
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


@dataclass
class ExperimentResult:
    spec: StrategySpec
    bars: tuple
    decisions: list
    orders: list
    order_events: list
    fills: list
    trades: list
    equity_curve: list
    risk_events: list
    metrics: dict
    input_sha256: str
    output_sha256: str

    def to_public(self):
        return {
            "classification": "SYNTHETIC",
            "strategy_id": self.spec.strategy_id,
            "strategy_version": self.spec.version,
            "spec": self.spec.to_dict(),
            "input_sha256": self.input_sha256,
            "output_sha256": self.output_sha256,
            "decisions": self.decisions,
            "orders": self.orders,
            "order_events": self.order_events,
            "fills": self.fills,
            "trades": self.trades,
            "equity_curve": self.equity_curve,
            "risk_events": self.risk_events,
            "metrics": self.metrics,
        }


def run_strategy(bars, spec, calendar):
    if not isinstance(spec, StrategySpec):
        raise TypeError("A versioned StrategySpec is required")
    bars = tuple(bars)
    if not bars:
        raise ValueError("No bars")
    if any(bar.symbol != spec.instrument_symbol or bar.contract != spec.contract or
           bar.provider != spec.provider or bar.dataset != spec.dataset for bar in bars):
        raise ValueError("Bars do not match the synthetic futures specification")
    if any(bar.bar_state != "TRADED" or bar.coverage_state == "UNKNOWN" or bar.volume <= 0 for bar in bars):
        raise ValueError("Missing or invalid bars are not tradable")
    validate(bars, calendar)
    feature = SignalFeatures(SignalConfig(
        momentum_windows=(spec.window,), reversion_window=spec.window,
        breakout_window=spec.window, realized_vol_window=spec.window, horizons=(1,)))
    decisions = []
    targets = []
    for index, bar in enumerate(bars):
        session = calendar.classify(bar.timestamp)
        if session is None:
            raise ValueError("Bar is outside the session calendar")
        values = feature.update(bar, session.trading_date)
        if spec.feature_name not in values:
            raise ValueError("Strategy feature was not computed")
        value = values[spec.feature_name]
        target, reason = _decide(spec, value)
        decisions.append({
            "bar_index": index,
            "bar_open": bar.timestamp,
            "decision_at": bar.end,
            "feature_name": spec.feature_name,
            "feature_value": value,
            "target_contracts": target,
            "reason": reason,
        })
        targets.append(Target(bar.end, bar.end, bar.end, target))
    traded = instrument(spec.instrument_symbol)
    spec_check = InstrumentSpec.from_instrument(traded)
    if spec_check.quantity_unit != "contracts":
        raise ValueError("Futures contract accounting is required")
    executed = simulate(bars, targets, calendar, traded, Config(
        initial_cash=spec.initial_cash, max_exposure=spec.max_exposure,
        spread_points=spec.spread_points, slippage_points=spec.slippage_points,
        commission_per_contract=spec.commission_per_contract,
        instrument_spec=spec_check, max_position_size=spec.max_position_size,
        max_gross_notional=spec.max_gross_notional, max_trade_risk=spec.max_trade_risk,
        max_daily_loss=spec.max_daily_loss, max_session_loss=spec.max_session_loss,
        max_buying_power_multiple=spec.max_buying_power_multiple))
    by_observation = {order["observation_at"]: order["id"] for order in executed.orders}
    for decision in decisions:
        decision["order_id"] = by_observation[decision["decision_at"]]
    for fill in executed.fills:
        decision_at = fill["decision_at"]
        source = next(bar for bar in bars if bar.end == decision_at)
        if fill["fill_at"] <= source.timestamp:
            raise AssertionError("Close-derived signal filled on its own bar")
    metrics = build_metrics(executed, spec.initial_cash, spec.max_exposure, traded.point_value)
    public_bars = [{
        "timestamp": bar.timestamp, "end": bar.end, "open": bar.open, "high": bar.high,
        "low": bar.low, "close": bar.close, "volume": bar.volume, "contract": bar.contract,
    } for bar in bars]
    input_sha256 = canonical_digest({"seed": spec.seed, "spec": spec.to_dict(), "bars": public_bars})
    output_body = {
        "decisions": decisions, "orders": executed.orders, "fills": executed.fills,
        "trades": executed.trades, "equity_curve": executed.equity_curve,
        "risk_events": executed.risk_events, "metrics": metrics,
    }
    return ExperimentResult(
        spec=spec, bars=bars, decisions=decisions, orders=executed.orders,
        order_events=executed.order_events, fills=executed.fills, trades=executed.trades,
        equity_curve=executed.equity_curve, risk_events=executed.risk_events, metrics=metrics,
        input_sha256=input_sha256, output_sha256=canonical_digest(output_body))
