from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from backtester.experiments.inputs import MINUTE, Observation, acceptance_fixture, make_session
from backtester.experiments.ledger import pair_session, scenarios
from backtester.experiments.protocol import Protocol, load_registry
from backtester.experiments.rules import detect_opening_range


DEFINITION = Path(__file__).resolve().parents[1] / "config/experiments/h4.synthetic.v1.toml"


def _pair(session, protocol, scenario_id):
    scenario = next(item for item in scenarios(protocol) if item.id == scenario_id)
    decision = detect_opening_range(session, protocol)
    return pair_session(session, protocol, decision, scenario, coverage_reason=session.coverage_reason())


@pytest.mark.parametrize(("original", "changed"), [
    ('stage = "synthetic"', 'stage = "historical"'),
    ("schema_version = 1", "schema_version = true"),
    ("outside_ticks = 1", "outside_ticks = 2"),
    ("outside_ticks = 1", "outside_ticks = true"),
    ("outside_ticks = 1", "outside_ticks = 1\noutside_ticks = 1"),
    ("outside_ticks = 1", "outside_ticks = 1\nprice_source = 'untrusted'"),
    ('"H9", "H10"', '"H9", "H9"'),
])
def test_registry_rejects_unrecognized_or_unapproved_definitions(tmp_path, original, changed):
    path = tmp_path / "definition.toml"
    path.write_text(DEFINITION.read_text(encoding="utf-8").replace(original, changed), encoding="utf-8")
    with pytest.raises(ValueError):
        load_registry(path)


def test_synthetic_h4_opening_range_acceptance():
    registry = load_registry(DEFINITION)
    protocol = registry.get("H4", "1.0.0")
    early, rejected, idle, final, missing = acceptance_fixture(protocol)
    assert len(registry.family) == 10
    assert protocol.amendments_pending == ("A1", "A2", "A3", "A4", "A5", "A6")

    for session, side, first, entry, exit_at in ((early, 1, 30, 33, 63), (final, -1, 117, 120, 150)):
        decision = detect_opening_range(session, protocol)
        assert decision.reason == "accepted"
        event = decision.event
        assert (event.range_high_ticks, event.range_low_ticks) == (80002, 79998)
        assert event.first_cross == session.cash_open + first * MINUTE
        assert event.max_source_availability == event.decision_time == session.cash_open + entry * MINUTE
        assert event.side == side
        for scenario in scenarios(protocol):
            pair, (candidate, benchmark) = _pair(session, protocol, scenario.id)
            assert candidate == replace(benchmark, arm="candidate")
            assert candidate.actual_entry == session.cash_open + (entry + scenario.delay_minutes) * MINUTE
            assert candidate.actual_exit == session.cash_open + (exit_at + scenario.delay_minutes) * MINUTE
            assert candidate.gross_cents == 5000
            assert candidate.cost_cents == scenario.fee_cents + 1000 * scenario.adverse_ticks_per_side
            assert candidate.net_cents == 5000 - scenario.fee_cents - 1000 * scenario.adverse_ticks_per_side
            assert candidate.entry_fill_ticks - candidate.entry_open_ticks == side * scenario.adverse_ticks_per_side
            assert candidate.exit_fill_ticks - candidate.exit_open_ticks == -side * scenario.adverse_ticks_per_side
            assert candidate.break_even_ticks_per_side == 4.5
            assert pair.eligible and pair.uplift_cents == 0

    pair, (candidate, benchmark) = _pair(rejected, protocol, "base")
    assert (pair.decision_reason, candidate.status, benchmark.status) == ("rejected", "abstained", "filled")
    assert candidate.cost_cents == 0
    assert benchmark.actual_entry == rejected.cash_open + 33 * MINUTE
    assert (pair.candidate_net_cents, pair.benchmark_net_cents, pair.uplift_cents) == (0, -6500, 6500)
    assert benchmark.break_even_ticks_per_side == -5.5
    pair, _ = _pair(idle, protocol, "base")
    assert (pair.decision_reason, pair.eligible, pair.uplift_cents) == ("no_cross", True, 0)
    pair, legs = _pair(missing, protocol, "base")
    assert (pair.decision_reason, pair.eligible, pair.uplift_cents) == ("missing_confirmation", False, None)
    assert all(leg.status == "excluded" and leg.net_cents is None for leg in legs)


def test_late_confirmation_and_missing_exact_entry():
    protocol = Protocol()
    closes = {30: 80003, 31: 80003, 32: 80003}
    day = date(2030, 3, 11)
    late = make_session(protocol, day, closes=closes, opens={}, late={32: 1})
    assert late.cash_open.hour == 13
    assert detect_opening_range(late, protocol).reason == "late_confirmation"
    gap = make_session(protocol, day, closes=closes, opens={}, missing=(33,))
    pair, legs = _pair(gap, protocol, "base")
    assert not pair.eligible and pair.uplift_cents is None
    assert all(leg.reason == "invalid_exact_entry_open" and leg.actual_entry is None for leg in legs)


def test_future_fill_opens_cannot_change_event():
    protocol = Protocol()
    closes = {30: 80003, 31: 80003, 32: 80003}
    day = date(2030, 1, 7)
    original = make_session(protocol, day, closes=closes, opens={})
    perturbed = make_session(protocol, day, closes=closes, opens={33: 81000, 63: 82000}, late={64: 5})
    assert detect_opening_range(original, protocol) == detect_opening_range(perturbed, protocol)
    assert _pair(original, protocol, "base")[0] != _pair(perturbed, protocol, "base")[0]


def test_bar_boundary_rejects_malformed_prices_and_availability():
    bar = next(iter(acceptance_fixture(Protocol())[0].observations.values())).bar
    with pytest.raises(ValueError, match="Impossible OHLC"):
        replace(bar, high=bar.low - 1)
    with pytest.raises(ValueError, match="whole tick"):
        Observation(replace(bar, close=bar.close + 0.125), bar.end)
    with pytest.raises(ValueError, match="at or after bar close"):
        Observation(bar, bar.timestamp)
