import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean, stdev
from typing import List


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    close: float


def read_bars(path: Path) -> List[Bar]:
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"date", "open", "close"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV must contain date,open,close columns")
        bars = [Bar(row["date"], float(row["open"]), float(row["close"])) for row in reader]
    validate_bars(bars)
    return bars


def validate_bars(bars):
    if len(bars) < 2:
        raise ValueError("At least two bars are required")
    previous = None
    for bar in bars:
        parsed = date.fromisoformat(bar.date)
        if previous is not None and parsed <= previous:
            raise ValueError("Dates must be unique and in ascending order")
        previous = parsed
        if not all(math.isfinite(x) for x in (bar.open, bar.close)):
            raise ValueError("Prices must be finite")


def backtest(bars, fast=20, slow=50, initial_cash=100000.0,
             multiplier=50.0, tick_size=0.25, slippage_ticks=1.0,
             commission=2.5, contracts=1, margin_per_contract=15000.0,
             periods_per_year=252):
    validate_bars(bars)
    if not 0 < fast < slow or slow >= len(bars):
        raise ValueError("Require 0 < fast < slow < number of bars")
    if not all(math.isfinite(x) and x > 0 for x in
               (initial_cash, multiplier, tick_size, margin_per_contract)):
        raise ValueError("Cash, multiplier, tick size and margin must be finite and positive")
    if not all(math.isfinite(x) and x >= 0 for x in (slippage_ticks, commission)):
        raise ValueError("Costs must be finite and nonnegative")
    if not isinstance(contracts, int) or contracts <= 0 or periods_per_year <= 0:
        raise ValueError("Contracts and periods per year must be positive integers")

    equity, position, target = initial_cash, 0, False
    closes, curve, trades, returns = [], [], [], []
    peak, max_drawdown = initial_cash, 0.0
    previous_close = bars[0].open
    for index, bar in enumerate(bars):
        previous_equity = equity
        equity += position * multiplier * (bar.open - previous_close)
        desired = contracts if target else 0
        if desired != position:
            change = desired - position
            cost = abs(change) * (commission + slippage_ticks * tick_size * multiplier)
            if desired and equity - cost < desired * margin_per_contract:
                raise ValueError("Insufficient configured margin to enter on " + bar.date)
            fill = bar.open + (slippage_ticks * tick_size if change > 0 else -slippage_ticks * tick_size)
            equity -= cost
            trades.append(dict(date=bar.date, side="BUY" if change > 0 else "SELL",
                               contracts=abs(change), price=fill,
                               commission=abs(change) * commission,
                               slippage_cost=abs(change) * slippage_ticks * tick_size * multiplier))
            position = desired
        equity += position * multiplier * (bar.close - bar.open)
        if equity <= 0:
            raise ValueError("Account equity exhausted on " + bar.date)
        if position and equity < position * margin_per_contract:
            raise ValueError("Configured margin breached on " + bar.date + "; simulation stopped")
        if index > 0:
            returns.append(equity / previous_equity - 1)
        peak = max(peak, equity)
        drawdown = equity / peak - 1
        max_drawdown = min(max_drawdown, drawdown)
        curve.append(dict(date=bar.date, equity=equity, contracts=position,
                          margin_used=position * margin_per_contract, drawdown=drawdown))
        closes.append(bar.close)
        previous_close = bar.close
        if len(closes) >= slow:
            target = mean(closes[-fast:]) > mean(closes[-slow:])

    volatility = stdev(returns) if len(returns) > 1 else 0.0
    summary = dict(
        strategy="long-only futures moving-average crossover",
        start=bars[0].date, end=bars[-1].date, bars=len(bars),
        fast=fast, slow=slow, initial_cash=initial_cash,
        final_equity=equity, total_return=equity / initial_cash - 1,
        annualized_return=(equity / initial_cash) ** (periods_per_year / (len(bars) - 1)) - 1,
        max_drawdown=max_drawdown,
        sharpe_zero_risk_free=mean(returns) / volatility * math.sqrt(periods_per_year) if volatility else None,
        fills=len(trades), open_contracts=position, contract_count=contracts,
        multiplier=multiplier, tick_size=tick_size, slippage_ticks=slippage_ticks,
        commission_per_contract_per_side=commission, margin_per_contract=margin_per_contract,
        periods_per_year=periods_per_year,
    )
    return summary, curve, trades
