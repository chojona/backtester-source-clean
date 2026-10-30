"""Independent arithmetic and timing checks for the synthetic feature engine."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math

import pytest

from backtester.quant_features import (CompletedSessionRV, FeatureError, MacroRelease, Observation,
    align_last_known, completed_session_rv, cross_asset_return, har_lags, macro_feature, price_volume,
    session_level, volatility)
from synthetic_feature_bars import bars

pytestmark = pytest.mark.unit


def test_exact_variance_coarse_blocks_and_bpv_segment_boundary():
    rows = bars("NQ", [100 * math.exp(i * .01) for i in range(16)])
    decision = "2026-01-05T14:46:00Z"
    assert volatility("rv_1m", rows, decision).value == pytest.approx(15 * .01**2)
    assert volatility("rv_5m", rows, decision).value == pytest.approx(3 * .05**2)
    assert volatility("rv_15m", rows, decision).value == pytest.approx(.15**2)
    segmented = [replace(row, segment="OVERNIGHT") if i < 8 else row for i, row in enumerate(rows)]
    # The crossing return is excluded from both adjacent pairs.
    assert volatility("bpv", segmented, decision).value == pytest.approx(12 * math.pi / 2 * .01**2)


def test_incomplete_gapped_late_and_timezone_windows_fail_closed():
    rows = bars("NQ", [100 + i for i in range(16)])
    with pytest.raises(FeatureError, match="incomplete"):
        volatility("rv_5m", rows[:-1], rows[-1].end)
    with pytest.raises(FeatureError, match="missing"):
        volatility("rv_1m", rows[:4] + rows[5:], rows[-1].end)
    with pytest.raises(FeatureError, match="arrived after"):
        volatility("rv_1m", rows, rows[-1].start)
    with pytest.raises(ValueError, match="UTC"):
        price_volume("vwap", rows, "2026-01-05T09:46:00-05:00")


def test_price_volume_and_complete_session_levels():
    rows = bars("NQ", [100, 102, 104])
    decision = "2026-01-05T14:33:00Z"
    assert price_volume("log_return", rows[-2:], decision).value == pytest.approx(math.log(104 / 102))
    expected_vwap = (100 * 100 + 102 * 101 + 104 * 102) / 303
    assert price_volume("vwap", rows, decision).value == pytest.approx(expected_vwap)
    assert price_volume("volume_sum", rows, decision, window=3).value == 303
    assert price_volume("volume_mean", rows, decision, window=3).value == 101
    with pytest.raises(FeatureError, match="zero-volume"):
        price_volume("vwap", [replace(r, volume=0) for r in rows], decision)
    with pytest.raises(FeatureError, match="incomplete"):
        session_level("opening_range_high", rows, decision, expected_bars=4,
                      current_session="2026-01-05", segment_open=rows[0].start)
    assert session_level("opening_range_high", rows, decision, expected_bars=3,
                         current_session="2026-01-05", segment_open=rows[0].start).value == 104
    with pytest.raises(FeatureError, match="prior completed"):
        session_level("previous_session_high", rows, decision, expected_bars=3,
                      current_session="2026-01-05", segment_open=rows[0].start,
                      previous_session="2026-01-02")


def test_har_uses_only_prior_22_completed_sessions():
    base = volatility("rv_1m", bars("NQ", [100, 101]), "2026-01-05T14:32:00Z")
    rows = []
    for i in range(22):
        day = datetime(2025, 12, 1, tzinfo=timezone.utc) + timedelta(days=i)
        start = day.replace(hour=14, minute=30).isoformat().replace("+00:00", "Z")
        end = day.replace(hour=14, minute=32).isoformat().replace("+00:00", "Z")
        output = replace(base, window_start=start, window_end=end, calculated_at=end,
                         available_at=end, decision_at=end, value=float(i + 1))
        rows.append(CompletedSessionRV(day.date().isoformat(), 2, 2, output))
    roster = [row.session for row in rows]
    daily, weekly, monthly = har_lags(rows, "2026-01-05T14:30:00Z", expected_sessions=roster)
    assert [daily.value, weekly.value, monthly.value] == [22, 20, 11.5]
    assert daily.dependency_hashes == (rows[-1].output.content_sha256,)
    with pytest.raises(FeatureError, match="target leakage"):
        har_lags(rows, rows[-2].output.window_end, expected_sessions=roster)
    with pytest.raises(FeatureError, match="22"):
        har_lags(rows[1:], "2026-01-05T14:30:00Z", expected_sessions=roster)
    with pytest.raises(FeatureError, match="incomplete"):
        completed_session_rv(bars("NQ", [100, 101]), "2026-01-05T14:32:00Z", expected_bars=3)


def test_cross_asset_last_known_arrival_staleness_and_session():
    es = bars("ES", [200, 202], arrival_seconds=30)
    rty = bars("RTY", [50, 51], arrival_seconds=120)
    decision = "2026-01-05T14:32:45Z"
    aligned = align_last_known(es + rty, ("NQ", "ES", "RTY"), decision, timedelta(minutes=2),
                               session="2026-01-05")
    assert aligned["NQ"] is None and aligned["RTY"] is None
    assert aligned["ES"] == es[-1]
    assert cross_asset_return(es, "ES", decision, timedelta(minutes=2)).value == pytest.approx(math.log(202 / 200))
    assert align_last_known(es, ("ES",), "2026-01-05T14:40:00Z", timedelta(minutes=2))["ES"] is None
    assert align_last_known(es, ("ES",), decision, timedelta(minutes=2), session="2026-01-06")["ES"] is None
    assert cross_asset_return([replace(es[0], session="2026-01-04"), es[1]], "ES", decision,
                              timedelta(minutes=2)) is None


def test_macro_actual_arrival_embargo_and_revision():
    base = MacroRelease("CPI", "BLS_SYNTHETIC", "2026-01-13T13:30:00Z",
                        "2026-01-13T13:30:02Z", "2026-01-13T13:30:05Z",
                        "2026-01-13T13:30:10Z", 2.4)
    assert macro_feature([base], "CPI", "2026-01-13T13:30:09Z") is None
    result = macro_feature([base], "CPI", "2026-01-13T13:30:10Z")
    assert result.value == 2.4 and result.available_at == base.embargo_until
    assert result.to_contract_v1()["feature_id"] == "macro_cpi"
    revised = replace(base, available_at="2026-01-13T14:00:00Z", revision=1, value=2.5)
    assert macro_feature([base, revised], "CPI", "2026-01-13T13:31:00Z").value == 2.4
    with pytest.raises(FeatureError, match="revision"):
        macro_feature([base, revised], "CPI", "2026-01-13T14:00:00Z")
    simultaneous = replace(base, published_at=base.scheduled_at, available_at=base.scheduled_at,
                           embargo_until=base.scheduled_at)
    assert macro_feature([simultaneous], "CPI", base.scheduled_at).value == 2.4


def test_hash_is_canonical_and_changes_with_dependency():
    row = price_volume("vwap", bars("NQ", [100, 102]), "2026-01-05T14:32:00Z")
    assert row.content_sha256 == hashlib.sha256(json.dumps(row.__dict__, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    altered = price_volume("vwap", bars("NQ", [100, 103]), "2026-01-05T14:32:00Z")
    assert altered.content_sha256 != row.content_sha256
