"""Synthetic and adversarial tests for the read-only exploratory adapter."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backtester.data import Bar
from backtester.research_nq import (
    BarAvailabilityClass,
    ExploratoryAdapterError,
    ReadOnlyExploratoryAdapter,
    classify_bar,
    validate_manifest,
)
from backtester.research_nq.schema import SCHEMA_VERSION


UTC = timezone.utc


def _sha(n: int = 1) -> str:
    return f"{n:064x}"


def manifest_doc(**overrides):
    document = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "synthetic-nq-adapter",
        "dataset_sha256": _sha(11),
        "instrument": "NQ",
        "contract": "NQZ26",
        "time_range": {
            "start_utc": "2026-01-05T14:00:00Z",
            "end_utc": "2026-01-05T15:00:00Z",
        },
        "source": {
            "provider": "SYNTHETIC",
            "locator": "memory://tests/test_research_nq_adapter",
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
            "calendar_sha256": _sha(12),
            "calendar_kind": "synthetic_test",
        },
        "strict_eligible": False,
        "lane": "exploratory",
    }
    document.update(overrides)
    return validate_manifest(document)


def traded(ts: datetime, price: float = 21000.0) -> Bar:
    return Bar(
        ts, price, price + 0.25, price - 0.25, price, 10.0, "NQZ26", "NQ",
        provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC", published=True,
    )


def inferred_no_trade(ts: datetime, price: float = 21000.0) -> Bar:
    return Bar(
        ts, price, price, price, price, 0.0, "NQZ26", "NQ",
        bar_state="NO_TRADE", coverage_state="PROVIDER_AVAILABLE",
        provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC", published=False,
        coverage_evidence="Complete untruncated stream + provider daily condition=available",
    )


def materialized(ts: datetime, price: float = 21000.0) -> Bar:
    return Bar(
        ts, price, price, price, price, 0.0, "NQZ26", "NQ",
        bar_state="NO_TRADE", coverage_state="PROVIDER_AVAILABLE",
        provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC", published=False,
        coverage_evidence="explicit previous-traded-price grid materialization",
    )


def test_classify_preserves_four_way_distinction():
    base = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
    assert classify_bar(traded(base)) is BarAvailabilityClass.OBSERVED
    assert classify_bar(inferred_no_trade(base + timedelta(minutes=1))) is (
        BarAvailabilityClass.PROVIDER_INFERRED_NO_TRADE
    )
    assert classify_bar(materialized(base + timedelta(minutes=2))) is (
        BarAvailabilityClass.MATERIALIZED
    )
    # Unpublished traded print is neither observed nor provider-inferred.
    odd = Bar(
        base + timedelta(minutes=4), 21000.0, 21000.25, 20999.75, 21000.0, 3.0,
        "NQZ26", "NQ", published=False, coverage_state="UNVERIFIED",
        provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC",
    )
    assert classify_bar(odd) is BarAvailabilityClass.UNRESOLVED


def test_decision_time_availability_filters_future_bars():
    t0 = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=1)
    adapter = ReadOnlyExploratoryAdapter(manifest_doc(), [traded(t0), traded(t1)])
    # Default available_at = bar close = open + 1m
    at_close_of_first = t0 + timedelta(minutes=1)
    available = adapter.bars_available_at(at_close_of_first)
    assert len(available) == 1
    assert available[0].bar.timestamp == t0
    assert available[0].strict_eligible is False
    assert available[0].as_dict()["strict_eligible"] is False

    both = adapter.bars_available_at(t1 + timedelta(minutes=1))
    assert len(both) == 2


def test_complete_observations_accept_observed_only():
    t0 = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
    bars = [
        traded(t0),
        inferred_no_trade(t0 + timedelta(minutes=1)),
        materialized(t0 + timedelta(minutes=2)),
    ]
    adapter = ReadOnlyExploratoryAdapter(manifest_doc(), bars)
    decision = t0 + timedelta(minutes=10)
    with pytest.raises(ExploratoryAdapterError, match="provider_inferred_no_trade"):
        adapter.require_complete_observations(decision)

    observed_only = ReadOnlyExploratoryAdapter(manifest_doc(), [traded(t0)])
    records = observed_only.require_complete_observations(decision)
    assert len(records) == 1
    assert records[0].classification is BarAvailabilityClass.OBSERVED


def test_complete_observations_reject_unavailable_and_materialized():
    t0 = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
    adapter = ReadOnlyExploratoryAdapter(manifest_doc(), [traded(t0)])
    too_early = t0 + timedelta(seconds=30)  # before bar close
    with pytest.raises(ExploratoryAdapterError, match="not available"):
        adapter.require_complete_observations(too_early)

    material = ReadOnlyExploratoryAdapter(manifest_doc(), [materialized(t0)])
    with pytest.raises(ExploratoryAdapterError, match="materialized"):
        material.require_complete_observations(t0 + timedelta(minutes=5))


def test_adapter_is_immutable_and_non_certifying():
    t0 = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
    adapter = ReadOnlyExploratoryAdapter(manifest_doc(), [traded(t0)])
    assert adapter.strict_eligible is False
    assert adapter.lane == "exploratory"
    assert adapter.describe()["strict_eligible"] is False
    with pytest.raises(ExploratoryAdapterError, match="immutable"):
        adapter._bars = ()


def test_contract_mismatch_rejected():
    t0 = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
    wrong = Bar(
        t0, 21000.0, 21000.25, 20999.75, 21000.0, 1.0, "NQH27", "NQ",
        provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC",
    )
    with pytest.raises(ExploratoryAdapterError, match="contract"):
        ReadOnlyExploratoryAdapter(manifest_doc(), [wrong])


def test_source_boundary_trust_roots_untouched():
    """Exploratory lane must not alter production trust roots."""
    from backtester.market_certification import PRODUCTION_MANIFESTS
    from backtester.evidence_registry import load_production_registry
    import json
    from pathlib import Path

    assert dict(PRODUCTION_MANIFESTS) == {}
    registry_path = Path(__file__).resolve().parents[1] / "config" / "approved_evidence.json"
    document = json.loads(registry_path.read_text(encoding="utf-8"))
    assert document == {"version": 1, "capture_manifests": [], "certification_ledgers": []}
    registry = load_production_registry()
    assert registry.capture_manifests == ()
    assert registry.certification_ledgers == ()
