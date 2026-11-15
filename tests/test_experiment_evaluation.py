import pytest

from backtester.experiments import evaluation
from backtester.experiments.evaluation import holm, joint_pvalue, session_bootstrap, stationary_indices
from backtester.experiments.protocol import FAMILY


def test_stationary_blocks_wrap_and_reproduce():
    draws = list(stationary_indices(12, 50, 1_000_000, 401))
    assert draws == list(stationary_indices(12, 50, 1_000_000, 401))
    assert any(11 in draw[:-1] for draw in draws)
    assert all(right == (left + 1) % 12 for draw in draws for left, right in zip(draw, draw[1:]))


def test_shared_session_draws_masks_centered_tail_and_degeneracy(monkeypatch):
    panel = [
        {"absolute": 0, "uplift": None, "constant": 5, "sparse": None},
        {"absolute": None, "uplift": None, "constant": None, "sparse": None},
        {"absolute": 1, "uplift": -1, "constant": 5, "sparse": None},
        {"absolute": 2, "uplift": 1, "constant": 5, "sparse": 4},
    ]

    def draws(size, repetitions, length, seed):
        assert (size, repetitions, length, seed) == (3, 3, 2, 10)
        return iter(((0, 0, 0), (1, 1, 1), (2, 2, 2)))

    monkeypatch.setattr(evaluation, "stationary_indices", draws)
    result = session_bootstrap(panel, draws=3, block_length=2, seed=10)
    assert result["absolute"].mean == 1
    assert result["absolute"].pvalue == 0.5  # The centered sample at +1 ties the observed statistic.
    assert result["absolute"].ci95 == pytest.approx((0.05, 1.95))
    assert (result["uplift"].eligible_sessions, result["uplift"].usable_draws) == (2, 2)
    assert result["uplift"].pvalue == pytest.approx(2 / 3)
    assert result["constant"].status == "constant_series" and result["constant"].pvalue is None
    assert result["sparse"].status == "insufficient_sessions" and result["sparse"].ci95 is None


def test_seeded_serial_fixture_and_holm():
    series = [value for block in range(20) for value in ([-2, -1, 0] if block % 2 else [2, 1, 0])]
    panel = [{"null": value, "positive": value + 3} for value in series]
    result = session_bootstrap(panel, draws=2_000, block_length=5, seed=401)
    assert result["null"].pvalue > 0.05
    assert result["positive"].pvalue == pytest.approx(1 / 2001)
    assert result["positive"].ci95[0] > 0

    assert joint_pvalue([0.001, 0.004]) == 0.004
    assert joint_pvalue([None, 0.004]) is None
    family = {name: {"H1": 0.01, "H4": 0.011, "H6": 0.04}.get(name, 1.0) for name in FAMILY}
    adjusted = holm(family)
    assert tuple(adjusted) == FAMILY
    assert [adjusted[name] for name in ("H1", "H4", "H6", "H10")] == pytest.approx([0.10, 0.10, 0.32, 1])
