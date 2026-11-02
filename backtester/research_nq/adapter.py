"""Read-only exploratory data adapter with decision-time availability.

The adapter never certifies datasets, never mutates bars or manifests, and
always reports ``strict_eligible=False``. Decision-time availability uses the
bar close (``timestamp + duration``) unless an explicit ``available_at`` is
supplied per bar. Analyses requiring complete observations reject any bar
outside ``COMPLETE_OBSERVATION_ALLOWED``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from backtester.data import Bar

from .classifications import (
    BarAvailabilityClass,
    COMPLETE_OBSERVATION_ALLOWED,
    classify_bar,
)
from .manifest import ExploratoryDatasetManifest, ManifestError, validate_manifest


class ExploratoryAdapterError(ValueError):
    """Adapter refused a request (availability, classification, or mutation)."""


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ExploratoryAdapterError("decision and availability times must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class AvailabilityRecord:
    """One bar viewed at a decision time with explicit availability metadata."""

    bar: Bar
    classification: BarAvailabilityClass
    available_at: datetime
    decision_utc: datetime
    available_for_decision: bool
    strict_eligible: bool = False
    lane: str = "exploratory"

    def as_dict(self) -> Mapping[str, object]:
        return MappingProxyType({
            "timestamp": self.bar.timestamp.isoformat().replace("+00:00", "Z"),
            "contract": self.bar.contract,
            "classification": self.classification.value,
            "available_at": self.available_at.isoformat().replace("+00:00", "Z"),
            "decision_utc": self.decision_utc.isoformat().replace("+00:00", "Z"),
            "available_for_decision": self.available_for_decision,
            "strict_eligible": False,
            "lane": "exploratory",
            "bar_state": self.bar.bar_state,
            "coverage_state": self.bar.coverage_state,
            "volume": self.bar.volume,
        })


class ReadOnlyExploratoryAdapter:
    """Immutable exploratory view over caller-supplied bars + validated manifest.

    Bars are provided by the caller (synthetic tests or local licensed paths
    outside this repository). This class does not download, regenerate, or
    rewrite historical captures.
    """

    def __init__(
        self,
        manifest: ExploratoryDatasetManifest | Mapping,
        bars: Sequence[Bar],
        *,
        available_at_by_timestamp: Mapping[datetime, datetime] | None = None,
    ):
        if isinstance(manifest, ExploratoryDatasetManifest):
            self._manifest = manifest
        else:
            self._manifest = validate_manifest(manifest)
        if self._manifest.strict_eligible is not False or self._manifest.lane != "exploratory":
            raise ManifestError("adapter requires non-certifying exploratory manifest")
        if not isinstance(bars, Sequence) or isinstance(bars, (str, bytes)):
            raise ExploratoryAdapterError("bars must be a sequence of Bar objects")
        frozen = tuple(bars)
        for bar in frozen:
            if not isinstance(bar, Bar):
                raise ExploratoryAdapterError("bars must contain only Bar instances")
            if bar.symbol != "NQ" or bar.contract != self._manifest.contract:
                raise ExploratoryAdapterError("bar instrument/contract must match manifest")
        self._bars = frozen
        overrides = {}
        for key, value in dict(available_at_by_timestamp or {}).items():
            overrides[_aware_utc(key)] = _aware_utc(value)
        self._available_at_overrides = MappingProxyType(overrides)
        self._locked = True

    @property
    def manifest(self) -> ExploratoryDatasetManifest:
        return self._manifest

    @property
    def strict_eligible(self) -> bool:
        return False

    @property
    def lane(self) -> str:
        return "exploratory"

    def __setattr__(self, name, value):
        if getattr(self, "_locked", False):
            raise ExploratoryAdapterError("ReadOnlyExploratoryAdapter is immutable")
        object.__setattr__(self, name, value)

    def _available_at(self, bar: Bar) -> datetime:
        override = self._available_at_overrides.get(_aware_utc(bar.timestamp))
        if override is not None:
            return override
        # Default decision-time availability: bar close (open + duration).
        return _aware_utc(bar.timestamp) + bar.duration

    def iter_records(self, decision_utc: datetime) -> Iterable[AvailabilityRecord]:
        decision = _aware_utc(decision_utc)
        for bar in self._bars:
            available_at = self._available_at(bar)
            yield AvailabilityRecord(
                bar=bar,
                classification=classify_bar(bar),
                available_at=available_at,
                decision_utc=decision,
                available_for_decision=available_at <= decision,
                strict_eligible=False,
                lane="exploratory",
            )

    def bars_available_at(self, decision_utc: datetime) -> tuple[AvailabilityRecord, ...]:
        """Return bars whose declared available_at is <= decision_utc."""
        return tuple(r for r in self.iter_records(decision_utc) if r.available_for_decision)

    def require_complete_observations(
        self,
        decision_utc: datetime,
        *,
        start_utc: datetime | None = None,
        end_utc: datetime | None = None,
    ) -> tuple[AvailabilityRecord, ...]:
        """Return available observed bars only; reject unsupported availability.

        Provider-inferred no-trade, materialized, and unresolved bars are
        refused for complete-observation analyses. Unknown future bars
        (available_at > decision) are also refused when they fall inside the
        requested window.
        """
        decision = _aware_utc(decision_utc)
        start = _aware_utc(start_utc) if start_utc is not None else None
        end = _aware_utc(end_utc) if end_utc is not None else None
        if start is not None and end is not None and start >= end:
            raise ExploratoryAdapterError("complete-observation window start must precede end")

        accepted: list[AvailabilityRecord] = []
        for record in self.iter_records(decision):
            stamp = _aware_utc(record.bar.timestamp)
            if start is not None and stamp < start:
                continue
            if end is not None and stamp >= end:
                continue
            if not record.available_for_decision:
                raise ExploratoryAdapterError(
                    f"bar at {stamp.isoformat()} not available at decision "
                    f"{decision.isoformat()} (available_at={record.available_at.isoformat()})"
                )
            if record.classification not in COMPLETE_OBSERVATION_ALLOWED:
                raise ExploratoryAdapterError(
                    f"complete observations reject classification "
                    f"{record.classification.value} at {stamp.isoformat()}"
                )
            accepted.append(record)
        return tuple(accepted)

    def classify_all(self) -> tuple[tuple[Bar, BarAvailabilityClass], ...]:
        return tuple((bar, classify_bar(bar)) for bar in self._bars)

    def describe(self) -> Mapping[str, object]:
        counts = {cls.value: 0 for cls in BarAvailabilityClass}
        for _, classification in self.classify_all():
            counts[classification.value] += 1
        return MappingProxyType({
            "lane": "exploratory",
            "strict_eligible": False,
            "dataset_id": self._manifest.dataset_id,
            "dataset_sha256": self._manifest.dataset_sha256,
            "instrument": self._manifest.instrument,
            "contract": self._manifest.contract,
            "bar_count": len(self._bars),
            "classification_counts": MappingProxyType(counts),
            "coverage_classifications": self._manifest.coverage_classifications,
            "calendar_identity": dict(self._manifest.calendar_identity),
        })
