"""Read-only exploratory data adapter with decision-time availability.

The adapter never certifies datasets, never mutates bars or manifests, and
always reports ``strict_eligible=False``. Admission requires cryptographic
binding of ``dataset_bytes`` and ``calendar_bytes`` (see ``binding.py``).

Availability provenance is explicit:

* ``assumed_bar_close`` — default retrospective assumption (open + duration)
* ``caller_declared_unverified`` — caller override; never establishes earlier
  availability than bar close and is refused by complete-observation analyses
* ``independently_verified_publication`` — publication time derived from
  independently supported evidence (``PROVIDER_AVAILABLE`` + ``source_ts_event_ns``)

Analyses requiring complete observations reject any bar outside
``COMPLETE_OBSERVATION_ALLOWED``, refuse incomplete grids, and keep assumed
availability visible on every record.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from backtester.data import Bar, validate
from backtester.sessions import SessionCalendar

from .binding import BindingError, bind_inputs
from .classifications import (
    BarAvailabilityClass,
    COMPLETE_OBSERVATION_ALLOWED,
    ClassificationError,
    classify_bar,
)
from .manifest import ExploratoryDatasetManifest, ManifestError, validate_manifest


class ExploratoryAdapterError(ValueError):
    """Adapter refused a request (availability, classification, or mutation)."""


class AvailabilityProvenance(str, Enum):
    ASSUMED_BAR_CLOSE = "assumed_bar_close"
    CALLER_DECLARED_UNVERIFIED = "caller_declared_unverified"
    INDEPENDENTLY_VERIFIED_PUBLICATION = "independently_verified_publication"


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ExploratoryAdapterError("decision and availability times must be timezone-aware")
    return value.astimezone(timezone.utc)


def _ns_to_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ExploratoryAdapterError("source_ts_event_ns must be a non-negative int when present")
    seconds, nanos = divmod(value, 1_000_000_000)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=nanos // 1000)


@dataclass(frozen=True)
class AvailabilityRecord:
    """One bar viewed at a decision time with explicit availability metadata."""

    bar: Bar
    classification: BarAvailabilityClass
    available_at: datetime
    decision_utc: datetime
    available_for_decision: bool
    availability_provenance: AvailabilityProvenance
    retrospective_assumption: bool
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
            "availability_provenance": self.availability_provenance.value,
            "retrospective_assumption": self.retrospective_assumption,
            "strict_eligible": False,
            "lane": "exploratory",
            "bar_state": self.bar.bar_state,
            "coverage_state": self.bar.coverage_state,
            "volume": self.bar.volume,
        })


class ReadOnlyExploratoryAdapter:
    """Immutable exploratory view over cryptographically bound bars + manifest.

    Bars are provided by the caller together with the dataset and calendar byte
    strings those digests claim to identify. This class does not download,
    regenerate, or rewrite historical captures.
    """

    def __init__(
        self,
        manifest: ExploratoryDatasetManifest | Mapping,
        bars: Sequence[Bar],
        *,
        dataset_bytes: bytes,
        calendar_bytes: bytes,
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
        for bar in bars:
            if not isinstance(bar, Bar):
                raise ExploratoryAdapterError("bars must contain only Bar instances")
            if bar.symbol != "NQ" or bar.contract != self._manifest.contract:
                raise ExploratoryAdapterError("bar instrument/contract must match manifest")
            evidence = bar.coverage_evidence
            if evidence is not None and not isinstance(evidence, str):
                raise ExploratoryAdapterError("coverage_evidence must be a string or null")

        try:
            frozen_bars, calendar, dataset_digest, calendar_digest = bind_inputs(
                dataset_sha256=self._manifest.dataset_sha256,
                content_sha256=self._manifest.content_sha256,
                calendar_sha256=self._manifest.calendar_identity["calendar_sha256"],
                dataset_bytes=dataset_bytes,
                calendar_bytes=calendar_bytes,
                bars=bars,
                source=self._manifest.source,
            )
        except BindingError as error:
            raise ExploratoryAdapterError(str(error)) from error

        self._bars = frozen_bars
        self._calendar = calendar
        self._dataset_digest = dataset_digest
        self._calendar_digest = calendar_digest
        overrides = {}
        for key, value in dict(available_at_by_timestamp or {}).items():
            overrides[_aware_utc(key)] = _aware_utc(value)
        self._available_at_overrides = MappingProxyType(overrides)
        self._locked = True

    @property
    def manifest(self) -> ExploratoryDatasetManifest:
        return self._manifest

    @property
    def calendar(self) -> SessionCalendar:
        return self._calendar

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

    def _resolve_availability(self, bar: Bar) -> tuple[datetime, AvailabilityProvenance, bool]:
        open_utc = _aware_utc(bar.timestamp)
        close_utc = open_utc + bar.duration
        override = self._available_at_overrides.get(open_utc)
        verified_publication = None
        if (
            bar.coverage_state == "PROVIDER_AVAILABLE"
            and bar.published
            and bar.source_ts_event_ns is not None
        ):
            verified_publication = _ns_to_utc(bar.source_ts_event_ns)

        if verified_publication is not None:
            if override is not None and override < verified_publication:
                raise ExploratoryAdapterError(
                    "caller override cannot establish earlier availability than "
                    "independently verified publication time"
                )
            return (
                verified_publication,
                AvailabilityProvenance.INDEPENDENTLY_VERIFIED_PUBLICATION,
                False,
            )

        if override is not None:
            if override < close_utc:
                raise ExploratoryAdapterError(
                    "caller override cannot establish earlier availability than bar close"
                )
            return (
                override,
                AvailabilityProvenance.CALLER_DECLARED_UNVERIFIED,
                True,
            )

        return (
            close_utc,
            AvailabilityProvenance.ASSUMED_BAR_CLOSE,
            True,
        )

    def iter_records(self, decision_utc: datetime) -> Iterable[AvailabilityRecord]:
        decision = _aware_utc(decision_utc)
        for bar in self._bars:
            try:
                classification = classify_bar(bar)
            except ClassificationError as error:
                raise ExploratoryAdapterError(str(error)) from error
            available_at, provenance, assumption = self._resolve_availability(bar)
            yield AvailabilityRecord(
                bar=bar,
                classification=classification,
                available_at=available_at,
                decision_utc=decision,
                available_for_decision=available_at <= decision,
                availability_provenance=provenance,
                retrospective_assumption=assumption,
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
        """Return a complete, calendar-valid observed window or raise.

        Successful return proves the requested interval is complete under the
        bound calendar and grid contract. Empty windows, missing expected
        minutes (including ``IntegrityReport.missing_intervals``), duplicates,
        overlaps, unsorted/off-grid timestamps, out-of-range bars, halt or
        out-of-session bars, mixed-session windows, unresolved calendar use,
        unsupported availability classes, and bars unavailable by decision time
        are rejected. Missing bars are never synthesized.
        """
        decision = _aware_utc(decision_utc)
        manifest_start = _aware_utc(datetime.fromisoformat(
            self._manifest.time_range["start_utc"].replace("Z", "+00:00")))
        manifest_end = _aware_utc(datetime.fromisoformat(
            self._manifest.time_range["end_utc"].replace("Z", "+00:00")))
        start = _aware_utc(start_utc) if start_utc is not None else manifest_start
        end = _aware_utc(end_utc) if end_utc is not None else manifest_end
        if start >= end:
            raise ExploratoryAdapterError("complete-observation window start must precede end")
        if start < manifest_start or end > manifest_end:
            raise ExploratoryAdapterError("complete-observation window exceeds manifest time_range")

        window_bars = [
            bar for bar in self._bars
            if start <= _aware_utc(bar.timestamp) < end
        ]
        if not window_bars:
            raise ExploratoryAdapterError("complete observations reject empty windows")

        for bar in window_bars:
            stamp = _aware_utc(bar.timestamp)
            if stamp < manifest_start or stamp >= manifest_end:
                raise ExploratoryAdapterError(
                    f"bar at {stamp.isoformat()} is outside the manifest interval"
                )
            if not self._calendar.valid_bar(stamp, bar.duration):
                raise ExploratoryAdapterError(
                    f"bar at {stamp.isoformat()} is outside permitted sessions or during a halt"
                )

        try:
            report = validate(window_bars, self._calendar)
        except ValueError as error:
            raise ExploratoryAdapterError(f"complete observations integrity failure: {error}") from error
        if report.missing_intervals:
            raise ExploratoryAdapterError(
                "complete observations reject missing expected minutes: "
                f"{report.missing_intervals}"
            )

        sessions = []
        for bar in window_bars:
            info = self._calendar.classify(_aware_utc(bar.timestamp))
            if info is None:
                raise ExploratoryAdapterError(
                    f"bar at {bar.timestamp.isoformat()} has unresolved calendar evidence"
                )
            sessions.append(info.session)
        if len(set(sessions)) != 1:
            raise ExploratoryAdapterError("complete observations reject mixed-session windows")

        accepted: list[AvailabilityRecord] = []
        for record in self.iter_records(decision):
            stamp = _aware_utc(record.bar.timestamp)
            if stamp < start or stamp >= end:
                continue
            if record.availability_provenance is AvailabilityProvenance.CALLER_DECLARED_UNVERIFIED:
                raise ExploratoryAdapterError(
                    f"complete observations reject caller-declared availability at {stamp.isoformat()}"
                )
            if not record.available_for_decision:
                raise ExploratoryAdapterError(
                    f"bar at {stamp.isoformat()} not available at decision "
                    f"{decision.isoformat()} (available_at={record.available_at.isoformat()}, "
                    f"provenance={record.availability_provenance.value})"
                )
            if record.classification not in COMPLETE_OBSERVATION_ALLOWED:
                raise ExploratoryAdapterError(
                    f"complete observations reject classification "
                    f"{record.classification.value} at {stamp.isoformat()}"
                )
            accepted.append(record)

        if not accepted:
            raise ExploratoryAdapterError("complete observations reject empty windows")
        if len(accepted) != len(window_bars):
            raise ExploratoryAdapterError(
                "complete observations could not admit every in-window bar"
            )
        return tuple(accepted)

    def classify_all(self) -> tuple[tuple[Bar, BarAvailabilityClass], ...]:
        try:
            return tuple((bar, classify_bar(bar)) for bar in self._bars)
        except ClassificationError as error:
            raise ExploratoryAdapterError(str(error)) from error

    def describe(self) -> Mapping[str, object]:
        counts = {cls.value: 0 for cls in BarAvailabilityClass}
        for _, classification in self.classify_all():
            counts[classification.value] += 1
        return MappingProxyType({
            "lane": "exploratory",
            "strict_eligible": False,
            "dataset_id": self._manifest.dataset_id,
            "dataset_sha256": self._dataset_digest,
            "calendar_sha256": self._calendar_digest,
            "instrument": self._manifest.instrument,
            "contract": self._manifest.contract,
            "bar_count": len(self._bars),
            "classification_counts": MappingProxyType(counts),
            "coverage_classifications": self._manifest.coverage_classifications,
            "calendar_identity": dict(self._manifest.calendar_identity),
            "availability_provenance_classes": tuple(
                item.value for item in AvailabilityProvenance
            ),
            "binding": MappingProxyType({
                "dataset_bytes_verified": True,
                "calendar_bytes_verified": True,
                "bar_sequence_reconciled": True,
            }),
        })
