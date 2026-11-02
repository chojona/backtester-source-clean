"""Synthetic and adversarial tests for the read-only exploratory adapter."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backtester.data import Bar
from backtester.research_nq import (
    AvailabilityProvenance,
    BarAvailabilityClass,
    ExploratoryAdapterError,
    ReadOnlyExploratoryAdapter,
    classify_bar,
    encode_dataset_bars,
    hash_bytes,
)
from backtester.research_nq.classifications import MATERIALIZATION_TOKEN
from backtester.research_nq.testing_support import (
    bound_manifest,
    inferred_no_trade,
    materialized,
    traded,
)


UTC = timezone.utc


def make_adapter(bars, **kwargs):
    manifest, dataset, calendar = bound_manifest(bars, **kwargs)
    return ReadOnlyExploratoryAdapter(
        manifest, bars, dataset_bytes=dataset, calendar_bytes=calendar,
    )


def test_classify_preserves_four_way_distinction():
    base = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    assert classify_bar(traded(base)) is BarAvailabilityClass.OBSERVED
    assert classify_bar(inferred_no_trade(base + timedelta(minutes=1))) is (
        BarAvailabilityClass.PROVIDER_INFERRED_NO_TRADE
    )
    assert classify_bar(materialized(base + timedelta(minutes=2))) is (
        BarAvailabilityClass.MATERIALIZED
    )
    unverified = Bar(
        base + timedelta(minutes=4), 21000.0, 21000.25, 20999.75, 21000.0, 3.0,
        "NQZ26", "NQ", published=True, coverage_state="UNVERIFIED",
        provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC",
    )
    assert classify_bar(unverified) is BarAvailabilityClass.UNRESOLVED
    unknown = Bar(
        base + timedelta(minutes=5), 21000.0, 21000.25, 20999.75, 21000.0, 3.0,
        "NQZ26", "NQ", published=True, coverage_state="UNKNOWN",
        provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC",
        coverage_evidence="coverage unresolved; unsupported",
    )
    assert classify_bar(unknown) is BarAvailabilityClass.UNRESOLVED


def test_decision_time_availability_filters_future_bars():
    t0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=1)
    adapter = make_adapter([traded(t0), traded(t1)])
    at_close_of_first = t0 + timedelta(minutes=1)
    available = adapter.bars_available_at(at_close_of_first)
    assert len(available) == 1
    assert available[0].bar.timestamp == t0
    assert available[0].availability_provenance is AvailabilityProvenance.ASSUMED_BAR_CLOSE
    assert available[0].retrospective_assumption is True
    assert available[0].strict_eligible is False

    both = adapter.bars_available_at(t1 + timedelta(minutes=1))
    assert len(both) == 2


def test_complete_observations_accept_observed_only():
    t0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    bars = [
        traded(t0),
        inferred_no_trade(t0 + timedelta(minutes=1)),
        materialized(t0 + timedelta(minutes=2)),
    ]
    adapter = make_adapter(bars)
    decision = t0 + timedelta(minutes=10)
    with pytest.raises(ExploratoryAdapterError, match="provider_inferred_no_trade"):
        adapter.require_complete_observations(decision)

    observed_only = make_adapter([traded(t0)])
    records = observed_only.require_complete_observations(
        decision, start_utc=t0, end_utc=t0 + timedelta(minutes=1),
    )
    assert len(records) == 1
    assert records[0].classification is BarAvailabilityClass.OBSERVED
    assert records[0].availability_provenance is AvailabilityProvenance.ASSUMED_BAR_CLOSE


def test_complete_observations_reject_unavailable_and_materialized():
    t0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    adapter = make_adapter([traded(t0)])
    too_early = t0 + timedelta(seconds=30)
    with pytest.raises(ExploratoryAdapterError, match="not available"):
        adapter.require_complete_observations(
            too_early, start_utc=t0, end_utc=t0 + timedelta(minutes=1),
        )

    material = make_adapter([materialized(t0)])
    with pytest.raises(ExploratoryAdapterError, match="materialized"):
        material.require_complete_observations(
            t0 + timedelta(minutes=5), start_utc=t0, end_utc=t0 + timedelta(minutes=1),
        )


def test_adapter_is_immutable_and_non_certifying():
    t0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    adapter = make_adapter([traded(t0)])
    assert adapter.strict_eligible is False
    assert adapter.lane == "exploratory"
    assert adapter.describe()["strict_eligible"] is False
    assert adapter.describe()["binding"]["dataset_bytes_verified"] is True
    with pytest.raises(ExploratoryAdapterError, match="immutable"):
        adapter._bars = ()


def test_contract_mismatch_rejected():
    t0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    wrong = Bar(
        t0, 21000.0, 21000.25, 20999.75, 21000.0, 1.0, "NQH27", "NQ",
        provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC",
        coverage_state="PROVIDER_AVAILABLE",
    )
    with pytest.raises(ExploratoryAdapterError, match="contract"):
        make_adapter([wrong])


def test_digest_mismatch_rejected():
    t0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    bars = [traded(t0)]
    manifest, dataset, calendar = bound_manifest(bars)
    # Mutate declared digest after binding helper computed matching bytes.
    bad = dict(manifest.to_dict())
    bad["dataset_sha256"] = "00" * 31 + "01"
    from backtester.research_nq import validate_manifest
    # Shape-valid wrong digest still validates as a document...
    shaped = validate_manifest(bad)
    with pytest.raises(ExploratoryAdapterError, match="dataset_sha256"):
        ReadOnlyExploratoryAdapter(
            shaped, bars, dataset_bytes=dataset, calendar_bytes=calendar,
        )


def test_unrelated_bytes_with_matching_digest_still_require_reconciliation():
    t0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    bars = [traded(t0)]
    unrelated = b'{"not":"bars"}'
    calendar = bound_manifest(bars)[2]
    from backtester.research_nq.schema import SCHEMA_VERSION
    from backtester.research_nq import validate_manifest

    document = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "unrelated-bytes",
        "dataset_sha256": hash_bytes(unrelated),
        "instrument": "NQ",
        "contract": "NQZ26",
        "time_range": {"start_utc": "2026-01-05T15:00:00Z", "end_utc": "2026-01-05T16:00:00Z"},
        "source": {
            "provider": "SYNTHETIC",
            "locator": "memory://unrelated",
            "acquisition_mode": "synthetic_constructed",
        },
        "coverage_classifications": ["observed"],
        "calendar_identity": {
            "calendar_id": "synthetic-test-calendar",
            "calendar_sha256": hash_bytes(calendar),
            "calendar_kind": "synthetic_test",
        },
        "strict_eligible": False,
        "lane": "exploratory",
    }
    with pytest.raises(ExploratoryAdapterError, match="dataset_bytes"):
        ReadOnlyExploratoryAdapter(
            validate_manifest(document), bars,
            dataset_bytes=unrelated, calendar_bytes=calendar,
        )


def test_synthetic_mode_rejects_licensed_provider_identity():
    t0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    licensed = traded(t0, provider="Databento", dataset="GLBX.MDP3")
    data = encode_dataset_bars([licensed])
    cal = bound_manifest([traded(t0)])[2]
    from backtester.research_nq import validate_manifest
    from backtester.research_nq.schema import SCHEMA_VERSION

    document = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "spoofed",
        "dataset_sha256": hash_bytes(data),
        "instrument": "NQ",
        "contract": "NQZ26",
        "time_range": {"start_utc": "2026-01-05T15:00:00Z", "end_utc": "2026-01-05T16:00:00Z"},
        "source": {
            "provider": "SYNTHETIC",
            "locator": "memory://spoofed",
            "acquisition_mode": "synthetic_constructed",
        },
        "coverage_classifications": ["observed"],
        "calendar_identity": {
            "calendar_id": "synthetic-test-calendar",
            "calendar_sha256": hash_bytes(cal),
            "calendar_kind": "synthetic_test",
        },
        "strict_eligible": False,
        "lane": "exploratory",
    }
    with pytest.raises(ExploratoryAdapterError, match="provider"):
        ReadOnlyExploratoryAdapter(
            validate_manifest(document), [licensed],
            dataset_bytes=data, calendar_bytes=cal,
        )


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
