"""Canonical market evidence policy v1. Offline; hashes never imply acceptance.

Production acceptance pins are deliberately empty. Adding an independently
reviewed manifest requires a separate reviewed code change, not a JSON flag.
Mathematical synthetic helpers elsewhere are not historical entry points.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

VERSION = "canonical-market-data-v1.0.0"
PRODUCTION_MANIFESTS = MappingProxyType({})
BASE = frozenset({"raw_integrity", "identity", "actual_calendar", "coverage",
                  "provenance", "revisions", "availability", "clock"})
RESEARCH = MappingProxyType({
    "HAR-RV": frozenset({"rv_definition", "rv_binding", "session_continuity"}),
    "VWAP": frozenset({"trade_notional", "complete_volume", "trade_conditions"}),
    "signal": frozenset({"feature_timing", "execution_timing", "partitions"}),
})
INSTRUMENT = MappingProxyType({
    "NQ": frozenset({"listing_roster", "predecessor_volume", "causal_selector"}),
    "SPY": frozenset({"corporate_actions", "venue_scope"}),
})
STATES = frozenset({"strict-certified", "exploratory", "rejected", "unresolved"})


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def utc(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise ValueError("Explicit UTC bounds required")
    return stamp


def required_claims(instrument, research):
    if instrument not in INSTRUMENT or research not in RESEARCH:
        raise ValueError("Unknown instrument or research profile")
    return BASE | INSTRUMENT[instrument] | RESEARCH[research]


def _assess(interval, research, evidence, accepted):
    """Diagnostic engine; accepted claim pins must come from outside the bundle.

    A claim pins exact instrument, interval, research profile, dataset, source
    bytes and independent review. Tests supply synthetic pins here only.
    """
    claims = required_claims(interval["instrument"], research)
    start, end = utc(interval["start"]), utc(interval["end"])
    if start >= end or interval["state"] not in STATES:
        raise ValueError("Invalid interval or classification")
    if interval["instrument"] == "SPY":
        ny = ZoneInfo("America/New_York")
        first, last = start.astimezone(ny).date(), (end-timedelta(microseconds=1)).astimezone(ny).date()
        if first <= datetime(2025, 12, 31).date() and last >= datetime(2025, 1, 1).date():
            return {"state": "rejected", "eligible": False, "reasons": ["SPY_2025_HOLDOUT"]}
        if first <= datetime(2024, 1, 11).date() <= last:
            return {"state": "rejected", "eligible": False, "reasons": ["PROHIBITED_JANUARY_11"]}
    missing = []
    refs = interval.get("evidence", {})
    for claim in sorted(claims):
        ref = refs.get(claim)
        record = evidence.get(ref) if isinstance(ref, str) else None
        expected = {
            "claim": claim, "instrument": interval["instrument"],
            "start": interval["start"], "end": interval["end"],
            "research": research, "dataset_sha256": interval.get("dataset_sha256"),
        }
        if (not record or any(record.get(k) != v for k, v in expected.items())
                or not _hash(record.get("source_sha256"))
                or not _hash(interval.get("dataset_sha256"))
                or not record.get("locator") or not record.get("review_id")
                or record.get("reviewer") == record.get("producer")
                or not record.get("reviewer") or not record.get("producer")
                or accepted.get(ref) != record):
            missing.append(claim)
    state = interval["state"]
    eligible = state == "strict-certified" and not missing
    return {"state": "unresolved" if state == "strict-certified" and missing else state,
            "eligible": eligible, "reasons": missing}


def assess_interval(interval, research, evidence):
    """Public diagnostic never accepts bundle-supplied semantic approvals."""
    return _assess(interval, research, evidence, {})


def _load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def require_strict_dataset(dataset_path, manifest_path, *, instrument, research):
    """Historical admission gate. Reject untrusted manifests before data reads.

    Trust pins bind exact manifest bytes, research and instrument. There is no
    allow-exploratory switch and no caller-provided production trust dictionary.
    """
    required_claims(instrument, research)
    if manifest_path is None:
        raise ValueError("Strict certification NO-GO: independently accepted manifest required")
    pin = sha256(manifest_path)
    authorization = PRODUCTION_MANIFESTS.get((pin, instrument, research))
    if authorization is None:
        raise ValueError("Strict certification NO-GO: no independent production acceptance")
    return _validate_manifest(dataset_path, manifest_path, instrument=instrument,
                              research=research, authorization=authorization)


def _validate_manifest(dataset_path, manifest_path, *, instrument, research, authorization):
    """Private verification engine, also used with synthetic acceptance fixtures."""
    manifest = _load_json(manifest_path)
    if manifest.get("version") != VERSION or manifest.get("dataset_sha256") != sha256(dataset_path):
        raise ValueError("Unversioned or changed dataset")
    sources = manifest.get("sources", {})
    if not sources:
        raise ValueError("No independently reviewed source files")
    for source in sources.values():
        path = Path(source["path"])
        if not path.is_absolute():
            path = Path(manifest_path).parent / path
        if path.resolve() in {Path(manifest_path).resolve(), Path(dataset_path).resolve()}:
            raise ValueError("Self-referential independent evidence")
        if not _hash(source.get("sha256")) or sha256(path) != source["sha256"]:
            raise ValueError("Changed evidence source")
    for evidence in manifest.get("evidence", {}).values():
        source = sources.get(evidence.get("source_id"))
        if not source or evidence.get("source_sha256") != source["sha256"]:
            raise ValueError("Evidence reference not bound to verified source bytes")
    intervals = manifest.get("intervals", [])
    if not intervals:
        raise ValueError("Empty certification manifest")
    previous = None
    for interval in intervals:
        if (interval["instrument"] != instrument
                or interval.get("dataset_sha256") != manifest["dataset_sha256"]
                or previous is not None and utc(interval["start"]) < previous):
            raise ValueError("Mixed, overlapping or unordered intervals")
        result = _assess(interval, research, manifest.get("evidence", {}), authorization)
        if not result["eligible"]:
            raise ValueError("Uncertified interval in strict research")
        previous = utc(interval["end"])
    return manifest


def classify_absence(*, active, observed, independently_proven_no_trade=False):
    """No filling; the caller must bind any no-trade claim to independent evidence."""
    if observed:
        return "observed" if active else "out-of-schedule-unresolved"
    if not active:
        return "scheduled-closure"
    return "confirmed-no-trade" if independently_proven_no_trade else "missing-or-unresolved"
