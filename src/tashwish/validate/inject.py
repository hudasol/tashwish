"""Controlled injection of SYNTHETIC interference into REAL observed traffic.

Everything returned from this module is synthetic: the frames carry `attrs["data_class"] == "synthetic"`, result files are
written under results/synthetic/ and never into observed-data tables or the dashboard's observed view.

Jamming-like injection is applied at the aircraft-bucket level: a chosen fraction of the aircraft observed in a target
cell-bucket has ALL of its samples there marked strongly degraded. This is exactly equivalent to rewriting NIC/NACp on those
samples, and far cheaper. Spoofing-like injection is applied at the point level: chosen airborne ADS-B aircraft have their
positions replaced by a common false location (plus a small scatter) for a time window, accuracy fields left nominal, which is
the hard case for accuracy-based detectors.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import config as cfg
from ..detect.spoofing import EARTH_KM

DATA_CLASS_SYNTHETIC = "synthetic"
JAM_STRATA = ("enroute", "high", "mid")


def seed_for(*parts) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "big")


@dataclass(frozen=True)
class JamScenario:
    sid: str
    day: str
    cells: tuple[str, ...]
    bucket0: pd.Timestamp
    n_buckets: int
    intensity: float
    seed: int


@dataclass(frozen=True)
class SpoofScenario:
    sid: str
    day: str
    centre_lat: float
    centre_lon: float
    t0: pd.Timestamp
    duration_min: float
    n_aircraft: int
    false_lat: float
    false_lon: float
    seed: int
    radius_km: float = 120.0


def mark_synthetic(df: pd.DataFrame) -> pd.DataFrame:
    df.attrs["data_class"] = DATA_CLASS_SYNTHETIC
    return df


def scenario_buckets(sc: JamScenario, grid: cfg.Grid) -> list[pd.Timestamp]:
    return [sc.bucket0 + pd.Timedelta(hours=grid.bucket_hours * i) for i in range(sc.n_buckets)]


def inject_jam(ab: pd.DataFrame, sc: JamScenario, grid: cfg.Grid) -> tuple[pd.DataFrame, dict]:
    """Return a copy of `ab` with the scenario applied and info {n_target, n_degraded} summed over target cell-buckets."""
    out = ab.copy()
    buckets = set(scenario_buckets(sc, grid))
    in_target = out["cell"].isin(sc.cells) & out["bucket"].isin(buckets)
    enr = out[in_target & (out["stratum"] == "enroute") & (out["n_samples"] >= cfg.MIN_SAMPLES_PER_AIRCRAFT)]
    n_target = n_degraded = 0
    chosen: list[tuple[str, pd.Timestamp, str]] = []
    for (cell, bucket), g in enr.groupby(["cell", "bucket"]):
        ids = sorted(g["icao24"].unique())
        k = int(round(sc.intensity * len(ids)))
        rng = np.random.default_rng(seed_for(sc.seed, cell, bucket.isoformat()))
        pick = rng.choice(len(ids), size=k, replace=False) if k else []
        chosen.extend((cell, bucket, ids[i]) for i in pick)
        n_target += len(ids)
        n_degraded += k
    if chosen:
        key = pd.MultiIndex.from_tuples(chosen, names=["cell", "bucket", "icao24"])
        idx = pd.MultiIndex.from_frame(out[["cell", "bucket", "icao24"]])
        sel = idx.isin(key) & out["stratum"].isin(JAM_STRATA).to_numpy()
        out.loc[sel, "n_strong"] = out.loc[sel, "n_samples"]
        out.loc[sel, "n_gpsjam"] = out.loc[sel, "n_samples"]
    return mark_synthetic(out), {"n_target": n_target, "n_degraded": n_degraded}


def _km_to_deg(lat: float, dx_km: float, dy_km: float) -> tuple[float, float]:
    return dy_km / EARTH_KM * 180 / np.pi, dx_km / (EARTH_KM * np.cos(np.radians(lat))) * 180 / np.pi


def inject_spoof(points: pd.DataFrame, sc: SpoofScenario, inplace: bool = False) -> tuple[pd.DataFrame, dict]:
    """Displace n aircraft to a common false location for the window. Returns (frame, info{n_spoofed}); copies unless inplace."""
    out = points if inplace else points.copy()
    t1 = sc.t0 + pd.Timedelta(minutes=sc.duration_min)
    ok = (out["src_type"] == cfg.SRC_ADSB) & (~out["on_ground"]) & (out["ts"] >= sc.t0) & (out["ts"] <= t1)
    w = out[ok]
    near = w[
        np.hypot(
            (w["lat"] - sc.centre_lat) * np.pi / 180 * EARTH_KM,
            (w["lon"] - sc.centre_lon) * np.pi / 180 * EARTH_KM * np.cos(np.radians(sc.centre_lat)),
        )
        <= sc.radius_km
    ]
    counts = near.groupby("icao24").size()
    cands = sorted(counts[counts >= 4].index)  # need several fixes in the window so the jump is observable
    rng = np.random.default_rng(seed_for(sc.seed, "spoof", sc.sid))
    n = min(sc.n_aircraft, len(cands))
    chosen = [cands[i] for i in rng.choice(len(cands), size=n, replace=False)] if n else []
    for icao in chosen:
        rows = out.index[(out["icao24"] == icao) & ok]
        # skip the first fix in the window so a before-fix exists inside the data, then displace everything until t1
        rows = rows[1:] if len(rows) > 1 else rows
        sx, sy = rng.normal(0, 1.5, 2)  # about 1.5 km scatter around the common false location
        d_lat, d_lon = _km_to_deg(sc.false_lat, sx, sy)
        out.loc[rows, "lat"] = sc.false_lat + d_lat
        out.loc[rows, "lon"] = sc.false_lon + d_lon
    return mark_synthetic(out), {"n_spoofed": len(chosen), "n_requested": sc.n_aircraft}
