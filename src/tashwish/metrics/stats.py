"""Small, dependency-light statistics used by the metrics and detection stages.

References (see docs/RESEARCH.md section 2.5): Wilson (1927) score interval; empirical-Bayes beta-binomial shrinkage;
Benjamini-Hochberg (1995) and Benjamini-Yekutieli (2001) false-discovery control.
"""

from __future__ import annotations

import numpy as np
from scipy import stats as sps


def wilson_interval(k, n, confidence: float = 0.95):
    """Wilson score interval for a binomial proportion. Vectorised; returns (lo, hi). n == 0 gives (nan, nan)."""
    k = np.asarray(k, dtype=float)
    n = np.asarray(n, dtype=float)
    z = sps.norm.ppf(0.5 + confidence / 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        phat = k / n
        denom = 1 + z**2 / n
        centre = (phat + z**2 / (2 * n)) / denom
        half = z * np.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2)) / denom
    lo = np.clip(centre - half, 0.0, 1.0)
    hi = np.clip(centre + half, 0.0, 1.0)
    # exact endpoints and containment of the point estimate despite floating-point rounding
    lo = np.where(k == 0, 0.0, np.minimum(lo, phat))
    hi = np.where(k == n, 1.0, np.maximum(hi, phat))
    bad = n <= 0
    lo = np.where(bad, np.nan, lo)
    hi = np.where(bad, np.nan, hi)
    return (lo, hi) if lo.ndim else (float(lo), float(hi))


def binom_sf_pvalue(k, n, p0):
    """One-sided p-value P(X >= k) for X ~ Binomial(n, p0): evidence that the true share exceeds p0."""
    k = np.asarray(k)
    n = np.asarray(n)
    p0 = np.clip(np.asarray(p0, dtype=float), 1e-12, 1 - 1e-12)
    p = sps.binom.sf(k - 1, n, p0)
    return p if np.ndim(p) else float(p)


def fit_beta_prior(k, n, min_n: int = 5, max_strength: float = 200.0):
    """Method-of-moments Beta(a, b) prior for cell shares from cells with n >= min_n.

    Moments are weighted by n. The prior strength a+b is capped so a few huge cells cannot make the prior rigid.
    Returns (a, b). Falls back to a weak uniform-ish prior when there is too little data or no variance.
    """
    k = np.asarray(k, dtype=float)
    n = np.asarray(n, dtype=float)
    ok = n >= min_n
    if ok.sum() < 3:
        return 1.0, 1.0
    p = k[ok] / n[ok]
    w = n[ok]
    m = np.average(p, weights=w)
    v = np.average((p - m) ** 2, weights=w)
    # remove expected binomial sampling variance to estimate between-cell variance
    samp = np.average(m * (1 - m) / n[ok], weights=w)
    between = v - samp
    m = float(np.clip(m, 1e-4, 1 - 1e-4))
    if between <= 1e-6:
        strength = max_strength
    else:
        strength = max(m * (1 - m) / between - 1, 1.0)
        strength = min(strength, max_strength)
    return m * strength, (1 - m) * strength


def shrunk_share(k, n, a: float, b: float):
    """Posterior mean of the share under a Beta(a, b) prior."""
    k = np.asarray(k, dtype=float)
    n = np.asarray(n, dtype=float)
    return (k + a) / (n + a + b)


def benjamini_hochberg(pvalues, q: float = 0.05, dependent: bool = False) -> np.ndarray:
    """Boolean mask of rejected hypotheses controlling FDR at level q.

    dependent=True applies the Benjamini-Yekutieli correction (threshold divided by sum(1/i)), valid under
    arbitrary dependence; adjacent H3 cells are spatially correlated, so detection uses it by default.
    """
    p = np.asarray(pvalues, dtype=float)
    m = p.size
    out = np.zeros(m, dtype=bool)
    if m == 0:
        return out
    c = np.sum(1.0 / np.arange(1, m + 1)) if dependent else 1.0
    order = np.argsort(p, kind="stable")
    thresh = q * (np.arange(1, m + 1) / m) / c
    passed = p[order] <= thresh
    if passed.any():
        kmax = np.max(np.nonzero(passed)[0])
        out[order[: kmax + 1]] = True
    return out
