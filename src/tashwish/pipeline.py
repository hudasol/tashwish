"""Stage orchestration: points -> aircraft-bucket rows (cached) -> cell-bucket metrics -> coverage -> detections.

Aircraft-bucket rows (`ab`) are a derived, aircraft-level intermediate (they contain ICAO24 ids). They are kept in
data/interim and are NEVER released; only cell-bucket aggregates and events (no identifiers) are.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config as cfg
from .metrics.aggregate import add_cells, aircraft_buckets, cell_bucket_metrics, metric_samples
from .metrics.loader import load_points

AB_COLS = ["cell", "bucket", "icao24", "n_samples", "n_strong", "n_gpsjam", "first_ts", "last_ts", "stratum"]


def ab_path(interim: Path, day: str, grid: cfg.Grid) -> Path:
    return interim / "ab" / f"ab_r{grid.h3_res}_b{grid.bucket_hours}_{day}.parquet"


def build_ab(interim: Path, day: str, grid: cfg.Grid = cfg.GRID_MAIN, force: bool = False) -> pd.DataFrame:
    """Aircraft-bucket table for one observed day, cached on disk."""
    path = ab_path(interim, day, grid)
    if path.exists() and not force:
        return pd.read_parquet(path)
    pts = load_points(interim, [day])
    d = add_cells(metric_samples(pts), grid)
    ab = aircraft_buckets(d)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    ab.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)
    return ab


def enroute_aircraft_stats(ab: pd.DataFrame) -> pd.DataFrame:
    """Per-aircraft en-route sample counts for one day, from `ab` (stratum 'enroute')."""
    e = ab[ab["stratum"] == "enroute"]
    g = e.groupby("icao24").agg(n=("n_samples", "sum"), n_low=("n_strong", "sum"))
    return g.reset_index()


def persistent_from_daily(daily: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Persistent low emitters (avionics heterogeneity, not interference) from per-day stats of BASELINE days only."""
    frames = [d.assign(day=k) for k, d in daily.items()]
    if not frames:
        return pd.DataFrame(columns=["icao24", "n", "days", "low_share"])
    a = pd.concat(frames, ignore_index=True)
    g = a.groupby("icao24").agg(n=("n", "sum"), n_low=("n_low", "sum"), days=("day", "nunique"))
    g["low_share"] = g["n_low"] / g["n"]
    out = g[
        (g["n"] >= cfg.PERSISTENT_MIN_SAMPLES)
        & (g["days"] >= cfg.PERSISTENT_MIN_DAYS)
        & (g["low_share"] >= cfg.PERSISTENT_LOW_SHARE)
    ]
    return out.reset_index()[["icao24", "n", "days", "low_share"]]


def metrics_for_day(ab: pd.DataFrame, persistent: pd.DataFrame | None = None) -> pd.DataFrame:
    """Cell-bucket metrics for one day, excluding persistent low emitters."""
    if persistent is not None and len(persistent):
        ab = ab[~ab["icao24"].isin(set(persistent["icao24"]))]
    return cell_bucket_metrics(ab)
