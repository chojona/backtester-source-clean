"""Reproduce the offline synthetic signal research report (no market data)."""
import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from backtester.data import Bar
from backtester.sessions import SessionCalendar, local_at
from backtester.signal_research import SignalConfig, compute_features, make_labels
from backtester.signal_evaluation import compare_distributions


VERSION = "1.0.0"


def synthetic_bars():
    """Twenty weekday RTH snippets with deterministic, visibly artificial prices."""
    rows = []
    day = date(2026, 1, 5)
    session = 0
    while session < 20:
        if day.weekday() < 5:
            for minute in range(60):
                tick = 80000 + session * 8 + minute // 4 + ((minute * 7 + session * 3) % 13 - 6)
                close = tick * .25
                rows.append(Bar(local_at(day, "09:30") + timedelta(minutes=minute),
                                close, close + .25, close - .25, close, 100 + minute % 11,
                                "NQH26", "NQ"))
            session += 1
        day += timedelta(days=1)
    return tuple(rows)


def build_report():
    calendar = SessionCalendar()
    config = SignalConfig()
    bars = synthetic_bars()
    features = compute_features(bars, calendar, config)
    labels = make_labels(bars, calendar, config.horizons)
    return {
        "version": VERSION, "dataset": "deterministic synthetic NQ-like 1-minute RTH snippets",
        "bars": len(bars), "sessions": 20,
        "decision_timing": "features available only at completed bar close",
        "outcome_timing": "close at exactly h later completed bars, within same trading date",
        "execution_assumption": "earliest hypothetical order submission after decision bar close; earliest hypothetical market fill next bar open; no orders or fills simulated",
        "cost_assumption": "illustrative NQ one tick adverse slippage and USD 2.50 fees per side per contract; not applied to close-to-close research labels",
        "threshold_policy": "fixed before outcomes; no fitting or evaluation-set optimization",
        "data_status": "synthetic only; no SPY or historical input; HAR-RV NO-GO unchanged",
        "comparison": compare_distributions(features, labels),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/signal-research-synthetic-v1.0.0.json"))
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
