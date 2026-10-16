"""Beta binomial sensitivity helpers on SYNTHETIC tables (invented numbers)."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("bbs", ROOT / "scripts" / "beta_binomial_sensitivity.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _table():
    rng = np.random.default_rng(3)
    n = rng.integers(5, 40, 400)
    k = rng.binomial(n, 0.02)
    k[:5] = (n[:5] * 0.8).astype(int)  # a few clearly degraded units
    from tashwish.metrics.stats import wilson_interval

    lo, _ = wilson_interval(k, n)
    return pd.DataFrame({"day": np.repeat(["d1", "d2"], 200), "n_aircraft": n, "k": k, "p0": 0.02, "ci_lo": lo})


def test_rho_zero_is_the_binomial_rule_and_more_rho_never_adds_flags():
    m = _mod()
    t = _table()
    f0 = m.betabinom_flags(t, 0.0)
    assert f0.iloc[:5].all() and f0.sum() >= 5
    counts = [int(m.betabinom_flags(t, r).sum()) for r in (0.0, 0.01, 0.05, 0.2)]
    assert counts == sorted(counts, reverse=True)


def test_rho_moments_is_near_zero_for_binomial_data_and_positive_for_clustered_data():
    m = _mod()
    rng = np.random.default_rng(5)
    n = np.full(3000, 20)
    binom = pd.DataFrame({"n_aircraft": n, "k": rng.binomial(n, 0.1), "p0": 0.1})
    clustered = pd.DataFrame({"n_aircraft": n, "k": rng.binomial(n, rng.beta(0.9, 8.1, 3000)), "p0": 0.1})  # rho 0.1
    assert m.rho_moments(binom) < 0.01
    assert 0.07 < m.rho_moments(clustered) < 0.13
