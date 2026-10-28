"""Score the baselines and the system on the same injected scenarios, and on the same real days.

  python -m tashwish.baselines.evaluate --split dev [--shard 0/2]
  python -m tashwish.baselines.evaluate --split held_out [--shard 0/2]
  python -m tashwish.baselines.evaluate --split dev --combine

The loop replicates `tashwish.validate.harness.run_day` step for step (same scenario generation with the same seeds, same
injection, same `drop_background` and `match_scenario`), and adds the baselines on the same injected frames. The system is
scored inside the same loop, and `--combine` compares its outcomes with the committed `results/<split>/synthetic_scenarios.csv`
as a reproduction check. Nothing in `detect/`, `validate/` or the scenario generation is changed.

Held out days: the run requires a clean tree for the baseline sources and the specification, requires a finished development
run, records the commit, and refuses to start a second time unless it is a resume under the same commit. Nothing is ever
fitted on a held out day. Synthetic outputs are SYNTHETIC; real day outputs are OBSERVED and carry no truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import h3
import numpy as np
import pandas as pd

from .. import config as cfg
from ..detect.discriminate import combine
from ..detect.jamming import build_events
from ..detect.spoofing import build_spoof_events, cluster_jumps
from ..metrics.loader import load_points
from ..pipeline import build_ab, metrics_for_day
from ..split import split
from ..validate import harness as hz
from ..validate.inject import inject_jam, inject_spoof
from ..validate.run import DEFAULT_MIX, ingested
from .jamming import (
    detect_climatology,
    detect_fixed_fraction,
    detect_no_coverage,
    detect_no_fdr,
    detect_no_regime,
    fit_climatology,
    fit_pooled,
)
from .spoofing import detect_naive_spoofing

ROOT = Path(__file__).resolve().parents[3]
GRID = hz.GRID
JAM_DETECTORS = ("system", "B1", "B1b", "B2", "B3a", "B3b", "B3c")
SPOOF_DETECTORS = ("system", "B4")
GUARDED = ["src/tashwish/baselines", "docs/BASELINES.md", "tests/test_baseline_fixed_fraction.py",
           "tests/test_baseline_climatology.py", "tests/test_baseline_ablations.py", "tests/test_baseline_spoofing.py"]  # fmt: skip
EMPTY_SPOOF = build_spoof_events(pd.DataFrame())
EMPTY_JAM = build_events(pd.DataFrame({"flag": pd.Series(dtype=bool)}), GRID)


def jam_result(events: pd.DataFrame) -> dict:
    return {"jam_events": events, "spoof_events": EMPTY_SPOOF, "events": combine(events, EMPTY_SPOOF)}


def spoof_result(events: pd.DataFrame) -> dict:
    return {"jam_events": EMPTY_JAM, "spoof_events": events, "events": combine(EMPTY_JAM, events)}


def strict_events(flags_inj: pd.DataFrame, flags_null: pd.DataFrame) -> pd.DataFrame:
    """Events built only from cell buckets that were NOT flagged on the uninjected day (flags caused by the injection)."""
    if flags_inj is None or flags_inj.empty:
        return EMPTY_JAM
    old: set = set()
    if len(flags_null):
        on = flags_null[flags_null["flag"]]
        old = set(zip(on["cell"], on["bucket"], strict=True))
    f = flags_inj.copy()
    seen = np.array([(c, b) in old for c, b in zip(f["cell"], f["bucket"], strict=True)], dtype=bool)
    f["flag"] = f["flag"].to_numpy(dtype=bool) & ~seen
    return build_events(f, GRID, "strong")


class DayFits:
    """Everything the baselines fit for one scoring day: development days other than the day itself, pooled over regimes."""

    def __init__(self, factory: hz.ContextFactory, day: str):
        others = [d for d in factory.dev_days if d != day]
        cb_dev = pd.concat([factory.cb[d] for d in others], ignore_index=True)
        self.days = others
        self.clim = fit_climatology(cb_dev, others, GRID)
        self.pooled = fit_pooled(cb_dev, others, GRID)


def run_all(ab: pd.DataFrame, pts: pd.DataFrame, ctx: hz.Context, fits: DayFits, day: str) -> dict:
    """Run the system and every baseline on one (possibly injected) day. Returns name -> result dict (plus flags)."""
    sysr = hz.score_ab(ab, pts, ctx, day, GRID)
    cb_raw = metrics_for_day(ab, ctx.persistent)
    out = {"system": {**sysr, "flags": sysr["flags"]}, "_cb": sysr["cb"], "_jumps": sysr["jumps"]}
    wb = hz.day_buckets(day, GRID)
    for name, (flags, ev) in {
        "B1": detect_fixed_fraction(cb_raw, GRID),
        "B1b": detect_fixed_fraction(cb_raw, GRID, sparsity_correction=True),
        "B2": detect_climatology(cb_raw, fits.clim, GRID),
        "B3a": detect_no_regime(cb_raw, fits.pooled, GRID, wb),
        "B3b": detect_no_coverage(cb_raw, ctx.base_days, ctx.p0, GRID),
        "B3c": detect_no_fdr(sysr["cb"], ctx.base_days, ctx.p0, GRID),
    }.items():
        out[name] = {**jam_result(ev), "flags": flags}
    nj, nev = detect_naive_spoofing(pts)
    out["B4"] = {**spoof_result(nev), "flags": None}
    out["_naive_jumps"] = nj
    return out


def _units_jam(flags: pd.DataFrame) -> set:
    if flags is None or flags.empty:
        return set()
    on = flags[flags["flag"] & (flags["stratum"] == "enroute")]
    return set(zip(on["cell"], on["bucket"], strict=True))


def _units_jumps(j: pd.DataFrame) -> set:
    if j is None or j.empty:
        return set()
    cells = [h3.latlng_to_cell(a, b, GRID.h3_res) for a, b in zip(j["lat0"], j["lon0"], strict=True)]
    buckets = j["t0"].dt.floor(f"{GRID.bucket_hours}h")
    return set(zip(cells, buckets, strict=True))


def _system_spoof_units(jumps: pd.DataFrame) -> set:
    """Origin units of the jumps that belong to system spoofing-like events (clusters of at least the minimum aircraft)."""
    if jumps is None or jumps.empty:
        return set()
    c = cluster_jumps(jumps)
    n = c.groupby("cluster")["icao24"].transform("nunique")
    return _units_jumps(c[n >= cfg.SPOOF_MIN_AIRCRAFT])


def real_rows(day: str, null: dict, meta: dict) -> list[dict]:
    """OBSERVED day, no truth: flagged units per detector and overlap with the system's flagged units."""
    rows = []
    sys_units = _units_jam(null["system"]["flags"])
    for name in JAM_DETECTORS:
        fl = null[name]["flags"]
        units = _units_jam(fl)
        tested = int((fl["stratum"] == "enroute").sum()) if fl is not None and len(fl) else 0
        both = len(units & sys_units)
        rows.append({"day": day, "detector": name, "kind": "jamming_like", "n_tested": tested, "n_flagged": len(units),
                     "n_events": int(len(null[name]["jam_events"])), "n_system": len(sys_units), "n_both": both,
                     "n_union": len(units | sys_units), "data_class": "observed", **meta})  # fmt: skip
    sp_sys = _system_spoof_units(null["_jumps"])
    sp_naive = _units_jumps(null["_naive_jumps"])
    for name, units, nev in (
        ("system", sp_sys, len(null["system"]["spoof_events"])),
        ("B4", sp_naive, len(null["B4"]["spoof_events"])),
    ):
        rows.append({"day": day, "detector": name, "kind": "spoofing_like", "n_tested": 0, "n_flagged": len(units),
                     "n_events": int(nev), "n_system": len(sp_sys), "n_both": len(units & sp_sys),
                     "n_union": len(units | sp_sys), "data_class": "observed", **meta})  # fmt: skip
    return rows


def run_day(factory: hz.ContextFactory, interim: Path, day: str, runs: int, mix) -> dict:
    ctx = factory.context(day)
    fits = DayFits(factory, day)
    tr, dr = factory.regimes_of(day)
    meta = {"traffic": tr, "degraded": dr}
    ab0 = build_ab(interim, day, GRID)
    pts0 = load_points(interim, [day])
    null = run_all(ab0, pts0, ctx, fits, day)
    real = real_rows(day, null, meta)
    nflags = null["system"]["flags"]
    avoid = (
        set(zip(nflags.loc[nflags["flag"], "cell"], nflags.loc[nflags["flag"], "bucket"], strict=True))
        if len(nflags)
        else set()
    )
    scen = []
    for run in range(runs):
        recs = hz.make_scenarios(null["_cb"], day, run, *mix, grid=GRID, avoid=avoid)
        ab_i, pts_i = ab0, pts0.copy()
        infos = {}
        for rec in recs:
            info = {}
            if "jam" in rec:
                ab_i, ji = inject_jam(ab_i, rec["jam"], GRID)
                info.update(ji)
            if "spoof" in rec:
                pts_i, si = inject_spoof(pts_i, rec["spoof"], inplace=True)
                info.update(si)
            infos[rec["sid"]] = info
        full = run_all(ab_i, pts_i, ctx, fits, day)
        dropped = {n: hz.drop_background(full[n], null[n]) for n in (*JAM_DETECTORS, "B4")}
        strict = {n: jam_result(strict_events(full[n]["flags"], null[n]["flags"])) for n in JAM_DETECTORS}
        for rec in recs:
            row = {"sid": rec["sid"], "kind": rec["kind"], "tier": rec["tier"], "day": day, "run": run,
                   "n_spoofed": infos[rec["sid"]].get("n_spoofed", 0), "displacement_km": rec.get("displacement_km", np.nan),
                   "scatter_km": rec.get("scatter_km", np.nan), "traffic": tr, "degraded": dr, "data_class": "synthetic"}  # fmt: skip
            for n in JAM_DETECTORS:
                row[f"{n}__jam"] = hz.match_scenario(rec, dropped[n], GRID)["jam_detected"]
                row[f"{n}__jam_strict"] = hz.match_scenario(rec, strict[n], GRID)["jam_detected"]
            for n in SPOOF_DETECTORS:
                row[f"{n}__spoof"] = hz.match_scenario(rec, dropped[n], GRID)["spoof_detected"]
            scen.append(row)
    return {"scenarios": scen, "real": real}


# ---------------------------------------------------------------- run control


def _git(*a: str) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def baseline_state() -> dict:
    h = hashlib.sha256()
    for g in GUARDED:
        p = ROOT / g
        for f in sorted(p.rglob("*.py")) if p.is_dir() else [p]:
            h.update(f.read_bytes())
    return {"commit": _git("rev-parse", "HEAD"), "dirty": bool(_git("status", "--porcelain", *GUARDED)),
            "sha256": h.hexdigest()}  # fmt: skip


def _days_for(split_name: str, interim: Path) -> tuple[list[str], list[str]]:
    dev, held = split()
    dev_all = [d.isoformat() for d in dev]
    held_all = [d.isoformat() for d in held]
    dev_days = ingested(interim, dev_all)
    if len(dev_days) != len(dev_all):
        raise SystemExit(f"development days missing: {sorted(set(dev_all) - set(dev_days))}")
    if split_name == "dev":
        return dev_days, dev_days
    score = ingested(interim, held_all)
    if len(score) != len(held_all):
        raise SystemExit(f"held out days missing: {sorted(set(held_all) - set(score))}")
    return dev_days, score


def run_split(split_name: str, interim: Path, out_root: Path, runs: int, shard: tuple[int, int]) -> None:
    out = out_root / split_name
    parts = out / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    dev_days, score_days = _days_for(split_name, interim)
    state = baseline_state()
    if split_name == "held_out":
        if state["dirty"]:
            raise SystemExit("uncommitted changes in the baseline sources or the specification: commit first")
        if not (out_root / "dev" / "run_meta.json").exists():
            raise SystemExit("the development run must be combined first (results/baselines/dev/run_meta.json)")
        marker = out / "RUNNING"
        if marker.exists():
            prev = json.loads(marker.read_text())
            if prev["sha256"] != state["sha256"]:
                raise SystemExit(
                    "baseline sources differ from the held out run already started; a changed run must be reported"
                )
        else:
            marker.write_text(json.dumps({**state, "started": pd.Timestamp.now("UTC").isoformat()}))
        if (out / "DONE").exists():
            raise SystemExit("the held out baseline run is finished; a second run must be reported as a second run")
    i, n = shard
    mine = [d for k, d in enumerate(score_days) if k % n == i]
    factory = hz.ContextFactory(interim, dev_days)
    t0 = time.time()
    for d in mine:
        pf = parts / f"{d}.json"
        if pf.exists():
            continue
        r = run_day(factory, interim, d, runs, DEFAULT_MIX)
        pf.write_text(json.dumps({"day": d, "commit": state["commit"], **r}, default=str))
        print(f"{split_name} {d} done ({time.time() - t0:.0f}s)", flush=True)


def combine_split(split_name: str, interim: Path, out_root: Path, runs: int) -> None:
    out = out_root / split_name
    _, score_days = _days_for(split_name, interim)
    scen, real, commits = [], [], set()
    for d in score_days:
        pf = out / "parts" / f"{d}.json"
        if not pf.exists():
            raise SystemExit(f"missing day {d}; run all shards first")
        j = json.loads(pf.read_text())
        scen += j["scenarios"]
        real += j["real"]
        commits.add(j["commit"])
    if len(commits) != 1:
        raise SystemExit(f"days were scored under different commits: {sorted(commits)}")
    s = pd.DataFrame(scen)
    r = pd.DataFrame(real)
    ref = pd.read_csv(ROOT / "results" / split_name / "synthetic_scenarios.csv")
    m = s.merge(ref[["sid", "jam_detected", "spoof_detected"]], on="sid", how="outer", indicator=True)
    both = m[m["_merge"] == "both"]
    repro = {
        "scenarios_here": int(len(s)), "scenarios_committed": int(len(ref)), "matched_sid": int(len(both)),
        "jam_detected_equal": int((both["system__jam"].astype(bool) == both["jam_detected"].astype(bool)).sum()),
        "spoof_detected_equal": int((both["system__spoof"].astype(bool) == both["spoof_detected"].astype(bool)).sum()),
    }  # fmt: skip
    s.to_csv(out / "synthetic_scenarios_baselines.csv", index=False)
    r.to_csv(out / "observed_days_baselines.csv", index=False)
    state = baseline_state()
    meta = {"split": split_name, "score_days": score_days, "runs_per_day": runs, "mix": DEFAULT_MIX,
            "run_commit": sorted(commits)[0], "combine_commit": state["commit"], "baseline_sources_sha256": state["sha256"],
            "combine_dirty": state["dirty"], "reproduction_of_system": repro, "finished": pd.Timestamp.now("UTC").isoformat()}  # fmt: skip
    if split_name == "held_out":
        marker = json.loads((out / "RUNNING").read_text())
        meta["baselines_fixed_before_run_commit"] = marker["commit"]
        meta["baseline_sources_sha256_at_start"] = marker["sha256"]
        (out / "DONE").write_text(meta["finished"])
    (out / "run_meta.json").write_text(json.dumps(meta, indent=1, default=str))
    print(json.dumps(repro, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "held_out"], required=True)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--combine", action="store_true")
    ap.add_argument("--interim", default="data/interim")
    ap.add_argument("--out", default="results/baselines")
    ap.add_argument("--runs", type=int, default=4)
    a = ap.parse_args()
    i, n = (int(x) for x in a.shard.split("/"))
    if a.combine:
        combine_split(a.split, Path(a.interim), Path(a.out), a.runs)
    else:
        run_split(a.split, Path(a.interim), Path(a.out), a.runs, (i, n))


if __name__ == "__main__":
    main()
