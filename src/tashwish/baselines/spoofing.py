"""B4: naive speed threshold on single position jumps, to compare with `tashwish.detect.spoofing`.

A jump is any pair of consecutive airborne ADS-B fixes of one aircraft whose implied ground speed exceeds B4_MIN_KT. There is
no minimum distance, no comparison with the reported speed, no clustering and no minimum number of aircraft: each jump is
its own event. Output says nothing about who caused a jump.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from .. import config as cfg
from ..detect.spoofing import KM_PER_KT_S, haversine_km
from . import constants as bc

EVENT_COLS = [
    "event_id", "kind", "start", "end", "n_aircraft", "n_jumps", "dest_lat", "dest_lon", "dest_spread_km", "origin_lat",
    "origin_lon", "origin_spread_km", "median_implied_kt", "median_gs_kt", "share_nominal_accuracy", "confidence",
]  # fmt: skip


def find_naive_jumps(points: pd.DataFrame) -> pd.DataFrame:
    """Jumps by speed alone. Same input filter as the system (airborne ADS-B only); columns follow `find_jumps`."""
    d = points[(~points["on_ground"]) & (points["src_type"] == cfg.SRC_ADSB)]
    d = d.dropna(subset=["lat", "lon"]).sort_values(["icao24", "ts"], kind="mergesort")
    cols = [
        "icao24",
        "t0",
        "t1",
        "lat0",
        "lon0",
        "lat1",
        "lon1",
        "dist_km",
        "implied_kt",
        "gs_kt",
        "nic_after",
        "nacp_after",
    ]
    if len(d) < 2:
        return pd.DataFrame(columns=cols)
    same = d["icao24"].to_numpy()[1:] == d["icao24"].to_numpy()[:-1]
    sec = (d["ts"] - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().to_numpy()
    a, b = d.iloc[:-1], d.iloc[1:]
    dt = sec[1:] - sec[:-1]
    dt_eff = np.maximum(dt, bc.B4_DT_FLOOR_S)
    dist = haversine_km(a["lat"].to_numpy(), a["lon"].to_numpy(), b["lat"].to_numpy(), b["lon"].to_numpy())
    with np.errstate(divide="ignore", invalid="ignore"):
        kt = dist / dt_eff / KM_PER_KT_S
    gs = np.fmax(a["gs_kt"].to_numpy(dtype=float), b["gs_kt"].to_numpy(dtype=float))
    ok = same & (dt >= 0) & (dt <= bc.B4_DT_MAX_S) & (kt > bc.B4_MIN_KT)
    j = pd.DataFrame({
        "icao24": a["icao24"].to_numpy()[ok], "t0": sec[:-1][ok], "t1": sec[1:][ok],
        "lat0": a["lat"].to_numpy()[ok], "lon0": a["lon"].to_numpy()[ok],
        "lat1": b["lat"].to_numpy()[ok], "lon1": b["lon"].to_numpy()[ok],
        "dist_km": dist[ok], "implied_kt": kt[ok], "gs_kt": np.where(np.isnan(gs[ok]), 0.0, gs[ok]),
        "nic_after": b["nic"].to_numpy()[ok], "nacp_after": b["nac_p"].to_numpy()[ok],
    })  # fmt: skip
    j["t0"] = pd.to_datetime(j["t0"], unit="s", utc=True)
    j["t1"] = pd.to_datetime(j["t1"], unit="s", utc=True)
    return j.reset_index(drop=True)


def naive_spoof_events(jumps: pd.DataFrame) -> pd.DataFrame:
    """One event per jump, with the columns that `combine` and `match_scenario` read. No aircraft identifier in the output."""
    if jumps.empty:
        return pd.DataFrame(columns=EVENT_COLS)
    ids = [
        "S-" + hashlib.sha1(f"naive|{i}|{t.isoformat()}|{la:.4f}|{lo:.4f}".encode()).hexdigest()[:12]
        for i, t, la, lo in zip(jumps["icao24"], jumps["t0"], jumps["lat1"], jumps["lon1"], strict=True)
    ]
    nominal = (jumps["nic_after"].fillna(0) >= cfg.NIC_STRONG_BELOW) & (
        jumps["nacp_after"].fillna(0) >= cfg.NACP_STRONG_BELOW
    )
    out = pd.DataFrame({
        "event_id": ids, "kind": "spoofing_like", "start": jumps["t0"].dt.floor("s").to_numpy(),
        "end": jumps["t1"].dt.ceil("s").to_numpy(), "n_aircraft": 1, "n_jumps": 1,
        "dest_lat": jumps["lat1"].to_numpy(), "dest_lon": jumps["lon1"].to_numpy(), "dest_spread_km": 0.0,
        "origin_lat": jumps["lat0"].to_numpy(), "origin_lon": jumps["lon0"].to_numpy(), "origin_spread_km": 0.0,
        "median_implied_kt": jumps["implied_kt"].to_numpy(), "median_gs_kt": jumps["gs_kt"].to_numpy(),
        "share_nominal_accuracy": nominal.astype(float).to_numpy(), "confidence": "medium",
    })  # fmt: skip
    out["start"] = pd.to_datetime(out["start"], utc=True)
    out["end"] = pd.to_datetime(out["end"], utc=True)
    return out[EVENT_COLS].sort_values(["start", "event_id"]).reset_index(drop=True)


def detect_naive_spoofing(points: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    jumps = find_naive_jumps(points)
    return jumps, naive_spoof_events(jumps)
