"""Reproducible synthetic inference validation. All inputs are constructed here."""

from dataclasses import asdict
from random import Random

from .evaluation import session_bootstrap
from .power import synthetic_power
from .spa import hansen_spa


def bootstrap_fixtures() -> dict:
    settings = {"draws": 1999, "seed": 401}

    def estimate(panel, length):
        return {name: asdict(result) for name, result in
                session_bootstrap(panel, block_length=length, **settings).items()}

    balanced = (-3.0, 1.0, -1.0, 3.0) * 24
    rng = Random(513)
    correlated = []
    state = 0.0
    for _ in range(96):
        state = 0.85 * state + rng.gauss(0, 1)
        correlated.append({"effect": state})
    sparse = [{"dense": float(index % 7 - 3), "sparse": {2: -1.0, 90: 3.0}.get(index),
               "singleton": 0.0 if index == 1 else None, "absent": None, "constant": 0.0}
              for index in range(96)]
    return {
        "settings": settings,
        "null": estimate([{"effect": value} for value in balanced], 5),
        "positive": estimate([{"effect": value + 1.0} for value in balanced], 5),
        "autocorrelated": {str(length): estimate(correlated, length) for length in (1, 5, 10, 20)},
        "sparse": estimate(sparse, 5),
    }


def synthetic_validation() -> dict:
    design = {"sessions": 96, "sigma": 1.0, "correlation": 0.5, "effects": (0.0, 0.25, 0.5, 0.75, 1.0),
              "simulations": 250, "draws": 399, "block_length": 5, "seed": 817, "alpha": 0.05,
              "family_slots": 10, "target_power": 0.8}
    return {
        "stage": "synthetic", "bootstrap": bootstrap_fixtures(),
        "power_design": design,
        "power": {str(rho): asdict(synthetic_power(rho=rho, **design)) for rho in (0.0, 0.6)},
        "spa": asdict(hansen_spa(benchmark_loss=[10] * 12,
                                 model_losses={"better": [7, 9, 8, 10] * 3, "worse": [14, 13, 15, 12] * 3},
                                 draws=1999, block_length=5, seed=401)),
    }
