from dataclasses import replace
from datetime import timedelta

import pytest

from backtester.sessions import SessionCalendar
from backtester.signal_interactions import HYPOTHESES, evaluate_interactions
from backtester.signal_research import SignalConfig, compute_features, make_labels
from scripts.run_signal_interactions_synthetic_v1 import build_report, synthetic_factorial_rows
from scripts.run_signal_research_synthetic_v1 import synthetic_bars


def test_known_positive_zero_negative_interactions_and_baselines():
    report = build_report()
    assert report == build_report()
    results = {row["id"]: row for row in report["evaluation"]["results"]}
    assert report["evaluation"]["hypotheses_tested"] == 3
    assert report["evaluation"]["nonoverlapping_eligible_by_horizon"] == {3: 1280}
    assert results["H1"]["effects"]["interaction"] == pytest.approx(.0004)
    assert results["H2"]["effects"]["interaction"] == pytest.approx(0, abs=1e-15)
    assert results["H3"]["effects"]["interaction"] == pytest.approx(-.00032)
    for row in results.values():
        assert row["sufficient"]
        assert all(cell["n"] == 320 and cell["sessions"] == 20 for cell in row["cells"])
        assert row["effects"]["single_signal_baseline"] is not None
        assert row["simultaneous_intervals"] is not None
    assert results["H1"]["simultaneous_intervals"]["interaction"][0] > 0
    assert results["H3"]["simultaneous_intervals"]["interaction"][1] < 0
    assert not results["H2"]["interaction_detected"]
    assert results["H1"]["interaction_detected"]
    assert results["H3"]["interaction_detected"]


def test_sparse_cells_suppress_all_effect_inference():
    features, labels, partitions = synthetic_factorial_rows()
    report = evaluate_interactions(features, labels, partitions, min_cell_n=321, replications=100)
    for row in report["results"]:
        assert not row["sufficient"]
        assert row["effects"] is None
        assert row["simultaneous_intervals"] is None
        assert row["bonferroni_adjusted_p"] is None


def test_label_endpoint_and_partition_boundaries_are_enforced():
    features, labels, partitions = synthetic_factorial_rows()
    with pytest.raises(ValueError, match="partition"):
        evaluate_interactions(features, labels, {})
    invalid = (replace(labels[0], outcome_at=features[193].decision_at), *labels[1:])
    with pytest.raises(ValueError, match="crosses a session"):
        evaluate_interactions(features, invalid, partitions)
    missing = (replace(labels[0], outcome_at=labels[0].outcome_at + timedelta(seconds=1)), *labels[1:])
    with pytest.raises(ValueError, match="invalid endpoint"):
        evaluate_interactions(features, missing, partitions)


def test_evaluation_split_excludes_other_sessions_without_refitting():
    features, labels, partitions = synthetic_factorial_rows()
    for day in sorted(partitions)[:10]:
        partitions[day] = "validation"
    result = evaluate_interactions(features, labels, partitions, replications=100)
    assert result["nonoverlapping_eligible_by_horizon"] == {3: 640}
    assert all(cell["n"] == 160 and cell["sessions"] == 10
               for row in result["results"] for cell in row["cells"])


def test_features_are_prefix_causal_and_existing_bars_integrate():
    bars = synthetic_bars()[:180]
    calendar = SessionCalendar()
    config = SignalConfig()
    full = compute_features(bars, calendar, config)
    assert full[:80] == compute_features(bars[:80], calendar, config)
    assert full[0].values["realized_vol"] is None
    assert full[0].values["current_log_return"] is None
    assert full[6].values["realized_vol"] is not None
    labels = make_labels(bars, calendar, (3,))
    partitions = {row.trading_date: "evaluation" for row in full}
    report = evaluate_interactions(full, labels, partitions, replications=100)
    assert report["hypotheses_tested"] == len(HYPOTHESES)
    assert report["nonoverlapping_eligible_by_horizon"] == {3: 57}
