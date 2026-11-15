"""Session-level inference for constructed paired panels."""

from collections import Counter
from dataclasses import asdict, dataclass
from itertools import pairwise
from math import isfinite
from random import Random
from statistics import mean, quantiles
from typing import Iterator, Mapping, Sequence

from .ledger import SessionRow
from .protocol import FAMILY, Protocol


@dataclass(frozen=True)
class BootstrapResult:
    status: str
    eligible_sessions: int
    mean: float | None
    ci95: tuple[float, float] | None
    pvalue: float | None
    usable_draws: int


def stationary_indices(size: int, draws: int, block_length: int, seed: int) -> Iterator[tuple[int, ...]]:
    """Draw circular blocks with geometric lengths, carrying whole session rows."""
    if min(size, draws, block_length) < 1:
        raise ValueError("Bootstrap size, draw count and block length must be positive")
    rng = Random(seed)
    restart = 1 / block_length
    for _ in range(draws):
        index = rng.randrange(size)
        sample = [index]
        for _ in range(size - 1):
            index = rng.randrange(size) if rng.random() < restart else (index + 1) % size
            sample.append(index)
        yield tuple(sample)


def session_bootstrap(
    panel: Sequence[Mapping[str, float | None]], *, draws: int, block_length: int, seed: int,
) -> dict[str, BootstrapResult]:
    """Test means at a zero boundary null using shared index draws and per-column masks.

    Compress calendar rows missing in every component. Keep other rows in order and
    skip draws with no eligible sessions for a component. Use percentile intervals.
    """
    if not panel or not panel[0] or draws < 2 or block_length < 1:
        raise ValueError("Expected a nonempty panel, at least two draws and a positive block length")
    names = tuple(panel[0])
    if any(row.keys() != panel[0].keys() for row in panel):
        raise ValueError("Every row must carry the same component keys")
    if any(value is not None and not isfinite(value) for row in panel for value in row.values()):
        raise ValueError("Bootstrap outcomes must be finite")

    ordered = [row for row in panel if any(value is not None for value in row.values())]
    results = {}
    tested = {}
    for name in names:
        series = [row[name] for row in ordered]
        observed = [value for value in series if value is not None]
        size = len(observed)
        estimate = float(mean(observed)) if observed else None
        if size < 2:
            results[name] = BootstrapResult("insufficient_sessions", size, estimate, None, None, 0)
        elif min(observed) == max(observed):
            results[name] = BootstrapResult("constant_series", size, estimate, (estimate, estimate), None, 0)
        else:
            tested[name] = (series, size, estimate, [])

    if tested:
        for indices in stationary_indices(len(ordered), draws, block_length, seed):
            for series, _, _, samples in tested.values():
                values = [series[index] for index in indices if series[index] is not None]
                if values:
                    samples.append(sum(values) / len(values))
    for name, (_, size, estimate, samples) in tested.items():
        usable = len(samples)
        if usable < 2:
            results[name] = BootstrapResult("insufficient_draws", size, estimate, None, None, usable)
            continue
        # Subtracting the observed mean centers the bootstrap at the boundary null.
        tail = sum(sample - estimate >= estimate for sample in samples)
        interval = quantiles(samples, n=40, method="inclusive")
        results[name] = BootstrapResult("tested", size, estimate, (interval[0], interval[-1]),
                                        (1 + tail) / (1 + usable), usable)
    return {name: results[name] for name in names}


def joint_pvalue(components: Sequence[float | None]) -> float | None:
    if not components or any(value is None for value in components):
        return None
    if any(not 0 <= value <= 1 for value in components):
        raise ValueError("Invalid component p-value")
    return max(components)


def holm(pvalues: Mapping[str, float]) -> dict[str, float]:
    """Adjust over all supplied slots, enforcing monotonic adjusted p-values."""
    if any(not 0 <= value <= 1 for value in pvalues.values()):
        raise ValueError("Invalid family p-value")
    adjusted = {}
    previous = 0.0
    for rank, (name, value) in enumerate(sorted(pvalues.items(), key=lambda entry: entry[1])):
        previous = min(1.0, max(previous, (len(pvalues) - rank) * value))
        adjusted[name] = previous
    return {name: adjusted[name] for name in pvalues}


def evaluate(rows: Sequence[SessionRow], protocol: Protocol) -> dict:
    base = [row for row in rows if row.scenario_id == "base"]
    if not base or any(left.day >= right.day for left, right in pairwise(base)):
        raise ValueError("Base rows must have unique, strictly increasing session dates")
    panel = [{"absolute_net_cents": row.candidate_net_cents, "uplift_cents": row.uplift_cents}
             for row in base]
    estimates = {
        str(length): session_bootstrap(panel, draws=protocol.bootstrap_draws, block_length=length,
                                       seed=protocol.seed)
        for length in protocol.block_lengths
    }
    primary = estimates[str(protocol.block_lengths[0])]
    joint = joint_pvalue([result.pvalue for result in primary.values()])
    adjusted = holm({name: joint if name == protocol.id and joint is not None else 1.0 for name in FAMILY})

    def conditional(reason):
        trades = [row.benchmark_net_cents for row in base
                  if row.decision_reason == reason and row.eligible and row.benchmark_status == "filled"]
        return {"filled_sessions": len(trades), "mean_benchmark_net_cents": float(mean(trades)) if trades else None}

    return {
        "stage": "synthetic",
        "claim_status": "fixture_only",
        "calendar_sessions": len(base),
        "eligible_sessions": sum(row.eligible for row in base),
        "decision_counts": dict(Counter(row.decision_reason for row in base)),
        "conditional_base_benchmark": {reason: conditional(reason) for reason in ("accepted", "rejected")},
        "bootstrap": {length: {name: asdict(result) for name, result in components.items()}
                      for length, components in estimates.items()},
        "family": [
            {"id": name, "status": "synthetic_test" if name == protocol.id and joint is not None else "untested",
             "joint_pvalue": joint if name == protocol.id else None,
             "holm_input_pvalue": joint if name == protocol.id and joint is not None else 1.0,
             "holm_pvalue": adjusted[name] if name == protocol.id and joint is not None else None}
            for name in FAMILY
        ],
    }
