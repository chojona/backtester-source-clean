"""Synthetic robustness runs for the fixed Step 9A strategies.

Overlays change published cost or risk settings only. They do not change a
strategy family, feature, window, threshold, or decision rule.
"""
from __future__ import annotations

from .sessions import SessionCalendar
from .strategy_pipeline import canonical_digest, run_strategy
from .strategy_spec import predefined, spec_for
from .robustness_regimes import INTENDED_BARS, REGIME_CATALOG, SEED, regime_bars, omitted_offsets


CLAIM = ("Synthetic robustness research only. These results are not historical alpha "
         "and are not a ranking of real-market strategies.")
REFUSAL = "Synthetic scenario results are not a ranking of real-market strategies."
PROTOCOL_ID = "step9b-v1"
INITIAL_CASH = 100_000.0
_FROZEN_RULES = {
    "family", "feature_name", "window", "threshold", "decision_phase", "fill_rule",
    "version", "flat_when_unavailable", "initial_cash", "instrument_symbol", "contract",
    "seed", "provider", "dataset", "strategy_id", "quantity_unit", "bar_duration_seconds",
}
_ALLOWED_OVERLAYS = {
    "spread_points", "slippage_points", "commission_per_contract", "contracts", "max_exposure",
    "max_position_size", "max_gross_notional", "max_trade_risk", "max_daily_loss",
    "max_session_loss", "max_buying_power_multiple",
}
CONFIGURATIONS = {
    "regime_baseline": {},
    "cost_zero": {},
    "cost_spread_one_tick": {"spread_points": 0.25},
    "cost_slippage_one_tick": {"slippage_points": 0.25},
    "cost_commission_two": {"commission_per_contract": 2.0},
    "cost_combined": {"spread_points": 0.25, "slippage_points": 0.25, "commission_per_contract": 2.0},
    "risk_exposure_rejection": {"contracts": 2, "max_exposure": 1},
    "risk_position_size_rejection": {"contracts": 2, "max_exposure": 2, "max_position_size": 1},
    "risk_notional_rejection": {"max_gross_notional": 1_000.0},
    "risk_buying_power_rejection": {"max_buying_power_multiple": 0.01},
    "risk_reversal_allowed": {},
    "risk_daily_loss_rejects_reversal": {"max_daily_loss": 10.0},
}
COST_SCHEDULES = (
    {"configuration_id": "cost_zero", "label": "Zero costs", **CONFIGURATIONS["cost_zero"]},
    {"configuration_id": "cost_spread_one_tick", "label": "Spread one tick",
     **CONFIGURATIONS["cost_spread_one_tick"]},
    {"configuration_id": "cost_slippage_one_tick", "label": "Slippage one tick",
     **CONFIGURATIONS["cost_slippage_one_tick"]},
    {"configuration_id": "cost_commission_two", "label": "Commission $2",
     **CONFIGURATIONS["cost_commission_two"]},
    {"configuration_id": "cost_combined", "label": "Spread, slippage, and commission",
     **CONFIGURATIONS["cost_combined"]},
)
RISK_POLICIES = (
    {"configuration_id": "risk_exposure_rejection", "label": "Exposure cap below target",
     "regime_id": "bullish_trend", "summary": "Two-contract target into a one-contract cap."},
    {"configuration_id": "risk_position_size_rejection", "label": "Position-size cap",
     "regime_id": "bullish_trend", "summary": "Two-contract target into a one-contract position cap."},
    {"configuration_id": "risk_notional_rejection", "label": "Gross notional cap",
     "regime_id": "bullish_trend", "summary": "One contract is above a $1,000 notional cap."},
    {"configuration_id": "risk_buying_power_rejection", "label": "Buying-power multiple",
     "regime_id": "bullish_trend", "summary": "One contract exceeds 1% of equity."},
    {"configuration_id": "risk_reversal_allowed", "label": "Reversal inside the cap",
     "regime_id": "sideways", "summary": "A one-contract reversal is inside max exposure."},
    {"configuration_id": "risk_daily_loss_rejects_reversal", "label": "Daily-loss lockout",
     "regime_id": "sideways", "summary": "A $10 daily-loss cap rejects the reversal after the open loss."},
)
COST_REGIMES = ("bullish_trend", "sideways")
_COMMON = {
    "initial_cash": INITIAL_CASH,
    "instrument_symbol": "NQ",
    "contract": "NQH26",
    "tick_size": 0.25,
    "point_value": 20.0,
    "quantity_unit": "contracts",
    "bar_duration_seconds": 60,
    "mark_to_market": "observed_close",
    "intended_bars": INTENDED_BARS,
}
LABELS = {
    "momentum_continuation": "Momentum continuation",
    "mean_reversion": "Mean reversion",
    "breakout_continuation": "Breakout continuation",
}


class RankingRefused(RuntimeError):
    """Synthetic cells are not ordered as real-market winners."""


def _overrides(configuration_id):
    if configuration_id not in CONFIGURATIONS:
        raise ValueError("Unknown robustness configuration: " + configuration_id)
    raw = dict(CONFIGURATIONS[configuration_id])
    illegal = set(raw) & _FROZEN_RULES
    if illegal:
        raise ValueError("Robustness overlays cannot retune strategy rules: " + ",".join(sorted(illegal)))
    unknown = set(raw) - _ALLOWED_OVERLAYS
    if unknown:
        raise ValueError("Unknown robustness overlay: " + ",".join(sorted(unknown)))
    return raw


def _window():
    bars = regime_bars("bullish_trend")
    return bars[0].timestamp, bars[-1].end


def _metrics(result):
    portfolio = result.metrics["portfolio"]
    closed = result.metrics["closed_trades"]
    return {
        "gross_pnl": portfolio["gross_pnl"],
        "net_pnl": portfolio["net_pnl"],
        "total_cost": portfolio["total_cost"],
        "spread_cost": portfolio["spread_cost"],
        "slippage_cost": portfolio["slippage_cost"],
        "commission": portfolio["commission"],
        "max_drawdown": portfolio["max_drawdown"],
        "closed_trade_count": closed["closed_trades"],
        "fill_count": len(result.fills),
        "turnover_notional": portfolio["turnover_notional"],
        "final_position": portfolio["final_position"],
        "cash": portfolio["cash"],
        "unrealized_pnl": portfolio["unrealized_pnl"],
        "final_equity": portfolio["final_equity"],
    }


def _execution_digest(result):
    return canonical_digest({
        "fills": [(fill["side"], fill["quantity"], fill["reference_price"]) for fill in result.fills],
        "orders": [(order["status"], order["reason"], order["target_contracts"]) for order in result.orders],
    })


def _unavailable(strategy_id, regime_id, configuration_id):
    start, end = _window()
    return {
        "strategy_id": strategy_id,
        "strategy_version": "1.0.0",
        "regime_id": regime_id,
        "configuration_id": configuration_id,
        "status": "not_generated",
        "applicability": "not_generated",
        "classification": "SYNTHETIC",
        "claim": CLAIM,
        "seed": SEED,
        "spec": None,
        "targets": None,
        "reasons": None,
        "decision_digest": None,
        "execution_digest": None,
        "output_sha256": None,
        "metrics": None,
        "fills": None,
        "equity_curve": None,
        "risk_reasons": None,
        "risk_events": None,
        "cost_effect": None,
        "unavailable_reason": "This strategy and regime combination has not been generated.",
        "protocol": {
            **_COMMON,
            "protocol_id": PROTOCOL_ID,
            "window_start": start,
            "window_end": end,
            "timezone": "America/New_York",
            "observed_bars": None,
            "omitted_offsets": [],
            "baseline_costs": {"spread_points": 0.0, "slippage_points": 0.0, "commission_per_contract": 0.0},
        },
    }


def run_cell(strategy_id, regime_id, configuration_id, bar_count=None):
    """Run one fixed strategy on one regime. ``bar_count`` keeps a causal prefix."""
    catalog = {item["regime_id"]: item for item in REGIME_CATALOG}
    if regime_id not in catalog:
        raise ValueError("Unknown synthetic regime: " + regime_id)
    if not catalog[regime_id]["generated"]:
        if bar_count is not None:
            raise ValueError("Ungenerated regimes have no prefix")
        return _unavailable(strategy_id, regime_id, configuration_id)
    overrides = _overrides(configuration_id)
    bars = regime_bars(regime_id)
    if bar_count is not None:
        if type(bar_count) is not int or not 1 <= bar_count <= len(bars):
            raise ValueError("Prefix length is outside the generated regime")
        bars = bars[:bar_count]
    spec = spec_for(strategy_id, **overrides)
    if spec.initial_cash != INITIAL_CASH or spec.instrument_symbol != "NQ" or spec.contract != "NQH26":
        raise ValueError("Robustness cells must keep the common capital and contract")
    result = run_strategy(bars, spec, SessionCalendar())
    targets = [decision["target_contracts"] for decision in result.decisions]
    reasons = [decision["reason"] for decision in result.decisions]
    metrics = _metrics(result)
    decision_open = {decision["decision_at"]: decision["bar_open"] for decision in result.decisions}
    fills = [{
        "side": fill["side"], "quantity": fill["quantity"], "reference_price": fill["reference_price"],
        "price": fill["price"], "fill_at": fill["fill_at"], "decision_at": fill["decision_at"],
        "signal_bar_open": decision_open[fill["decision_at"]],
    } for fill in result.fills]
    execution_digest = _execution_digest(result)
    decision_digest = canonical_digest({"targets": targets, "reasons": reasons})
    if configuration_id.startswith("risk_"):
        cost_effect = "risk_policy"
    elif configuration_id.startswith("cost_") and configuration_id != "cost_zero":
        control = run_cell(strategy_id, regime_id, "cost_zero", bar_count=bar_count)
        same_path = (control["execution_digest"] == execution_digest
                     and control["decision_digest"] == decision_digest)
        cost_effect = "costs_only" if same_path else "execution_or_risk_changed"
    else:
        cost_effect = "baseline"
    start, end = _window()
    cell = {
        "strategy_id": strategy_id,
        "strategy_version": spec.version,
        "regime_id": regime_id,
        "configuration_id": configuration_id,
        "status": "generated",
        "applicability": "applicable",
        "classification": "SYNTHETIC",
        "claim": CLAIM,
        "seed": spec.seed,
        "spec": spec.to_dict(),
        "targets": targets,
        "reasons": reasons,
        "decision_digest": decision_digest,
        "execution_digest": execution_digest,
        "metrics": metrics,
        "fills": fills,
        "equity_curve": [{
            "timestamp": row["timestamp"], "equity": row["equity"], "drawdown": row["drawdown"],
            "cash": row["cash"], "unrealized_pnl": row["unrealized_pnl"], "position": row["position"],
        } for row in result.equity_curve],
        "risk_reasons": [event["reason"] for event in result.risk_events],
        "risk_events": [{
            "order_id": event["order_id"], "at": event["at"], "reason": event["reason"],
        } for event in result.risk_events],
        "cost_effect": cost_effect,
        "unavailable_reason": None,
        "protocol": {
            **_COMMON,
            "protocol_id": PROTOCOL_ID,
            "window_start": start,
            "window_end": end,
            "timezone": "America/New_York",
            "observed_bars": len(bars) if bar_count is None else len(regime_bars(regime_id)),
            "omitted_offsets": list(omitted_offsets(regime_id)),
            "baseline_costs": {"spread_points": 0.0, "slippage_points": 0.0, "commission_per_contract": 0.0},
        },
    }
    cell["output_sha256"] = canonical_digest({
        "targets": targets, "reasons": reasons, "metrics": metrics, "fills": fills,
        "risk_reasons": cell["risk_reasons"], "execution_digest": execution_digest,
    })
    return cell


def compare_cells(cells):
    """Score generated cells. Unavailable cells stay out and are not zeros."""
    scored = []
    excluded = []
    for cell in cells:
        if cell["status"] != "generated":
            if cell.get("metrics") is not None or cell.get("targets") is not None:
                raise ValueError("not_generated cells cannot carry metrics or targets")
            excluded.append({
                "strategy_id": cell["strategy_id"],
                "regime_id": cell["regime_id"],
                "configuration_id": cell["configuration_id"],
            })
            continue
        protocol = cell["protocol"]
        for key, expected in _COMMON.items():
            if protocol.get(key) != expected:
                raise ValueError("common " + key.replace("_", " ") + " mismatch")
        if protocol.get("mark_to_market") != "observed_close":
            raise ValueError("common mark to market mismatch")
        scored.append(cell)
    return {
        "scored": scored,
        "excluded": excluded,
        "ranking": None,
        "ranking_refused": True,
        "refusal_reason": REFUSAL,
    }


def rank_strategies(cells):
    raise RankingRefused(REFUSAL)


def _strategy_rows():
    return [{**item.to_dict(), "label": LABELS[item.strategy_id]} for item in predefined()]


def build_study():
    """The full predefined grid. This does not search parameters."""
    strategies = tuple(item.strategy_id for item in predefined())
    generated = [item["regime_id"] for item in REGIME_CATALOG if item["generated"]]
    cells = []
    for strategy_id in strategies:
        for regime_id in generated:
            cells.append(run_cell(strategy_id, regime_id, "regime_baseline"))
        for regime_id in (item["regime_id"] for item in REGIME_CATALOG if not item["generated"]):
            cells.append(run_cell(strategy_id, regime_id, "regime_baseline"))
        for regime_id in COST_REGIMES:
            for schedule in COST_SCHEDULES:
                cells.append(run_cell(strategy_id, regime_id, schedule["configuration_id"]))
        for policy in RISK_POLICIES:
            cells.append(run_cell(strategy_id, policy["regime_id"], policy["configuration_id"]))
    compared = compare_cells(cells)
    return {
        "classification": "SYNTHETIC",
        "claim": CLAIM,
        "accounting": ("USD futures contracts use the Step 7B simulator. "
                       "Shares and options accounting are refused."),
        "historical_gates": {
            "spy_signal_eligibility": "0/440 NO-GO",
            "spy_har_rv_training": "0/82 NO-GO",
            "spy_har_rv_validation": "0/82 NO-GO",
        },
        "protocol": {
            "protocol_id": PROTOCOL_ID,
            **_COMMON,
            "window_start": _window()[0],
            "window_end": _window()[1],
            "timezone": "America/New_York",
            "mark_to_market": "observed_close",
            "baseline_costs": {"spread_points": 0.0, "slippage_points": 0.0, "commission_per_contract": 0.0},
            "unavailable_treatment": "exclude_not_generated",
            "seed": SEED,
            "path": "closed_form",
        },
        "strategies": _strategy_rows(),
        "regimes": list(REGIME_CATALOG),
        "cost_schedules": [dict(item) for item in COST_SCHEDULES],
        "risk_policies": [dict(item) for item in RISK_POLICIES],
        "cells": cells,
        "comparison": {
            "ranking": None,
            "ranking_refused": True,
            "refusal_reason": REFUSAL,
            "excluded_not_generated": compared["excluded"],
            "scored_cell_count": len(compared["scored"]),
        },
        "limitations": [
            "Synthetic bars only. No historical SPY or NQ market data is used.",
            "Results are not historical alpha and are not a ranking of real-market strategies.",
            "Strategy families, windows, and thresholds stay at the Step 9A specification.",
            "The calendar is a weekday template and does not certify exchange holidays or halts.",
            "Version 1 paths are closed-form. The seed is pinned and does not perturb prices.",
            "An ungenerated strategy and regime cell is excluded. It is not a zero return.",
            "Cost schedules keep the same targets when the execution path is unchanged.",
            "Loss and exposure limits reject new exposure. They do not liquidate.",
        ],
    }
