"""Shared synthetic fixtures for exploratory NQ M1-R tests (no licensed data)."""
from __future__ import annotations

from datetime import datetime, timezone

from backtester.data import Bar
from backtester.research_nq import (
    encode_calendar_document,
    encode_dataset_bars,
    hash_bytes,
    validate_manifest,
)
from backtester.research_nq.classifications import (
    MATERIALIZATION_TOKEN,
    PROVIDER_INFERRED_EVIDENCE_TOKEN,
)
from backtester.research_nq.schema import SCHEMA_VERSION

UTC = timezone.utc

DEFAULT_CALENDAR_DOCUMENT = {
    "product": "NQ",
    "template": "equity",
    "eth_open": "18:00",
    "eth_close": "17:00",
    "rth_open": "09:30",
    "rth_close": "16:00",
    "breaks": [["16:15", "16:30"]],
    "overrides": {},
    "source": "weekday template; holidays NOT certified",
}


def calendar_bytes(document=None) -> bytes:
    return encode_calendar_document(document or DEFAULT_CALENDAR_DOCUMENT)


def bound_manifest(bars, *, time_range=None, calendar_doc=None, **overrides):
    data = encode_dataset_bars(bars)
    cal = calendar_bytes(calendar_doc)
    document = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "synthetic-nq-m1r",
        "dataset_sha256": hash_bytes(data),
        "content_sha256": hash_bytes(data),
        "instrument": "NQ",
        "contract": "NQZ26",
        "time_range": time_range or {
            "start_utc": "2026-01-05T15:00:00Z",
            "end_utc": "2026-01-05T16:00:00Z",
        },
        "source": {
            "provider": "SYNTHETIC",
            "locator": "memory://tests/research_nq",
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
            "calendar_sha256": hash_bytes(cal),
            "calendar_kind": "synthetic_test",
        },
        "strict_eligible": False,
        "lane": "exploratory",
        "limitations": ["synthetic constructed inputs only"],
    }
    document.update(overrides)
    return validate_manifest(document), data, cal


def traded(ts: datetime, price: float = 21000.0, **fields) -> Bar:
    payload = dict(
        provider="SYNTHETIC",
        dataset="STEP_M1_SYNTHETIC",
        published=True,
        coverage_state="PROVIDER_AVAILABLE",
        coverage_evidence="published traded print under provider-available coverage",
    )
    payload.update(fields)
    return Bar(
        ts, price, price + 0.25, price - 0.25, price, 10.0, "NQZ26", "NQ",
        **payload,
    )


def inferred_no_trade(ts: datetime, price: float = 21000.0, **fields) -> Bar:
    payload = dict(
        bar_state="NO_TRADE",
        coverage_state="PROVIDER_AVAILABLE",
        provider="SYNTHETIC",
        dataset="STEP_M1_SYNTHETIC",
        published=False,
        coverage_evidence=PROVIDER_INFERRED_EVIDENCE_TOKEN
        + "; minute completeness is inferred, not independently proven",
    )
    payload.update(fields)
    return Bar(ts, price, price, price, price, 0.0, "NQZ26", "NQ", **payload)


def materialized(ts: datetime, price: float = 21000.0, **fields) -> Bar:
    payload = dict(
        bar_state="NO_TRADE",
        coverage_state="PROVIDER_AVAILABLE",
        provider="SYNTHETIC",
        dataset="STEP_M1_SYNTHETIC",
        published=False,
        coverage_evidence=PROVIDER_INFERRED_EVIDENCE_TOKEN + "; " + MATERIALIZATION_TOKEN,
    )
    payload.update(fields)
    return Bar(ts, price, price, price, price, 0.0, "NQZ26", "NQ", **payload)
