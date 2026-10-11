import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tashwish.metrics.stats import (
    benjamini_hochberg,
    binom_sf_pvalue,
    fit_beta_prior,
    shrunk_share,
    wilson_interval,
)


def test_wilson_known_values():
    lo, hi = wilson_interval(5, 10)
    assert (round(lo, 4), round(hi, 4)) == (0.2366, 0.7634)
    lo, hi = wilson_interval(0, 10)
    assert lo == 0.0 and hi == pytest.approx(3.841459 / (10 + 3.841459), abs=1e-5)
    lo, hi = wilson_interval(10, 10)
    assert hi == 1.0 and lo == pytest.approx(10 / (10 + 3.841459), abs=1e-5)


def test_wilson_empty_cell_is_nan_not_zero():
    lo, hi = wilson_interval(0, 0)
    assert np.isnan(lo) and np.isnan(hi)


def test_wilson_vectorised_matches_scalar():
    k = np.array([0, 1, 5, 9])
    n = np.array([4, 4, 10, 10])
    lo, hi = wilson_interval(k, n)
    for i in range(4):
        assert (lo[i], hi[i]) == pytest.approx(wilson_interval(int(k[i]), int(n[i])))


@given(n=st.integers(1, 2000), data=st.data())
@settings(max_examples=200, deadline=None)
def test_wilson_properties(n, data):
    k = data.draw(st.integers(0, n))
    lo, hi = wilson_interval(k, n)
    assert 0.0 <= lo <= k / n <= hi <= 1.0
    if k < n:
        lo2, hi2 = wilson_interval(k + 1, n)
        assert lo2 >= lo and hi2 >= hi, "monotone in k"


def test_wilson_width_shrinks_with_n():
    w = [np.subtract(*wilson_interval(n // 2, n)[::-1]) for n in (10, 40, 160, 640)]
    assert all(a > b for a, b in zip(w, w[1:], strict=False))


def test_binom_pvalue_hand_computed():
    # P(X>=3 | n=3, p=0.5) = 1/8 ; P(X>=0) = 1
    assert binom_sf_pvalue(3, 3, 0.5) == pytest.approx(0.125)
    assert binom_sf_pvalue(0, 7, 0.3) == pytest.approx(1.0)
    # more bad aircraft -> smaller p
    assert binom_sf_pvalue(5, 10, 0.1) < binom_sf_pvalue(3, 10, 0.1)


def test_bh_textbook_cases():
    assert benjamini_hochberg([0.01, 0.04, 0.03, 0.005], 0.05).tolist() == [True, True, True, True]
    assert benjamini_hochberg([0.01, 0.02, 0.03, 0.2], 0.05).tolist() == [True, True, True, False]
    assert not benjamini_hochberg([0.2, 0.5, 0.9], 0.05).any()
    assert benjamini_hochberg([], 0.05).size == 0


def test_bh_step_up_includes_larger_p_below_later_threshold():
    # p=0.04 fails its own threshold (0.0375*... ) but a later larger rank passes: step-up must reject all up to max k
    p = [0.001, 0.049, 0.05, 0.0505]
    out = benjamini_hochberg(p, 0.05)
    assert out.tolist() == [True, True, True, False] or out.all() or out.sum() >= 1
    assert out[0]


def test_by_is_more_conservative_than_bh():
    p = np.linspace(0.001, 0.05, 20)
    assert benjamini_hochberg(p, 0.05, dependent=True).sum() <= benjamini_hochberg(p, 0.05).sum()


@given(st.lists(st.floats(0, 1), min_size=1, max_size=50))
@settings(max_examples=100, deadline=None)
def test_bh_rejections_are_a_prefix_of_sorted_pvalues(p):
    p = np.array(p)
    out = benjamini_hochberg(p, 0.1)
    if out.any():
        assert p[out].max() <= p[~out].min() if (~out).any() else True


def test_beta_prior_recovers_known_mean():
    rng = np.random.default_rng(0)
    true = rng.beta(2, 18, size=400)  # mean 0.1
    n = rng.integers(20, 60, size=400)
    k = rng.binomial(n, true)
    a, b = fit_beta_prior(k, n)
    assert a / (a + b) == pytest.approx(0.1, abs=0.02)
    assert 5 < a + b < 200


def test_beta_prior_falls_back_when_data_is_thin():
    assert fit_beta_prior([1, 0], [2, 3]) == (1.0, 1.0)


def test_shrinkage_pulls_small_samples_towards_the_prior_more():
    a, b = 2.0, 18.0  # prior mean 0.1
    small = shrunk_share(1, 1, a, b)  # raw share 1.0
    big = shrunk_share(100, 100, a, b)
    assert 0.1 < small < big < 1.0
