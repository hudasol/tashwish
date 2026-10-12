"""Jamming-like detector on cell-bucket metrics.

A cell-bucket is flagged when, among aircraft observed in it, the degraded share is significantly above that cell's own
baseline (one-sided binomial test, Benjamini-Yekutieli FDR per day) AND the Wilson lower bound clears an effect-size gate
AND at least DETECT_MIN_BAD aircraft are degraded. Only cell-buckets with status "ok" are tested; insufficient or
coverage_lost buckets are never flagged and never counted as quiet. Flags are merged into events by H3 adjacency and time.
Output is evidence of jamming-LIKE degradation, not proof, and says nothing about who caused it.
"""

from __future__ import annotations

import hashlib

import h3
import numpy as np
import pandas as pd

from .. import config as cfg
from ..metrics.stats import benjamini_hochberg, binom_sf_pvalue, fit_beta_prior, wilson_interval


def baseline_p0(cb: pd.DataFrame, baseline_days: list[str], tier: str = "strong") -> pd.DataFrame:
    """Per (cell, stratum) degraded share over baseline days, leave-one-day-out, shrunk and floored.

    Returns one row per (cell, stratum, day) in `cb` with columns p0 and n_base. Contamination of the baseline by past
    events can only raise p0, which makes the detector more conservative.
    """
    kcol = "k_strong" if tier == "strong" else "k_gpsjam"
    d = cb.assign(day=cb["bucket"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d"))
    base = d[d["day"].isin(set(baseline_days))]
    per_day = base.groupby(["cell", "stratum", "day"], as_index=False).agg(k=(kcol, "sum"), n=("n_aircraft", "sum"))
    tot = per_day.groupby(["cell", "stratum"], as_index=False).agg(K=("k", "sum"), N=("n", "sum"))
    keys = d[["cell", "stratum", "day"]].drop_duplicates()
    m = keys.merge(tot, on=["cell", "stratum"], how="left").merge(per_day, on=["cell", "stratum", "day"], how="left")
    for c in ("K", "N", "k", "n"):
        m[c] = m[c].fillna(0.0)
    m["k_base"] = m["K"] - m["k"]  # leave this day out (zero if the day is not a baseline day)
    m["n_base"] = m["N"] - m["n"]
    a, b = fit_beta_prior(tot["K"].to_numpy(), tot["N"].to_numpy())
    m["p0"] = np.maximum((m["k_base"] + a) / (m["n_base"] + a + b), cfg.DETECT_P0_FLOOR)
    return m[["cell", "stratum", "day", "p0", "n_base"]]


def fit_p0(cb: pd.DataFrame, baseline_days: list[str], tier: str = "strong") -> pd.DataFrame:
    """Pooled (not leave-one-out) per (cell, stratum) baseline p0 for scoring days that are NOT baseline days."""
    kcol = "k_strong" if tier == "strong" else "k_gpsjam"
    d = cb.assign(day=cb["bucket"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d"))
    base = d[d["day"].isin(set(baseline_days))]
    tot = base.groupby(["cell", "stratum"], as_index=False).agg(K=(kcol, "sum"), N=("n_aircraft", "sum"))
    a, b = fit_beta_prior(tot["K"].to_numpy(), tot["N"].to_numpy())
    tot["p0"] = np.maximum((tot["K"] + a) / (tot["N"] + a + b), cfg.DETECT_P0_FLOOR)
    return tot[["cell", "stratum", "p0"]]


def flag_buckets(
    cb: pd.DataFrame,
    baseline_days: list[str],
    tier: str = "strong",
    stratum: str = "enroute",
    p0: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return the tested cell-buckets of one stratum with p-values and a boolean `flag`.

    `p0`: optional precomputed table from fit_p0 (for scoring days that are not baseline days); otherwise
    leave-one-day-out baselines.
    """
    kcol = "k_strong" if tier == "strong" else "k_gpsjam"
    t = cb[(cb["stratum"] == stratum) & (cb["status"] == "ok")].copy()
    if t.empty:
        return t.assign(p0=[], p_value=[], p_adj_ok=[], ci_lo=[], ci_hi=[], k=[], flag=[])
    t["day"] = t["bucket"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d")
    if p0 is None:
        t = t.merge(baseline_p0(cb, baseline_days, tier), on=["cell", "stratum", "day"], how="left")
    else:
        t = t.merge(p0, on=["cell", "stratum"], how="left")
    t["p0"] = t["p0"].fillna(cfg.DETECT_P0_FLOOR)
    t["k"] = t[kcol].astype(int)
    t["p_value"] = binom_sf_pvalue(t["k"], t["n_aircraft"], t["p0"])
    lo, hi = wilson_interval(t["k"], t["n_aircraft"])
    t["ci_lo"], t["ci_hi"] = lo, hi
    t["p_adj_ok"] = False
    for _, idx in t.groupby("day").groups.items():
        t.loc[idx, "p_adj_ok"] = benjamini_hochberg(t.loc[idx, "p_value"].to_numpy(), cfg.DETECT_FDR_Q, dependent=True)
    t["flag"] = t["p_adj_ok"] & (t["k"] >= cfg.DETECT_MIN_BAD) & (t["ci_lo"] >= cfg.DETECT_MIN_LOWER_BOUND)
    return t.drop(columns=["day"])


def build_events(flags: pd.DataFrame, grid: cfg.Grid, tier: str = "strong") -> pd.DataFrame:
    """Merge flagged cell-buckets into events (H3 neighbours, same or nearby buckets). Deterministic ids."""
    f = flags[flags["flag"]].reset_index(drop=True)
    cols = [
        "event_id", "kind", "tier", "start", "end", "n_cells", "n_buckets", "cells", "k_total", "n_total", "peak_share",
        "peak_ci_lo", "min_p", "lat", "lon", "confidence",
    ]  # fmt: skip
    if f.empty:
        return pd.DataFrame(columns=cols)
    step = pd.Timedelta(hours=grid.bucket_hours)
    gap = step * (cfg.DETECT_MERGE_GAP_BUCKETS + 1)
    parent = list(range(len(f)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_cell: dict[str, list[int]] = {}
    for i, c in enumerate(f["cell"]):
        by_cell.setdefault(c, []).append(i)
    for i, (c, b) in enumerate(zip(f["cell"], f["bucket"], strict=True)):
        for nb in h3.grid_disk(c, 1):
            for j in by_cell.get(nb, ()):
                if j != i and abs(f["bucket"].iat[j] - b) < gap:
                    parent[find(i)] = find(j)
    f["_g"] = [find(i) for i in range(len(f))]
    out = []
    for _, g in f.groupby("_g", sort=False):
        cells = sorted(g["cell"].unique())
        start, end = g["bucket"].min(), g["bucket"].max() + step
        ll = np.array([h3.cell_to_latlng(c) for c in cells])
        peak_lo = float(g["ci_lo"].max())
        conf = (
            "high"
            if (len(cells) >= 2 and g["bucket"].nunique() >= 2 and peak_lo >= cfg.DETECT_HIGH_LOWER_BOUND)
            else ("medium" if (len(cells) >= 2 or g["bucket"].nunique() >= 2) else "low")
        )
        eid = hashlib.sha1(f"jam|{tier}|{start.isoformat()}|{cells[0]}|{len(cells)}".encode()).hexdigest()[:12]
        out.append({
            "event_id": f"J-{eid}", "kind": "jamming_like", "tier": tier, "start": start, "end": end,
            "n_cells": len(cells), "n_buckets": int(g["bucket"].nunique()), "cells": ",".join(cells),
            "k_total": int(g["k"].sum()), "n_total": int(g["n_aircraft"].sum()),
            "peak_share": float((g["k"] / g["n_aircraft"]).max()), "peak_ci_lo": peak_lo, "min_p": float(g["p_value"].min()),
            "lat": float(ll[:, 0].mean()), "lon": float(ll[:, 1].mean()), "confidence": conf,
        })  # fmt: skip
    return pd.DataFrame(out, columns=cols).sort_values(["start", "event_id"]).reset_index(drop=True)


def detect_jamming(cb, baseline_days, grid, tier="strong", stratum="enroute", p0=None):
    flags = flag_buckets(cb, baseline_days, tier, stratum, p0)
    return flags, build_events(flags, grid, tier)
