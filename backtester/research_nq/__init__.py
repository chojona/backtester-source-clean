"""NQ exploratory research lane (non-certifying).

Lane contract
-------------
This package is an isolated exploratory research surface. It does not certify
historical datasets, does not authorize live or paper trading, and must not
mutate production trust roots (``PRODUCTION_MANIFESTS``,
``config/approved_evidence.json``).

Every exploratory output declares ``strict_eligible=False``. Analyses that
require complete observations must reject unknown or unsupported availability
classifications; observed, provider-inferred no-trade, materialized, and
unresolved bars remain distinct.

M1 scope stops at dataset identity, manifests, a read-only adapter with
decision-time availability semantics, and synthetic/adversarial tests.
"""

from .classifications import (
    BarAvailabilityClass,
    COMPLETE_OBSERVATION_ALLOWED,
    classify_bar,
)
from .manifest import (
    ExploratoryDatasetManifest,
    ManifestError,
    load_manifest,
    validate_manifest,
)
from .adapter import (
    AvailabilityRecord,
    ExploratoryAdapterError,
    ReadOnlyExploratoryAdapter,
)

LANE = "exploratory"
STRICT_ELIGIBLE = False
VERSION = "research-nq-m1.0.0"

__all__ = [
    "LANE",
    "STRICT_ELIGIBLE",
    "VERSION",
    "BarAvailabilityClass",
    "COMPLETE_OBSERVATION_ALLOWED",
    "classify_bar",
    "ExploratoryDatasetManifest",
    "ManifestError",
    "load_manifest",
    "validate_manifest",
    "AvailabilityRecord",
    "ExploratoryAdapterError",
    "ReadOnlyExploratoryAdapter",
]
