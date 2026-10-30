"""Generate the Step 6A preregistered, fully artificial interaction report."""
import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from backtester.sessions import local_at
from backtester.signal_interactions import HYPOTHESES, evaluate_interactions
from backtester.signal_research import FeatureRow, LabelRow


VERSION = "1.0.0"


def synthetic_factorial_rows():
    """Balanced six-bit design; known positive, zero, and negative interactions."""
    features, labels, partitions = [], [], {}
    day = date(2026, 1, 5)
    session = 0
    while session < 20:
        if day.weekday() < 5:
            partitions[day] = "evaluation"
            start = local_at(day, "09:30")
            for minute in range(193):
                index = minute // 3
                at = start + timedelta(minutes=minute)
                bits = [1 if index & (1 << bit) else -1 for bit in range(6)]
                m, v, b, vol, r, large = bits
                values = {"momentum_3": m * .0002, "vwap_distance": v * .0001,
                          "breakout": float(b), "realized_vol": .0002 if vol > 0 else .0001,
                          "reversion_z": float(r),
                          "current_log_return": .0002 if large > 0 else .0001}
                features.append(FeatureRow(at, day, "SYNTHETIC", values))
                if minute % 3 == 0 and index < 64:
                    # Session-level variation makes the bootstrap meaningful. H2 is
                    # exactly additive; H1/H3 have opposing interaction signs.
                    outcome = (m * (.00004 + (.0001 + (session - 9.5) * .000002) * v)
                               + b * .00003
                               + r * (-.00004 + (-.00008 + (session - 9.5) * .000001) * large)
                               + (session - 9.5) * .000003)
                    labels.append(LabelRow(at, at + timedelta(minutes=3), 3, outcome, None))
            session += 1
        day += timedelta(days=1)
    return tuple(features), tuple(labels), partitions


def build_report():
    features, labels, partitions = synthetic_factorial_rows()
    return {"version": VERSION, "dataset": "balanced deterministic synthetic factorial rows",
            "sessions": len(partitions), "decision_rows": len(labels),
            "feature_contract": "precomputed close-of-bar feature rows; no future observations read",
            "outcome_contract": "separate synthetic 3-bar forward log-return labels",
            "split_policy": "single explicit synthetic evaluation split; no fitting or threshold selection",
            "known_effects": {"H1": "positive", "H2": "zero", "H3": "negative"},
            "hypothesis_register": [vars(h) for h in HYPOTHESES],
            "evaluation": evaluate_interactions(features, labels, partitions)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("docs/signal-interactions-synthetic-v1.0.0.json"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_report(), sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
