"""Portfolio and closed-trade statistics for synthetic strategy runs.

Closed-trade figures use completed round-trip slices only. Portfolio figures
mark the book to the latest observed close, including open positions.
Profit factor is undefined when there is no losing closed trade; it is never
reported as infinity.
"""
from __future__ import annotations


def closed_trade_metrics(trades):
    nets = [float(trade["net_pnl"]) for trade in trades]
    grosses = [float(trade["gross_pnl"]) for trade in trades]
    count = len(nets)
    gross_profit = sum(value for value in nets if value > 0)
    gross_loss = sum(value for value in nets if value < 0)
    if count == 0:
        status, factor = "no_closed_trades", None
    elif gross_loss == 0 and gross_profit > 0:
        status, factor = "undefined_zero_losses", None
    elif gross_loss == 0:
        status, factor = "undefined_zero_pnl", None
    else:
        status, factor = "defined", gross_profit / abs(gross_loss)
    wins = sum(1 for value in nets if value > 0)
    return {
        "closed_trades": count,
        "win_rate": (wins / count) if count else None,
        "profit_factor": factor,
        "profit_factor_status": status,
        "average_trade_pnl": (sum(nets) / count) if count else None,
        "gross_profit": gross_profit,
        "gross_loss": abs(gross_loss),
        "net_pnl": sum(nets),
        "gross_pnl": sum(grosses),
        "scope": "closed_trades",
    }


def portfolio_metrics(curve, *, cash, unrealized, initial_cash, realized_gross, spread,
                      slippage, commission, turnover, position, exposures):
    """Drawdown includes the initial cash peak. Costs are summed by the caller."""
    if initial_cash <= 0:
        raise ValueError("Initial cash must be positive")
    peak = initial_cash
    max_drawdown = 0.0
    for row in curve:
        equity = float(row["equity"])
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    total_cost = spread + slippage + commission
    final_equity = float(curve[-1]["equity"]) if curve else initial_cash
    net = final_equity - initial_cash
    mean_exposure = sum(exposures) / len(exposures) if exposures else 0.0
    return {
        "scope": "mark_to_market",
        "cash": cash,
        "unrealized_pnl": unrealized,
        "realized_gross_pnl": realized_gross,
        "gross_pnl": net + total_cost,
        "spread_cost": spread,
        "slippage_cost": slippage,
        "commission": commission,
        "total_cost": total_cost,
        "net_pnl": net,
        "final_equity": final_equity,
        "max_drawdown": max_drawdown,
        "max_drawdown_pct": max_drawdown / peak if peak else 0.0,
        "turnover_notional": turnover,
        "turnover_ratio": turnover / initial_cash,
        "mean_exposure": mean_exposure,
        "final_position": position,
    }


def order_counts(orders, risk_events):
    counts = {}
    for order in orders:
        counts[order["status"]] = counts.get(order["status"], 0) + 1
    rejected = [order for order in orders if order["status"] == "REJECTED"]
    return {
        "by_status": counts,
        "rejected_orders": len(rejected),
        "risk_events": len(risk_events),
        "unfilled_orders": sum(1 for order in orders if order["status"] in {"REJECTED", "EXPIRED", "CANCELLED"}),
    }


def build_metrics(result, initial_cash, max_exposure, multiplier):
    for row in result.equity_curve:
        if abs(row["cash"] + row["unrealized_pnl"] - row["equity"]) > 1e-8:
            raise AssertionError("Equity does not equal cash plus unrealized P&L")
    spread = sum(fill["spread_cost"] for fill in result.fills)
    slippage = sum(fill["slippage_cost"] for fill in result.fills)
    commission = sum(fill["commission"] for fill in result.fills)
    position = 0
    turnover = 0.0
    for fill in result.fills:
        signed = fill["quantity"] if fill["side"] == "BUY" else -fill["quantity"]
        position += signed
        turnover += fill["quantity"] * fill["reference_price"] * multiplier
    final = result.equity_curve[-1]
    if position != final["position"]:
        raise AssertionError("Fill-reconstructed position does not match the marked book")
    realized_gross = sum(trade["gross_pnl"] for trade in result.trades)
    portfolio = portfolio_metrics(
        result.equity_curve, cash=final["cash"], unrealized=final["unrealized_pnl"],
        initial_cash=initial_cash, realized_gross=realized_gross, spread=spread,
        slippage=slippage, commission=commission, turnover=turnover, position=position,
        exposures=[abs(row["position"]) / max_exposure for row in result.equity_curve])
    if abs(portfolio["gross_pnl"] - portfolio["total_cost"] - portfolio["net_pnl"]) > 1e-8:
        raise AssertionError("Gross P&L, costs, and net P&L do not reconcile")
    if position == 0 and abs(portfolio["gross_pnl"] - realized_gross) > 1e-8:
        raise AssertionError("Flat-book reference gross does not match closed trades")
    if position == 0 and abs(final["cash"] - (initial_cash + sum(trade["net_pnl"] for trade in result.trades))) > 1e-8:
        raise AssertionError("Flat-book cash does not match closed-trade net P&L")
    return {
        "classification": "SYNTHETIC",
        "closed_trades": closed_trade_metrics(result.trades),
        "portfolio": portfolio,
        "orders": order_counts(result.orders, result.risk_events),
    }
