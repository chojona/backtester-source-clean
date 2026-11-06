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

M1-R requires cryptographic binding of dataset and calendar bytes, calendar-
backed complete-observation integrity, explicit availability provenance, and
Python/JSON Schema acceptance parity before exploratory admission.
"""

from .adapter import (
    AvailabilityProvenance,
    AvailabilityRecord,
    ExploratoryAdapterError,
    ReadOnlyExploratoryAdapter,
)
from .binding import (
    BindingError,
    bind_inputs,
    encode_calendar_document,
    encode_dataset_bars,
)
from .classifications import (
    BarAvailabilityClass,
    COMPLETE_OBSERVATION_ALLOWED,
    ClassificationError,
    classify_bar,
)
from .manifest import (
    ExploratoryDatasetManifest,
    ManifestError,
    hash_bytes,
    load_manifest,
    validate_manifest,
)

LANE = "exploratory"
STRICT_ELIGIBLE = False
VERSION = "research-nq-m1r.1.0.0"

__all__ = [
    "LANE",
    "STRICT_ELIGIBLE",
    "VERSION",
    "AvailabilityProvenance",
    "AvailabilityRecord",
    "BarAvailabilityClass",
    "COMPLETE_OBSERVATION_ALLOWED",
    "ClassificationError",
    "classify_bar",
    "BindingError",
    "bind_inputs",
    "encode_calendar_document",
    "encode_dataset_bars",
    "hash_bytes",
    "ExploratoryDatasetManifest",
    "ManifestError",
    "load_manifest",
    "validate_manifest",
    "ExploratoryAdapterError",
    "ReadOnlyExploratoryAdapter",
]
