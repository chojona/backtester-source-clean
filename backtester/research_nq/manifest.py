"""Non-certifying exploratory dataset manifests.

Manifests describe local or synthetic exploratory inputs. They never enter
``PRODUCTION_MANIFESTS`` or ``config/approved_evidence.json``. Validation
forces ``strict_eligible=False`` and ``lane="exploratory"``.
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


def _utc(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise ManifestError("time_range bounds must be explicit UTC")
    return stamp.astimezone(timezone.utc)


def _require_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ManifestError(f"{field} must be a lowercase 64-hex SHA-256 digest")
    return value


@dataclass(frozen=True)
class ExploratoryDatasetManifest:
    """Validated exploratory dataset identity.

    ``strict_eligible`` is always ``False``. Presence of a manifest never
    implies certification, trading authorization, or production acceptance.
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


def validate_manifest(document: Mapping[str, Any]) -> ExploratoryDatasetManifest:
    """Validate and freeze an exploratory manifest document."""
    if not isinstance(document, Mapping):
        raise ManifestError("manifest must be a mapping")
    unknown = set(document) - set(EXPLORATORY_MANIFEST_SCHEMA["properties"])
    if unknown:
        raise ManifestError(f"unknown manifest fields: {sorted(unknown)}")

    if document.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(f"schema_version must be {SCHEMA_VERSION}")
    if document.get("lane") != "exploratory":
        raise ManifestError("lane must be exploratory")
    if document.get("strict_eligible") is not False:
        raise ManifestError("exploratory manifests must declare strict_eligible=false")
    if document.get("instrument") != "NQ":
        raise ManifestError("instrument must be NQ")

    dataset_id = document.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ManifestError("dataset_id is required")
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
    start = _utc(str(time_range["start_utc"]))
    end = _utc(str(time_range["end_utc"]))
    if start >= end:
        raise ManifestError("time_range start_utc must precede end_utc")

    source = document.get("source")
    if not isinstance(source, Mapping):
        raise ManifestError("source is required")
    source_unknown = set(source) - {"provider", "locator", "acquisition_mode", "notes"}
    if source_unknown:
        raise ManifestError(f"unknown source fields: {sorted(source_unknown)}")
    for field in ("provider", "locator", "acquisition_mode"):
        if not isinstance(source.get(field), str) or not source[field].strip():
            raise ManifestError(f"source.{field} is required")
    if source["acquisition_mode"] not in _ALLOWED_MODES:
        raise ManifestError("unsupported source.acquisition_mode")

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
    if not isinstance(calendar.get("calendar_id"), str) or not calendar["calendar_id"].strip():
        raise ManifestError("calendar_identity.calendar_id is required")
    _require_sha(calendar.get("calendar_sha256"), "calendar_identity.calendar_sha256")
    kind = calendar.get("calendar_kind", "unpinned_local")
    if kind not in _ALLOWED_CALENDAR_KINDS:
        raise ManifestError("unsupported calendar_identity.calendar_kind")

    limitations = document.get("limitations", [])
    if limitations is None:
        limitations = []
    if not isinstance(limitations, list) or any(
            not isinstance(item, str) or not item.strip() for item in limitations):
        raise ManifestError("limitations must be a list of non-empty strings")

    try:
        import jsonschema
    except ImportError:
        pass
    else:
        jsonschema.validate(instance=dict(document), schema=EXPLORATORY_MANIFEST_SCHEMA)

    frozen_calendar = dict(calendar)
    frozen_calendar.setdefault("calendar_kind", "unpinned_local")
    return ExploratoryDatasetManifest(
        schema_version=SCHEMA_VERSION,
        dataset_id=dataset_id.strip(),
        dataset_sha256=dataset_sha256,
        instrument="NQ",
        contract=contract,
        time_range=MappingProxyType({
            "start_utc": start.isoformat().replace("+00:00", "Z"),
            "end_utc": end.isoformat().replace("+00:00", "Z"),
        }),
        source=MappingProxyType(dict(source)),
        coverage_classifications=tuple(classes),
        calendar_identity=MappingProxyType(frozen_calendar),
        strict_eligible=False,
        lane="exploratory",
        content_sha256=content_sha256,
        limitations=tuple(limitations),
    )


def load_manifest(path: str | Path) -> ExploratoryDatasetManifest:
    """Load a manifest JSON document from disk (read-only path argument)."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_manifest(payload)


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hash_mapping(document: Mapping[str, Any]) -> str:
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hash_bytes(encoded)
