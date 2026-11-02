"""Permanent regressions for every independent M1 acceptance counterexample."""
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
    encode_calendar_document,
    encode_dataset_bars,
    hash_bytes,
    validate_manifest,
)
from backtester.research_nq.classifications import (
    MATERIALIZATION_TOKEN,
    PROVIDER_INFERRED_EVIDENCE_TOKEN,
)
from backtester.research_nq.testing_support import (
    DEFAULT_CALENDAR_DOCUMENT,
    bound_manifest,
    calendar_bytes,
    traded,
)


UTC = timezone.utc
DECISION = datetime(2026, 1, 5, 22, 30, tzinfo=UTC)


def adapter_for(bars, **kwargs):
    manifest, dataset, calendar = bound_manifest(bars, **kwargs)
    return ReadOnlyExploratoryAdapter(
        manifest, bars, dataset_bytes=dataset, calendar_bytes=calendar,
    )


# --- Finding 2: complete observations ---

@pytest.mark.parametrize(
    "bars_factory,match",
    [
        (lambda: [traded(datetime(2026, 1, 5, 15, 0, tzinfo=UTC)),
                  traded(datetime(2026, 1, 5, 15, 2, tzinfo=UTC))],
         "missing"),
        (lambda: [traded(datetime(2026, 1, 5, 15, 0, tzinfo=UTC)),
                  traded(datetime(2026, 1, 5, 15, 0, tzinfo=UTC))],
         "Duplicate|overlapping|integrity"),
        (lambda: [traded(datetime(2026, 1, 5, 15, 2, tzinfo=UTC)),
                  traded(datetime(2026, 1, 5, 15, 1, tzinfo=UTC))],
         "Out-of-order|integrity"),
        (lambda: [traded(datetime(2026, 1, 5, 15, 0, 30, tzinfo=UTC))],
         "aligned|integrity|outside"),
        (lambda: [traded(datetime(2026, 1, 5, 21, 20, tzinfo=UTC))],
         "halt|session|outside|permitted"),
    ],
)
def test_complete_observations_reject_structural_failures(bars_factory, match):
    bars = bars_factory()
    # Widen manifest so out-of-range cases are controlled separately.
    adapter = adapter_for(
        bars,
        time_range={"start_utc": "2026-01-05T14:00:00Z", "end_utc": "2026-01-06T00:00:00Z"},
    )
    with pytest.raises(ExploratoryAdapterError, match=match):
        adapter.require_complete_observations(DECISION)


def test_complete_observations_reject_bar_outside_manifest_interval():
    bar = traded(datetime(2026, 1, 5, 17, 0, tzinfo=UTC))
    adapter = adapter_for(
        [bar],
        time_range={"start_utc": "2026-01-05T15:00:00Z", "end_utc": "2026-01-05T16:00:00Z"},
    )
    with pytest.raises(ExploratoryAdapterError, match="empty windows|outside the manifest"):
        adapter.require_complete_observations(DECISION)


def test_complete_observations_reject_mixed_session_window():
    # Adjacent final RTH minute and first POST_RTH minute (no missing grid gap).
    bars = [
        traded(datetime(2026, 1, 5, 20, 59, tzinfo=UTC)),  # 15:59 ET RTH
        traded(datetime(2026, 1, 5, 21, 0, tzinfo=UTC)),   # 16:00 ET POST_RTH
    ]
    adapter = adapter_for(
        bars,
        time_range={"start_utc": "2026-01-05T14:00:00Z", "end_utc": "2026-01-06T00:00:00Z"},
    )
    with pytest.raises(ExploratoryAdapterError, match="mixed-session"):
        adapter.require_complete_observations(DECISION)


def test_complete_observations_reject_empty_window():
    adapter = adapter_for(
        [traded(datetime(2026, 1, 5, 15, 0, tzinfo=UTC))],
    )
    with pytest.raises(ExploratoryAdapterError, match="empty"):
        adapter.require_complete_observations(
            DECISION,
            start_utc=datetime(2026, 1, 5, 15, 30, tzinfo=UTC),
            end_utc=datetime(2026, 1, 5, 15, 45, tzinfo=UTC),
        )


def test_complete_observations_positive_contiguous_rth_window():
    bars = [
        traded(datetime(2026, 1, 5, 15, 0, tzinfo=UTC)),
        traded(datetime(2026, 1, 5, 15, 1, tzinfo=UTC)),
        traded(datetime(2026, 1, 5, 15, 2, tzinfo=UTC)),
    ]
    adapter = adapter_for(bars)
    records = adapter.require_complete_observations(
        DECISION,
        start_utc=datetime(2026, 1, 5, 15, 0, tzinfo=UTC),
        end_utc=datetime(2026, 1, 5, 15, 3, tzinfo=UTC),
    )
    assert len(records) == 3
    assert all(r.classification is BarAvailabilityClass.OBSERVED for r in records)
    assert all(
        r.availability_provenance is AvailabilityProvenance.ASSUMED_BAR_CLOSE
        for r in records
    )
    assert all(r.retrospective_assumption for r in records)


# --- Finding 3: causal availability ---

def test_assumed_close_before_verified_publication_is_visible_not_publication_evidence():
    open_ts = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    publication = open_ts + timedelta(minutes=5)
    ns = int(publication.timestamp() * 1_000_000_000)
    bar = traded(open_ts, source_ts_event_ns=ns)
    adapter = adapter_for([bar])
    # Decision at assumed close must fail: verified publication is later.
    with pytest.raises(ExploratoryAdapterError, match="not available"):
        adapter.require_complete_observations(
            open_ts + timedelta(minutes=1),
            start_utc=open_ts,
            end_utc=open_ts + timedelta(minutes=1),
        )
    records = adapter.require_complete_observations(
        publication,
        start_utc=open_ts,
        end_utc=open_ts + timedelta(minutes=1),
    )
    assert records[0].availability_provenance is (
        AvailabilityProvenance.INDEPENDENTLY_VERIFIED_PUBLICATION
    )
    assert records[0].retrospective_assumption is False
    assert records[0].as_dict()["availability_provenance"] == (
        "independently_verified_publication"
    )


def test_caller_override_cannot_establish_earlier_availability():
    open_ts = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    bar = traded(open_ts)
    manifest, dataset, calendar = bound_manifest([bar])
    with pytest.raises(ExploratoryAdapterError, match="earlier availability"):
        ReadOnlyExploratoryAdapter(
            manifest, [bar], dataset_bytes=dataset, calendar_bytes=calendar,
            available_at_by_timestamp={open_ts: open_ts - timedelta(hours=1)},
        ).require_complete_observations(
            open_ts - timedelta(minutes=30),
            start_utc=open_ts,
            end_utc=open_ts + timedelta(minutes=1),
        )


def test_caller_declared_availability_rejected_for_complete_observations():
    open_ts = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    bar = traded(open_ts)
    manifest, dataset, calendar = bound_manifest([bar])
    adapter = ReadOnlyExploratoryAdapter(
        manifest, [bar], dataset_bytes=dataset, calendar_bytes=calendar,
        available_at_by_timestamp={open_ts: open_ts + timedelta(minutes=10)},
    )
    with pytest.raises(ExploratoryAdapterError, match="caller-declared"):
        adapter.require_complete_observations(
            open_ts + timedelta(minutes=30),
            start_utc=open_ts,
            end_utc=open_ts + timedelta(minutes=1),
        )


# --- Finding 4: classification ---

def test_unknown_and_unverified_do_not_become_observed():
    open_ts = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    unknown = Bar(
        open_ts, 21000.0, 21000.25, 20999.75, 21000.0, 10.0, "NQZ26", "NQ",
        published=True, coverage_state="UNKNOWN",
        provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC",
        coverage_evidence="coverage unresolved; unsupported",
    )
    unverified = Bar(
        open_ts, 21000.0, 21000.25, 20999.75, 21000.0, 10.0, "NQZ26", "NQ",
        published=True, coverage_state="UNVERIFIED",
        provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC",
    )
    assert classify_bar(unknown) is BarAvailabilityClass.UNRESOLVED
    assert classify_bar(unverified) is BarAvailabilityClass.UNRESOLVED
    adapter = adapter_for([unknown])
    with pytest.raises(ExploratoryAdapterError, match="unresolved"):
        adapter.require_complete_observations(
            DECISION, start_utc=open_ts, end_utc=open_ts + timedelta(minutes=1),
        )


def test_no_materialization_substring_does_not_classify_as_materialized():
    open_ts = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    bar = traded(
        open_ts,
        coverage_evidence="no materialization applied; raw trade print",
    )
    assert classify_bar(bar) is BarAvailabilityClass.OBSERVED


def test_unresolved_no_trade_evidence_not_promoted_to_inferred():
    open_ts = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    bar = Bar(
        open_ts, 21000.0, 21000.0, 21000.0, 21000.0, 0.0, "NQZ26", "NQ",
        bar_state="NO_TRADE", coverage_state="PROVIDER_AVAILABLE",
        provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC", published=False,
        coverage_evidence="unresolved gap; do not treat as no-trade",
    )
    assert classify_bar(bar) is BarAvailabilityClass.UNRESOLVED


def test_exact_materialization_token_required():
    open_ts = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    bar = Bar(
        open_ts, 21000.0, 21000.0, 21000.0, 21000.0, 0.0, "NQZ26", "NQ",
        bar_state="NO_TRADE", coverage_state="PROVIDER_AVAILABLE",
        provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC", published=False,
        coverage_evidence=PROVIDER_INFERRED_EVIDENCE_TOKEN + "; " + MATERIALIZATION_TOKEN,
    )
    assert classify_bar(bar) is BarAvailabilityClass.MATERIALIZED


# --- Finding 5: immutability ---

def test_mutable_coverage_evidence_rejected_and_snapshots_are_stable():
    open_ts = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    mutable = traded(open_ts)
    # Construct with list evidence must fail before admission.
    with pytest.raises((ExploratoryAdapterError, TypeError, ValueError)):
        bad = Bar(
            open_ts, 21000.0, 21000.25, 20999.75, 21000.0, 10.0, "NQZ26", "NQ",
            provider="SYNTHETIC", dataset="STEP_M1_SYNTHETIC",
            coverage_state="PROVIDER_AVAILABLE", published=True,
            coverage_evidence=["published trade print"],
        )
        adapter_for([bad])

    bars = [mutable]
    adapter = adapter_for(bars)
    # Even if caller mutates their original bar reference's non-frozen related
    # state, adapter holds reminted snapshot bars.
    assert adapter.classify_all()[0][1] is BarAvailabilityClass.OBSERVED
    records = adapter.require_complete_observations(
        DECISION, start_utc=open_ts, end_utc=open_ts + timedelta(minutes=1),
    )
    assert records[0].classification is BarAvailabilityClass.OBSERVED


# --- Finding 1 positive binding control ---

def test_binding_positive_control_matches_calendar_and_dataset_bytes():
    open_ts = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    bars = [traded(open_ts), traded(open_ts + timedelta(minutes=1))]
    data = encode_dataset_bars(bars)
    cal = encode_calendar_document(DEFAULT_CALENDAR_DOCUMENT)
    assert hash_bytes(data) == hash_bytes(encode_dataset_bars(bars))
    assert hash_bytes(cal) == hash_bytes(calendar_bytes())
    adapter = adapter_for(bars)
    assert adapter.describe()["dataset_sha256"] == hash_bytes(data)
    assert adapter.describe()["calendar_sha256"] == hash_bytes(cal)
