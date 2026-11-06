"""Deterministic and adversarial tests for exploratory NQ manifests."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from backtester.research_nq import ManifestError, load_manifest, validate_manifest
from backtester.research_nq.schema import EXPLORATORY_MANIFEST_SCHEMA, SCHEMA_VERSION


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
    loaded = load_manifest(path)
    assert loaded.dataset_id == "synthetic-nq-m1-demo"
    assert loaded.dataset_sha256 == _sha(1)


def test_load_manifest_rejects_duplicate_json_keys(tmp_path: Path):
    path = tmp_path / "dup.json"
    path.write_text(
        '{"schema_version":"%s","dataset_id":"x","dataset_sha256":"%s",'
        '"dataset_sha256":"%s","instrument":"NQ","contract":"NQZ26",'
        '"time_range":{"start_utc":"2026-01-02T00:00:00Z","end_utc":"2026-01-02T01:00:00Z"},'
        '"source":{"provider":"SYNTHETIC","locator":"memory://dup","acquisition_mode":"synthetic_constructed"},'
        '"coverage_classifications":["observed"],'
        '"calendar_identity":{"calendar_id":"c","calendar_sha256":"%s"},'
        '"strict_eligible":false,"lane":"exploratory"}'
        % (SCHEMA_VERSION, "aa" * 32, "bb" * 32, "cc" * 32),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="Duplicate JSON key"):
        load_manifest(path)


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
        (lambda d: d.__setitem__("dataset_id", " "), "dataset_id|non-whitespace|pattern|schema"),
        (lambda d: d.__setitem__("dataset_id", "x" * 257), "maxLength|dataset_id|schema"),
        (lambda d: d.__setitem__("content_sha256", None), "content_sha256"),
        (lambda d: d.__setitem__("limitations", None), "limitations"),
        (lambda d: d["source"].__setitem__("notes", {"x": 1}), "notes"),
        (lambda d: d["time_range"].__setitem__("start_utc", "2026-01-02T00:00:00-05:00"), "UTC|pattern|schema"),
        (lambda d: d["time_range"].__setitem__("start_utc", "2026-01-02T00:00:00"), "UTC|pattern|schema"),
        (lambda d: d["time_range"].__setitem__("start_utc", "not-a-timestampZ"), "UTC|valid|schema"),
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


def test_python_and_jsonschema_parity_accept_and_reject():
    jsonschema = pytest.importorskip("jsonschema")
    good = valid_manifest()
    validate_manifest(good)
    jsonschema.validate(instance=good, schema=EXPLORATORY_MANIFEST_SCHEMA)

    rejects = [
        valid_manifest(dataset_id=" "),
        valid_manifest(dataset_id="x" * 257),
        {**valid_manifest(), "content_sha256": None},
        {**valid_manifest(), "limitations": None},
        {**valid_manifest(), "source": {**valid_manifest()["source"], "notes": {"x": 1}}},
        {**valid_manifest(), "time_range": {
            "start_utc": "2026-01-02T01:00:00Z",
            "end_utc": "2026-01-02T00:00:00Z",
        }},
    ]
    for document in rejects:
        with pytest.raises(ManifestError):
            validate_manifest(document)
        # Ordering (start < end) is enforced only in Python; schema still
        # accepts lexicographically valid UTC strings for that case alone.
        if document.get("time_range", {}).get("start_utc") == "2026-01-02T01:00:00Z":
            jsonschema.validate(instance=document, schema=EXPLORATORY_MANIFEST_SCHEMA)
            continue
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=document, schema=EXPLORATORY_MANIFEST_SCHEMA)


def test_python_validator_parity_without_jsonschema(monkeypatch):
    import builtins
    import backtester.research_nq.manifest as manifest_mod

    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "jsonschema" or name.startswith("jsonschema."):
            raise ImportError("simulated missing jsonschema")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    validate_manifest(valid_manifest())
    with pytest.raises(ManifestError, match="dataset_id|maxLength"):
        validate_manifest(valid_manifest(dataset_id="x" * 257))
    with pytest.raises(ManifestError, match="notes"):
        document = valid_manifest()
        document["source"]["notes"] = {"x": 1}
        validate_manifest(document)
    with pytest.raises(ManifestError, match="content_sha256"):
        validate_manifest({**valid_manifest(), "content_sha256": None})
    with pytest.raises(ManifestError, match="limitations"):
        validate_manifest({**valid_manifest(), "limitations": None})
    assert manifest_mod is not None
