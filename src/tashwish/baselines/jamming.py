"""Jamming-like comparison detectors B1, B1b, B2 and the B3 ablations of the real detector.

All consume the cell bucket metrics produced by `tashwish.pipeline.metrics_for_day` (optionally with the coverage model
applied) and emit flags in the columns of `tashwish.detect.jamming.flag_buckets`, then events through the unchanged
`build_events`. Flags describe jamming-LIKE degradation only and say nothing about who caused it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import config as cfg
from ..coverage.model import apply_coverage, fit_coverage, slot_of_day
from ..detect.jamming import build_events, fit_p0, flag_buckets
from ..metrics.stats import wilson_interval
from . import constants as bc

FLAG_COLS = ["cell", "bucket", "stratum", "n_aircraft", "k", "ci_lo", "ci_hi", "p_value", "flag"]


def _day(bucket: pd.Series) -> pd.Series:
    return bucket.dt.tz_convert("UTC").dt.strftime("%Y-%m-%d")


def _frame(t: pd.DataFrame, flag: np.ndarray) -> pd.DataFrame:
    """Flags in the shape `build_events` reads. `p_value` is NaN because these baselines compute none."""
    t = t.reset_index(drop=True)
    k = t["k_strong"].astype(int).to_numpy()
    n = t["n_aircraft"].to_numpy()
    lo, hi = wilson_interval(k, n)
    out = pd.DataFrame({
        "cell": t["cell"], "bucket": t["bucket"], "stratum": t["stratum"], "n_aircraft": n, "k": k,
        "ci_lo": np.asarray(lo), "ci_hi": np.asarray(hi), "p_value": np.nan, "flag": np.asarray(flag, dtype=bool),
    })  # fmt: skip
    return out[FLAG_COLS]


def _tested(cb: pd.DataFrame, stratum: str, min_aircraft: int) -> pd.DataFrame:
    return cb[(cb["stratum"] == stratum) & (cb["n_aircraft"] >= min_aircraft)].reset_index(drop=True)


# ---------------------------------------------------------------- B1 and B1b: fixed fraction


def flag_fixed_fraction(cb: pd.DataFrame, stratum: str = "enroute", sparsity_correction: bool = False) -> pd.DataFrame:
    """B1 (and B1b with `sparsity_correction`): flag when the degraded share is at least B1_MIN_SHARE, with enough aircraft.

    No baseline, no interval, no coverage model, no multiple test control. B1b subtracts B1B_SPARSITY_OFFSET from the
    degraded count before dividing.
    """
    t = _tested(cb, stratum, bc.B1_MIN_AIRCRAFT)
    offset = bc.B1B_SPARSITY_OFFSET if sparsity_correction else 0
    share = (t["k_strong"].to_numpy(dtype=float) - offset) / t["n_aircraft"].to_numpy(dtype=float)
    return _frame(t, share >= bc.B1_MIN_SHARE)


def detect_fixed_fraction(cb, grid, stratum="enroute", sparsity_correction=False):
    flags = flag_fixed_fraction(cb, stratum, sparsity_correction)
    return flags, build_events(flags, grid, "strong")


# ---------------------------------------------------------------- B2: climatology z score


def fit_climatology(cb: pd.DataFrame, days: list[str], grid: cfg.Grid, stratum: str = "enroute") -> pd.DataFrame:
    """Mean and sample standard deviation of the degraded share per (cell, slot) over `days` (development days only).

    Only cell buckets with at least B2_MIN_AIRCRAFT aircraft contribute. Returns cell, slot, mean, sd, n_days.
    """
    d = cb[(cb["stratum"] == stratum) & (cb["n_aircraft"] >= bc.B2_MIN_AIRCRAFT)]
    d = d[_day(d["bucket"]).isin(set(days))].copy()
    d["slot"] = slot_of_day(d["bucket"], grid)
    d["share"] = d["k_strong"].to_numpy(dtype=float) / d["n_aircraft"].to_numpy(dtype=float)
    g = d.groupby(["cell", "slot"])["share"].agg(mean="mean", sd=lambda s: s.std(ddof=1), n_days="size").reset_index()
    return g[g["n_days"] >= bc.B2_MIN_DAYS].reset_index(drop=True)


def flag_climatology(cb: pd.DataFrame, clim: pd.DataFrame, grid: cfg.Grid, stratum: str = "enroute") -> pd.DataFrame:
    """B2: flag when the share is strictly above mean plus B2_Z standard deviations of the cell's own slot climatology."""
    t = _tested(cb, stratum, bc.B2_MIN_AIRCRAFT)
    t = t.assign(slot=slot_of_day(t["bucket"], grid) if len(t) else pd.Series(dtype=int))
    m = t.merge(clim, on=["cell", "slot"], how="left")
    share = m["k_strong"].to_numpy(dtype=float) / m["n_aircraft"].to_numpy(dtype=float)
    thr = m["mean"].to_numpy(dtype=float) + bc.B2_Z * m["sd"].to_numpy(dtype=float)
    with np.errstate(invalid="ignore"):
        flag = np.where(np.isnan(thr), False, share > thr)
    return _frame(m, flag)


def detect_climatology(cb, clim, grid, stratum="enroute"):
    flags = flag_climatology(cb, clim, grid, stratum)
    return flags, build_events(flags, grid, "strong")


# ---------------------------------------------------------------- B3: the real binomial detector with safeguards removed


@dataclass
class PooledFit:
    """Coverage model and baseline share fitted on all development days (other than the scored day), ignoring regimes."""

    days: list[str]
    cov: pd.DataFrame
    p0: pd.DataFrame


def fit_pooled(cb_dev: pd.DataFrame, days: list[str], grid: cfg.Grid) -> PooledFit:
    """B3a fit: the system's own `fit_coverage` and `fit_p0`, applied to every development day without regime selection."""
    return PooledFit(list(days), fit_coverage(cb_dev, days, grid), fit_p0(cb_dev, days))


def detect_no_regime(cb_raw, pooled: PooledFit, grid, day_buckets=None, stratum="enroute"):
    """B3a: real detector, pooled coverage and p0 (no regime awareness)."""
    cb = apply_coverage(cb_raw, pooled.cov, grid, pooled.days, window_buckets=day_buckets)
    flags = flag_buckets(cb, pooled.days, "strong", stratum, pooled.p0)
    return flags, build_events(flags, grid, "strong")


def detect_no_coverage(cb_raw, base_days, p0, grid, stratum="enroute"):
    """B3b: real detector with regime aware p0 but no coverage gating (status is only 'at least 5 aircraft')."""
    flags = flag_buckets(cb_raw, base_days, "strong", stratum, p0)
    return flags, build_events(flags, grid, "strong")


def detect_no_fdr(cb_cov, base_days, p0, grid, stratum="enroute"):
    """B3c: real detector and p values, but a per test threshold B3C_ALPHA instead of false discovery control."""
    flags = flag_buckets(cb_cov, base_days, "strong", stratum, p0)
    if len(flags):
        flags = flags.assign(
            flag=(flags["p_value"] < bc.B3C_ALPHA)
            & (flags["k"] >= cfg.DETECT_MIN_BAD)
            & (flags["ci_lo"] >= cfg.DETECT_MIN_LOWER_BOUND)
        )
    return flags, build_events(flags, grid, "strong")
