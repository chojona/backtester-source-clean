"""Design sensitivity for a constructed two-component Gaussian AR(1) panel."""

from bisect import bisect_left
from dataclasses import dataclass
from itertools import pairwise
from math import isfinite, sqrt
from random import Random
from statistics import mean
from typing import Sequence

from .evaluation import stationary_indices


@dataclass(frozen=True)
class PowerPoint:
    effect: float
    rejections: int
    probability: float
    monte_carlo_ci95: tuple[float, float]


@dataclass(frozen=True)
class PowerAnalysis:
    points: tuple[PowerPoint, ...]
    minimum_detectable_effect: float | None
    simulations: int
    local_alpha: float
    target_power: float


def synthetic_power(*, sessions: int, sigma: float, rho: float, correlation: float,
                    effects: Sequence[float], simulations: int, draws: int,
                    block_length: int, seed: int, alpha: float = 0.05,
                    family_slots: int = 10, target_power: float = 0.8) -> PowerAnalysis:
    """Shift both outcomes equally and require both one-sided tests to reject.

    Sigma is the marginal session SD of each outcome. Alpha/family_slots targets
    the first Holm threshold. The MDE is the first grid point reaching target
    power by point estimate. A zero point estimates joint boundary rejection.
    """
    grid = tuple(effects)
    if (any(type(value) is not int for value in (sessions, simulations, draws, block_length, family_slots))
            or sessions < 2 or simulations < 2 or draws < 2 or min(block_length, family_slots) < 1
            or not 0 < alpha < 1 or not 0 < target_power < 1
            or not isfinite(sigma) or sigma <= 0 or not -1 < rho < 1 or not -1 <= correlation <= 1
            or not grid or any(not isfinite(effect) or effect < 0 for effect in grid)
            or any(a >= b for a, b in pairwise(grid))):
        raise ValueError("Invalid synthetic power design")
    local_alpha = alpha / family_slots
    if 1 / (draws + 1) > local_alpha:
        raise ValueError("Too few draws to resolve the requested local alpha")

    rng = Random(seed)
    innovation_scale = sqrt(1 - rho**2)
    independent_scale = sqrt(1 - correlation**2)
    counts = [0] * len(grid)
    for _ in range(simulations):
        left, right = rng.gauss(0, 1), rng.gauss(0, 1)
        panel = []
        for _ in range(sessions):
            panel.append((sigma * left, sigma * (correlation * left + independent_scale * right)))
            left = rho * left + innovation_scale * rng.gauss(0, 1)
            right = rho * right + innovation_scale * rng.gauss(0, 1)
        columns = tuple(zip(*panel, strict=True))
        estimates = tuple(map(mean, columns))
        indices = tuple(stationary_indices(sessions, draws, block_length, rng.getrandbits(64)))
        # Common random numbers across effects. The location shift cancels in
        # the centered resamples, so only the observed threshold changes.
        centered = [sorted(sum(column[i] for i in draw) / sessions - estimate for draw in indices)
                    for column, estimate in zip(columns, estimates, strict=True)]
        for index, effect in enumerate(grid):
            pvalue = max((1 + draws - bisect_left(samples, estimate + effect)) / (draws + 1)
                         for samples, estimate in zip(centered, estimates, strict=True))
            counts[index] += pvalue <= local_alpha

    def point(effect: float, count: int) -> PowerPoint:
        probability = count / simulations
        z = 1.959963984540054
        scale = 1 + z**2 / simulations
        center = (probability + z**2 / (2 * simulations)) / scale
        radius = z * sqrt(probability * (1 - probability) / simulations + z**2 / (4 * simulations**2)) / scale
        lower = center - radius if count else 0.0
        upper = center + radius if count < simulations else 1.0
        return PowerPoint(effect, count, probability, (lower, upper))

    points = tuple(point(effect, count) for effect, count in zip(grid, counts, strict=True))
    mde = next((result.effect for result in points if result.probability >= target_power), None)
    return PowerAnalysis(points, mde, simulations, local_alpha, target_power)
