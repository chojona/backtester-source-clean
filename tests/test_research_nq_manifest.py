"""Deterministic and adversarial tests for exploratory NQ manifests."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from backtester.research_nq import ManifestError, validate_manifest
from backtester.research_nq.schema import SCHEMA_VERSION


def _sha(n: int = 1) -> str:
    return f"{n:064x}"


def valid_manifest(**overrides):
    document = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "synthetic-nq-m1-demo",
        "dataset_sha256": _sha(1),
        "instrument": "NQ",
        "contract": "NQZ26",
        "time_range": {
            "start_utc": "2026-01-02T00:00:00Z",
            "end_utc": "2026-01-02T01:00:00Z",
        },
        "source": {
            "provider": "SYNTHETIC",
            "locator": "memory://tests/test_research_nq_manifest",
            "acquisition_mode": "synthetic_constructed",
        },
        "coverage_classifications": [
            "observed",
            "provider_inferred_no_trade",
            "materialized",
            "unresolved",
        ],
        "calendar_identity": {
            "calendar_id": "synthetic-test-calendar",
            "calendar_sha256": _sha(2),
            "calendar_kind": "synthetic_test",
        },
        "strict_eligible": False,
        "lane": "exploratory",
        "limitations": ["synthetic constructed inputs only"],
    }
    document.update(overrides)
    return document


def test_valid_manifest_forces_non_certifying_lane():
    manifest = validate_manifest(valid_manifest())
    assert manifest.strict_eligible is False
    assert manifest.lane == "exploratory"
    assert manifest.instrument == "NQ"
    assert manifest.contract == "NQZ26"
    assert "observed" in manifest.coverage_classifications
    payload = manifest.to_dict()
    assert payload["strict_eligible"] is False
    assert payload["lane"] == "exploratory"


def test_load_manifest_roundtrip(tmp_path: Path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(valid_manifest()), encoding="utf-8")
    from backtester.research_nq import load_manifest

    loaded = load_manifest(path)
    assert loaded.dataset_id == "synthetic-nq-m1-demo"
    assert loaded.dataset_sha256 == _sha(1)


@pytest.mark.parametrize(
    "mutator,match",
    [
        (lambda d: d.__setitem__("strict_eligible", True), "strict_eligible"),
        (lambda d: d.__setitem__("lane", "strict"), "exploratory"),
        (lambda d: d.__setitem__("instrument", "ES"), "NQ"),
        (lambda d: d.__setitem__("contract", "ESZ26"), "contract"),
        (lambda d: d.__setitem__("dataset_sha256", "abc"), "dataset_sha256"),
        (lambda d: d.__setitem__("schema_version", "wrong"), "schema_version"),
        (lambda d: d.__setitem__("coverage_classifications", ["imaginary"]), "coverage"),
        (lambda d: d.__setitem__("coverage_classifications", []), "coverage"),
        (lambda d: d["time_range"].__setitem__("end_utc", "2026-01-01T00:00:00Z"), "precede"),
        (lambda d: d["source"].__setitem__("acquisition_mode", "live_broker"), "acquisition_mode"),
        (lambda d: d.__setitem__("extra_field", 1), "unknown"),
    ],
)
def test_adversarial_manifest_rejection(mutator, match):
    document = valid_manifest()
    mutator(document)
    with pytest.raises(ManifestError, match=match):
        validate_manifest(document)


def test_missing_required_identity_rejected():
    document = valid_manifest()
    del document["calendar_identity"]
    with pytest.raises(ManifestError, match="calendar_identity"):
        validate_manifest(document)


def test_naive_timestamps_rejected():
    document = valid_manifest()
    document["time_range"] = {
        "start_utc": "2026-01-02T00:00:00",
        "end_utc": "2026-01-02T01:00:00",
    }
    with pytest.raises(ManifestError, match="UTC"):
        validate_manifest(document)


def test_manifest_deepcopy_isolation():
    document = valid_manifest()
    manifest = validate_manifest(document)
    document["dataset_id"] = "mutated"
    assert manifest.dataset_id == "synthetic-nq-m1-demo"
    cloned = copy.deepcopy(manifest.to_dict())
    cloned["strict_eligible"] = True
    with pytest.raises(ManifestError):
        validate_manifest(cloned)
