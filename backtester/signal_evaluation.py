"""Descriptive conditional outcome summaries, separate from signal generation."""
from collections import defaultdict
from math import floor, ceil, isfinite
from random import Random
from statistics import mean, median


# Fixed before observing labels. These are illustrative bins, not trained cutoffs.
DEFAULT_BINS = {
    "momentum_3": 0.0, "momentum_6": 0.0,
    "rolling_return_mean": 0.0, "reversion_z": 1.0,
    "breakout": 1.0, "vwap_distance": 0.0,
}


def _percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    at = (len(values) - 1) * p
    lo, hi = floor(at), ceil(at)
    return values[lo] + (values[hi] - values[lo]) * (at - lo)


def _bucket(value, cutoff):
    if cutoff == 0:
        return "positive" if value > 0 else "negative" if value < 0 else "neutral"
    return "positive" if value >= cutoff else "negative" if value <= -cutoff else "neutral"


def _simultaneous_interval(by_session, alpha, seed, replications):
    # Resample whole trading sessions: all observations from a session move together.
    if len(by_session) < 5:
        return None
    rng = Random(seed)
    sessions = list(by_session)
    estimates = []
    for _ in range(replications):
        sample = [x for _ in sessions for x in by_session[rng.choice(sessions)]]
        estimates.append(mean(sample))
    return [_percentile(estimates, alpha / 2), _percentile(estimates, 1 - alpha / 2)]


def compare_distributions(features, labels, bins=DEFAULT_BINS, *, alpha=0.05, seed=1701, replications=500):
    """Use fixed bins and a nonoverlapping decision grid per session and horizon.

    Bonferroni divides alpha across all requested feature/horizon/bucket cells.
    CIs are descriptive session-bootstrap intervals; sparse cells receive null.
    """
    if not 0 < alpha < 1 or replications < 100:
        raise ValueError("Invalid uncertainty settings")
    features = tuple(features)
    labels = tuple(labels)
    if not features or not labels or not bins or any(not isfinite(x) or x < 0 for x in bins.values()):
        raise ValueError("Nonempty features, labels, and nonnegative finite bins are required")
    feature_map = {row.decision_at: row for row in features}
    if len(feature_map) != len(features) or any(name not in features[0].values for name in bins):
        raise ValueError("Duplicate timestamps or unknown feature")
    if len({(row.decision_at, row.horizon_bars) for row in labels}) != len(labels):
        raise ValueError("Duplicate decision/horizon labels")
    if any(row.horizon_bars < 1 or (row.forward_log_return is not None and
           (not isfinite(row.forward_log_return) or row.outcome_at is None or row.outcome_at <= row.decision_at))
           for row in labels):
        raise ValueError("Invalid outcome timestamp or return")
    horizons = sorted({row.horizon_bars for row in labels})
    families = len(bins) * len(horizons) * 3
    selected = defaultdict(list)
    censored = defaultdict(int)
    nonoverlapping = defaultdict(int)
    for h in horizons:
        last_outcome = {}
        for label in sorted((x for x in labels if x.horizon_bars == h), key=lambda x: x.decision_at):
            row = feature_map.get(label.decision_at)
            if row is None:
                raise ValueError("Label has no matching feature timestamp")
            if label.forward_log_return is None:
                censored[h] += 1
                continue
            if label.decision_at < last_outcome.get(row.trading_date, label.decision_at):
                continue
            last_outcome[row.trading_date] = label.outcome_at
            nonoverlapping[h] += 1
            for name, cutoff in bins.items():
                value = row.values[name]
                if value is not None:
                    selected[(name, h, _bucket(value, cutoff))].append((row.trading_date, label.forward_log_return))
    cells = []
    contrasts = []
    for name, cutoff in bins.items():
        for h in horizons:
            for bucket in ("negative", "neutral", "positive"):
                observations = selected[(name, h, bucket)]
                values = [x for _, x in observations]
                by_session = defaultdict(list)
                for day, value in observations:
                    by_session[day].append(value)
                cells.append({
                    "feature": name, "cutoff": cutoff, "horizon_bars": h, "bucket": bucket,
                    "n": len(values), "sessions": len(by_session),
                    "mean": mean(values) if values else None,
                    "median": median(values) if values else None,
                    "p10": _percentile(values, .1), "p90": _percentile(values, .9),
                    "simultaneous_mean_interval": _simultaneous_interval(by_session, alpha / families,
                                                                           seed, replications),
                })
            negative = [value for _, value in selected[(name, h, "negative")]]
            positive = [value for _, value in selected[(name, h, "positive")]]
            contrasts.append({"feature": name, "horizon_bars": h,
                              "positive_minus_negative_mean": mean(positive) - mean(negative)
                              if positive and negative else None,
                              "positive_n": len(positive), "negative_n": len(negative),
                              "uncertainty": "descriptive contrast only; no interval or significance test"})
    return {
        "method": "fixed bins; same-session complete close-to-close labels; nonoverlapping grids per horizon; session bootstrap; Bonferroni across all requested cells",
        "alpha_familywise": alpha, "multiplicity_cells": families, "bootstrap_seed": seed,
        "bootstrap_replications": replications, "censored_by_horizon": dict(sorted(censored.items())),
        "nonoverlapping_eligible_by_horizon": dict(sorted(nonoverlapping.items())),
        "cells": cells, "contrasts": contrasts,
        "inference": "synthetic demonstration only; no alpha or profitability claim",
    }
