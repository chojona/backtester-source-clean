"""Reproducible metadata and metrics, including empty research-only runs."""
from dataclasses import asdict, is_dataclass
from datetime import datetime, date, timedelta
from enum import Enum
from collections import defaultdict
from statistics import mean, median
from pathlib import Path
import csv
import json
from .sessions import NY


def serial(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return asdict(value)
    raise TypeError("Not serializable: " + repr(value))


def dump(path, value):
    Path(path).write_text(json.dumps(value, default=serial, indent=2, allow_nan=False) + "\n")


def trade_metrics(trades, equity_curve, observed_days=None):
    values = [t["net_pnl"] for t in trades]
    wins, losses = [x for x in values if x > 0], [x for x in values if x < 0]
    r_values = [t["r_multiple"] for t in trades if t["r_multiple"] is not None]
    positive, negative = sum(wins), -sum(losses)
    days = observed_days if observed_days is not None else len({t["trading_date"] for t in trades})
    metrics = dict(total_trades=len(trades), wins=len(wins), losses=len(losses),
        breakeven=len(values) - len(wins) - len(losses), win_rate=len(wins) / len(values) if values else None,
        gross_profit=positive, gross_loss=negative, gross_profit_basis="sum_positive_net_trade_pnl",
        gross_pnl_before_costs=sum(t["gross_pnl"] for t in trades),
        fees=sum(t["fees"] for t in trades), slippage=sum(t["slippage"] for t in trades),
        net_profit=sum(values), average_winner=mean(wins) if wins else None,
        average_loser=mean(losses) if losses else None,
        profit_factor=positive / negative if negative else None,
        profit_factor_no_losses=bool(positive and not negative), expectancy=mean(values) if values else None,
        average_R=mean(r_values) if r_values else None, median_R=median(r_values) if r_values else None,
        maximum_drawdown_dollars=max((e["drawdown_dollars"] for e in equity_curve), default=0),
        maximum_drawdown_percentage=max((e["drawdown_percentage"] for e in equity_curve), default=0),
        largest_winner=max(wins) if wins else None, largest_loser=min(losses) if losses else None,
        average_holding_seconds=mean([t["holding_seconds"] for t in trades]) if trades else None,
        observed_trading_days=days, trades_per_day=len(trades) / days if days else None)
    return metrics


def breakdowns(trades):
    groups = {key: defaultdict(list) for key in ("weekday", "hour", "session", "instrument", "direction")}
    for trade in trades:
        local = trade["entry_time"].astimezone(NY)
        keys = dict(weekday=local.strftime("%A"), hour=local.strftime("%H"),
                    **{k: trade[k] for k in ("session", "instrument", "direction")})
        for name, value in keys.items():
            groups[name][value].append(trade)
    return {name: {key: trade_metrics(rows, []) for key, rows in group.items()} for name, group in groups.items()}


def csv_rows(path, rows):
    if not rows:
        Path(path).write_text("")
        return
    fields = sorted({key for row in rows for key in row})
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: serial(value) if isinstance(value, (datetime, date, Enum)) else value for key, value in row.items()})


def write_run(directory, metadata, engine, events, research_stats, rolls, integrity):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    observed_days = len({row["trading_date"] for row in engine.feature_rows})
    metrics = trade_metrics(engine.portfolio.trades, engine.portfolio.equity_curve, observed_days)
    metrics["breakdowns"] = breakdowns(engine.portfolio.trades)
    metrics["ambiguous_execution_bars"] = len(engine.ambiguous_bars)
    metrics["final_equity"] = engine.portfolio.equity_curve[-1]["equity"]
    metrics["open_position"] = asdict(engine.portfolio.position) if engine.portfolio.position else None
    metrics["research"] = research_stats
    dump(directory / "metadata.json", metadata)
    dump(directory / "summary.json", metrics)
    dump(directory / "integrity.json", integrity)
    dump(directory / "events.json", events)
    dump(directory / "rolls.json", rolls)
    dump(directory / "ambiguous_bars.json", engine.ambiguous_bars)
    dump(directory / "orders.json", engine.orders)
    dump(directory / "fills.json", engine.fills)
    dump(directory / "features.json", engine.feature_rows)
    dump(directory / "warnings.json", sorted(set(engine.warnings)))
    csv_rows(directory / "trades.csv", engine.portfolio.trades)
    csv_rows(directory / "equity.csv", engine.portfolio.equity_curve)
    csv_rows(directory / "trade_equity.csv", engine.portfolio.trade_equity)
    return metrics
