"""Independent checks for the synthetic strategy laboratory.

Expected prices, P&L, and drawdowns below are calculated from the NQ point
value ($20) and the Step 7B next-open rule. They are not copied from a
simulator summary.
"""
from dataclasses import replace
from datetime import date, timedelta
import json

import pytest

from backtester.data import Bar
from backtester.sessions import SessionCalendar, local_at
from backtester.strategy_analytics import closed_trade_metrics, portfolio_metrics
from backtester.strategy_fixtures import fixture_bars
from backtester.strategy_pipeline import run_strategy
from backtester.strategy_spec import predefined, spec_for
from backtester.synthetic_execution import Config, Target, simulate
from backtester.instruments import instrument

CAL = SessionCalendar()
POINT = 20.0


def _run(name, fixture_id, **overrides):
    spec = spec_for(name, **overrides)
    bars = fixture_bars(fixture_id)
    return run_strategy(bars, spec, CAL)


def test_predefined_strategies_are_versioned_and_futures_only():
    specs = predefined()
    assert [item.strategy_id for item in specs] == [
        "momentum_continuation", "mean_reversion", "breakout_continuation"]
    assert {item.version for item in specs} == {"1.0.0"}
    for item in specs:
        assert item.quantity_unit == "contracts"
        assert item.instrument_symbol == "NQ"
        assert item.provider == "SYNTHETIC"
        assert item.seed == 9
        assert item.decision_phase == "completed_bar_close"
        assert item.fill_rule == "next_eligible_open"


def test_equity_and_option_accounting_are_refused():
    with pytest.raises(ValueError, match="futures"):
        spec_for("momentum_continuation", instrument_symbol="SPY")
    with pytest.raises(ValueError, match="futures"):
        spec_for("momentum_continuation", quantity_unit="shares")


def test_feature_unavailable_bars_stay_flat_and_do_not_fill_same_bar():
    result = _run("momentum_continuation", "long_round_trip")
    early = result.decisions[:3]
    assert [row["reason"] for row in early] == ["feature_unavailable"] * 3
    assert [row["target_contracts"] for row in early] == [0, 0, 0]
    signal = next(row for row in result.decisions if row["reason"] == "signal_long")
    fill = next(item for item in result.fills if item["order_id"] == signal["order_id"])
    assert fill["fill_at"] > signal["bar_open"]
    assert fill["fill_at"] == signal["decision_at"]
    assert fill["reference_price"] == 101


def test_long_round_trip_matches_hand_pnl():
    result = _run("momentum_continuation", "long_round_trip")
    assert result.trades[0]["direction"] == "long"
    assert result.trades[0]["gross_pnl"] == (100 - 101) * POINT
    assert result.trades[0]["net_pnl"] == -20
    assert result.metrics["portfolio"]["net_pnl"] == -20
    assert result.metrics["portfolio"]["gross_pnl"] == -20
    assert result.metrics["portfolio"]["final_position"] == 0
    assert result.metrics["portfolio"]["max_drawdown"] == 20
    assert result.metrics["closed_trades"]["win_rate"] == 0
    assert result.metrics["closed_trades"]["profit_factor"] == 0
    assert result.metrics["closed_trades"]["profit_factor_status"] == "defined"
    assert result.metrics["closed_trades"]["average_trade_pnl"] == -20
    assert result.metrics["classification"] == "SYNTHETIC"
    expired = [row for row in result.orders if row["status"] == "EXPIRED"]
    assert len(expired) == 1
    assert expired[0]["target_contracts"] == -1


def test_short_round_trip_matches_hand_pnl():
    result = _run("momentum_continuation", "short_round_trip")
    assert result.trades[0]["direction"] == "short"
    assert result.trades[0]["gross_pnl"] == -1 * (101 - 100) * POINT
    assert result.metrics["portfolio"]["net_pnl"] == -20
    assert result.metrics["portfolio"]["final_position"] == 0


def test_reversal_separates_closed_trade_pnl_from_open_mark():
    result = _run("momentum_continuation", "reversal")
    assert result.trades[0]["net_pnl"] == -20
    assert result.metrics["closed_trades"]["net_pnl"] == -20
    assert result.metrics["portfolio"]["final_position"] == -1
    assert result.metrics["portfolio"]["unrealized_pnl"] == 20
    assert result.metrics["portfolio"]["net_pnl"] == 0
    assert result.metrics["portfolio"]["cash"] == 99_980


def test_winner_drawdown_and_zero_loss_profit_factor():
    result = _run("momentum_continuation", "winner")
    assert result.trades[0]["net_pnl"] == (105 - 103) * POINT
    assert result.metrics["portfolio"]["max_drawdown"] == 40
    assert result.metrics["portfolio"]["net_pnl"] == 40
    assert result.metrics["closed_trades"]["win_rate"] == 1
    assert result.metrics["closed_trades"]["profit_factor"] is None
    assert result.metrics["closed_trades"]["profit_factor_status"] == "undefined_zero_losses"
    assert result.metrics["closed_trades"]["average_trade_pnl"] == 40


def test_adverse_costs_are_tick_rounded_and_reconcile():
    result = _run("momentum_continuation", "adverse_costs",
                  spread_points=0.5, commission_per_contract=2.0)
    assert [item["price"] for item in result.fills] == [101.25, 99.75]
    portfolio = result.metrics["portfolio"]
    assert portfolio["spread_cost"] == 10
    assert portfolio["slippage_cost"] == 0
    assert portfolio["commission"] == 4
    assert portfolio["gross_pnl"] == -20
    assert portfolio["net_pnl"] == -34
    assert portfolio["gross_pnl"] - portfolio["total_cost"] == portfolio["net_pnl"]


def test_missing_bar_rejects_without_position_change():
    result = _run("momentum_continuation", "missing_bar")
    assert any(row["reason"] == "missing_bar" for row in result.risk_events)
    assert result.fills == []
    assert result.metrics["portfolio"]["final_position"] == 0
    assert result.metrics["portfolio"]["net_pnl"] == 0
    assert result.metrics["portfolio"]["cash"] == 100_000


def test_market_closure_expires_the_session_ending_order():
    result = _run("momentum_continuation", "market_closure")
    expired = [row for row in result.orders if row["reason"] == "market_closure"]
    assert len(expired) == 1
    assert expired[0]["status"] == "EXPIRED"
    assert expired[0]["fill_at"] is None


def test_exposure_limit_rejects_the_order_and_preserves_cash():
    result = _run("momentum_continuation", "exposure_rejection", contracts=2)
    assert any(row["reason"] == "max_exposure" for row in result.risk_events)
    assert result.fills == []
    assert result.metrics["portfolio"]["cash"] == 100_000
    assert result.metrics["portfolio"]["final_position"] == 0


def test_flat_market_has_no_closed_trades():
    result = _run("momentum_continuation", "flat")
    assert result.fills == []
    assert result.metrics["closed_trades"]["profit_factor_status"] == "no_closed_trades"
    assert result.metrics["closed_trades"]["profit_factor"] is None
    assert result.metrics["portfolio"]["net_pnl"] == 0
    assert result.metrics["portfolio"]["max_drawdown"] == 0


def test_mean_reversion_fades_a_two_standard_deviation_close():
    result = _run("mean_reversion", "mean_reverting")
    fade = next(row for row in result.decisions if row["reason"] == "signal_short")
    assert fade["feature_value"] == pytest.approx(2.0)
    assert fade["target_contracts"] == -1
    fill = next(item for item in result.fills if item["order_id"] == fade["order_id"])
    assert fill["side"] == "SELL"
    assert fill["fill_at"] == result.bars[fade["bar_index"] + 1].timestamp


def test_breakout_continues_only_after_the_prior_range():
    result = _run("breakout_continuation", "range_breakout")
    early = [row for row in result.decisions if row["feature_value"] is None]
    assert len(early) == 6
    assert {row["target_contracts"] for row in early} == {0}
    breakout = next(row for row in result.decisions if row["reason"] == "signal_long")
    assert breakout["feature_value"] == 1
    assert breakout["bar_index"] == 6
    fill = next(item for item in result.fills if item["order_id"] == breakout["order_id"])
    assert fill["side"] == "BUY"
    assert fill["reference_price"] == 100.25


def test_future_close_does_not_change_an_earlier_decision_or_fill():
    spec = spec_for("momentum_continuation")
    bars = list(fixture_bars("long_round_trip"))
    original = run_strategy(bars, spec, CAL)
    changed = replace(bars[-1], close=150, high=150)
    mutated = run_strategy([*bars[:-1], changed], spec, CAL)
    assert original.decisions[:-1] == mutated.decisions[:-1]
    assert original.fills == mutated.fills
    assert mutated.decisions[-1]["feature_value"] != original.decisions[-1]["feature_value"]


def test_labels_are_not_features_and_replay_is_deterministic():
    import backtester.strategy_pipeline as pipeline
    assert "make_labels" not in pipeline.__dict__
    first = _run("momentum_continuation", "trending")
    second = _run("momentum_continuation", "trending")
    assert first.output_sha256 == second.output_sha256
    assert first.input_sha256 == second.input_sha256
    assert first.metrics["portfolio"]["final_position"] == 1
    encoded = json.dumps(first.to_public(), sort_keys=True, default=str)
    assert json.dumps(second.to_public(), sort_keys=True, default=str) == encoded


def test_analytics_do_not_treat_simulator_summary_as_the_oracle():
    result = _run("momentum_continuation", "winner")
    trades = [{"net_pnl": 40.0, "gross_pnl": 40.0}]
    closed = closed_trade_metrics(trades)
    assert closed["profit_factor_status"] == "undefined_zero_losses"
    curve = [{"equity": 100_000.0}, {"equity": 99_960.0}, {"equity": 100_040.0}]
    portfolio = portfolio_metrics(curve, cash=100_040.0, unrealized=0.0, initial_cash=100_000.0,
                                  realized_gross=40.0, spread=0.0, slippage=0.0, commission=0.0,
                                  turnover=0.0, position=0, exposures=[0.0, 1.0, 0.0])
    assert portfolio["max_drawdown"] == 40
    assert result.metrics["portfolio"]["max_drawdown"] == portfolio["max_drawdown"]


def test_pipeline_reuses_step7b_targets_without_rewriting_fills():
    spec = spec_for("momentum_continuation")
    bars = fixture_bars("long_round_trip")
    result = run_strategy(bars, spec, CAL)
    targets = [Target(row["decision_at"], row["decision_at"], row["decision_at"], row["target_contracts"])
               for row in result.decisions]
    direct = simulate(bars, targets, CAL, instrument("NQ"), Config(
        initial_cash=spec.initial_cash, max_exposure=spec.max_exposure,
        spread_points=spec.spread_points, slippage_points=spec.slippage_points,
        commission_per_contract=spec.commission_per_contract))
    assert result.fills == direct.fills
    assert result.trades == direct.trades


def test_same_session_gap_does_not_use_pre_gap_features_as_if_contiguous():
    result = _run("momentum_continuation", "missing_bar")
    after_gap = result.decisions[-1]
    assert after_gap["reason"] == "feature_unavailable"
    assert after_gap["target_contracts"] == 0
