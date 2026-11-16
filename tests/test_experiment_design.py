from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import date, timedelta
from fractions import Fraction
from itertools import pairwise, product
from math import log, sqrt

import pytest

from backtester.experiments import custody, spa
from backtester.experiments.evaluation import stationary_indices
from backtester.experiments.power import synthetic_power
from backtester.experiments.splits import plan_forward
from backtester.experiments.validation import bootstrap_fixtures


def test_forward_plan_embargo_snapshot_and_unused_tail():
    days = [date(2030, 1, 1) + timedelta(days=2*i) for i in range(14)]
    original = tuple(days)
    settings = dict(holdout_start=days[11] - timedelta(days=1), minimum_train=3, validation_size=3, gap=1)
    plan = plan_forward(days, **settings)
    days.pop()
    assert plan.eligible == original
    assert plan.folds[0].train == original[:3]
    assert plan.folds[0].embargo == original[3:4]
    assert plan.folds[0].validation == original[4:7]
    assert plan.folds[1].train == original[:6]
    assert plan.folds[1].validation == original[7:10]
    assert plan.holdout_embargo == original[10:11]
    assert plan.holdout == original[11:]
    assert not plan.unused_development
    assert plan_forward(original, **settings).sha256 == plan.sha256
    assert plan_forward(days, **settings).sha256 != plan.sha256
    assert plan_forward(original, **{**settings, "validation_size": 4}).unused_development == original[8:10]
    with pytest.raises(FrozenInstanceError):
        plan.eligible = ()


@pytest.mark.parametrize("days", [(1, 1, 2), (2, 1, 3), (1, 2)])
def test_forward_plan_refuses_bad_order_or_missing_holdout(days):
    with pytest.raises(ValueError):
        plan_forward([date(2030, 1, value) for value in days], holdout_start=date(2030, 1, 3),
                     minimum_train=1, validation_size=1)


def test_custody_refuses_historical_before_any_binding_or_disk_read(tmp_path, monkeypatch):
    monkeypatch.setattr(custody, "_binding", lambda: pytest.fail("Historical reached binding"))
    with pytest.raises(PermissionError, match="Historical"):
        custody.evaluate_locked(tmp_path / "absent", stage="historical", confirmation="anything")
    assert not list(tmp_path.iterdir())


def test_custody_requires_binding_and_allows_only_one_concurrent_claim(tmp_path):
    binding = custody.prepare_rehearsal(tmp_path)
    assert custody.prepare_rehearsal(tmp_path) == binding
    with pytest.raises(PermissionError, match="confirmation"):
        custody.evaluate_locked(tmp_path, stage="synthetic", confirmation="wrong")

    def attempt():
        try:
            return custody.evaluate_locked(tmp_path, stage="synthetic", confirmation=binding)
        except PermissionError as error:
            assert "already been claimed" in str(error)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = [report for report in pool.map(lambda _: attempt(), range(2)) if report is not None]
    assert len(reports) == 1
    assert reports[0]["decision_counts"] == {"accepted": 2}
    assert reports[0]["eligible_sessions"] == 2
    assert len(list(tmp_path.glob("*/consumed/report.json"))) == 1
    assert attempt() is None


def test_custody_burns_failed_attempt_and_detects_binding_changes(tmp_path, monkeypatch):
    def fail(*_):
        raise RuntimeError("bad evaluation")

    binding = custody.prepare_rehearsal(tmp_path)
    manifest = next(tmp_path.glob("*/binding.json"))
    original = manifest.read_bytes()
    manifest.write_bytes(b"{}")
    with pytest.raises(PermissionError, match="confirmation"):
        custody.evaluate_locked(tmp_path, stage="synthetic", confirmation=binding)
    manifest.write_bytes(original)
    monkeypatch.setattr(custody, "evaluate", fail)
    with pytest.raises(RuntimeError, match="bad evaluation"):
        custody.evaluate_locked(tmp_path, stage="synthetic", confirmation=binding)
    assert list(tmp_path.glob("*/consumed/attempt.json"))
    assert not list(tmp_path.glob("*/consumed/report.json"))
    with pytest.raises(PermissionError, match="already been claimed"):
        custody.evaluate_locked(tmp_path, stage="synthetic", confirmation=binding)


def test_bootstrap_null_positive_autocorrelation_and_sparse_masks():
    results = bootstrap_fixtures()
    null, positive, sparse = results["null"]["effect"], results["positive"]["effect"], results["sparse"]
    assert null["mean"] == 0 and 0.4 < null["pvalue"] < 0.7
    assert positive["mean"] == 1 and positive["pvalue"] == 1/2000
    assert positive["ci95"] == pytest.approx(tuple(value + 1 for value in null["ci95"]))
    width = {key: case["effect"]["ci95"][1] - case["effect"]["ci95"][0]
             for key, case in results["autocorrelated"].items()}
    assert all(width[length] > 1.4 * width["1"] for length in ("5", "10", "20"))
    assert sparse["sparse"]["eligible_sessions"] == 2
    assert sparse["sparse"]["mean"] == 1
    assert 0 < sparse["sparse"]["usable_draws"] < sparse["dense"]["usable_draws"]
    assert sparse["singleton"]["status"] == sparse["absent"]["status"] == "insufficient_sessions"
    assert sparse["singleton"]["mean"] == 0 and sparse["absent"]["mean"] is None
    assert sparse["constant"]["status"] == "constant_series"


def test_stationary_indices_restart_and_circular_continuation():
    for block, expected in [(1, 1/12), (5, 0.8 + 0.2/12)]:
        draws = tuple(stationary_indices(12, 1000, block, 81))
        assert draws == tuple(stationary_indices(12, 1000, block, 81))
        transitions = [pair for draw in draws for pair in pairwise(draw)]
        observed = sum((a+1) % 12 == b for a, b in transitions) / len(transitions)
        assert observed == pytest.approx(expected, abs=0.02)
        assert (11, 0) in transitions


def test_power_joint_grid_and_resolution():
    design = dict(sessions=32, sigma=1.0, rho=0.2, correlation=0.5, effects=(0, 0.5, 2),
                  simulations=40, draws=399, block_length=5, seed=17)
    result = synthetic_power(**design)
    assert result == synthetic_power(**design)
    assert result.local_alpha == 0.005
    assert result.points[0].probability < result.points[1].probability < result.points[2].probability == 1
    assert result.minimum_detectable_effect == 2
    assert synthetic_power(**{**design, "effects": (0,)}).minimum_detectable_effect is None
    with pytest.raises(ValueError, match="Too few draws"):
        synthetic_power(**{**design, "draws": 98})


@pytest.mark.parametrize("block", [1, 2])
def test_spa_matches_independent_exact_stationary_oracle(block, monkeypatch):
    # Enumerate the transition law directly. Each tuple has probability
    # multiplicity / (3 * (3 * block)**2). No production sampler or covariance.
    paths = []
    for indices in product(range(3), repeat=3):
        multiplicity = 1
        for first, second in pairwise(indices):
            if (first + 1) % 3 == second:
                multiplicity *= 1 + 3 * (block - 1)
        paths.extend([indices] * multiplicity)
    assert len(paths) == 3 * (3 * block)**2
    monkeypatch.setattr(spa, "stationary_indices", lambda *_: iter(paths))
    losses = ((7, 11, 10), (11, 13, 6), (20, 16, 11), (7, 13, 11))
    observed_means, boot_means, standard_errors = [], [], []
    for model in losses:
        advantages = [10 - value for value in model]
        observed = Fraction(sum(advantages), 3)
        centered = [Fraction(sum(advantages[i] for i in path), 3) - observed for path in paths]
        observed_means.append(observed)
        boot_means.append(centered)
        standard_errors.append(sqrt(sum(value**2 for value in centered) / len(paths)))
    observed_scores = [m / s for m, s in zip(observed_means, standard_errors, strict=True)]
    observed_max = max(0, *observed_scores)
    cutoff = -sqrt(2 * log(log(3)))
    offsets = ([min(0, score) for score in observed_scores],
               [score if score <= cutoff else 0 for score in observed_scores], [0] * len(losses))
    expected = []
    for shift in offsets:
        tails = sum(max(0, *(value / se + offset for value, se, offset in
                             zip(sample, standard_errors, shift, strict=True))) >= observed_max - 1e-12
                    for sample in zip(*boot_means, strict=True))
        expected.append((1 + tails) / (1 + len(paths)))
    result = spa.hansen_spa(benchmark_loss=[10, 10, 10], model_losses=dict(zip("abcd", losses, strict=True)),
                           draws=len(paths), block_length=block, seed=0)
    assert result.statistic == pytest.approx(observed_max)
    assert [result.lower_pvalue, result.consistent_pvalue, result.upper_pvalue] == pytest.approx(expected)
    assert result.mean_loss_advantages == (("a", 2/3), ("b", 0), ("c", -17/3), ("d", -1/3))


def test_spa_loss_orientation_and_incomplete_panel_refusal():
    settings = dict(draws=499, block_length=3, seed=301)
    benchmark = [10] * 12
    model = [6, 8, 7, 9] * 3
    result = spa.hansen_spa(benchmark_loss=benchmark, model_losses={"model": model}, **settings)
    reverse = spa.hansen_spa(benchmark_loss=model, model_losses={"model": benchmark}, **settings)
    assert result.statistic > 0 and result.consistent_pvalue <= 0.01
    assert reverse.statistic == 0 and reverse.consistent_pvalue == 1
    for bad in ([1, 3], [5] * 12, [None] * 12, [float("nan")] * 12):
        with pytest.raises(ValueError):
            spa.hansen_spa(benchmark_loss=benchmark, model_losses={"model": bad}, **settings)
