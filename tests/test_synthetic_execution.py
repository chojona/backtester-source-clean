"""Independent arithmetic fixtures for the synthetic execution contract."""
from dataclasses import replace
from datetime import date, timedelta
import json
import pytest

from backtester.data import Bar
from backtester.instruments import instrument
from backtester.sessions import SessionCalendar, local_at
from backtester.synthetic_execution import Config, Target, simulate

CAL = SessionCalendar()
INS = instrument("NQ")  # USD 20 per point


def bars(prices, *, day=date(2026, 1, 5), gap=0):
    start = local_at(day, "09:30")
    return tuple(Bar(start + timedelta(minutes=i + (gap if i >= 2 else 0)),
                     p, p, p, p, 100, "NQH26", "NQ",
                     provider="SYNTHETIC", dataset="STEP7A_SYNTHETIC")
                 for i, p in enumerate(prices))


def at(rows, index, target, *, delay=timedelta(0)):
    stamp = rows[index].end
    return Target(stamp, stamp, stamp + delay, target)


def run(prices, commands, *, config=Config(), gap=0):
    rows = bars(prices, gap=gap)
    return simulate(rows, [at(rows, i, t) for i, t in commands], CAL, INS, config)


@pytest.mark.parametrize("entry,exit_price,direction,expected", [
    (100, 102, 1, 40), (100, 98, 1, -40),
    (100, 98, -1, 40), (100, 102, -1, -40),
])
def test_independent_long_short_reference_pnl(entry, exit_price, direction, expected):
    result = run([99, entry, exit_price, exit_price], [(0, direction), (1, 0)])
    assert result.fills[0]["reference_price"] == entry
    assert result.fills[1]["reference_price"] == exit_price
    assert result.fills[0]["fill_at"] == bars([99, entry, exit_price, exit_price])[1].timestamp
    assert result.trades[0]["gross_pnl"] == expected
    assert result.trades[0]["net_pnl"] == expected
    assert result.summary["final_cash"] == 100000 + expected


def test_flat_no_trade():
    result = run([100, 101, 102], [])
    assert result.summary["fills"] == 0
    assert result.summary["net_pnl"] == 0
    assert result.summary["mean_exposure"] == 0


def test_spread_and_commission_independently():
    result = run([100, 100, 100, 100], [(0, 1), (1, 0)],
                 config=Config(spread_points=.5, commission_per_contract=2))
    assert [f["price"] for f in result.fills] == [100.25, 99.75]
    assert result.summary["spread_cost"] == 10
    assert result.summary["commission"] == 4
    assert result.summary["net_pnl"] == -14
    assert result.trades[0]["net_pnl"] == -14


def test_slippage_independently():
    result = run([100] * 4, [(0, -1), (1, 0)], config=Config(slippage_points=.25))
    assert [f["price"] for f in result.fills] == [99.75, 100.25]
    assert result.summary["slippage_cost"] == 10
    assert result.summary["net_pnl"] == -10


def test_delayed_execution_and_no_lookahead():
    rows = bars([100, 101, 102, 103])
    target = at(rows, 0, 1, delay=timedelta(minutes=1))
    result = simulate(rows, [target], CAL, INS)
    assert result.fills[0]["fill_at"] == rows[2].timestamp
    assert result.fills[0]["reference_price"] == 102
    modified = list(rows)
    modified[3] = replace(modified[3], open=200, high=200, low=200, close=200)
    other = simulate(modified, [target], CAL, INS)
    assert result.fills == other.fills
    assert result.equity_curve[:3] == other.equity_curve[:3]


def test_reversal_closes_and_opens_at_same_next_open():
    result = run([99, 100, 98, 97], [(0, 1), (1, -1)])
    assert [f["quantity"] for f in result.fills] == [1, 2]
    assert result.trades[0]["gross_pnl"] == -40
    assert result.summary["final_position"] == -1
    assert result.summary["net_pnl"] == -20  # short gains 1 point after reversal


def test_partial_close_and_configurable_size():
    result = run([99, 100, 101, 102, 102], [(0, 2), (1, 1), (2, 0)],
                 config=Config(max_exposure=2, commission_per_contract=1))
    assert [f["quantity"] for f in result.fills] == [2, 1, 1]
    assert [t["gross_pnl"] for t in result.trades] == [20, 40]
    assert [t["net_pnl"] for t in result.trades] == [18, 38]
    assert result.summary["net_pnl"] == 56
    assert result.summary["total_cost"] == 4


def test_reversal_costs_reconcile_each_portfolio_mark():
    result = run([100, 100, 98, 101], [(0, 1), (1, -1)],
                 config=Config(spread_points=.5, slippage_points=.25,
                               commission_per_contract=2))
    assert result.trades[0]["gross_pnl"] == -40
    assert result.trades[0]["net_pnl"] == -64
    for row in result.equity_curve:
        costs = (row["cumulative_commission"] + row["cumulative_spread_cost"]
                 + row["cumulative_slippage_cost"])
        assert row["gross_equity"] - row["equity"] == pytest.approx(costs)


def test_gap_uses_next_open_and_missing_bar_rejects():
    result = run([99, 100, 90, 90], [(0, 1), (1, 0)])
    assert result.fills[1]["reference_price"] == 90
    assert result.summary["net_pnl"] == -200
    missing = run([99, 100, 90, 90], [(1, 1)], gap=1)
    assert missing.orders[0]["status"] == "REJECTED"
    assert missing.orders[0]["reason"] == "missing_bar"
    assert missing.summary["fills"] == 0


def test_missing_observation_and_market_closure():
    rows = bars([100, 101]) + bars([102, 103], day=date(2026, 1, 6))
    absent = Target(rows[0].timestamp + timedelta(seconds=30), rows[0].end,
                    rows[0].end, 1)
    close = at(rows, 1, 1)
    result = simulate(rows, [absent, close], CAL, INS)
    assert [o["reason"] for o in result.orders] == ["missing_observation", "market_closure"]
    assert not result.fills


def test_drawdown_cash_equity_and_cost_reconciliation():
    result = run([100, 100, 95, 105], [(0, 1)],
                 config=Config(spread_points=.5, slippage_points=.25, commission_per_contract=2))
    assert result.equity_curve[1]["cash"] == 99998
    assert result.equity_curve[1]["unrealized_pnl"] == -10
    assert result.equity_curve[1]["equity"] == 99988
    assert result.summary["max_drawdown"] == 112
    assert result.summary["gross_pnl"] - result.summary["net_pnl"] == result.summary["total_cost"]
    assert all(r["cash"] + r["unrealized_pnl"] == r["equity"] for r in result.equity_curve)
    assert result.summary["turnover_notional"] == 2000
    assert result.summary["mean_exposure"] == .75


def test_rejected_exposure_and_end_expiry():
    over = run([100, 101], [(0, 2)])
    assert over.orders[0]["reason"] == "max_exposure"
    end = run([100], [(0, 1)])
    assert end.orders[0]["reason"] == "dataset_end"


def test_timestamp_and_data_contract_rejections():
    rows = bars([100, 101, 102])
    with pytest.raises(ValueError, match="ordering"):
        simulate(rows, [Target(rows[0].end, rows[0].timestamp, rows[0].end, 1)], CAL, INS)
    with pytest.raises(ValueError, match="Multiple targets"):
        simulate(rows, [at(rows, 0, 1), at(rows, 0, -1)], CAL, INS)
    with pytest.raises(ValueError, match="positive, traded"):
        simulate((replace(rows[0], volume=0), *rows[1:]), [], CAL, INS)
    with pytest.raises(ValueError, match="synthetic"):
        simulate((replace(rows[0], provider=None), *rows[1:]), [], CAL, INS)


def test_deterministic_reproduction():
    first = run([100, 100, 98, 101], [(0, 1), (1, -1)],
                config=Config(spread_points=.5, slippage_points=.25, commission_per_contract=2,
                              max_exposure=2))
    second = run([100, 100, 98, 101], [(0, 1), (1, -1)],
                 config=Config(spread_points=.5, slippage_points=.25, commission_per_contract=2,
                               max_exposure=2))
    assert json.dumps(first.__dict__, default=str, sort_keys=True) == json.dumps(second.__dict__, default=str, sort_keys=True)
