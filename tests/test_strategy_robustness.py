"""Independent checks for synthetic regime, cost, and risk robustness.

Expected dollars are computed from the published bar formulas, the NQ $20
point value, and the Step 7B adverse-tick cost rule. They are not copied
from a previous simulator summary.
"""
from datetime import timedelta
from math import log, sqrt

import pytest

from backtester.robustness import RankingRefused, build_study, compare_cells, rank_strategies, run_cell
from backtester.robustness_regimes import regime_bars
from backtester.strategy_spec import predefined


POINT = 20.0
BULLISH = [100 + 0.25 * index for index in range(12)]
BEARISH = [103 - 0.25 * index for index in range(12)]
SIDEWAYS = [100, 100, 100, 101, 101, 101, 100, 100, 100, 101, 101, 101]
EXPANSION = [100.0] * 6 + [100.5, 101.5, 103.0, 105.5, 109.0, 113.5]


def _pnl(cell):
    return cell["metrics"]


def test_predefined_strategy_rules_stay_at_the_step_9a_values():
    specs = {item.strategy_id: item for item in predefined()}
    assert specs["momentum_continuation"].window == 3
    assert specs["momentum_continuation"].threshold == 0.0
    assert specs["mean_reversion"].window == 6
    assert specs["mean_reversion"].threshold == 1.0
    assert specs["breakout_continuation"].window == 6
    assert specs["breakout_continuation"].threshold == 0.0
    for spec in specs.values():
        assert spec.contracts == 1
        assert spec.max_exposure == 1
        assert spec.initial_cash == 100_000.0
        assert spec.spread_points == spec.slippage_points == spec.commission_per_contract == 0.0
        assert spec.version == "1.0.0"
        assert spec.seed == 9


def test_regimes_share_a_window_and_published_prices():
    bullish = regime_bars("bullish_trend")
    bearish = regime_bars("bearish_trend")
    sideways = regime_bars("sideways")
    expansion = regime_bars("volatility_expansion")
    gaps = regime_bars("price_gaps")
    missing = regime_bars("missing_bars")
    low = regime_bars("low_volatility")
    high = regime_bars("high_volatility")
    assert [bar.close for bar in bullish] == BULLISH
    assert [bar.close for bar in bearish] == BEARISH
    assert [bar.close for bar in sideways] == SIDEWAYS
    assert [bar.close for bar in expansion] == EXPANSION
    assert [bar.close for bar in low] == [100.0] * 12
    assert [bar.close for bar in high] == [100.0, 108.0] * 6
    assert [bar.close for bar in gaps] == BULLISH
    assert gaps[0].open == BULLISH[0]
    assert [bar.open for bar in gaps[1:]] == [price - 0.5 for price in BULLISH[1:]]
    assert bullish[0].timestamp == missing[0].timestamp == gaps[0].timestamp
    assert bullish[-1].end == missing[-1].end == gaps[-1].end
    assert len(bullish) == 12
    assert len(missing) == 11
    assert missing[4].timestamp - missing[3].timestamp == timedelta(minutes=2)
    assert all(bullish[index].timestamp - bullish[index - 1].timestamp == timedelta(minutes=1)
               for index in range(1, 12))
    assert max(abs(high[index].close - high[index - 1].close) for index in range(1, 12)) == 8
    assert max(abs(low[index].close - low[index - 1].close) for index in range(1, 12)) == 0
    with pytest.raises(ValueError, match="not been generated"):
        regime_bars("exchange_halt")


def test_replay_is_deterministic_and_a_prefix_cannot_see_later_bars():
    first = run_cell("momentum_continuation", "bullish_trend", "regime_baseline")
    second = run_cell("momentum_continuation", "bullish_trend", "regime_baseline")
    assert first["output_sha256"] == second["output_sha256"]
    assert first["targets"] == second["targets"]
    for count in range(1, 12):
        prefix = run_cell("momentum_continuation", "bullish_trend", "regime_baseline", bar_count=count)
        assert prefix["targets"] == first["targets"][:count]
        for fill in prefix["fills"]:
            assert fill["signal_bar_open"] < fill["fill_at"]
            assert fill["fill_at"] == fill["decision_at"]


def test_momentum_bullish_bearish_expansion_and_gap_dollars():
    bullish = run_cell("momentum_continuation", "bullish_trend", "regime_baseline")
    bearish = run_cell("momentum_continuation", "bearish_trend", "regime_baseline")
    expansion = run_cell("momentum_continuation", "volatility_expansion", "regime_baseline")
    gaps = run_cell("momentum_continuation", "price_gaps", "regime_baseline")
    bars = regime_bars("bullish_trend")
    assert (bars[-1].close - bars[4].open) * POINT == 35
    assert _pnl(bullish)["net_pnl"] == _pnl(bullish)["gross_pnl"] == 35
    assert _pnl(bullish)["total_cost"] == 0
    assert _pnl(bullish)["max_drawdown"] == 0
    assert _pnl(bullish)["final_position"] == 1
    assert _pnl(bullish)["cash"] == 100_000
    assert _pnl(bullish)["unrealized_pnl"] == 35
    assert _pnl(bullish)["final_equity"] == 100_035
    assert _pnl(bullish)["closed_trade_count"] == 0
    assert _pnl(bullish)["fill_count"] == 1
    assert _pnl(bullish)["turnover_notional"] == bars[4].open * POINT
    assert bullish["fills"][0]["reference_price"] == 101
    assert bullish["fills"][0]["signal_bar_open"] < bullish["fills"][0]["fill_at"]
    assert bullish["fills"][0]["reference_price"] != bars[3].close
    assert _pnl(bearish)["net_pnl"] == 35
    assert _pnl(bearish)["final_position"] == -1
    assert _pnl(bearish)["cash"] == 100_000
    assert (regime_bars("volatility_expansion")[-1].close - 101.5) * POINT == 240
    assert _pnl(expansion)["net_pnl"] == 240
    assert _pnl(expansion)["final_position"] == 1
    assert gaps["targets"] == bullish["targets"]
    assert gaps["reasons"] == bullish["reasons"]
    assert _pnl(gaps)["net_pnl"] == 45
    assert gaps["fills"][0]["reference_price"] == 100.5


def test_mean_reversion_and_breakout_on_the_bullish_path():
    closes = BULLISH
    history = closes[0:6]
    center = sum(history) / 6
    dispersion = sqrt(sum((price - center) ** 2 for price in history) / 6)
    assert (closes[6] - center) / dispersion > 1
    reversion = run_cell("mean_reversion", "bullish_trend", "regime_baseline")
    breakout = run_cell("breakout_continuation", "bullish_trend", "regime_baseline")
    assert reversion["targets"][6] == -1
    assert _pnl(reversion)["net_pnl"] == -20
    assert _pnl(reversion)["final_position"] == -1
    assert _pnl(reversion)["cash"] == 100_000
    assert breakout["targets"][6] == 1
    assert _pnl(breakout)["net_pnl"] == 20
    assert _pnl(breakout)["final_position"] == 1
    assert breakout["fills"][0]["reference_price"] == 101.75


def test_low_volatility_is_a_real_flat_result_and_sideways_round_trips():
    for strategy_id in ("momentum_continuation", "mean_reversion", "breakout_continuation"):
        flat = run_cell(strategy_id, "low_volatility", "regime_baseline")
        assert flat["status"] == "generated"
        assert _pnl(flat)["net_pnl"] == _pnl(flat)["gross_pnl"] == 0
        assert _pnl(flat)["final_position"] == 0
        assert _pnl(flat)["fill_count"] == 0
        assert _pnl(flat)["closed_trade_count"] == 0
        assert _pnl(flat)["max_drawdown"] == 0
    path = run_cell("momentum_continuation", "sideways", "regime_baseline")
    assert _pnl(path)["gross_pnl"] == _pnl(path)["net_pnl"] == -40
    assert _pnl(path)["closed_trade_count"] == 2
    assert _pnl(path)["fill_count"] == 3
    assert _pnl(path)["final_position"] == 1
    assert _pnl(path)["cash"] == 99_960
    assert _pnl(path)["unrealized_pnl"] == 0
    assert _pnl(path)["final_equity"] == 99_960
    assert _pnl(path)["max_drawdown"] == 40
    assert _pnl(path)["turnover_notional"] == (101 + 200 + 202) * POINT
    assert [(fill["side"], fill["quantity"], fill["reference_price"]) for fill in path["fills"]] == [
        ("BUY", 1, 101), ("SELL", 2, 100), ("BUY", 2, 101)]


def test_cost_schedules_change_dollars_without_changing_decisions():
    zero = run_cell("momentum_continuation", "bullish_trend", "cost_zero")
    spread = run_cell("momentum_continuation", "bullish_trend", "cost_spread_one_tick")
    slippage = run_cell("momentum_continuation", "bullish_trend", "cost_slippage_one_tick")
    commission = run_cell("momentum_continuation", "bullish_trend", "cost_commission_two")
    combined = run_cell("momentum_continuation", "bullish_trend", "cost_combined")
    baseline = run_cell("momentum_continuation", "bullish_trend", "regime_baseline")
    assert _pnl(zero) == _pnl(baseline)
    for cell in (spread, slippage, commission, combined):
        assert cell["cost_effect"] == "costs_only"
        assert cell["targets"] == zero["targets"]
        assert cell["execution_digest"] == zero["execution_digest"]
        assert _pnl(cell)["gross_pnl"] == 35
        assert _pnl(cell)["fill_count"] == _pnl(zero)["fill_count"] == 1
        assert _pnl(cell)["closed_trade_count"] == 0
        assert _pnl(cell)["turnover_notional"] == _pnl(zero)["turnover_notional"]
        assert _pnl(cell)["net_pnl"] == _pnl(cell)["gross_pnl"] - _pnl(cell)["total_cost"]
    assert _pnl(spread)["spread_cost"] == 5
    assert _pnl(spread)["slippage_cost"] == 0
    assert _pnl(spread)["commission"] == 0
    assert _pnl(spread)["net_pnl"] == 30
    assert _pnl(spread)["max_drawdown"] == 5
    assert spread["fills"][0]["price"] == 101.25
    assert _pnl(slippage)["slippage_cost"] == 5
    assert _pnl(slippage)["spread_cost"] == 0
    assert _pnl(slippage)["net_pnl"] == 30
    assert slippage["fills"][0]["price"] == 101.25
    assert _pnl(commission)["commission"] == 2
    assert _pnl(commission)["spread_cost"] == _pnl(commission)["slippage_cost"] == 0
    assert _pnl(commission)["net_pnl"] == 33
    assert _pnl(commission)["cash"] == 99_998
    assert _pnl(commission)["max_drawdown"] == 2
    assert commission["fills"][0]["price"] == 101
    assert _pnl(combined)["spread_cost"] == 5
    assert _pnl(combined)["slippage_cost"] == 5
    assert _pnl(combined)["commission"] == 2
    assert _pnl(combined)["total_cost"] == 12
    assert _pnl(combined)["net_pnl"] == 23
    assert _pnl(combined)["max_drawdown"] == 12
    assert combined["fills"][0]["price"] == 101.5
    ranged = run_cell("momentum_continuation", "sideways", "cost_commission_two")
    assert ranged["cost_effect"] == "costs_only"
    assert _pnl(ranged)["gross_pnl"] == -40
    assert _pnl(ranged)["commission"] == 10
    assert _pnl(ranged)["net_pnl"] == -50
    assert _pnl(ranged)["closed_trade_count"] == 2
    assert _pnl(ranged)["turnover_notional"] == (101 + 200 + 202) * POINT
    assert _pnl(ranged)["cash"] == 99_950
    assert _pnl(ranged)["final_position"] == 1


def test_risk_rejection_reversal_and_cash_reconciliation():
    exposure = run_cell("momentum_continuation", "bullish_trend", "risk_exposure_rejection")
    position_cap = run_cell("momentum_continuation", "bullish_trend", "risk_position_size_rejection")
    notional = run_cell("momentum_continuation", "bullish_trend", "risk_notional_rejection")
    buying_power = run_cell("momentum_continuation", "bullish_trend", "risk_buying_power_rejection")
    reversal = run_cell("momentum_continuation", "sideways", "risk_reversal_allowed")
    locked = run_cell("momentum_continuation", "sideways", "risk_daily_loss_rejects_reversal")
    baseline = run_cell("momentum_continuation", "bullish_trend", "regime_baseline")
    assert exposure["spec"]["window"] == baseline["spec"]["window"] == 3
    assert exposure["spec"]["threshold"] == 0.0
    assert [sign(target) for target in exposure["targets"]] == [sign(target) for target in baseline["targets"]]
    assert "max_exposure" in exposure["risk_reasons"]
    assert _pnl(exposure)["fill_count"] == 0
    assert _pnl(exposure)["final_position"] == 0
    assert _pnl(exposure)["cash"] == _pnl(exposure)["final_equity"] == 100_000
    assert "max_position_size" in position_cap["risk_reasons"]
    assert _pnl(position_cap)["final_position"] == 0
    assert "max_gross_notional" in notional["risk_reasons"]
    assert _pnl(notional)["cash"] == 100_000
    assert _pnl(notional)["final_position"] == 0
    assert "insufficient_buying_power" in buying_power["risk_reasons"]
    assert _pnl(buying_power)["final_position"] == 0
    assert ("SELL", 2) in [(fill["side"], fill["quantity"]) for fill in reversal["fills"]]
    assert _pnl(reversal)["closed_trade_count"] == 2
    assert _pnl(reversal)["final_position"] == 1
    assert _pnl(reversal)["cash"] == 99_960
    assert _pnl(reversal)["final_equity"] == _pnl(reversal)["cash"] + _pnl(reversal)["unrealized_pnl"]
    assert "daily_loss_lockout" in locked["risk_reasons"]
    assert _pnl(locked)["closed_trade_count"] == 0
    assert _pnl(locked)["final_position"] == 1
    assert _pnl(locked)["cash"] == 100_000
    assert _pnl(locked)["final_equity"] == 100_000
    assert _pnl(locked)["max_drawdown"] == 20
    assert locked["cost_effect"] == "risk_policy"


def test_missing_bars_reject_the_pending_order_and_reset_the_feature():
    cell = run_cell("momentum_continuation", "missing_bars", "regime_baseline")
    assert cell["protocol"]["omitted_offsets"] == [4]
    assert cell["protocol"]["observed_bars"] == 11
    assert cell["protocol"]["window_start"] == run_cell(
        "momentum_continuation", "bullish_trend", "regime_baseline")["protocol"]["window_start"]
    assert "missing_bar" in cell["risk_reasons"]
    assert _pnl(cell)["net_pnl"] == 10
    assert _pnl(cell)["final_position"] == 1
    assert cell["fills"][0]["reference_price"] == 102.25
    assert all(log(BULLISH[index] / BULLISH[index - 3]) > 0 for index in (3, 8))


def test_unavailable_regimes_are_excluded_and_ranking_is_refused():
    study = build_study()
    halted = [cell for cell in study["cells"] if cell["regime_id"] == "exchange_halt"]
    assert len(halted) == 3
    assert {cell["strategy_id"] for cell in halted} == {
        "momentum_continuation", "mean_reversion", "breakout_continuation"}
    for cell in halted:
        assert cell["status"] == "not_generated"
        assert cell["metrics"] is None
        assert cell["targets"] is None
    compared = compare_cells(study["cells"])
    assert compared["ranking"] is None
    assert compared["ranking_refused"] is True
    assert all(cell["regime_id"] != "exchange_halt" for cell in compared["scored"])
    assert len(compared["excluded"]) == 3
    low = [cell for cell in compared["scored"]
           if cell["regime_id"] == "low_volatility" and cell["configuration_id"] == "regime_baseline"]
    assert len(low) == 3
    assert all(cell["metrics"]["net_pnl"] == 0 for cell in low)
    fabricated = {**halted[0], "metrics": {"net_pnl": 0}}
    with pytest.raises(ValueError, match="not_generated"):
        compare_cells([fabricated])
    mismatched = {**low[0], "protocol": {**low[0]["protocol"], "initial_cash": 50_000}}
    with pytest.raises(ValueError, match="initial cash"):
        compare_cells([mismatched])
    with pytest.raises(RankingRefused):
        rank_strategies(study["cells"])
    assert study["comparison"]["ranking"] is None
    assert study["comparison"]["ranking_refused"] is True
    assert "not historical alpha" in study["claim"].lower()
    assert study["historical_gates"]["spy_signal_eligibility"] == "0/440 NO-GO"
    for cell in compared["scored"]:
        metrics = cell["metrics"]
        assert abs(metrics["gross_pnl"] - metrics["net_pnl"] - metrics["total_cost"]) < 1e-8
        assert abs(metrics["final_equity"] - metrics["cash"] - metrics["unrealized_pnl"]) < 1e-8
        assert cell["protocol"]["initial_cash"] == 100_000
        assert cell["protocol"]["contract"] == "NQH26"
        assert cell["protocol"]["mark_to_market"] == "observed_close"
        for row in cell["equity_curve"]:
            assert abs(row["cash"] + row["unrealized_pnl"] - row["equity"]) < 1e-8
        if cell["configuration_id"].startswith("cost_") and cell["cost_effect"] == "costs_only":
            control = next(item for item in compared["scored"]
                           if item["strategy_id"] == cell["strategy_id"]
                           and item["regime_id"] == cell["regime_id"]
                           and item["configuration_id"] == "cost_zero")
            assert metrics["gross_pnl"] == control["metrics"]["gross_pnl"]
            assert metrics["closed_trade_count"] == control["metrics"]["closed_trade_count"]
            assert metrics["turnover_notional"] == control["metrics"]["turnover_notional"]


def sign(target):
    return (target > 0) - (target < 0)
