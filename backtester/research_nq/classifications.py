"""Bar availability classifications for the exploratory NQ lane.

These labels preserve distinctions that certification and audit code already
treat carefully in the original environment:

* ``observed`` — a published traded bar with positive volume evidence.
* ``provider_inferred_no_trade`` — absence under provider-available coverage,
  without grid materialization (inference only; not independent confirmation).
* ``materialized`` — an explicit previous-price grid fill under a materialize
  policy. Distinct from both observed trades and unmaterialized inference.
* ``unresolved`` — unknown/unsupported coverage, unpriced no-trade, or any
  state that cannot be adjudicated from retained evidence.

Analyses that require complete observations may consume only
``COMPLETE_OBSERVATION_ALLOWED`` classes and must fail closed otherwise.
"""
from __future__ import annotations

from enum import Enum

from backtester.data import Bar


class BarAvailabilityClass(str, Enum):
    OBSERVED = "observed"
    PROVIDER_INFERRED_NO_TRADE = "provider_inferred_no_trade"
    MATERIALIZED = "materialized"
    UNRESOLVED = "unresolved"


COMPLETE_OBSERVATION_ALLOWED = frozenset({
    BarAvailabilityClass.OBSERVED,
})

SUPPORTED_COVERAGE_FOR_INFERENCE = frozenset({"PROVIDER_AVAILABLE"})


def classify_bar(bar: Bar) -> BarAvailabilityClass:
    """Map a ``Bar`` onto the exploratory availability taxonomy.

    Classification is descriptive only. It never promotes unresolved absence
    into no-trade, and never treats materialized fills as observed trades.
    """
    evidence = str(getattr(bar, "coverage_evidence", "") or "")
    if "materialization" in evidence.lower():
        return BarAvailabilityClass.MATERIALIZED
    if bar.bar_state == "TRADED" and bar.volume > 0 and bar.published:
        return BarAvailabilityClass.OBSERVED
    if (
        bar.bar_state == "NO_TRADE"
        and bar.coverage_state in SUPPORTED_COVERAGE_FOR_INFERENCE
        and bar.volume == 0
        and not bar.published
    ):
        return BarAvailabilityClass.PROVIDER_INFERRED_NO_TRADE
    return BarAvailabilityClass.UNRESOLVED
