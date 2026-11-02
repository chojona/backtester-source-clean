"""Cryptographic binding and calendar/dataset reconciliation for exploratory NQ.

Binding contract (M1-R)
-----------------------
A bound exploratory admission requires all of the following:

1. ``calendar_bytes`` — UTF-8 JSON document describing the reviewed
   ``SessionCalendar`` inputs. ``sha256(calendar_bytes)`` must equal
   ``manifest.calendar_identity.calendar_sha256``. The document is decoded into
   a ``SessionCalendar``; unresolved or unsupported calendar kinds without
   bytes are rejected.

2. ``dataset_bytes`` — UTF-8 JSON array of canonical bar records (see
   ``canonical_bar_record``). ``sha256(dataset_bytes)`` must equal
   ``manifest.dataset_sha256``. If ``content_sha256`` is present it must also
   equal that digest (content identity is the same byte string for this lane).

3. Caller-supplied ``Bar`` objects must reconcile field-for-field with the
   decoded dataset records. Hashing an unrelated file that merely matches the
   hex shape of ``dataset_sha256`` is insufficient: the bar sequence itself
   must decode from the verified bytes.

4. ``source.provider`` / ``source.dataset`` identity on each bar must match the
   manifest source identity. ``synthetic_constructed`` may not admit bars that
   claim a live licensed provider identity unless the manifest source names
   that provider.

Digests are lowercase hex SHA-256 of the exact supplied bytes. A syntactically
valid digest string alone never constitutes verified provenance.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from backtester.data import Bar
from backtester.sessions import SessionCalendar

from .manifest import ManifestError, hash_bytes

CANONICAL_BAR_FIELDS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "contract",
    "symbol",
    "duration_seconds",
    "bar_state",
    "coverage_state",
    "provider",
    "dataset",
    "schema",
    "published",
    "coverage_evidence",
    "source_ts_event_ns",
)


class BindingError(ManifestError):
    """Dataset or calendar bytes failed cryptographic binding or reconciliation."""


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_bar_record(bar: Bar) -> dict[str, Any]:
    """Deterministic JSON-ready record for one bar (binding / reconciliation)."""
    evidence = bar.coverage_evidence
    if evidence is not None and not isinstance(evidence, str):
        raise BindingError("coverage_evidence must be a string or null for binding")
    return {
        "timestamp": _stamp(bar.timestamp),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "contract": bar.contract,
        "symbol": bar.symbol,
        "duration_seconds": int(bar.duration.total_seconds()),
        "bar_state": bar.bar_state,
        "coverage_state": bar.coverage_state,
        "provider": bar.provider,
        "dataset": bar.dataset,
        "schema": bar.schema,
        "published": bar.published,
        "coverage_evidence": evidence,
        "source_ts_event_ns": bar.source_ts_event_ns,
    }


def encode_dataset_bars(bars: Sequence[Bar]) -> bytes:
    """Encode bars to the canonical dataset byte string used for SHA-256 binding."""
    payload = [canonical_bar_record(bar) for bar in bars]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def encode_calendar_document(document: Mapping[str, Any]) -> bytes:
    """Encode a calendar identity document to binding bytes."""
    if not isinstance(document, Mapping):
        raise BindingError("calendar document must be a mapping")
    return json.dumps(dict(document), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def decode_calendar(calendar_bytes: bytes) -> SessionCalendar:
    """Decode reviewed calendar bytes into a ``SessionCalendar``."""
    try:
        document = json.loads(calendar_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BindingError("calendar_bytes must be UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise BindingError("calendar document must be a JSON object")
    product = document.get("product")
    if product not in (None, "NQ"):
        raise BindingError("calendar product must be NQ when present")
    try:
        return SessionCalendar(
            template=document.get("template", "equity"),
            eth_open=document.get("eth_open", "18:00"),
            eth_close=document.get("eth_close", "17:00"),
            rth_open=document.get("rth_open"),
            rth_close=document.get("rth_close"),
            breaks=document.get("breaks"),
            overrides=dict(document.get("overrides") or {}),
            source=document.get("source", "weekday template; holidays NOT certified"),
        )
    except (TypeError, ValueError) as error:
        raise BindingError(f"calendar_bytes do not define a usable SessionCalendar: {error}") from error


def decode_dataset_bars(dataset_bytes: bytes) -> tuple[dict[str, Any], ...]:
    try:
        payload = json.loads(dataset_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BindingError("dataset_bytes must be UTF-8 JSON") from error
    if not isinstance(payload, list):
        raise BindingError("dataset_bytes must decode to a JSON array of bar records")
    records: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise BindingError(f"dataset record {index} must be an object")
        unknown = set(item) - set(CANONICAL_BAR_FIELDS)
        if unknown:
            raise BindingError(f"dataset record {index} has unknown fields: {sorted(unknown)}")
        missing = [field for field in CANONICAL_BAR_FIELDS if field not in item]
        if missing:
            raise BindingError(f"dataset record {index} missing fields: {missing}")
        records.append(item)
    return tuple(records)


def verify_digest(payload: bytes, expected: str, field: str) -> str:
    digest = hash_bytes(payload)
    if digest != expected:
        raise BindingError(f"{field} does not match sha256 of supplied bytes")
    return digest


def reconcile_bars(
    bars: Sequence[Bar],
    dataset_records: Sequence[Mapping[str, Any]],
) -> tuple[Bar, ...]:
    """Require caller bars to match the verified dataset records exactly."""
    if len(bars) != len(dataset_records):
        raise BindingError("bar count does not match bound dataset_bytes")
    frozen: list[Bar] = []
    for index, (bar, record) in enumerate(zip(bars, dataset_records)):
        expected = canonical_bar_record(bar)
        if expected != dict(record):
            raise BindingError(f"bar at index {index} does not reconcile with bound dataset_bytes")
        # Re-mint with immutable string evidence snapshot.
        evidence = record["coverage_evidence"]
        if evidence is not None and not isinstance(evidence, str):
            raise BindingError(f"bar at index {index} has non-string coverage_evidence")
        frozen.append(
            Bar(
                bar.timestamp,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.contract,
                bar.symbol,
                duration=timedelta(seconds=int(record["duration_seconds"])),
                bar_state=bar.bar_state,
                coverage_state=bar.coverage_state,
                provider=bar.provider,
                dataset=bar.dataset,
                schema=bar.schema,
                published=bar.published,
                coverage_evidence=evidence,
                source_ts_event_ns=bar.source_ts_event_ns,
                trade_count=bar.trade_count,
                bid_volume=bar.bid_volume,
                ask_volume=bar.ask_volume,
                open_interest=bar.open_interest,
                instrument_id=bar.instrument_id,
                raw_symbol=bar.raw_symbol,
                request_id=bar.request_id,
            )
        )
    return tuple(frozen)


def assert_source_identity(bars: Sequence[Bar], source: Mapping[str, str]) -> None:
    """Reject bars whose provider/dataset identity contradicts the manifest source."""
    mode = source["acquisition_mode"]
    provider = source["provider"]
    for index, bar in enumerate(bars):
        if bar.provider != provider:
            raise BindingError(
                f"bar at index {index} provider {bar.provider!r} does not match "
                f"manifest source.provider {provider!r}"
            )
        if mode == "synthetic_constructed":
            dataset = bar.dataset
            if isinstance(dataset, str) and dataset.startswith("GLBX."):
                raise BindingError(
                    "synthetic_constructed bars may not claim licensed GLBX dataset identity"
                )


def bind_inputs(
    *,
    dataset_sha256: str,
    content_sha256: str | None,
    calendar_sha256: str,
    dataset_bytes: bytes,
    calendar_bytes: bytes,
    bars: Sequence[Bar],
    source: Mapping[str, str],
) -> tuple[tuple[Bar, ...], SessionCalendar, str, str]:
    """Verify digests, decode calendar, and reconcile bars to dataset bytes."""
    if not isinstance(dataset_bytes, (bytes, bytearray)):
        raise BindingError("dataset_bytes must be bytes")
    if not isinstance(calendar_bytes, (bytes, bytearray)):
        raise BindingError("calendar_bytes must be bytes")
    dataset_bytes = bytes(dataset_bytes)
    calendar_bytes = bytes(calendar_bytes)
    verify_digest(dataset_bytes, dataset_sha256, "dataset_sha256")
    if content_sha256 is not None:
        verify_digest(dataset_bytes, content_sha256, "content_sha256")
    verify_digest(calendar_bytes, calendar_sha256, "calendar_identity.calendar_sha256")
    calendar = decode_calendar(calendar_bytes)
    records = decode_dataset_bars(dataset_bytes)
    frozen = reconcile_bars(bars, records)
    assert_source_identity(frozen, source)
    return frozen, calendar, hash_bytes(dataset_bytes), hash_bytes(calendar_bytes)
