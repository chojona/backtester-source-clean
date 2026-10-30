"""Preregistered, offline difference-in-effects research on point-in-time rows.

No feature is fitted or recomputed here. Returns are labels supplied separately.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from math import ceil, floor, isfinite
from random import Random
from statistics import mean, median
from typing import Mapping

from .signal_research import FeatureRow, LabelRow


@dataclass(frozen=True)
class InteractionHypothesis:
    id: str
    signal: str
    modifier: str
    horizon_bars: int
    signal_cutoff: float
    modifier_cutoff: float
    modifier_rule: str
    prediction: str


# Fixed in source before viewing any forward-return labels. Exactly three tests.
HYPOTHESES = (
    InteractionHypothesis("H1", "momentum_3", "vwap_distance", 3, 0.0, 0.0,
                          "signed", "momentum effect differs above and below VWAP"),
    InteractionHypothesis("H2", "breakout", "realized_vol", 3, 1.0, 0.00015,
                          "magnitude", "breakout effect differs in high and low recent volatility"),
    InteractionHypothesis("H3", "reversion_z", "current_log_return", 3, 1.0, 0.00015,
                          "absolute", "reversion effect differs after large and ordinary returns"),
)


def _percentile(values, probability):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    low, high = floor(position), ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _summary(values):
    return {"n": len(values), "mean": mean(values) if values else None,
            "median": median(values) if values else None,
            "p10": _percentile(values, .1), "p90": _percentile(values, .9)}


def _signal_bucket(value, cutoff):
    if value is None or not isfinite(value):
        return None
    return "positive" if value >= cutoff and value > 0 else "negative" if value <= -cutoff and value < 0 else None


def _modifier_bucket(value, hypothesis):
    if value is None or not isfinite(value):
        return None
    if hypothesis.modifier_rule == "signed":
        return "high" if value > 0 else "low" if value < 0 else None
    if hypothesis.modifier_rule == "absolute":
        value = abs(value)
    if hypothesis.modifier_rule not in ("magnitude", "absolute"):
        raise ValueError("Unknown modifier rule")
    return "high" if value >= hypothesis.modifier_cutoff else "low"


def _effects(groups):
    def average(regime, sign):
        values = groups.get((regime, sign), ())
        return mean(values) if values else None
    high_pos, high_neg = average("high", "positive"), average("high", "negative")
    low_pos, low_neg = average("low", "positive"), average("low", "negative")
    if None in (high_pos, high_neg, low_pos, low_neg):
        return None
    high, low = high_pos - high_neg, low_pos - low_neg
    pooled_pos = groups[("high", "positive")] + groups[("low", "positive")]
    pooled_neg = groups[("high", "negative")] + groups[("low", "negative")]
    baseline = mean(pooled_pos) - mean(pooled_neg)
    return {"high_effect": high, "low_effect": low, "single_signal_baseline": baseline,
            "high_incremental_vs_baseline": high - baseline,
            "low_incremental_vs_baseline": low - baseline,
            "interaction": high - low}


def evaluate_interactions(
    features: tuple[FeatureRow, ...], labels: tuple[LabelRow, ...],
    session_partitions: Mapping[date, str], *, hypotheses=HYPOTHESES,
    split="evaluation", alpha=.05, seed=1701, replications=3000,
    min_cell_n=20, min_cell_sessions=5,
):
    """Evaluate a fixed family on nonoverlapping outcomes, resampling whole sessions.

    Outcome endpoints must have matching feature rows in the same session and split.
    Sparse four-cell tables produce no effect estimate, interval, or significance call.
    """
    if not 0 < alpha < 1 or replications < 100 or min_cell_n < 1 or min_cell_sessions < 2:
        raise ValueError("Invalid inference settings")
    hypotheses, features, labels = tuple(hypotheses), tuple(features), tuple(labels)
    if not hypotheses or len({h.id for h in hypotheses}) != len(hypotheses):
        raise ValueError("Hypothesis family must be nonempty with unique IDs")
    if not features or not labels:
        raise ValueError("Features and labels are required")
    feature_map = {row.decision_at: row for row in features}
    if len(feature_map) != len(features):
        raise ValueError("Duplicate feature timestamps")
    label_keys = {(row.decision_at, row.horizon_bars) for row in labels}
    if len(label_keys) != len(labels):
        raise ValueError("Duplicate decision/horizon labels")
    for row in features:
        if row.trading_date not in session_partitions:
            raise ValueError("Every feature session needs an explicit partition")
    if split not in set(session_partitions.values()):
        raise ValueError("Requested split is absent")
    for hypothesis in hypotheses:
        if (hypothesis.horizon_bars < 1 or hypothesis.signal_cutoff < 0 or
                hypothesis.modifier_cutoff < 0 or not isfinite(hypothesis.signal_cutoff) or
                not isfinite(hypothesis.modifier_cutoff) or
                hypothesis.modifier_rule not in ("signed", "magnitude", "absolute") or
                any(hypothesis.signal not in row.values or hypothesis.modifier not in row.values for row in features)):
            raise ValueError("Invalid or unavailable preregistered feature")
    for label in labels:
        start = feature_map.get(label.decision_at)
        if start is None:
            raise ValueError("Label has no decision feature")
        if label.forward_log_return is None:
            continue
        end = feature_map.get(label.outcome_at)
        if (end is None or end.trading_date != start.trading_date or
                session_partitions[end.trading_date] != session_partitions[start.trading_date] or
                label.outcome_at <= label.decision_at or not isfinite(label.forward_log_return)):
            raise ValueError("Outcome crosses a session/partition or has an invalid endpoint")
    selected = defaultdict(list)
    eligible = defaultdict(int)
    for horizon in {h.horizon_bars for h in hypotheses}:
        last_outcome = {}
        for label in sorted((x for x in labels if x.horizon_bars == horizon), key=lambda x: x.decision_at):
            row = feature_map[label.decision_at]
            if session_partitions[row.trading_date] != split or label.forward_log_return is None:
                continue
            if label.decision_at < last_outcome.get(row.trading_date, label.decision_at):
                continue
            last_outcome[row.trading_date] = label.outcome_at
            eligible[horizon] += 1
            for hypothesis in hypotheses:
                if hypothesis.horizon_bars != horizon:
                    continue
                sign = _signal_bucket(row.values[hypothesis.signal], hypothesis.signal_cutoff)
                regime = _modifier_bucket(row.values[hypothesis.modifier], hypothesis)
                if sign and regime:
                    selected[hypothesis.id].append((row.trading_date, regime, sign, label.forward_log_return))
    results = []
    # Six reported effect estimands per hypothesis share simultaneous coverage.
    interval_alpha = alpha / (len(hypotheses) * 6)
    for hypothesis in hypotheses:
        observations = selected[hypothesis.id]
        groups = defaultdict(list)
        sessions_by_cell = defaultdict(set)
        by_session = defaultdict(list)
        for day, regime, sign, outcome in observations:
            groups[(regime, sign)].append(outcome)
            sessions_by_cell[(regime, sign)].add(day)
            by_session[day].append((regime, sign, outcome))
        keys = ((regime, sign) for regime in ("high", "low") for sign in ("positive", "negative"))
        cells = [{"regime": regime, "signal": sign, "sessions": len(sessions_by_cell[(regime, sign)]),
                  **_summary(groups[(regime, sign)])} for regime, sign in keys]
        sufficient = all(cell["n"] >= min_cell_n and cell["sessions"] >= min_cell_sessions for cell in cells)
        effects = _effects(groups) if sufficient else None
        intervals = None
        p_adjusted = None
        valid_bootstraps = 0
        if effects is not None:
            rng = Random(seed + sum(ord(character) for character in hypothesis.id))
            days = sorted(by_session)
            replicates = defaultdict(list)
            for _ in range(replications):
                sample = defaultdict(list)
                for _ in days:
                    for regime, sign, outcome in by_session[rng.choice(days)]:
                        sample[(regime, sign)].append(outcome)
                estimate = _effects(sample)
                if estimate is not None:
                    for key, value in estimate.items():
                        replicates[key].append(value)
            valid_bootstraps = len(replicates["interaction"])
            if valid_bootstraps >= ceil(.95 * replications):
                intervals = {key: [_percentile(values, interval_alpha / 2),
                                   _percentile(values, 1 - interval_alpha / 2)]
                             for key, values in replicates.items()}
                observed = effects["interaction"]
                centered_tail = sum(abs(value - observed) >= abs(observed) - 1e-15
                                    for value in replicates["interaction"])
                p_adjusted = min(1.0, len(hypotheses) * (centered_tail + 1) / (valid_bootstraps + 1))
        results.append({"id": hypothesis.id, "signal": hypothesis.signal,
                        "modifier": hypothesis.modifier, "horizon_bars": hypothesis.horizon_bars,
                        "signal_cutoff": hypothesis.signal_cutoff,
                        "modifier_cutoff": hypothesis.modifier_cutoff,
                        "modifier_rule": hypothesis.modifier_rule,
                        "prediction": hypothesis.prediction, "cells": cells,
                        "sufficient": sufficient, "effects": effects,
                        "simultaneous_intervals": intervals,
                        "bonferroni_adjusted_p": p_adjusted,
                        "valid_bootstrap_replications": valid_bootstraps,
                        "interaction_detected": bool(intervals and
                            (intervals["interaction"][0] > 0 or intervals["interaction"][1] < 0))})
    return {"method": "fixed preregistered bins; same-session endpoints; nonoverlapping horizon grids; whole-session bootstrap; Bonferroni family",
            "split": split, "alpha_familywise": alpha, "hypotheses_tested": len(hypotheses),
            "per_interaction_test_alpha": alpha / len(hypotheses),
            "per_reported_interval_alpha": interval_alpha, "bootstrap_seed": seed,
            "bootstrap_replications": replications, "min_cell_n": min_cell_n,
            "min_cell_sessions": min_cell_sessions,
            "nonoverlapping_eligible_by_horizon": dict(sorted(eligible.items())),
            "results": results,
            "inference": "conditional association only; synthetic demonstration is not real-market alpha or profitability"}
