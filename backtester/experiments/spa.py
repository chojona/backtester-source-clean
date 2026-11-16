"""Optional Hansen SPA diagnostic for complete, paired synthetic losses."""

from dataclasses import dataclass
from math import fsum, isfinite, log, sqrt
from statistics import mean
from typing import Mapping, Sequence

from .evaluation import stationary_indices


@dataclass(frozen=True)
class SPAResult:
    statistic: float
    lower_pvalue: float
    consistent_pvalue: float
    upper_pvalue: float
    mean_loss_advantages: tuple[tuple[str, float], ...]
    sessions: int
    draws: int


def _stationary_mean_se(centered: tuple[float, ...], block_length: int) -> float:
    """Conditional SE using circular autocovariances and restart probability."""
    size = len(centered)
    restart_survival = 1 - 1 / block_length
    variance = fsum(value**2 for value in centered) / size
    for lag in range(1, size):
        weight = restart_survival**lag
        if not weight:
            break
        covariance = fsum(value * centered[(index + lag) % size]
                          for index, value in enumerate(centered)) / size
        variance += 2 * (1 - lag / size) * weight * covariance
    if not isfinite(variance) or variance <= 0:
        raise ValueError("SPA requires positive long-run variance for every model")
    return sqrt(variance / size)


def hansen_spa(*, benchmark_loss: Sequence[float], model_losses: Mapping[str, Sequence[float]],
               draws: int, block_length: int, seed: int) -> SPAResult:
    """Use lower-is-better losses. A positive benchmark-minus-model mean favors the model.

    Hansen (2005) lower, consistent and upper recenterings share stationary
    draws and fixed studentizers. Count ties and apply an add-one correction.
    Missing or constant model differentials invalidate the complete panel.
    """
    benchmark = tuple(benchmark_loss)
    size = len(benchmark)
    if (size < 3 or not model_losses or type(draws) is not int or draws < 2
            or type(block_length) is not int or block_length < 1):
        raise ValueError("Invalid SPA design")
    averages, series, errors = {}, [], []
    for name, model in model_losses.items():
        if len(model) != size or any(type(value) not in (float, int) or not isfinite(value)
                                     for column in (benchmark, model) for value in column):
            raise ValueError("SPA requires finite paired losses on identical sessions")
        differential = tuple(b - m for b, m in zip(benchmark, model, strict=True))
        if any(not isfinite(value) for value in differential):
            raise ValueError("SPA loss differences must be finite")
        estimate = averages[name] = float(mean(differential))
        centered = tuple(value - estimate for value in differential)
        series.append(centered)
        errors.append(_stationary_mean_se(centered, block_length))

    scores = tuple(estimate / error for estimate, error in zip(averages.values(), errors, strict=True))
    statistic = max(0.0, *scores)
    threshold = -sqrt(2 * log(log(size)))
    shifts = (tuple(min(0.0, score) for score in scores),
              tuple(score if score <= threshold else 0.0 for score in scores),
              (0.0,) * len(scores))
    tails = [0, 0, 0]
    for indices in stationary_indices(size, draws, block_length, seed):
        boot = tuple(fsum(column[index] for index in indices) / size / error
                     for column, error in zip(series, errors, strict=True))
        for index, shift in enumerate(shifts):
            resampled = max(0.0, *(value + offset for value, offset in zip(boot, shift, strict=True)))
            tails[index] += resampled >= statistic
    lower, consistent, upper = ((count + 1) / (draws + 1) for count in tails)
    return SPAResult(statistic, lower, consistent, upper, tuple(averages.items()), size, draws)
