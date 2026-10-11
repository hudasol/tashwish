"""Empirical coverage model: "no data" must never be read as "no interference".

Receiver positions are not published for the source archive, so coverage is inferred from history: for each
(cell, slot-of-day, stratum) we measure on how many baseline days enough aircraft were observed to test anything.

  covered      baseline presence >= COVERED_PRESENCE   (usually testable)
  marginal     baseline presence >= MARGINAL_PRESENCE  (sometimes testable)
  no_coverage  otherwise                                (never reliably observed: never testable)

A cell-bucket is then given a status:
  ok               enough aircraft now AND not a no_coverage cell
  insufficient     too few aircraft now (cell is covered/marginal, or no_coverage): no statement about interference
  coverage_lost    cell is normally covered, but this bucket has far fewer aircraft than usual (or none)
Missing rows for covered cells are materialised as `coverage_lost` so a hole in the data is drawn as a hole.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config as cfg

COVERED_PRESENCE = 0.5
MARGINAL_PRESENCE = 0.1
LOST_RATIO = 0.3  # current aircraft below this fraction of the baseline mean => coverage (or traffic) lost


def slot_of_day(bucket: pd.Series, grid: cfg.Grid) -> pd.Series:
    return (bucket.dt.tz_convert("UTC").dt.hour // grid.bucket_hours).astype(int)


def fit_coverage(cb: pd.DataFrame, baseline_days: list[str], grid: cfg.Grid) -> pd.DataFrame:
    """Baseline coverage per (cell, slot, stratum) from cell-bucket metrics `cb` (needs cell, bucket, stratum, n_aircraft)."""
    days = pd.to_datetime(pd.Series(baseline_days)).dt.date.tolist()
    if not days:
        raise ValueError("baseline_days must not be empty")
    c = cb.copy()
    c["day"] = c["bucket"].dt.tz_convert("UTC").dt.date
    c = c[c["day"].isin(days)]
    c["slot"] = slot_of_day(c["bucket"], grid)
    c["tested"] = c["n_aircraft"] >= cfg.MIN_AIRCRAFT_PER_CELL
    g = c.groupby(["cell", "slot", "stratum"]).agg(
        sum_n=("n_aircraft", "sum"), days_testable=("tested", "sum"), days_seen=("day", "nunique")
    )
    g = g.reset_index()
    d = len(days)
    g["baseline_days"] = d
    g["mean_n"] = g["sum_n"] / d
    g["presence"] = g["days_testable"] / d
    g["coverage_class"] = np.select(
        [g["presence"] >= COVERED_PRESENCE, g["presence"] >= MARGINAL_PRESENCE], ["covered", "marginal"], "no_coverage"
    )
    return g


def apply_coverage(
    cb: pd.DataFrame,
    cov: pd.DataFrame,
    grid: cfg.Grid,
    baseline_days: list[str],
    window_buckets: list[pd.Timestamp] | None = None,
) -> pd.DataFrame:
    """Attach coverage class and a final status to cell-bucket metrics; materialise coverage holes.

    Rows that fall on a baseline day are scored leave-one-day-out: that day's own contribution is removed from the
    baseline first, so a day cannot vouch for its own coverage.
    """
    key = ["cell", "slot", "stratum"]
    cb = cb.copy()
    cb["slot"] = slot_of_day(cb["bucket"], grid)

    if window_buckets is not None:
        usable = cov.loc[cov["coverage_class"].isin(["covered", "marginal"]), key]
        parts = []
        for b in window_buckets:
            b = pd.Timestamp(b).tz_convert("UTC")
            u = usable[usable["slot"] == b.hour // grid.bucket_hours].copy()
            u["bucket"] = b
            parts.append(u)
        if parts:
            holes = pd.concat(parts, ignore_index=True)
            have = cb[["cell", "bucket", "stratum"]].assign(_have=1)
            holes = holes.merge(have, on=["cell", "bucket", "stratum"], how="left")
            holes = holes[holes["_have"].isna()].drop(columns="_have")
            if len(holes):
                for col in ("n_aircraft", "k_strong", "k_gpsjam", "n_samples"):
                    holes[col] = 0
                holes["sufficient"] = False
                cb = pd.concat([cb, holes], ignore_index=True)

    base = cb[key].merge(cov[[*key, "sum_n", "days_testable"]], on=key, how="left")
    sum_n = base["sum_n"].fillna(0.0).to_numpy()
    tested = base["days_testable"].fillna(0.0).to_numpy()
    n_days = float(len(baseline_days))
    day = cb["bucket"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d")
    in_base = day.isin(set(baseline_days)).to_numpy()
    own_n = np.where(in_base, cb["n_aircraft"].to_numpy(), 0.0)
    own_t = np.where(in_base & (cb["n_aircraft"].to_numpy() >= cfg.MIN_AIRCRAFT_PER_CELL), 1.0, 0.0)
    denom = np.where(in_base, n_days - 1.0, n_days)
    if (denom <= 0).any():
        raise ValueError("leave-one-day-out needs at least 2 baseline days")
    cb["baseline_mean_n"] = (sum_n - own_n) / denom
    cb["baseline_presence"] = (tested - own_t) / denom
    cb["coverage_class"] = np.select(
        [cb["baseline_presence"] >= COVERED_PRESENCE, cb["baseline_presence"] >= MARGINAL_PRESENCE],
        ["covered", "marginal"],
        "no_coverage",
    )
    mean_n = cb["baseline_mean_n"].to_numpy()
    cb["coverage_ratio"] = np.where(mean_n > 0, cb["n_aircraft"].to_numpy() / np.where(mean_n > 0, mean_n, 1), np.nan)

    enough = cb["n_aircraft"] >= cfg.MIN_AIRCRAFT_PER_CELL
    usable_cls = cb["coverage_class"] != "no_coverage"
    lost = (
        (cb["coverage_class"] == "covered") & ~enough & ((cb["n_aircraft"] == 0) | (cb["coverage_ratio"] < LOST_RATIO))
    )
    cb["status"] = np.select([enough & usable_cls, lost], ["ok", "coverage_lost"], "insufficient")
    cb.loc[cb["n_aircraft"] == 0, "share_strong"] = np.nan
    return cb
