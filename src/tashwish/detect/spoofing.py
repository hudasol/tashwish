"""Spoofing-like detector: impossible position jumps whose destinations coincide across several aircraft.

Signature (docs/RESEARCH.md 2.4): an aircraft's reported position jumps by an implied speed no aircraft can fly, and several
distinct aircraft are displaced to the SAME false place. A single aircraft jumping is never an event on its own (receiver
faults, MLAT glitches and bad merges look the same); it is kept only as a per-jump record. Accuracy fields can stay nominal
under spoofing, so this detector does not use NIC/NACp to decide; it reports them as evidence for the jamming-versus-spoofing
discrimination (detect/discriminate.py). It detects spoofing-LIKE behaviour only and says nothing about who caused it.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from .. import config as cfg

EARTH_KM = 6371.0088
KM_PER_KT_S = 1.852 / 3600.0  # km per second per knot


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _epoch_s(ts: pd.Series) -> np.ndarray:
    """Seconds since the epoch as float64, independent of the timestamp resolution pandas picked."""
    return (ts - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().to_numpy()


def find_jumps(points: pd.DataFrame) -> pd.DataFrame:
    """Per-aircraft consecutive-fix jumps. Input columns: icao24, ts, lat, lon, gs_kt, on_ground, src_type, nic, nac_p.

    Returns one row per jump with origin (lat0, lon0) = last fix before, destination (lat1, lon1) = first fix after.
    """
    # ADS-B broadcast positions only: MLAT positions are computed by the network and can be coarse, non-transponder emitters are vehicles
    d = points[(~points["on_ground"]) & (points["src_type"] == cfg.SRC_ADSB)]
    d = d.dropna(subset=["lat", "lon"]).sort_values(["icao24", "ts"], kind="mergesort")
    same = d["icao24"].to_numpy()[1:] == d["icao24"].to_numpy()[:-1]
    sec = _epoch_s(d["ts"])
    a, b = d.iloc[:-1], d.iloc[1:]
    dt = sec[1:] - sec[:-1]
    dt_eff = np.maximum(
        dt, cfg.SPOOF_DT_FLOOR_S
    )  # fixes closer than the floor are treated as the floor (conservative speed)
    dist = haversine_km(a["lat"].to_numpy(), a["lon"].to_numpy(), b["lat"].to_numpy(), b["lon"].to_numpy())
    with np.errstate(divide="ignore", invalid="ignore"):
        kt = dist / dt_eff / KM_PER_KT_S
    gs = np.fmax(a["gs_kt"].to_numpy(dtype=float), b["gs_kt"].to_numpy(dtype=float))
    gs = np.where(np.isnan(gs), 0.0, gs)
    ref = np.maximum(gs, 100.0)
    ok = (
        same
        & (dt >= 0)
        & (dt <= cfg.SPOOF_DT_MAX_S)
        & (dist >= cfg.SPOOF_JUMP_MIN_KM)
        & (kt >= cfg.SPOOF_JUMP_MIN_KT)
        & (kt >= cfg.SPOOF_JUMP_SPEED_RATIO * ref)
    )
    j = pd.DataFrame(
        {
            "icao24": a["icao24"].to_numpy()[ok],
            "t0": sec[:-1][ok],
            "t1": sec[1:][ok],
            "lat0": a["lat"].to_numpy()[ok],
            "lon0": a["lon"].to_numpy()[ok],
            "lat1": b["lat"].to_numpy()[ok],
            "lon1": b["lon"].to_numpy()[ok],
            "dist_km": dist[ok],
            "implied_kt": kt[ok],
            "gs_kt": gs[ok],
            "nic_before": a["nic"].to_numpy()[ok],
            "nacp_before": a["nac_p"].to_numpy()[ok],
            "nic_after": b["nic"].to_numpy()[ok],
            "nacp_after": b["nac_p"].to_numpy()[ok],
        }
    )
    j["t0"] = pd.to_datetime(j["t0"], unit="s", utc=True)
    j["t1"] = pd.to_datetime(j["t1"], unit="s", utc=True)
    return j.reset_index(drop=True)


def _xy_km(lat, lon, lat_ref):
    return np.column_stack([np.radians(lon) * EARTH_KM * np.cos(np.radians(lat_ref)), np.radians(lat) * EARTH_KM])


def cluster_jumps(jumps: pd.DataFrame) -> pd.DataFrame:
    """Add `cluster` ids: jumps whose destinations are within SPOOF_CLUSTER_KM and SPOOF_CLUSTER_MIN of each other."""
    j = jumps.copy()
    if j.empty:
        j["cluster"] = pd.Series(dtype=int)
        return j
    lat_ref = float(j["lat1"].mean())
    xy = _xy_km(j["lat1"].to_numpy(), j["lon1"].to_numpy(), lat_ref)
    t = _epoch_s(j["t1"])
    # scale time so SPOOF_CLUSTER_MIN seconds equals SPOOF_CLUSTER_KM km, then a single Chebyshev-free L2 radius
    scale = cfg.SPOOF_CLUSTER_KM / cfg.SPOOF_CLUSTER_MIN
    feats = np.column_stack([xy, t * scale])
    tree = cKDTree(feats)
    pairs = tree.query_pairs(r=cfg.SPOOF_CLUSTER_KM, output_type="ndarray")
    n = len(j)
    if len(pairs):
        g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    else:
        g = coo_matrix((n, n))
    _, labels = connected_components(g, directed=False)
    j["cluster"] = labels
    return j


def build_spoof_events(jumps: pd.DataFrame) -> pd.DataFrame:
    """Events = clusters with at least SPOOF_MIN_AIRCRAFT distinct aircraft. No aircraft identifiers in the output."""
    cols = [
        "event_id", "kind", "start", "end", "n_aircraft", "n_jumps", "dest_lat", "dest_lon", "dest_spread_km",
        "origin_lat", "origin_lon", "origin_spread_km", "median_implied_kt", "median_gs_kt", "share_nominal_accuracy",
        "confidence",
    ]  # fmt: skip
    if jumps.empty:
        return pd.DataFrame(columns=cols)
    j = cluster_jumps(jumps)
    out = []
    for _, g in j.groupby("cluster"):
        na = g["icao24"].nunique()
        if na < cfg.SPOOF_MIN_AIRCRAFT:
            continue
        lat_ref = float(g["lat1"].mean())
        dxy = _xy_km(g["lat1"].to_numpy(), g["lon1"].to_numpy(), lat_ref)
        spread = float(np.sqrt(((dxy - dxy.mean(axis=0)) ** 2).sum(axis=1)).max())
        oxy = _xy_km(g["lat0"].to_numpy(), g["lon0"].to_numpy(), lat_ref)
        ospread = float(np.sqrt(((oxy - oxy.mean(axis=0)) ** 2).sum(axis=1)).max())
        nominal = (
            (g["nic_after"].fillna(0) >= cfg.NIC_STRONG_BELOW) & (g["nacp_after"].fillna(0) >= cfg.NACP_STRONG_BELOW)
        ).mean()
        conf = "high" if (na >= cfg.SPOOF_HIGH_AIRCRAFT and spread <= cfg.SPOOF_HIGH_SPREAD_KM) else "medium"
        start = g["t0"].min().floor("s")
        eid = hashlib.sha1(
            f"spoof|{start.isoformat()}|{round(g['lat1'].mean(), 2)}|{round(g['lon1'].mean(), 2)}".encode()
        ).hexdigest()[:12]
        out.append({
            "event_id": f"S-{eid}", "kind": "spoofing_like", "start": start, "end": g["t1"].max().ceil("s"),
            "n_aircraft": int(na), "n_jumps": int(len(g)), "dest_lat": float(g["lat1"].mean()), "dest_lon": float(g["lon1"].mean()),
            "dest_spread_km": spread, "origin_lat": float(g["lat0"].mean()), "origin_lon": float(g["lon0"].mean()),
            "origin_spread_km": ospread, "median_implied_kt": float(g["implied_kt"].median()),
            "median_gs_kt": float(g["gs_kt"].median()), "share_nominal_accuracy": float(nominal), "confidence": conf,
        })  # fmt: skip
    return pd.DataFrame(out, columns=cols).sort_values(["start", "event_id"]).reset_index(drop=True)


def detect_spoofing(points: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    jumps = find_jumps(points)
    return jumps, build_spoof_events(jumps)
