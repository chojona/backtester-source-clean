from dataclasses import replace
from datetime import timedelta

import pytest

from backtester.sessions import SessionCalendar
from backtester.signal_research import SignalConfig, compute_features, make_labels
from backtester.signal_evaluation import compare_distributions
from scripts.run_signal_research_synthetic_v1 import build_report, synthetic_bars


def test_prefix_invariance_and_outcomes_are_separate():
    bars = synthetic_bars()[:65]
    calendar = SessionCalendar()
    config = SignalConfig()
    full = compute_features(bars, calendar, config)
    for n in (1, 7, 20, 59, 60, 65):
        assert full[:n] == compute_features(bars[:n], calendar, config)
    labels = make_labels(bars, calendar, config.horizons)
    assert labels[0].decision_at == bars[0].end
    assert labels[0].outcome_at == bars[1].end
    assert labels[0].forward_log_return is not None
    assert next(x for x in labels if x.decision_at == bars[59].end).censored_reason
    changed = list(bars)
    changed[21] = replace(bars[21], open=bars[21].open + .25,
                          high=bars[21].high + .25, close=bars[21].close + .25)
    assert compute_features(changed, calendar, config)[:21] == full[:21]
    assert make_labels(changed, calendar, (1,))[20].forward_log_return != make_labels(bars, calendar, (1,))[20].forward_log_return


def test_exact_features_and_session_reset():
    bars = synthetic_bars()
    features = compute_features(bars, SessionCalendar())
    first, second = features[0], features[60]
    assert first.decision_at == bars[0].end
    assert first.values["session_vwap"] == pytest.approx((bars[0].high + bars[0].low + bars[0].close) / 3)
    assert first.values["momentum_3"] is None
    assert features[6].values["prior_range_high"] == max(x.high for x in bars[:6])
    assert features[6].values["prior_range_low"] == min(x.low for x in bars[:6])
    assert second.values["session_vwap"] == pytest.approx((bars[60].high + bars[60].low + bars[60].close) / 3)
    assert second.values["momentum_3"] is None
    assert second.values["breakout"] is None


def test_in_session_gap_and_unknown_coverage_rejected():
    bars = synthetic_bars()[:15]
    with pytest.raises(ValueError, match="Missing in-session"):
        compute_features(bars[:5] + bars[6:], SessionCalendar())
    with pytest.raises(ValueError, match="Unknown provider"):
        compute_features((replace(bars[0], coverage_state="UNKNOWN"), *bars[1:]), SessionCalendar())


def test_nonoverlap_multiplicity_and_determinism():
    bars = synthetic_bars()
    calendar = SessionCalendar()
    features = compute_features(bars, calendar)
    labels = make_labels(bars, calendar)
    a = compare_distributions(features, labels)
    b = compare_distributions(features, labels)
    assert a == b
    assert a["multiplicity_cells"] == 54
    assert len(a["contrasts"]) == 18
    assert a["nonoverlapping_eligible_by_horizon"] == {1: 1180, 3: 380, 6: 180}
    assert a["censored_by_horizon"] == {1: 20, 3: 60, 6: 120}
    for cell in a["cells"]:
        assert cell["n"] <= 20 * (60 // cell["horizon_bars"] + 1)
        assert cell["simultaneous_mean_interval"] is None or cell["sessions"] >= 5
    assert build_report() == build_report()


def test_invalid_configuration():
    with pytest.raises(ValueError):
        SignalConfig(momentum_windows=(0,))
    with pytest.raises(ValueError):
        SignalConfig(horizons=(1, 1))
