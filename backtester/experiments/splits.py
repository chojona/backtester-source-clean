"""Chronological planning from session dates, before outcomes are available."""

from dataclasses import asdict, dataclass
from datetime import date
from itertools import pairwise
from typing import Sequence

from .artifacts import canonical_json, digest


@dataclass(frozen=True)
class Fold:
    train: tuple[date, ...]
    embargo: tuple[date, ...]
    validation: tuple[date, ...]


@dataclass(frozen=True)
class ForwardPlan:
    eligible: tuple[date, ...]
    holdout_start: date
    minimum_train: int
    validation_size: int
    gap: int
    folds: tuple[Fold, ...]
    unused_development: tuple[date, ...]
    holdout_embargo: tuple[date, ...]
    holdout: tuple[date, ...]

    @property
    def sha256(self) -> str:
        return digest(canonical_json({"schema_version": 1, **asdict(self)}))


def plan_forward(eligible: Sequence[date], *, holdout_start: date, minimum_train: int,
                 validation_size: int, gap: int = 0) -> ForwardPlan:
    """Expand training, step by a fixed validation size, and reserve the final dates.

    Sizes and gaps count eligible sessions. Each validation window is complete.
    The holdout boundary is an explicit date, so exclusions cannot move it.
    """
    days = tuple(eligible)
    if (type(holdout_start) is not date or any(type(day) is not date for day in days)
            or any(a >= b for a, b in pairwise(days))):
        raise ValueError("Expected strictly increasing, unique eligible dates")
    if (any(type(size) is not int for size in (minimum_train, validation_size, gap))
            or min(minimum_train, validation_size) < 1 or gap < 0):
        raise ValueError("Invalid split sizes")
    development = tuple(day for day in days if day < holdout_start)
    holdout = days[len(development):]
    if not holdout or len(development) < minimum_train + 2 * gap + validation_size:
        raise ValueError("Need at least one full forward fold and a nonempty holdout")
    end = len(development) - gap
    first = minimum_train + gap
    starts = range(first, end - validation_size + 1, validation_size)
    folds = tuple(Fold(development[:start - gap], development[start - gap:start],
                       development[start:start + validation_size]) for start in starts)
    unused = development[starts[-1] + validation_size:end]
    return ForwardPlan(days, holdout_start, minimum_train, validation_size, gap,
                       folds, unused, development[end:], holdout)
