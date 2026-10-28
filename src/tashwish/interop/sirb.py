"""Empirical GNSS degradation parameter file for a drone-show planner and verifier (`tashwish.sirb_gnss_params.v1`).

WHAT THIS IS: distributions of reported position quality (NIC, NACp), degraded episode duration and rate, update interval and
dropout, and quality transitions, measured from public aircraft ADS-B broadcasts in the Gulf, each with uncertainty.
WHAT THIS IS NOT: a model of a drone receiver. Aircraft avionics at cruise-type altitudes are not small antennas near the
ground, and en-route interference is not low-altitude urban multipath. The file says this in its `caveats` block, and the
numbers are to be used only as an illustrative stress prior. Nothing here attributes interference to any actor.

Method (details and thresholds are written into the output under `definitions`):
  * samples: airborne, own-transponder ADS-B (`src_type == adsb_icao`) position samples inside the region box, with altitude;
    duplicates of (aircraft, timestamp) removed; clusters for resampling are AIRCRAFT-DAYS;
  * quality samples: samples that carry their own NIC (not carried forward from an earlier message when `q_carried` exists);
  * strongly degraded: NIC < 4 or NACp < 5 (tashwish.config); a degraded EPISODE is a maximal run of one aircraft's consecutive
    quality samples that are all strongly degraded with at most EPISODE_GAP_S between neighbours, and at least MIN_EPISODE_SAMPLES samples;
  * intervals use all position samples of an aircraft-day; an interval is classified by the state of the earlier sample.
Every interval is a bootstrap over aircraft-days (resampled with replacement), seeded and deterministic.
Only DEV days (tashwish.split) may be used unless `allow_held_out` is set explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from .. import __version__
from .. import config as cfg
from .. import split as splitmod
from ..attribution import DATASET_ATTRIBUTION
from ..metrics.aggregate import stratum_labels
from ..metrics.loader import load_points
from ..metrics.stats import wilson_interval
from .marsad import code_commit

SCHEMA_ID = "tashwish.sirb_gnss_params.v1"

# --- definitions (design choices; each is written into the output file) ---
EPISODE_GAP_S = 120.0  # neighbouring quality samples further apart than this end an episode
MIN_EPISODE_SAMPLES = 2  # a run needs at least this many samples to count as an episode (so it has a duration)
DT_HORIZON_S = 600.0  # intervals longer than this are leg changes or coverage loss, counted but not used
DROPOUT_THRESHOLDS_S = (20.0, 60.0)
NEW_LEG_FLAG = 2  # flags bit: new leg
NO_POS_20S_FLAG = 1  # flags bit: no position for 20 s before this point (cross-check only)
CATEGORIES = 12  # NIC and NACp take values 0..11
EPISODE_QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
DT_QUANTILES = (0.5, 0.9, 0.95, 0.99)
MIN_CLUSTERS = 10  # fewer aircraft-days than this: no interval is reported
MIN_N_CATEGORICAL = 30
MIN_EPISODES = 20
CONFIDENCE = 0.95
DEFAULT_SEED = 20261012
DEFAULT_N_BOOT = 1000
REGIONS = {"gulf_box": cfg.REGION}
BANDS = {"low": 0, "mid": 1, "high": 2}
STRATUM_BANDS = {"enroute": (1, 2), "high": (2,), "mid": (1,), "low": (0,)}
# update interval histogram: 0.1 s bins to 30 s, then 100 log spaced bins to the horizon
DT_EDGES = np.concatenate([np.arange(0.0, 30.0, 0.1), np.geomspace(30.0, DT_HORIZON_S, 101)])
CLASSES = ("baseline", "degraded_episode")

SIRB_COLS = ["icao24", "ts", "lat", "lon", "alt_baro_ft", "on_ground", "src_type", "nic", "nac_p", "flags", "q_carried"]

NOTICE = (
    "Empirical stress prior from public aircraft ADS-B broadcasts. It does not describe drone receivers. "
    "No actor attribution. See caveats."
)

CAVEATS = {
    "summary": (
        "These parameters come from public aircraft ADS-B broadcasts, mostly at cruise-type altitudes, over the Gulf. "
        "They describe how aircraft avionics report position quality and how often those reports pause during en-route "
        "interference. They do NOT describe a drone-scale receiver, low-altitude urban multipath, or a small antenna. "
        "Use them only as an illustrative stress prior for scenario testing, never as a measured model of a drone's GNSS "
        "behaviour, and never as a certification input."
    ),
    "points": [
        "Source: adsb.lol globe_history archives of volunteer receivers (ODbL 1.0). Coverage differs by place and time.",
        "NIC and NACp are accuracy classes that an aircraft transmits about its own position, not measured position errors.",
        "A low NIC or NACp can also come from old avionics, installation faults or ADS-B version differences, so a degraded "
        "episode is evidence of degraded reporting, not proof of interference.",
        "Update intervals and dropouts mix three things: aircraft transmission behaviour, receiver coverage gaps, and the "
        "thinning applied by the archive. They are not the dropout behaviour of a drone receiver.",
        "In the archive, update intervals rarely run much beyond the 20 second mark that the source itself uses to flag a gap in "
        "position, so the upper tail of the update interval and the 20 second dropout share reflect archive sampling as well as "
        "real gaps. Read them as properties of this data source, not of a receiver.",
        "Counts of samples are not independent (one aircraft contributes many consecutive samples). Wilson intervals treat samples "
        "as independent and are therefore too narrow; the bootstrap intervals resample aircraft-days and are the ones to use.",
        "Parameters are built from the listed days only, which are development days. They may not transfer to other days or seasons.",
        "A block marked insufficient does not have enough aircraft-days or events to report an interval, and is not a statement of zero.",
        "No attribution: the file says nothing about who or what caused any degradation.",
    ],
    "not_for": [
        "navigation or flight planning",
        "safety of life decisions",
        "claims about a specific drone, receiver or site",
        "attributing interference to any state or actor",
    ],
}


# ----------------------------------------------------------------------------------------------------------------------
# preparation: one chunk (whole UTC days) of points -> aircraft-day level counts
# ----------------------------------------------------------------------------------------------------------------------


def _as_float(s: pd.Series) -> np.ndarray:
    return pd.to_numeric(s, errors="coerce").astype("float64").to_numpy()


def _count_matrix(cl: np.ndarray, col: np.ndarray, ncol: int, weights: np.ndarray | None = None) -> np.ndarray:
    """Cluster by category count matrix (rows = distinct clusters in `cl`, sorted)."""
    if cl.size == 0:
        return np.zeros((0, ncol))
    uniq, inv = np.unique(cl, return_inverse=True)
    flat = np.bincount(inv * ncol + col, weights=weights, minlength=len(uniq) * ncol)
    return flat.reshape(len(uniq), ncol).astype("float64")


def summarise_chunk(df: pd.DataFrame, region: cfg.Region) -> dict[str, dict]:
    """Aircraft-day level counts for one chunk (whole UTC days). Returns {stratum: summary}."""
    need = {"icao24", "ts", "lat", "lon", "alt_baro_ft", "on_ground", "src_type", "nic", "nac_p", "flags"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"points table is missing columns {sorted(missing)}")
    keep = (
        (df["src_type"] == cfg.SRC_ADSB)
        & (~df["on_ground"].astype(bool))
        & df["alt_baro_ft"].notna()
        & (df["lat"] >= region.lat_min)
        & (df["lat"] <= region.lat_max)
        & (df["lon"] >= region.lon_min)
        & (df["lon"] <= region.lon_max)
    )
    cols = [c for c in (*need, "q_carried") if c in df.columns]
    d = df.loc[keep, cols].sort_values(["icao24", "ts"], kind="mergesort")
    d = d.drop_duplicates(["icao24", "ts"]).reset_index(drop=True)
    empty = {s: _empty_summary() for s in cfg.STRATA}
    if d.empty:
        return empty
    ts = pd.to_datetime(d["ts"], utc=True)
    t = (ts - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().to_numpy()
    day = ts.dt.strftime("%Y-%m-%d")
    cl = d.assign(_day=day).groupby(["icao24", "_day"], sort=False).ngroup().to_numpy()
    band = stratum_labels(d["alt_baro_ft"]).map(BANDS).to_numpy()
    nic = _as_float(d["nic"])
    nacp = _as_float(d["nac_p"])
    flags = _as_float(d["flags"])
    flags = np.where(np.isnan(flags), 0, flags).astype(int)
    known = ~np.isnan(nic)
    with np.errstate(invalid="ignore"):
        deg = known & ((nic < cfg.NIC_STRONG_BELOW) | (~np.isnan(nacp) & (nacp < cfg.NACP_STRONG_BELOW)))
    carried = (
        d["q_carried"].fillna(False).astype(bool).to_numpy() if "q_carried" in d.columns else np.zeros(len(d), bool)
    )
    own = known & ~carried
    n = len(d)

    # quality samples and runs ---------------------------------------------------------------------------------------
    oi = np.flatnonzero(own)
    o_cl, o_t, o_deg, o_band = cl[oi], t[oi], deg[oi], band[oi]
    no = len(oi)
    linked = np.zeros(no, bool)  # linked[i]: quality sample i follows i-1 within the gap, same aircraft-day
    if no > 1:
        linked[1:] = (o_cl[1:] == o_cl[:-1]) & ((o_t[1:] - o_t[:-1]) <= EPISODE_GAP_S)
    cont = np.zeros(no, bool)
    cont[1:] = o_deg[1:] & o_deg[:-1] & linked[1:]
    start = o_deg & ~cont
    run_id = np.where(o_deg, np.cumsum(start) - 1, -1)
    nruns = int(start.sum())
    run_n = np.bincount(run_id[o_deg], minlength=nruns) if nruns else np.zeros(0, int)
    first_idx = np.flatnonzero(start)
    valid_run = run_n >= MIN_EPISODE_SAMPLES
    last_idx = first_idx + run_n - 1 if nruns else first_idx
    ep_dur = (o_t[last_idx] - o_t[first_idx]) if nruns else np.zeros(0)
    ep_band = o_band[first_idx] if nruns else np.zeros(0, int)
    ep_cl = o_cl[first_idx] if nruns else np.zeros(0, int)
    o_ep = np.where(o_deg & (valid_run[np.maximum(run_id, 0)] if nruns else False), run_id, -1)  # episode id or -1
    o_cls = np.where(~o_deg, 0, np.where(o_ep >= 0, 1, -1))  # 0 baseline, 1 episode, -1 isolated degraded

    # class of every position sample (for update intervals) ----------------------------------------------------------
    pos_cls = np.full(n, -1)
    pos_cls[known & ~deg] = 0
    if no:
        idx = np.arange(n)
        j = np.searchsorted(oi, idx, side="right") - 1
        k = np.searchsorted(oi, idx, side="left")
        okjk = (j >= 0) & (k < no)
        jj, kk = np.clip(j, 0, no - 1), np.clip(k, 0, no - 1)
        in_ep = okjk & (o_cl[jj] == cl) & (o_cl[kk] == cl) & (o_ep[jj] >= 0) & (o_ep[jj] == o_ep[kk])
        pos_cls[in_ep] = 1

    # intervals between position samples -----------------------------------------------------------------------------
    dt = np.full(n, np.nan)
    same = np.zeros(n, bool)
    if n > 1:
        same[1:] = cl[1:] == cl[:-1]
        dt[1:] = np.where(same[1:], t[1:] - t[:-1], np.nan)
    over = same & (dt > DT_HORIZON_S)
    use = same & (dt > 0) & (dt <= DT_HORIZON_S) & ((flags & NEW_LEG_FLAG) == 0)
    iv = np.flatnonzero(use)
    iv_prev = iv - 1
    iv_dt, iv_cl, iv_cls, iv_band = dt[iv], cl[iv], pos_cls[iv_prev], band[iv_prev]
    iv_bin = np.clip(np.searchsorted(DT_EDGES, iv_dt, side="right") - 1, 0, len(DT_EDGES) - 2)

    out: dict[str, dict] = {}
    icao = d["icao24"].to_numpy()
    for stratum, bands in STRATUM_BANDS.items():
        s = _empty_summary()
        # categorical (quality samples)
        sel_o = np.isin(o_band, bands)
        for ci, cname in enumerate(CLASSES):
            m = sel_o & (o_cls == ci)
            nic_col = np.clip(nic[oi][m].astype(int), 0, CATEGORIES - 1)
            nacp_raw = nacp[oi][m]
            nacp_col = np.where(
                np.isnan(nacp_raw), CATEGORIES, np.clip(np.nan_to_num(nacp_raw).astype(int), 0, CATEGORIES - 1)
            )
            s["cat"][cname]["nic"] = _count_matrix(o_cl[m], nic_col, CATEGORIES)
            s["cat"][cname]["nacp"] = _count_matrix(o_cl[m], nacp_col, CATEGORIES + 1)
            # nic and nacp rows must stay aligned: both come from the same samples, so the same clusters in the same order
        # update intervals
        sel_i = np.isin(iv_band, bands)
        for ci, cname in enumerate(CLASSES):
            m = sel_i & (iv_cls == ci)
            hist = _count_matrix(iv_cl[m], iv_bin[m], len(DT_EDGES) - 1)
            cnt_cols = np.stack(
                [np.ones(m.sum(), int), iv_dt[m] > DROPOUT_THRESHOLDS_S[0], iv_dt[m] > DROPOUT_THRESHOLDS_S[1]], axis=1
            )
            cnt = np.zeros((hist.shape[0], 3))
            if m.sum():
                _, inv = np.unique(iv_cl[m], return_inverse=True)
                for c in range(3):
                    cnt[:, c] = np.bincount(inv, weights=cnt_cols[:, c].astype(float), minlength=hist.shape[0])
            s["dt"][cname] = {"hist": hist, "cnt": cnt}
        s["n_over_horizon"] = int(np.isin(band[:-1][over[1:]], bands).sum()) if n > 1 else 0
        # exposure, episodes, transitions (quality samples)
        pair = linked & np.isin(np.roll(o_band, 1), bands)
        pair[0:1] = False
        ex_cl = o_cl[pair]
        ex_s = (o_t - np.roll(o_t, 1))[pair]
        ep_m = valid_run & np.isin(ep_band, bands)
        single_m = (~valid_run) & np.isin(ep_band, bands)
        clusters = np.unique(np.concatenate([ex_cl, ep_cl[ep_m]]))
        expo = np.zeros((len(clusters), 2))  # exposure seconds, episodes started
        if len(clusters):
            expo[:, 0] = np.bincount(np.searchsorted(clusters, ex_cl), weights=ex_s, minlength=len(clusters))
            expo[:, 1] = np.bincount(np.searchsorted(clusters, ep_cl[ep_m]), minlength=len(clusters))
        s["expo"] = expo
        s["ep_dur"] = ep_dur[ep_m]
        s["ep_row"] = np.searchsorted(clusters, ep_cl[ep_m]).astype(int)
        prev_deg = np.roll(o_deg, 1)
        tr_m = pair
        tcl = o_cl[tr_m]
        pd_, nd_ = prev_deg[tr_m], o_deg[tr_m]
        tr = np.zeros((0, 4))
        if tcl.size:
            u, inv = np.unique(tcl, return_inverse=True)
            tr = np.zeros((len(u), 4))
            tr[:, 0] = np.bincount(inv, weights=pd_.astype(float), minlength=len(u))
            tr[:, 1] = np.bincount(inv, weights=(pd_ & nd_).astype(float), minlength=len(u))
            tr[:, 2] = np.bincount(inv, weights=(~pd_).astype(float), minlength=len(u))
            tr[:, 3] = np.bincount(inv, weights=((~pd_) & nd_).astype(float), minlength=len(u))
        s["trans"] = tr
        # counters
        in_s = np.isin(band, bands)
        s["counts"] = {
            "position_samples": int(in_s.sum()),
            "quality_samples": int(sel_o.sum()),
            "isolated_degraded_samples": int((sel_o & (o_cls == -1)).sum()),
            "intervals_used": int(sel_i.sum()),
            "intervals_over_horizon": s["n_over_horizon"],
            "samples_flag_no_position_20s": int((in_s & ((flags & NO_POS_20S_FLAG) > 0)).sum()),
            "single_sample_runs": int(single_m.sum()),
        }
        s["aircraft"] = set(map(str, np.unique(icao[in_s])))
        s["aircraft_days"] = int(len(np.unique(cl[in_s])))
        out[stratum] = s
    return out


def _empty_summary() -> dict:
    return {
        "cat": {c: {"nic": np.zeros((0, CATEGORIES)), "nacp": np.zeros((0, CATEGORIES + 1))} for c in CLASSES},
        "dt": {c: {"hist": np.zeros((0, len(DT_EDGES) - 1)), "cnt": np.zeros((0, 3))} for c in CLASSES},
        "expo": np.zeros((0, 2)),
        "ep_dur": np.zeros(0),
        "ep_row": np.zeros(0, int),
        "trans": np.zeros((0, 4)),
        "n_over_horizon": 0,
        "counts": dict.fromkeys(
            ("position_samples", "quality_samples", "isolated_degraded_samples", "intervals_used", "intervals_over_horizon",
             "samples_flag_no_position_20s", "single_sample_runs"), 0),
        "aircraft": set(),
        "aircraft_days": 0,
    }  # fmt: skip


def merge_summaries(parts: list[dict]) -> dict:
    """Concatenate per-chunk summaries of one stratum (aircraft-days of different chunks are different clusters)."""
    out = _empty_summary()
    if not parts:
        return out
    row_off = 0
    ep_rows, ep_durs, expos = [], [], []
    for p in parts:
        for c in CLASSES:
            for k in ("nic", "nacp"):
                out["cat"][c][k] = np.vstack([out["cat"][c][k], p["cat"][c][k]])
            for k in ("hist", "cnt"):
                out["dt"][c][k] = np.vstack([out["dt"][c][k], p["dt"][c][k]])
        expos.append(p["expo"])
        ep_rows.append(p["ep_row"] + row_off)
        ep_durs.append(p["ep_dur"])
        row_off += p["expo"].shape[0]
        out["trans"] = np.vstack([out["trans"], p["trans"]])
        for k, v in p["counts"].items():
            out["counts"][k] += v
        out["aircraft"] |= p["aircraft"]
        out["aircraft_days"] += p["aircraft_days"]
    out["expo"] = np.vstack(expos)
    out["ep_row"] = np.concatenate(ep_rows)
    out["ep_dur"] = np.concatenate(ep_durs)
    return out


# ----------------------------------------------------------------------------------------------------------------------
# statistics: cluster bootstrap over aircraft-days
# ----------------------------------------------------------------------------------------------------------------------


def _f(x: Any) -> float | None:
    x = float(x)
    return (
        None if not np.isfinite(x) else float(f"{x:.8g}")
    )  # 8 significant digits: removes float noise, keeps small rates


def _rng(seed: int, *labels: str) -> np.random.Generator:
    h = int.from_bytes(hashlib.sha256("|".join(labels).encode()).digest()[:8], "big")
    return np.random.default_rng([seed, h])


def _boot_weights(c: int, n_boot: int, rng: np.random.Generator) -> Iterator[np.ndarray]:
    """Yield chunks of resampling weights (draws x clusters); deterministic for a given generator state."""
    chunk = max(1, int(3_000_000 // max(c, 1)))
    done = 0
    pv = np.full(c, 1.0 / c)
    while done < n_boot:
        b = min(chunk, n_boot - done)
        yield rng.multinomial(c, pv, size=b).astype("float64")
        done += b


def _boot_apply(m: np.ndarray, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """Bootstrap totals of columns of `m` (clusters x columns): (draws x columns)."""
    return np.vstack([w @ m for w in _boot_weights(m.shape[0], n_boot, rng)])


def _ci(draws: np.ndarray, level: float = CONFIDENCE) -> tuple[float | None, float | None]:
    d = draws[np.isfinite(draws)]
    if len(d) < 0.9 * len(draws) or len(d) < 20:
        return None, None
    a = (1 - level) / 2
    lo, hi = np.quantile(d, [a, 1 - a])
    return _f(lo), _f(hi)


def _hist_quantiles(h: np.ndarray, qs: tuple[float, ...]) -> np.ndarray:
    """Quantiles from histogram counts (rows = draws) with linear interpolation inside bins; nan for empty rows."""
    h = np.atleast_2d(h)
    cum = np.cumsum(h, axis=1)
    tot = cum[:, -1]
    out = np.full((h.shape[0], len(qs)), np.nan)
    rows = np.arange(h.shape[0])
    for i, q in enumerate(qs):
        target = q * tot
        idx = np.argmax(cum >= target[:, None] - 1e-9, axis=1)
        inb = h[rows, idx]
        prev = cum[rows, idx] - inb
        frac = np.where(inb > 0, (target - prev) / np.where(inb > 0, inb, 1), 0.0)
        val = DT_EDGES[idx] + np.clip(frac, 0, 1) * (DT_EDGES[idx + 1] - DT_EDGES[idx])
        out[:, i] = np.where(tot > 0, val, np.nan)
    return out


def _weighted_quantiles(vals_sorted: np.ndarray, w: np.ndarray, qs: tuple[float, ...]) -> np.ndarray:
    """Inverted-CDF weighted quantiles; `w` is (draws x episodes) aligned with `vals_sorted`."""
    cum = np.cumsum(w, axis=1)
    tot = cum[:, -1]
    out = np.full((w.shape[0], len(qs)), np.nan)
    for i, q in enumerate(qs):
        idx = np.argmax(cum >= (q * tot)[:, None] - 1e-9, axis=1)
        out[:, i] = np.where(tot > 0, vals_sorted[idx], np.nan)
    return out


def _share(k: float, n: float, boot_k: np.ndarray | None, boot_n: np.ndarray | None) -> dict:
    lo, hi = wilson_interval(k, n) if n > 0 else (np.nan, np.nan)
    d: dict[str, Any] = {"k": int(k), "n": int(n), "share": _f(k / n) if n > 0 else None,
                         "wilson_lo": _f(lo), "wilson_hi": _f(hi), "boot_lo": None, "boot_hi": None}  # fmt: skip
    if boot_k is not None and boot_n is not None:
        with np.errstate(invalid="ignore", divide="ignore"):
            d["boot_lo"], d["boot_hi"] = _ci(np.where(boot_n > 0, boot_k / boot_n, np.nan))
    return d


def _nonempty(m: np.ndarray) -> np.ndarray:
    return m[m.sum(axis=1) > 0] if m.shape[0] else m


def _cat_block(nic_m: np.ndarray, nacp_m: np.ndarray, n_boot: int, rng: np.random.Generator) -> dict:
    rows = nic_m.sum(axis=1) > 0
    nic_m, nacp_m = nic_m[rows], nacp_m[rows]
    c = nic_m.shape[0]
    n = float(nic_m.sum())
    block: dict[str, Any] = {"n_quality_samples": int(n), "n_aircraft_days": int(c)}
    if c < MIN_CLUSTERS or n < MIN_N_CATEGORICAL:
        block["status"] = "insufficient"
        return block
    both = np.hstack([nic_m, nacp_m])
    boot = _boot_apply(both, n_boot, rng)
    tot = both.sum(axis=0)
    nic_t, nacp_t = tot[:CATEGORIES], tot[CATEGORIES : 2 * CATEGORIES]
    nacp_missing = tot[2 * CATEGORIES]
    nic_b, nacp_b = boot[:, :CATEGORIES], boot[:, CATEGORIES : 2 * CATEGORIES]
    block["status"] = "ok"
    block["nic"] = {str(v): _share(nic_t[v], nic_t.sum(), nic_b[:, v], nic_b.sum(axis=1)) for v in range(CATEGORIES)}
    block["nacp"] = {
        str(v): _share(nacp_t[v], nacp_t.sum(), nacp_b[:, v], nacp_b.sum(axis=1)) for v in range(CATEGORIES)
    }
    block["n_nacp_missing"] = int(nacp_missing)
    return block


def _dt_block(hist: np.ndarray, cnt: np.ndarray, n_boot: int, rng: np.random.Generator) -> dict:
    rows = cnt[:, 0] > 0 if cnt.shape[0] else np.zeros(0, bool)
    hist, cnt = hist[rows], cnt[rows]
    c = hist.shape[0]
    block: dict[str, Any] = {"n_intervals": int(cnt[:, 0].sum()) if c else 0, "n_aircraft_days": int(c)}
    if c < MIN_CLUSTERS:
        block["status"] = "insufficient"
        return block
    m = np.hstack([hist, cnt])
    boot = _boot_apply(m, n_boot, rng)
    nb = hist.shape[1]
    point_q = _hist_quantiles(hist.sum(axis=0), DT_QUANTILES)[0]
    boot_q = _hist_quantiles(boot[:, :nb], DT_QUANTILES)
    block["status"] = "ok"
    block["update_interval_s"] = {
        f"q{int(round(q * 100)):02d}": {"value": _f(point_q[i]), "boot_lo": _ci(boot_q[:, i])[0], "boot_hi": _ci(boot_q[:, i])[1]}
        for i, q in enumerate(DT_QUANTILES)
    }  # fmt: skip
    tot = cnt.sum(axis=0)
    bn = boot[:, nb]
    block["dropout"] = {
        f"share_gt_{int(th)}s": _share(tot[1 + i], tot[0], boot[:, nb + 1 + i], bn)
        for i, th in enumerate(DROPOUT_THRESHOLDS_S)
    }
    return block


def _episode_block(
    expo: np.ndarray, ep_dur: np.ndarray, ep_row: np.ndarray, n_boot: int, rng: np.random.Generator
) -> dict:
    c = expo.shape[0]
    hours = float(expo[:, 0].sum()) / 3600.0
    k = int(expo[:, 1].sum())
    block: dict[str, Any] = {"n_episodes": k, "n_aircraft_days": int(c), "exposure_aircraft_hours": _f(hours)}
    if c < MIN_CLUSTERS or hours <= 0:
        block["status"] = "insufficient"
        return block
    order = np.argsort(ep_dur, kind="stable")
    dur_sorted, row_sorted = ep_dur[order], ep_row[order]
    rate_draws, q_draws = [], []
    for w in _boot_weights(c, n_boot, rng):
        with np.errstate(invalid="ignore", divide="ignore"):
            hrs = (w @ expo[:, 0]) / 3600.0
            rate_draws.append(np.where(hrs > 0, (w @ expo[:, 1]) / hrs, np.nan))
        if k >= MIN_EPISODES:
            q_draws.append(_weighted_quantiles(dur_sorted, w[:, row_sorted], EPISODE_QUANTILES))
    rate = np.concatenate(rate_draws)
    plo = sps.chi2.ppf((1 - CONFIDENCE) / 2, 2 * k) / 2 if k > 0 else 0.0
    phi = sps.chi2.ppf(1 - (1 - CONFIDENCE) / 2, 2 * (k + 1)) / 2
    block["rate_per_aircraft_hour"] = {
        "value": _f(k / hours),
        "boot_lo": _ci(rate)[0],
        "boot_hi": _ci(rate)[1],
        "poisson_exact_lo": _f(plo / hours),
        "poisson_exact_hi": _f(phi / hours),
    }
    if k < MIN_EPISODES:
        block["duration_s"] = {"status": "insufficient"}
        block["status"] = "ok"
        return block
    qd = np.vstack(q_draws)
    ones = np.ones((1, k))
    pq_ = _weighted_quantiles(dur_sorted, ones, EPISODE_QUANTILES)[0]
    block["duration_s"] = {
        "status": "ok",
        "quantiles": {
            f"q{int(round(q * 100)):02d}": {
                "value": _f(pq_[i]),
                "boot_lo": _ci(qd[:, i])[0],
                "boot_hi": _ci(qd[:, i])[1],
            }
            for i, q in enumerate(EPISODE_QUANTILES)
        },
    }
    block["status"] = "ok"
    return block


def _trans_block(tr: np.ndarray, n_boot: int, rng: np.random.Generator) -> dict:
    tr = _nonempty(tr)
    c = tr.shape[0]
    block: dict[str, Any] = {"n_aircraft_days": int(c)}
    if c < MIN_CLUSTERS:
        block["status"] = "insufficient"
        return block
    boot = _boot_apply(tr, n_boot, rng)
    tot = tr.sum(axis=0)
    block["status"] = "ok"
    block["p_next_degraded_given_current_degraded"] = _share(tot[1], tot[0], boot[:, 1], boot[:, 0])
    block["p_next_degraded_given_current_nominal"] = _share(tot[3], tot[2], boot[:, 3], boot[:, 2])
    return block


def stratum_params(s: dict, seed: int, region: str, stratum: str, n_boot: int) -> dict:
    """Parameter block for one stratum from a merged summary."""
    res: dict[str, Any] = {
        "n": {**s["counts"], "aircraft": len(s["aircraft"]), "aircraft_days": s["aircraft_days"]},
        "baseline": {}, "degraded_episode": {},
    }  # fmt: skip
    for c in CLASSES:
        r = _rng(seed, region, stratum, c, "cat")
        res[c]["quality_categories"] = _cat_block(s["cat"][c]["nic"], s["cat"][c]["nacp"], n_boot, r)
        res[c]["update_interval_and_dropout"] = _dt_block(
            s["dt"][c]["hist"], s["dt"][c]["cnt"], n_boot, _rng(seed, region, stratum, c, "dt")
        )
    res["degraded_episode"]["episodes"] = _episode_block(
        s["expo"], s["ep_dur"], s["ep_row"], n_boot, _rng(seed, region, stratum, "episodes")
    )
    res["transitions"] = _trans_block(s["trans"], n_boot, _rng(seed, region, stratum, "trans"))
    return res


# ----------------------------------------------------------------------------------------------------------------------
# public API
# ----------------------------------------------------------------------------------------------------------------------


def _check_days(days_meta: list[dict], allow_held_out: bool) -> list[dict]:
    if not days_meta:
        raise ValueError("days_meta must list at least one day")
    out, seen = [], set()
    for m in days_meta:
        day = m["day"]
        d = date.fromisoformat(day)
        if day in seen:
            raise ValueError(f"day {day} listed twice")
        seen.add(day)
        held = splitmod.is_held_out(d)
        expected = "held_out" if held else "dev"
        if m.get("split") != expected:
            raise ValueError(f"days_meta says {day} is {m.get('split')!r} but tashwish.split says {expected!r}")
        if held and not allow_held_out:
            raise PermissionError(
                f"{day} is a HELD OUT day. The parameter file must be built from dev days only (pass allow_held_out=True "
                "or --allow-held-out only for a deliberate, recorded exception)."
            )
        out.append(dict(m))
    return sorted(out, key=lambda x: x["day"])


def _chunks(points: pd.DataFrame | Iterable[pd.DataFrame]) -> Iterator[pd.DataFrame]:
    if isinstance(points, pd.DataFrame):
        if points.empty:
            return
        day = pd.to_datetime(points["ts"], utc=True).dt.strftime("%Y-%m-%d")
        for _, g in points.groupby(day, sort=True):
            yield g
    else:
        yield from points


def build_params(
    points: pd.DataFrame | Iterable[pd.DataFrame],
    days_meta: list[dict],
    *,
    regions: dict[str, cfg.Region] | None = None,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = DEFAULT_SEED,
    allow_held_out: bool = False,
    dataset_version: str = "unreleased",
    data_class: str = cfg.DATA_CLASS_OBSERVED,
    generated_at: str | datetime | None = None,
    commit: str | None = None,
) -> dict:
    """Build the parameter file (a dict) from ADS-B points.

    `points` is one DataFrame of whole UTC days, or an iterable of DataFrames each holding whole UTC days (so a caller can load
    day by day). Columns: icao24, ts, lat, lon, alt_baro_ft, on_ground, src_type, nic, nac_p, flags, and optionally
    q_carried. `days_meta` lists `{"day", "split", ...}` for every day present; held-out days are refused unless allowed.
    """
    if data_class not in (cfg.DATA_CLASS_OBSERVED, cfg.DATA_CLASS_SYNTHETIC):
        raise ValueError("unknown data_class")
    meta = _check_days(days_meta, allow_held_out)
    regions = regions or REGIONS
    parts: dict[tuple[str, str], list[dict]] = {}
    days_seen: set[str] = set()
    for chunk in _chunks(points):
        days_seen |= set(pd.to_datetime(chunk["ts"], utc=True).dt.strftime("%Y-%m-%d").unique())
        for rname, region in regions.items():
            for stratum, summ in summarise_chunk(chunk, region).items():
                parts.setdefault((rname, stratum), []).append(summ)
    listed = {m["day"] for m in meta}
    if days_seen != listed:
        raise ValueError(f"days in the points {sorted(days_seen)} differ from days_meta {sorted(listed)}")
    if isinstance(gen := generated_at, datetime):
        gen = gen.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    gen = gen or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_regions = {}
    for rname, region in regions.items():
        strata = {}
        for stratum in cfg.STRATA:
            merged = merge_summaries(parts.get((rname, stratum), []))
            strata[stratum] = stratum_params(merged, seed, rname, stratum, n_boot)
        out_regions[rname] = {
            "bbox": {"lat_min": region.lat_min, "lat_max": region.lat_max, "lon_min": region.lon_min, "lon_max": region.lon_max},
            "strata": strata,
        }  # fmt: skip
    dev_only = all(m["split"] == "dev" for m in meta)
    caveats = json.loads(json.dumps(CAVEATS))
    if not dev_only:
        caveats["points"].insert(
            0, "WARNING: this file includes HELD OUT days and must not be used for tuning or as a dev result."
        )
    if data_class == cfg.DATA_CLASS_SYNTHETIC:
        caveats["summary"] = "SYNTHETIC DATA, invented for tests. " + caveats["summary"]
    return {
        "schema": SCHEMA_ID,
        "data_class": data_class,
        "notice": ("SYNTHETIC DATA. " if data_class == cfg.DATA_CLASS_SYNTHETIC else "") + NOTICE,
        "provenance": {
            "source": "adsb.lol globe_history archives (ODbL 1.0)",
            "dataset_version": dataset_version,
            "days": meta,
            "dev_only": dev_only,
            "split_rule": splitmod.RULE_ID,
            "code_commit": commit if commit is not None else code_commit(),
            "tashwish_version": __version__,
            "attribution": DATASET_ATTRIBUTION,
            "generated_at": gen,
            "seed": seed,
            "n_boot": n_boot,
            "bootstrap_unit": "aircraft-day, resampled with replacement",
            "confidence_level": CONFIDENCE,
        },
        "definitions": {
            "sample_filter": "airborne, src_type adsb_icao (own transponder), inside the region box, with barometric altitude; "
            "duplicates of (icao24, ts) removed",
            "quality_sample": "a sample with its own NIC (not carried forward from an earlier message)",
            "strongly_degraded": f"NIC < {cfg.NIC_STRONG_BELOW} or NACp < {cfg.NACP_STRONG_BELOW}",
            "episode": f"maximal run of one aircraft's consecutive quality samples, all strongly degraded, neighbours at most "
            f"{EPISODE_GAP_S:g} s apart, at least {MIN_EPISODE_SAMPLES} samples; duration is last minus first sample time",
            "baseline": "quality samples (or intervals starting at samples) that are not strongly degraded",
            "degraded_episode": "quality samples inside an episode (intervals: starting at a sample inside an episode)",
            "isolated_degraded": "strongly degraded runs shorter than the episode minimum belong to neither class; counted in n",
            "strata": {
                "enroute": f"barometric altitude >= {cfg.ENROUTE_MIN_FT} ft",
                "high": f">= {cfg.HIGH_MIN_FT} ft",
                "mid": f"{cfg.ENROUTE_MIN_FT} to {cfg.HIGH_MIN_FT} ft",
                "low": f"< {cfg.ENROUTE_MIN_FT} ft",
                "note": "enroute is the union of mid and high; strata overlap by construction",
            },
            "update_interval": f"seconds between consecutive position samples of one aircraft-day, up to {DT_HORIZON_S:g} s; "
            "longer gaps and samples flagged as a new leg are excluded and counted; quantiles use 0.1 s bins below 30 s",
            "dropout": f"share of intervals longer than {DROPOUT_THRESHOLDS_S[0]:g} s and {DROPOUT_THRESHOLDS_S[1]:g} s",
            "episode_rate": "episodes started per aircraft hour of observed quality-sample time (neighbours within the gap)",
            "transitions": "probability that the next quality sample is strongly degraded given the current one is degraded or "
            "nominal, within one aircraft and gap",
            "intervals": "boot_lo/boot_hi: percentile bootstrap over aircraft-days; wilson_*: ignores clustering, too narrow; "
            "poisson_exact_*: assumes independent episodes, too narrow",
            "min_sizes": {
                "aircraft_days": MIN_CLUSTERS,
                "quality_samples_categorical": MIN_N_CATEGORICAL,
                "episodes_for_duration": MIN_EPISODES,
            },  # fmt: skip
        },
        "caveats": caveats,
        "regions": out_regions,
    }


def days_meta_from_manifest(interim: Path, days: list[str]) -> list[dict]:
    """Day metadata for `days` from data/interim/manifest.jsonl (latest complete record per day), with the dev/held_out split."""
    recs: dict[str, dict] = {}
    mf = interim / "manifest.jsonl"
    if mf.exists():
        for line in mf.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("status") == "complete" and r.get("data_class") == cfg.DATA_CLASS_OBSERVED:
                    recs[r["day"]] = r
    out = []
    for day in days:
        r = recs.get(day, {})
        out.append({
            "day": day,
            "split": "held_out" if splitmod.is_held_out(date.fromisoformat(day)) else "dev",
            "rows": r.get("rows"), "aircraft": r.get("aircraft"), "out_sha256": r.get("out_sha256"),
            "ingested_utc": r.get("ingested_utc"), "ingest_code_version": r.get("code_version"),
        })  # fmt: skip
    return out


def _iter_days(interim: Path, days: list[str]) -> Iterator[pd.DataFrame]:
    for d in days:
        yield load_points(interim, [d], cols=SIRB_COLS)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tashwish.interop.sirb", description=__doc__.split("\n")[0])
    ap.add_argument("--days", nargs="+", required=True, help="UTC days YYYY-MM-DD (dev days only by default)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--interim", type=Path, default=Path("data/interim"))
    ap.add_argument("--n-boot", type=int, default=DEFAULT_N_BOOT)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--dataset-version", default=None, help="default: draft-<digest of the input files' sha256 values>")
    ap.add_argument("--allow-held-out", action="store_true", help="deliberate exception; recorded in the file")
    a = ap.parse_args(argv)
    days = sorted(set(a.days))
    meta = days_meta_from_manifest(a.interim, days)
    try:
        _check_days(meta, a.allow_held_out)
    except PermissionError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    digest = hashlib.sha256("|".join(f"{m['day']}:{m['out_sha256']}" for m in meta).encode()).hexdigest()[:12]
    params = build_params(
        _iter_days(a.interim, days),
        meta,
        n_boot=a.n_boot,
        seed=a.seed,
        allow_held_out=a.allow_held_out,
        dataset_version=a.dataset_version or f"draft-{digest}",
    )
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(
        json.dumps(params, ensure_ascii=False, allow_nan=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {a.out} from days {', '.join(days)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
