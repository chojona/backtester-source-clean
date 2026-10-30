import argparse
import csv
import json
from pathlib import Path

from .engine import backtest, read_bars


def main():
    parser = argparse.ArgumentParser(description="Backtest a long-only futures moving-average crossover on CSV prices")
    parser.add_argument("--data", type=Path, default=Path("data/sample.csv"))
    parser.add_argument("--fast", type=int, default=20)
    parser.add_argument("--slow", type=int, default=50)
    parser.add_argument("--cash", type=float, default=100000)
    parser.add_argument("--multiplier", type=float, default=50)
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument("--slippage-ticks", type=float, default=1)
    parser.add_argument("--commission", type=float, default=2.5)
    parser.add_argument("--contracts", type=int, default=1)
    parser.add_argument("--margin", type=float, default=15000)
    parser.add_argument("--periods-per-year", type=int, default=252)
    parser.add_argument("--output", type=Path, default=Path("results/latest"))
    args = parser.parse_args()
    try:
        summary, curve, trades = backtest(
            read_bars(args.data), args.fast, args.slow, args.cash,
            multiplier=args.multiplier, tick_size=args.tick_size,
            slippage_ticks=args.slippage_ticks, commission=args.commission,
            contracts=args.contracts, margin_per_contract=args.margin,
            periods_per_year=args.periods_per_year)
    except (ValueError, OSError, OverflowError) as error:
        parser.error(str(error))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    for filename, rows, fields in (
        ("equity.csv", curve, ["date", "equity", "contracts", "margin_used", "drawdown"]),
        ("trades.csv", trades, ["date", "side", "contracts", "price", "commission", "slippage_cost"]),
    ):
        with (args.output / filename).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    print("Final equity: ${:,.2f}".format(summary["final_equity"]))
    print("Return: {:.2%} | Max drawdown: {:.2%} | Fills: {}".format(
        summary["total_return"], summary["max_drawdown"], summary["fills"]))
    print("Results: {}".format(args.output.resolve()))


if __name__ == "__main__":
    main()
