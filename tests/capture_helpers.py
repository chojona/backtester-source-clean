"""Synthetic plumbing helpers for QUA-24 capture tests.

These build hash-checked generic capture artifacts and mint verified bars
through an explicit *test* evidence registry (``_test_registry``). This is
plumbing only: production gates (calls without ``_test_registry``) consult
only ``config/approved_evidence.json`` and reject every fixture built
here. Never add a hash produced here to the production registry.
"""
import hashlib
import json
from pathlib import Path

from backtester.data import verify_open_interest_from_capture_artifacts
from backtester.evidence_registry import EvidenceRegistry


def write_capture_artifacts(bars, root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    observations = []
    for bar in bars:
        ns = int(bar.timestamp.timestamp()) * 1_000_000_000
        observations.append({
            "contract": bar.contract, "instrument_id": bar.instrument_id,
            "provider": bar.provider, "dataset": bar.dataset,
            "request_id": bar.request_id, "bar_timestamp": bar.timestamp.isoformat(),
            "bar_source_ts_event_ns": bar.source_ts_event_ns,
            "oi_source_ts_event_ns": ns - 2, "oi_source_ts_recv_ns": ns - 1,
            "quantity": bar.open_interest,
        })
    obs_path = root / "observations.jsonl"
    obs_path.write_text("".join(json.dumps(row) + "\n" for row in observations))
    first = bars[0]
    manifest = {
        "capture_complete": True, "provider": first.provider,
        "dataset": first.dataset, "request_id": first.request_id,
        "observations_file": "observations.jsonl",
        "files": {"observations.jsonl": hashlib.sha256(obs_path.read_bytes()).hexdigest()},
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def capture_test_registry(root):
    """Plumbing registry approving exactly the manifest in ``root``."""
    manifest_sha = hashlib.sha256((Path(root) / "manifest.json").read_bytes()).hexdigest()
    return EvidenceRegistry.for_testing(capture_manifest_sha256s=[manifest_sha])


def ledger_test_registry(ledger):
    """Plumbing registry approving exactly this (synthetic) ledger."""
    return EvidenceRegistry.for_testing(certification_ledgers=[{
        "ledger_sha256": ledger.ledger_sha256,
        "calendar_file_sha256": ledger.calendar_file_sha256,
        "calendar_document_sha256": ledger.calendar_document_sha256,
        "certification_version": ledger.certification_version}])


def verify_bars(bars, root):
    manifest_sha = write_capture_artifacts(bars, root)
    registry = EvidenceRegistry.for_testing(capture_manifest_sha256s=[manifest_sha])
    return [verify_open_interest_from_capture_artifacts(
                bar, root, expected_manifest_sha256=manifest_sha, _test_registry=registry)
            for bar in bars]
