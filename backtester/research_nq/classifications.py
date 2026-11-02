"""Bar availability classifications for the exploratory NQ lane.

These labels preserve distinctions that certification and audit code already
treat carefully in the original environment:

* ``observed`` — published traded bar with positive volume **and** supported
  ``PROVIDER_AVAILABLE`` coverage evidence. ``UNVERIFIED`` / ``UNKNOWN`` never
  promote to observed solely because a bar is published with volume.
* ``provider_inferred_no_trade`` — absence under provider-available coverage
  with explicit supporting inference evidence, without grid materialization.
* ``materialized`` — explicit previous-price grid fill under a materialize
  policy, identified by exact structured materialization evidence.
* ``unresolved`` — unknown/unsupported coverage, unpriced no-trade, or any
  state that cannot be adjudicated from retained evidence.

Analyses that require complete observations may consume only
``COMPLETE_OBSERVATION_ALLOWED`` classes and must fail closed otherwise.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from backtester.data import Bar


class BarAvailabilityClass(str, Enum):
    OBSERVED = "observed"
    PROVIDER_INFERRED_NO_TRADE = "provider_inferred_no_trade"
    MATERIALIZED = "materialized"
    UNRESOLVED = "unresolved"


COMPLETE_OBSERVATION_ALLOWED = frozenset({
    BarAvailabilityClass.OBSERVED,
})

SUPPORTED_COVERAGE_FOR_OBSERVED = frozenset({"PROVIDER_AVAILABLE"})
SUPPORTED_COVERAGE_FOR_INFERENCE = frozenset({"PROVIDER_AVAILABLE"})

# Exact materialization token used by providers/databento.py. Substring checks
# that would match "no materialization" are intentionally not used.
MATERIALIZATION_TOKEN = "explicit previous-traded-price grid materialization"

# Evidence that supports provider-inferred no-trade (must appear verbatim).
PROVIDER_INFERRED_EVIDENCE_TOKEN = (
    "Complete untruncated stream + provider daily condition=available"
)

# Evidence that forbids promoting a NO_TRADE bar to provider-inferred.
UNRESOLVED_NO_TRADE_MARKERS = (
    "unresolved",
    "do not treat as no-trade",
)


class ClassificationError(ValueError):
    """Coverage evidence is unsupported or contradictory for classification."""


def _evidence_string(evidence: Any) -> str | None:
    if evidence is None:
        return None
    if isinstance(evidence, str):
        return evidence
    raise ClassificationError("coverage_evidence must be a string or null")


def _is_materialized(evidence: str | None) -> bool:
    if evidence is None:
        return False
    if evidence == MATERIALIZATION_TOKEN:
        return True
    # Structured append form used by databento materialize policy.
    return evidence.endswith("; " + MATERIALIZATION_TOKEN)


def _supports_provider_inferred(evidence: str | None) -> bool:
    if evidence is None:
        return False
    lowered = evidence.lower()
    if any(marker in lowered for marker in UNRESOLVED_NO_TRADE_MARKERS):
        return False
    return PROVIDER_INFERRED_EVIDENCE_TOKEN in evidence


def classify_bar(bar: Bar) -> BarAvailabilityClass:
    """Map a ``Bar`` onto the exploratory availability taxonomy.

    Classification is descriptive only. It never promotes unresolved absence
    into no-trade, never treats materialized fills as observed trades, and
    never promotes ``UNVERIFIED`` / ``UNKNOWN`` coverage to observed.
    """
    evidence = _evidence_string(getattr(bar, "coverage_evidence", None))

    # Exact materialization evidence wins over inferred no-trade text that may
    # precede the materialization token in provider append form.
    if _is_materialized(evidence):
        if bar.bar_state == "TRADED" and bar.volume > 0 and bar.published:
            raise ClassificationError("contradictory materialization and traded evidence")
        return BarAvailabilityClass.MATERIALIZED

    observed_shape = (
        bar.bar_state == "TRADED"
        and bar.volume > 0
        and bar.published
        and bar.coverage_state in SUPPORTED_COVERAGE_FOR_OBSERVED
    )
    inferred_shape = (
        bar.bar_state == "NO_TRADE"
        and bar.coverage_state in SUPPORTED_COVERAGE_FOR_INFERENCE
        and bar.volume == 0
        and not bar.published
        and _supports_provider_inferred(evidence)
    )
    if observed_shape and inferred_shape:
        raise ClassificationError("contradictory observed and no-trade classifications")
    if observed_shape:
        return BarAvailabilityClass.OBSERVED
    if inferred_shape:
        return BarAvailabilityClass.PROVIDER_INFERRED_NO_TRADE
    return BarAvailabilityClass.UNRESOLVED
