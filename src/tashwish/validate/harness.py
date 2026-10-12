"""Evaluation harness: build the analysis context for one scoring day, place scenarios, run detectors, match, score.

A scoring day is scored with everything fitted on the DEV days other than itself (so a dev day used while developing the
harness never scores itself, and a held-out day sees all DEV days). Nothing is ever fitted on a held-out day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import h3
import numpy as np
import pandas as pd

from .. import config as cfg
from ..coverage.model import apply_coverage, fit_coverage
from ..detect.discriminate import combine
from ..detect.jamming import detect_jamming, fit_p0
from ..detect.spoofing import EARTH_KM, build_spoof_events, find_jumps, haversine_km
from ..metrics.loader import load_points
from ..pipeline import build_ab, enroute_aircraft_stats, metrics_for_day, persistent_from_daily
from .inject import JamScenario, SpoofScenario, inject_jam, inject_spoof, seed_for

GRID = cfg.GRID_MAIN
MATCH_KM = 130.0  # centroid distance for matching a spoofing event to a scenario (injection radius is 120 km)
TRAFFIC_BINS = (("low", 3, 4), ("mid", 5, 9), ("high", 10, 10**6))
INTENSITIES = (0.3, 0.5, 0.8)
AREAS = (1, 3, 7)
DURATIONS = (1, 2, 3)
SPOOF_COUNTS = (1, 2, 3, 5, 8)
DISPLACEMENTS_KM = (
    10.0,
    40.0,
    100.0,
    250.0,
)  # real jumps seen on dev days: median about 80 km, 10th to 90th percentile 12 to 306 km


@dataclass
class Context:
    """Everything fitted from baseline days (DEV days minus the scoring day)."""

    base_days: list[str]
    persistent: pd.DataFrame
    cov: pd.DataFrame
    p0: pd.DataFrame
    cb_base: pd.DataFrame = field(repr=False, default=None)


class ContextFactory:
    """Loads DEV days once and hands out per-scoring-day contexts fitted on the other DEV days.

    The persistent-low-emitter list is computed once from ALL dev days (a day in the baseline contributes to it even when
    scored; the list needs at least 3 days of evidence per aircraft, so the self-influence is negligible). Nothing from a
    held-out day is ever loaded into the factory.
    """

    def __init__(self, interim: Path, dev_days: list[str], grid: cfg.Grid = GRID):
        self.interim, self.dev_days, self.grid = interim, list(dev_days), grid
        self.ab = {d: build_ab(interim, d, grid) for d in self.dev_days}
        self.persistent = persistent_from_daily({d: enroute_aircraft_stats(a) for d, a in self.ab.items()})
        self.cb = {d: metrics_for_day(a, self.persistent) for d, a in self.ab.items()}

    def context(self, score_day: str | None) -> Context:
        base = [d for d in self.dev_days if d != score_day]
        cb_base = pd.concat([self.cb[d] for d in base], ignore_index=True)
        return Context(base, self.persistent, fit_coverage(cb_base, base, self.grid), fit_p0(cb_base, base), cb_base)


def build_context(interim: Path, dev_days: list[str], score_day: str, grid: cfg.Grid = GRID) -> Context:
    """One-off context (slow path used by tests and debugging): factory over the dev days, scoring `score_day`."""
    return ContextFactory(interim, [d for d in dev_days if d != score_day], grid).context(score_day)


def day_buckets(day: str, grid: cfg.Grid = GRID) -> list[pd.Timestamp]:
    t0 = pd.Timestamp(day, tz="UTC")
    return [t0 + pd.Timedelta(hours=grid.bucket_hours * i) for i in range(24 // grid.bucket_hours)]


def score_ab(ab: pd.DataFrame, points: pd.DataFrame | None, ctx: Context, day: str, grid: cfg.Grid = GRID) -> dict:
    """Run the full detection chain for one day. `points` may be None to skip the spoofing detector."""
    cb = metrics_for_day(ab, ctx.persistent)
    cb = apply_coverage(cb, ctx.cov, grid, ctx.base_days, window_buckets=day_buckets(day, grid))
    flags, jam_ev = detect_jamming(cb, ctx.base_days, grid, p0=ctx.p0)
    if points is not None:
        jumps = find_jumps(points)
        spoof_ev = build_spoof_events(jumps)
    else:
        jumps, spoof_ev = pd.DataFrame(), build_spoof_events(pd.DataFrame())
    return {"cb": cb, "flags": flags, "jam_events": jam_ev, "jumps": jumps, "spoof_events": spoof_ev,
            "events": combine(jam_ev, spoof_ev)}  # fmt: skip


# ---------------------------------------------------------------- scenario placement


def _ring(cells, k=1):
    out = set()
    for c in cells:
        out.update(h3.grid_disk(c, k))
    return out


def _centre(cells) -> tuple[float, float]:
    ll = np.array([h3.cell_to_latlng(c) for c in cells])
    return float(ll[:, 0].mean()), float(ll[:, 1].mean())


def _compatible(a: dict, b: dict) -> bool:
    """Two scenario footprints may share a run if far apart in space, or separated in time by a free bucket."""
    d = min(haversine_km(p[0], p[1], q[0], q[1]) for p in a["pts"] for q in b["pts"])
    if d >= 260.0:
        return True
    return a["b1"] + 1 < b["b0"] or b["b1"] + 1 < a["b0"]


def traffic_bin(n: float) -> str:
    for name, lo, hi in TRAFFIC_BINS:
        if lo <= n <= hi:
            return name
    return "none"


def sample_sites(cb: pd.DataFrame, rng: np.random.Generator, per_bin: int) -> list[tuple[str, pd.Timestamp, str]]:
    """Candidate centres (cell, bucket, traffic_bin) from enroute cell-buckets, stratified by traffic so hard cases exist."""
    e = cb[(cb["stratum"] == "enroute") & (cb["n_aircraft"] >= TRAFFIC_BINS[0][1])]
    sites = []
    for name, lo, hi in TRAFFIC_BINS:
        sub = e[(e["n_aircraft"] >= lo) & (e["n_aircraft"] <= hi)].sort_values(["cell", "bucket"])
        if sub.empty:
            continue
        idx = rng.choice(len(sub), size=min(per_bin * 6, len(sub)), replace=False)  # oversample for placement rejection
        sites += [(r.cell, r.bucket, name) for r in sub.iloc[idx].itertuples()]
    rng.shuffle(sites)
    return sites


JAM_TIERS = ("easy", "medium", "hard", "random")


def _tier_design(tier: str, rng: np.random.Generator) -> tuple[float, int, int, tuple[str, ...]]:
    """(intensity, area, duration, allowed traffic bins) for a jamming-type scenario of a given difficulty tier."""
    if tier == "easy":
        return 0.8, int(rng.choice([3, 7])), int(rng.choice([2, 3])), ("high",)
    if tier == "medium":
        return 0.5, 3, 2, ("high",)
    if tier == "hard":
        return float(rng.choice([0.3, 0.5])), 1, 1, ("low", "mid") if rng.random() < 0.5 else ("low", "mid", "high")
    return float(rng.choice(INTENSITIES)), int(rng.choice(AREAS)), int(rng.choice(DURATIONS)), ("low", "mid", "high")


def make_scenarios(
    cb: pd.DataFrame, day: str, run: int, n_jam: int, n_spoof: int, n_both: int, n_null: int, grid: cfg.Grid = GRID
) -> list[dict]:
    """Place non-interfering scenarios for one run.

    Jamming-type scenarios cycle through difficulty tiers (easy, medium, hard, random) so every tier has enough cases; spoofing
    scenarios cycle through the number of displaced aircraft. Returns dicts with `kind`, `tier`, JamScenario/SpoofScenario and axes.
    """
    rng = np.random.default_rng(seed_for("scenarios", day, run))
    pool = sample_sites(cb, rng, per_bin=max(n_jam + n_spoof + n_both + n_null, 4) * 2)
    wanted = ["jam_only"] * n_jam + ["spoof_jump"] * n_spoof + ["spoof_and_jam"] * n_both + ["null"] * n_null
    placed: list[dict] = []
    counters = {"jam": rng.integers(0, 4), "spoof": rng.integers(0, len(SPOOF_COUNTS))}
    for k, kind in enumerate(wanted):
        if kind in ("jam_only", "spoof_and_jam"):
            tier = JAM_TIERS[counters["jam"] % 4] if kind == "jam_only" else ("easy", "medium")[counters["jam"] % 2]
            counters["jam"] += 1
        else:
            tier = "none"
        intensity, area, dur, bins = _tier_design(tier if tier != "none" else "random", rng)
        if kind in ("spoof_jump", "spoof_and_jam"):
            bins = ("high",)
        if kind == "spoof_and_jam":
            dur = min(dur, 2)
        n_sp_forced = None
        if kind == "spoof_jump":
            n_sp_forced = SPOOF_COUNTS[counters["spoof"] % len(SPOOF_COUNTS)]
            counters["spoof"] += 1
        elif kind == "spoof_and_jam":
            n_sp_forced = int(rng.choice([3, 5, 8]))
        i = 0
        while i < len(pool):
            cell, bucket, tbin = pool[i]
            i += 1
            if tbin not in bins:
                continue
            ring = sorted(h3.grid_disk(cell, 1))
            others = [c for c in ring if c != cell]
            rng.shuffle(others)
            cells = tuple(sorted([cell] + others[: {1: 0, 3: 2, 7: 6}[area]]))
            lat, lon = _centre(cells)
            b0 = int((bucket - pd.Timestamp(day, tz="UTC")).total_seconds() // (3600 * grid.bucket_hours))
            if b0 + dur > 24 // grid.bucket_hours:
                continue
            spoof_params = None
            if n_sp_forced is not None:
                ang = rng.uniform(0, 2 * np.pi)
                dist = float(rng.choice(DISPLACEMENTS_KM))
                f_lat = lat + (dist * np.cos(ang)) / EARTH_KM * 180 / np.pi
                f_lon = lon + (dist * np.sin(ang)) / (EARTH_KM * np.cos(np.radians(lat))) * 180 / np.pi
                spoof_params = (n_sp_forced, dist, f_lat, f_lon)
            pts = [(lat, lon)] + ([(spoof_params[2], spoof_params[3])] if spoof_params else [])
            fp = {"pts": pts, "b0": b0, "b1": b0 + dur - 1}
            if not all(_compatible(fp, p["fp"]) for p in placed):
                continue
            pool.pop(i - 1)
            sid = f"{day}_r{run}_{k:02d}_{kind}"
            seed = seed_for(sid)
            rec = {"sid": sid, "kind": kind, "tier": tier, "day": day, "run": run, "traffic_bin_centre": tbin, "fp": fp,
                   "area": area, "duration": dur, "intensity": intensity, "cells": cells, "centre_lat": lat,
                   "centre_lon": lon, "bucket0": bucket}  # fmt: skip
            if kind in ("jam_only", "spoof_and_jam"):
                rec["jam"] = JamScenario(sid, day, cells, bucket, dur, intensity, seed)
            if spoof_params:
                n_sp, dist, f_lat, f_lon = spoof_params
                rec["n_spoof"], rec["displacement_km"] = n_sp, dist
                rec["spoof"] = SpoofScenario(
                    sid, day, lat, lon, bucket + pd.Timedelta(minutes=30), 40.0, n_sp, f_lat, f_lon, seed
                )
            placed.append(rec)
            break
    return placed


# ---------------------------------------------------------------- matching and scoring


def _overlap(a0, a1, b0, b1) -> bool:
    return a0 < b1 and b0 < a1


def drop_background(result: dict, null: dict) -> dict:
    """Remove events that are identical (same deterministic id) to events found without any injection.

    Those are pre-existing real events, unlabelled; they must neither count as detections of an injected scenario nor as
    false alarms of the detector. Events altered by the injection get new ids and stay.
    """
    jam = result["jam_events"]
    sp = result["spoof_events"]
    jam = jam[~jam["event_id"].isin(set(null["jam_events"]["event_id"]))] if len(jam) else jam
    sp = sp[~sp["event_id"].isin(set(null["spoof_events"]["event_id"]))] if len(sp) else sp
    return {**result, "jam_events": jam, "spoof_events": sp, "events": combine(jam, sp)}


def match_scenario(rec: dict, result: dict, grid: cfg.Grid = GRID) -> dict:
    """Compare (background-free) detector output to one scenario. Returns the per-scenario outcome row."""
    step = pd.Timedelta(hours=grid.bucket_hours)
    t0 = rec["bucket0"]
    t1 = t0 + step * rec["duration"]
    area = _ring(rec["cells"], 1)
    out = {"sid": rec["sid"], "kind": rec["kind"]}
    # jamming-like events overlapping the scenario in space and time
    je = result["jam_events"]
    jm = pd.DataFrame()
    if len(je):
        ok = je.apply(
            lambda e: _overlap(e["start"], e["end"], t0, t1) and bool(set(e["cells"].split(",")) & area), axis=1
        )
        jm = je[ok.to_numpy(dtype=bool)]
    out["jam_detected"] = bool(len(jm))
    out["jam_delay_buckets"] = float(max(0.0, (jm["start"].min() - t0) / step)) if len(jm) else np.nan
    # spoofing-like events: a jump-out cluster (origin near the true area) or a jump-back cluster (destination near it)
    se = result["spoof_events"]
    s_t0 = t0 + pd.Timedelta(minutes=30)
    sm = pd.DataFrame()
    if len(se) and "spoof" in rec:
        sp = rec["spoof"]
        d_out = haversine_km(se["origin_lat"], se["origin_lon"], rec["centre_lat"], rec["centre_lon"])
        d_back = haversine_km(se["dest_lat"], se["dest_lon"], rec["centre_lat"], rec["centre_lon"])
        d_false = haversine_km(se["dest_lat"], se["dest_lon"], sp.false_lat, sp.false_lon)
        d_false_o = haversine_km(se["origin_lat"], se["origin_lon"], sp.false_lat, sp.false_lon)
        spatial = ((d_out <= MATCH_KM) & (d_false <= MATCH_KM)) | ((d_false_o <= MATCH_KM) & (d_back <= MATCH_KM))
        in_time = (se["start"] < s_t0 + pd.Timedelta(minutes=90)) & (se["end"] > s_t0 - pd.Timedelta(minutes=10))
        sm = se[(spatial & in_time).to_numpy(dtype=bool)]
    elif len(
        se
    ):  # non spoof scenarios: any spoofing event near the area in time counts as a spurious spoofing detection
        d = haversine_km(se["origin_lat"], se["origin_lon"], rec["centre_lat"], rec["centre_lon"])
        sm = se[((d <= MATCH_KM) & (se["start"] < t1) & (se["end"] > t0)).to_numpy(dtype=bool)]
    out["spoof_detected"] = bool(len(sm))
    out["spoof_delay_min"] = float(max(0.0, (sm["start"].min() - s_t0).total_seconds() / 60)) if len(sm) else np.nan
    mids = set(jm["event_id"]) | set(sm["event_id"]) if (len(jm) or len(sm)) else set()
    ev = result["events"]
    lab, unc, eids = "none", False, set()
    if len(ev) and mids:
        hit = ev["components"].apply(lambda c: bool(set(c.split("+")) & mids))
        m = ev[hit.to_numpy(dtype=bool)]
        if len(m):
            order = {"both": 3, "spoofing_like": 2, "jamming_like": 1}
            m2 = m.assign(_o=m["kind"].map(order)).sort_values("_o", ascending=False)
            lab, unc, eids = m2.iloc[0]["kind"], bool(m2.iloc[0]["label_uncertain"]), set(m["event_id"])
    out.update({"label": lab, "label_uncertain": unc, "event_ids": ",".join(sorted(eids))})
    return out


def run_day(
    interim: Path, day: str, ctx: Context, runs: int, mix: tuple[int, int, int, int], grid: cfg.Grid = GRID
) -> dict:
    """Evaluate one scoring day: a null run plus `runs` injection runs. Returns scenario rows, event rows and context stats."""
    ab0 = build_ab(interim, day, grid)
    pts0 = load_points(interim, [day])
    null = score_ab(ab0, pts0, ctx, day, grid)
    scen_rows, ev_rows = [], []
    for run in range(runs):
        recs = make_scenarios(null["cb"], day, run, *mix, grid=grid)
        ab_i, pts_i = ab0, pts0.copy()
        infos = {}
        for rec in recs:
            info = {}
            if "jam" in rec:
                ab_i, ji = inject_jam(ab_i, rec["jam"], grid)
                info.update(ji)
            if "spoof" in rec:
                pts_i, si = inject_spoof(pts_i, rec["spoof"], inplace=True)
                info.update(si)
            infos[rec["sid"]] = info
        res_full = score_ab(ab_i, pts_i, ctx, day, grid)
        cbi = res_full["cb"]
        res = drop_background(res_full, null)
        for rec in recs:
            row = match_scenario(rec, res, grid)
            sub = null["cb"][(null["cb"]["stratum"] == "enroute") & null["cb"]["cell"].isin(rec["cells"])]
            b0 = rec["bucket0"]
            tgt = sub[
                (sub["bucket"] >= b0) & (sub["bucket"] < b0 + pd.Timedelta(hours=grid.bucket_hours * rec["duration"]))
            ]
            tgt_i = cbi[
                (cbi["stratum"] == "enroute") & cbi["cell"].isin(rec["cells"]) & cbi["bucket"].isin(tgt["bucket"])
            ]
            row.update({
                "tier": rec["tier"], "day": day, "run": run, "intensity": rec["intensity"], "area": rec["area"], "duration": rec["duration"],
                "n_spoof_requested": rec.get("n_spoof", 0), "displacement_km": rec.get("displacement_km", np.nan), "n_spoofed": infos[rec["sid"]].get("n_spoofed", 0),
                "traffic_median": float(tgt["n_aircraft"].median()) if len(tgt) else np.nan,
                "traffic_bin": traffic_bin(float(tgt["n_aircraft"].median())) if len(tgt) else "none",
                "ok_share": float((tgt_i["status"] == "ok").mean()) if len(tgt_i) else 0.0,
                "coverage_class": tgt_i["coverage_class"].mode().iat[0] if len(tgt_i) else "none",
                "n_target": infos[rec["sid"]].get("n_target", 0), "data_class": "synthetic",
            })  # fmt: skip
            scen_rows.append(row)
        # events left after removing background: matched to a scenario, or false (injection-induced) events
        used = set()
        for r in scen_rows:
            if r["day"] == day and r["run"] == run and r["event_ids"]:
                used |= set(r["event_ids"].split(","))
        for e in res["events"].itertuples():
            ev_rows.append({"day": day, "run": run, "event_id": e.event_id, "kind": e.kind, "confidence": e.confidence,
                            "label_uncertain": e.label_uncertain, "matches_scenario": e.event_id in used,
                            "n_background_dropped": int(len(res_full["events"]) - len(res["events"])),
                            "data_class": "synthetic"})  # fmt: skip
    return {"day": day, "scenarios": scen_rows, "events": ev_rows, "null_events": null["events"].assign(day=day),
            "null_cb_stats": {"rows": int(len(null["cb"])), "ok": int((null["cb"]["status"] == "ok").sum())}}  # fmt: skip
