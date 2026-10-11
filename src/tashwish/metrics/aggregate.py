"""Per cell, per time bucket, per altitude stratum degradation metrics from ingested points.

Unit of counting is the *aircraft* (unique icao24), not the message. Within a cell-bucket an aircraft is degraded
if at least DEGRADED_FRACTION of its quality-bearing samples are degraded (and it has >= MIN_SAMPLES_PER_AIRCRAFT).
Cells with fewer than MIN_AIRCRAFT_PER_CELL eligible aircraft are marked `insufficient`, never "quiet".
"""

from __future__ import annotations

import h3
import numpy as np
import pandas as pd

from .. import config as cfg
from .stats import fit_beta_prior, shrunk_share, wilson_interval

POINT_COLS = ["icao24", "ts", "lat", "lon", "alt_baro_ft", "nic", "nac_p"]


def metric_samples(points: pd.DataFrame) -> pd.DataFrame:
    """Airborne, non-vehicle samples that carry quality information, with degradation flags."""
    p = points
    keep = (p["src_type"] != cfg.SRC_NON_TRANSPONDER) & (~p["on_ground"]) & p["nic"].notna() & p["alt_baro_ft"].notna()
    d = p.loc[keep, POINT_COLS].copy()
    nic_low = d["nic"] < cfg.NIC_STRONG_BELOW
    nacp_known = d["nac_p"].notna()
    d["low_strong"] = nic_low | (nacp_known & (d["nac_p"] < cfg.NACP_STRONG_BELOW))
    d["low_gpsjam"] = nacp_known & (d["nac_p"] < cfg.NACP_GPSJAM_BELOW)
    return d


def add_cells(d: pd.DataFrame, grid: cfg.Grid) -> pd.DataFrame:
    d = d.copy()
    d["cell"] = [h3.latlng_to_cell(a, b, grid.h3_res) for a, b in zip(d["lat"], d["lon"], strict=True)]
    ts = d["ts"].dt.tz_convert("UTC")
    d["bucket"] = ts.dt.floor(f"{grid.bucket_hours}h")
    return d


def stratum_labels(alt_ft: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [alt_ft >= cfg.HIGH_MIN_FT, alt_ft >= cfg.ENROUTE_MIN_FT],
            ["high", "mid"],
            default="low",
        ),
        index=alt_ft.index,
    )


def persistent_low_aircraft(samples: pd.DataFrame) -> pd.DataFrame:
    """Aircraft that are degraded almost all the time wherever they are seen (avionics, not interference).

    Computed on a baseline window of en-route samples. Returned table lists the aircraft and the evidence.
    """
    e = samples[samples["alt_baro_ft"] >= cfg.ENROUTE_MIN_FT]
    g = e.groupby("icao24").agg(
        n=("low_strong", "size"),
        low_share=("low_strong", "mean"),
        days=("ts", lambda s: s.dt.tz_convert("UTC").dt.date.nunique()),
    )
    out = g[
        (g.n >= cfg.PERSISTENT_MIN_SAMPLES)
        & (g.days >= cfg.PERSISTENT_MIN_DAYS)
        & (g.low_share >= cfg.PERSISTENT_LOW_SHARE)
    ]
    return out.reset_index()


def aircraft_buckets(d: pd.DataFrame) -> pd.DataFrame:
    """One row per (cell, bucket, stratum-label, aircraft) for strata low/mid/high and the union 'enroute'."""
    d = d.copy()
    d["band"] = stratum_labels(d["alt_baro_ft"])
    frames = []
    for label, sel in (
        ("enroute", d["band"].isin(["mid", "high"])),
        ("high", d["band"] == "high"),
        ("mid", d["band"] == "mid"),
        ("low", d["band"] == "low"),
    ):
        s = d[sel]
        if s.empty:
            continue
        g = s.groupby(["cell", "bucket", "icao24"], sort=True).agg(
            n_samples=("low_strong", "size"),
            n_strong=("low_strong", "sum"),
            n_gpsjam=("low_gpsjam", "sum"),
            first_ts=("ts", "min"),
            last_ts=("ts", "max"),
        )
        g["stratum"] = label
        frames.append(g.reset_index())
    if not frames:
        return pd.DataFrame(
            columns=["cell", "bucket", "icao24", "n_samples", "n_strong", "n_gpsjam", "first_ts", "last_ts", "stratum"]
        )
    return pd.concat(frames, ignore_index=True)


def cell_bucket_metrics(ab: pd.DataFrame, n_excluded: pd.DataFrame | None = None) -> pd.DataFrame:
    """Aggregate aircraft-bucket rows to cell-bucket metrics with intervals and sufficiency status."""
    cols = [
        "cell", "bucket", "stratum", "n_aircraft", "k_strong", "k_gpsjam", "n_samples", "share_strong",
        "ci_lo_strong", "ci_hi_strong", "share_gpsjam", "ci_lo_gpsjam", "ci_hi_gpsjam", "sufficient", "status",
        "shrunk_share_strong", "traffic_ratio",
    ]  # fmt: skip
    if ab.empty:
        return pd.DataFrame(columns=cols)
    e = ab[ab["n_samples"] >= cfg.MIN_SAMPLES_PER_AIRCRAFT].copy()
    e["deg_strong"] = (e["n_strong"] / e["n_samples"]) >= cfg.DEGRADED_FRACTION
    e["deg_gpsjam"] = (e["n_gpsjam"] / e["n_samples"]) >= cfg.DEGRADED_FRACTION
    g = e.groupby(["cell", "bucket", "stratum"], sort=True).agg(
        n_aircraft=("icao24", "nunique"),
        k_strong=("deg_strong", "sum"),
        k_gpsjam=("deg_gpsjam", "sum"),
        n_samples=("n_samples", "sum"),
    )
    g = g.reset_index()
    g["share_strong"] = g.k_strong / g.n_aircraft
    g["ci_lo_strong"], g["ci_hi_strong"] = wilson_interval(g.k_strong, g.n_aircraft)
    g["share_gpsjam"] = g.k_gpsjam / g.n_aircraft
    g["ci_lo_gpsjam"], g["ci_hi_gpsjam"] = wilson_interval(g.k_gpsjam, g.n_aircraft)
    g["sufficient"] = g.n_aircraft >= cfg.MIN_AIRCRAFT_PER_CELL
    g["status"] = np.where(g.sufficient, "ok", "insufficient")
    g["shrunk_share_strong"] = np.nan
    for _stratum, idx in g.groupby("stratum").groups.items():
        sub = g.loc[idx]
        a, b = fit_beta_prior(sub.k_strong.to_numpy(), sub.n_aircraft.to_numpy(), cfg.MIN_AIRCRAFT_PER_CELL)
        g.loc[idx, "shrunk_share_strong"] = shrunk_share(sub.k_strong.to_numpy(), sub.n_aircraft.to_numpy(), a, b)
    med = g.groupby(["cell", "stratum"]).n_aircraft.transform("median")
    g["traffic_ratio"] = g.n_aircraft / med
    g["k_strong"] = g.k_strong.astype(int)
    g["k_gpsjam"] = g.k_gpsjam.astype(int)
    return g[cols]
