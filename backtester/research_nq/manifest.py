"""Non-certifying exploratory dataset manifests.

Manifests describe local or synthetic exploratory inputs. They never enter
``PRODUCTION_MANIFESTS`` or ``config/approved_evidence.json``. Validation
forces ``strict_eligible=False`` and ``lane="exploratory"``.

Python validation and ``EXPLORATORY_MANIFEST_SCHEMA`` share one acceptance set.
All failures raise ``ManifestError`` whether or not ``jsonschema`` is installed.
Digests are shape-checked here; cryptographic binding of supplied bytes is
performed by ``binding.bind_inputs`` before adapter admission.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .schema import EXPLORATORY_MANIFEST_SCHEMA, SCHEMA_VERSION

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTRACT = re.compile(r"^NQ[FGHJKMNQUVXZ][0-9]{1,2}$")
_UTC_Z = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$")
_ALLOWED_CLASSES = frozenset({
    "observed",
    "provider_inferred_no_trade",
    "materialized",
    "unresolved",
})
_ALLOWED_MODES = frozenset({
    "synthetic_constructed",
    "local_licensed_readonly",
    "provider_capture_readonly",
})
_ALLOWED_CALENDAR_KINDS = frozenset({
    "synthetic_test",
    "dated_session",
    "history_bridge",
    "unpinned_local",
})


class ManifestError(ValueError):
    """Exploratory manifest is incomplete, inconsistent, or certification-seeking."""


def _require_stripped_string(value: Any, field: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"{field} must be a string")
    if value.strip() != value or not value.strip():
        raise ManifestError(f"{field} must be a nonempty non-whitespace string")
    if len(value) > max_length:
        raise ManifestError(f"{field} exceeds maxLength {max_length}")
    return value


def _utc_z(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not _UTC_Z.fullmatch(value):
        raise ManifestError(f"{field} must be an explicit UTC timestamp ending in Z")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ManifestError(f"{field} is not a valid UTC timestamp") from error
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise ManifestError(f"{field} must be explicit UTC")
    return stamp.astimezone(timezone.utc)


def _require_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ManifestError(f"{field} must be a lowercase 64-hex SHA-256 digest")
    return value


def _freeze_mapping(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(value, Mapping):
            frozen[key] = _freeze_mapping(value)
        elif isinstance(value, list):
            frozen[key] = tuple(value)
        else:
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise ManifestError(f"unsupported mutable manifest value for {key!r}")
            frozen[key] = value
    return MappingProxyType(frozen)


@dataclass(frozen=True)
class ExploratoryDatasetManifest:
    """Validated exploratory dataset identity.

    ``strict_eligible`` is always ``False``. Presence of a manifest never
    implies certification, trading authorization, or production acceptance.
    Digest fields are shape-validated only until ``binding.bind_inputs`` verifies
    the corresponding supplied bytes.
    """

    schema_version: str
    dataset_id: str
    dataset_sha256: str
    instrument: str
    contract: str
    time_range: Mapping[str, str]
    source: Mapping[str, str]
    coverage_classifications: tuple[str, ...]
    calendar_identity: Mapping[str, str]
    strict_eligible: bool
    lane: str
    content_sha256: str | None = None
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "dataset_sha256": self.dataset_sha256,
            "instrument": self.instrument,
            "contract": self.contract,
            "time_range": dict(self.time_range),
            "source": dict(self.source),
            "coverage_classifications": list(self.coverage_classifications),
            "calendar_identity": dict(self.calendar_identity),
            "strict_eligible": self.strict_eligible,
            "lane": self.lane,
        }
        if self.content_sha256 is not None:
            payload["content_sha256"] = self.content_sha256
        if self.limitations:
            payload["limitations"] = list(self.limitations)
        return payload


def _validate_with_jsonschema(document: Mapping[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError:
        return
    try:
        jsonschema.validate(instance=dict(document), schema=EXPLORATORY_MANIFEST_SCHEMA)
    except jsonschema.ValidationError as error:
        raise ManifestError(f"manifest schema validation failed: {error.message}") from error


def validate_manifest(document: Mapping[str, Any]) -> ExploratoryDatasetManifest:
    """Validate and freeze an exploratory manifest document."""
    if not isinstance(document, Mapping):
        raise ManifestError("manifest must be a mapping")
    unknown = set(document) - set(EXPLORATORY_MANIFEST_SCHEMA["properties"])
    if unknown:
        raise ManifestError(f"unknown manifest fields: {sorted(unknown)}")

    # Optional fields: null is rejected (schema has no null type).
    if "content_sha256" in document and document["content_sha256"] is None:
        raise ManifestError("content_sha256 must be a string when present")
    if "limitations" in document and document["limitations"] is None:
        raise ManifestError("limitations must be a list of non-empty strings")

    if document.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(f"schema_version must be {SCHEMA_VERSION}")
    if document.get("lane") != "exploratory":
        raise ManifestError("lane must be exploratory")
    if document.get("strict_eligible") is not False:
        raise ManifestError("exploratory manifests must declare strict_eligible=false")
    if document.get("instrument") != "NQ":
        raise ManifestError("instrument must be NQ")

    dataset_id = _require_stripped_string(document.get("dataset_id"), "dataset_id", max_length=256)
    dataset_sha256 = _require_sha(document.get("dataset_sha256"), "dataset_sha256")
    content_sha256 = document.get("content_sha256")
    if content_sha256 is not None:
        content_sha256 = _require_sha(content_sha256, "content_sha256")

    contract = document.get("contract")
    if not isinstance(contract, str) or not _CONTRACT.fullmatch(contract):
        raise ManifestError("contract must be an NQ futures symbol like NQZ26")

    time_range = document.get("time_range")
    if not isinstance(time_range, Mapping) or set(time_range) != {"start_utc", "end_utc"}:
        raise ManifestError("time_range requires exactly start_utc and end_utc")
    start = _utc_z(time_range.get("start_utc"), "time_range.start_utc")
    end = _utc_z(time_range.get("end_utc"), "time_range.end_utc")
    if start >= end:
        raise ManifestError("time_range start_utc must precede end_utc")

    source = document.get("source")
    if not isinstance(source, Mapping):
        raise ManifestError("source is required")
    source_unknown = set(source) - {"provider", "locator", "acquisition_mode", "notes"}
    if source_unknown:
        raise ManifestError(f"unknown source fields: {sorted(source_unknown)}")
    provider = _require_stripped_string(source.get("provider"), "source.provider", max_length=256)
    locator = _require_stripped_string(source.get("locator"), "source.locator", max_length=1024)
    mode = source.get("acquisition_mode")
    if mode not in _ALLOWED_MODES:
        raise ManifestError("unsupported source.acquisition_mode")
    notes = source.get("notes")
    if notes is not None:
        if not isinstance(notes, str):
            raise ManifestError("source.notes must be a string when present")
        if len(notes) > 4096:
            raise ManifestError("source.notes exceeds maxLength 4096")

    classes = document.get("coverage_classifications")
    if not isinstance(classes, list) or not classes:
        raise ManifestError("coverage_classifications must be a non-empty list")
    if len(set(classes)) != len(classes):
        raise ManifestError("coverage_classifications must be unique")
    if any(item not in _ALLOWED_CLASSES for item in classes):
        raise ManifestError("unsupported coverage classification")

    calendar = document.get("calendar_identity")
    if not isinstance(calendar, Mapping):
        raise ManifestError("calendar_identity is required")
    calendar_unknown = set(calendar) - {"calendar_id", "calendar_sha256", "calendar_kind"}
    if calendar_unknown:
        raise ManifestError(f"unknown calendar_identity fields: {sorted(calendar_unknown)}")
    calendar_id = _require_stripped_string(
        calendar.get("calendar_id"), "calendar_identity.calendar_id", max_length=256,
    )
    calendar_sha256 = _require_sha(calendar.get("calendar_sha256"), "calendar_identity.calendar_sha256")
    kind = calendar.get("calendar_kind", "unpinned_local")
    if kind not in _ALLOWED_CALENDAR_KINDS:
        raise ManifestError("unsupported calendar_identity.calendar_kind")

    if "limitations" not in document:
        limitations: list[str] = []
    else:
        limitations = document["limitations"]
    if not isinstance(limitations, list) or any(
            not isinstance(item, str) for item in limitations):
        raise ManifestError("limitations must be a list of non-empty strings")
    cleaned_limitations = [
        _require_stripped_string(item, "limitations[]", max_length=1024)
        for item in limitations
    ]

    _validate_with_jsonschema(document)

    frozen_source = {"provider": provider, "locator": locator, "acquisition_mode": mode}
    if notes is not None:
        frozen_source["notes"] = notes
    frozen_calendar = {
        "calendar_id": calendar_id,
        "calendar_sha256": calendar_sha256,
        "calendar_kind": kind,
    }
    return ExploratoryDatasetManifest(
        schema_version=SCHEMA_VERSION,
        dataset_id=dataset_id,
        dataset_sha256=dataset_sha256,
        instrument="NQ",
        contract=contract,
        time_range=MappingProxyType({
            "start_utc": start.isoformat().replace("+00:00", "Z"),
            "end_utc": end.isoformat().replace("+00:00", "Z"),
        }),
        source=_freeze_mapping(frozen_source),
        coverage_classifications=tuple(classes),
        calendar_identity=_freeze_mapping(frozen_calendar),
        strict_eligible=False,
        lane="exploratory",
        content_sha256=content_sha256,
        limitations=tuple(cleaned_limitations),
    )


def _load_json_unique(text: str) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ManifestError("Duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=unique)
    except ManifestError:
        raise
    except json.JSONDecodeError as error:
        raise ManifestError(f"manifest JSON is malformed: {error}") from error


def load_manifest(path: str | Path) -> ExploratoryDatasetManifest:
    """Load a manifest JSON document from disk (read-only path argument)."""
    payload = _load_json_unique(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ManifestError("manifest must be a JSON object")
    return validate_manifest(payload)


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hash_mapping(document: Mapping[str, Any]) -> str:
    """Hash a JSON-compatible mapping. Non-JSON values raise ``ManifestError``."""
    try:
        encoded = json.dumps(
            document, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ManifestError("hash_mapping requires JSON-compatible values") from error
    return hash_bytes(encoded)
