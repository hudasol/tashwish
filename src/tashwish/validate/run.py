"""Validation runner.

  python -m tashwish.validate.run --split dev        development evaluation on DEV days (leave-one-day-out); may be run repeatedly
  python -m tashwish.validate.run --split held_out   the held-out evaluation. Requires a freeze (results/FREEZE.json written by
                                                     --freeze), refuses to run twice, and only ever fits on DEV days.

Outputs go to results/<split>/ . Synthetic outputs are in files with `synthetic` in the name and carry data_class = synthetic;
real-data outputs (events, coverage outcomes) carry data_class = observed and contain no aircraft identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import pandas as pd

from .. import config as cfg
from ..metrics.loader import load_points
from ..pipeline import build_ab
from ..split import split
from . import coverage_test as cvt
from .harness import ContextFactory, run_day, score_ab
from .summary import summarize_injection

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MIX = (6, 4, 3, 3)  # jam_only, spoof_jump, spoof_and_jam, null scenarios per run


def config_constants() -> dict:
    return {
        k: getattr(cfg, k) for k in dir(cfg) if k.isupper() and isinstance(getattr(cfg, k), (int, float, str, tuple))
    }


def code_state() -> dict:
    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    src_hash = hashlib.sha256()
    for f in sorted((ROOT / "src").rglob("*.py")):
        src_hash.update(f.read_bytes())
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "src", "tests")),
            "src_sha256": src_hash.hexdigest(), "constants": config_constants()}  # fmt: skip


def ingested(interim: Path, days: list[str]) -> list[str]:
    return [d for d in days if (interim / f"points_{d}.parquet").exists()]


def real_events(ctx_for_day, interim: Path, days: list[str]) -> tuple[pd.DataFrame, list[pd.DataFrame]]:
    frames, cbs = [], []
    for d in days:
        ab = build_ab(interim, d)
        pts = load_points(interim, [d])
        ctx = ctx_for_day(d)
        res = score_ab(ab, pts, ctx, d)
        ev = res["events"].copy()
        ev["day"] = d
        ev["data_class"] = "observed"
        frames.append(ev)
        cbs.append(res["cb"].assign(day=d))
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), cbs


def run(
    split_name: str, interim: Path, out_root: Path, runs: int, mix, max_days: int | None, do_sensitivity: bool
) -> None:
    dev, held = split()
    dev_all = [d.isoformat() for d in dev]
    held_all = [d.isoformat() for d in held]
    dev_days = ingested(interim, dev_all)
    out = out_root / split_name
    out.mkdir(parents=True, exist_ok=True)
    if split_name == "held_out":
        if max_days is not None or out_root.resolve() != (ROOT / "results").resolve():
            raise SystemExit("the held-out run takes no --max-days and writes only to results/held_out")
        if not (out_root / "FREEZE.json").exists():
            raise SystemExit("no freeze: run --freeze first")
        freeze = json.loads((out_root / "FREEZE.json").read_text())
        state = code_state()
        if state["dirty"]:
            raise SystemExit("uncommitted changes in src/ or tests/")
        if freeze["commit"] != state["commit"] or freeze["src_sha256"] != state["src_sha256"]:
            raise SystemExit(
                "code differs from the freeze; a changed freeze must be recorded (see FREEZE_LOG.jsonl) and reported"
            )
        if (out / "DONE").exists() or (out / "RUNNING").exists():
            raise SystemExit(
                "a held-out run already started or finished; a second run must be reported as a second run"
            )
        score_days = ingested(interim, held_all)
        if len(score_days) != len(held_all):
            raise SystemExit(f"held-out days missing: {sorted(set(held_all) - set(score_days))}")
        if len(dev_days) != len(dev_all):
            raise SystemExit(f"dev days missing: {sorted(set(dev_all) - set(dev_days))}")
        (out / "RUNNING").write_text(
            json.dumps({"commit": state["commit"], "started": pd.Timestamp.now("UTC").isoformat()})
        )
    else:
        score_days = dev_days
    if max_days:
        score_days = score_days[:max_days]
    t0 = time.time()
    factory = ContextFactory(interim, dev_days)
    ctx_for = factory.context  # a held-out day is not in the factory's development days, so nothing is left out for it
    ingest_hash = {}
    mp = interim / "manifest.jsonl"
    if mp.exists():
        for line in mp.read_text().splitlines():
            r = json.loads(line)
            if r.get("status") == "complete" and r["day"] in score_days + dev_days:
                ingest_hash[r["day"]] = r.get("out_sha256")
    meta = {"split": split_name, "input_sha256": ingest_hash, "score_days": score_days, "dev_days_used_for_fitting": dev_days, "runs_per_day": runs,
            "mix": mix, "code": code_state(), "started": pd.Timestamp.now("UTC").isoformat()}  # fmt: skip

    # 1. controlled injection (SYNTHETIC)
    scen_rows, ev_rows, null_ev = [], [], []
    for d in score_days:
        r = run_day(interim, d, ctx_for(d), runs, mix)
        scen_rows += r["scenarios"]
        ev_rows += r["events"]
        null_ev.append(r["null_events"])
        print(f"{d} injection done ({time.time() - t0:.0f}s)", flush=True)
    scen = pd.DataFrame(scen_rows)
    evs = pd.DataFrame(ev_rows)
    scen.to_csv(out / "synthetic_scenarios.csv", index=False)
    evs.to_csv(out / "synthetic_scenario_events.csv", index=False)
    (out / "synthetic_injection_summary.json").write_text(
        json.dumps(summarize_injection(scen, evs), indent=1, default=float)
    )

    # 2. real events and coverage failure test (OBSERVED)
    real, cbs = real_events(ctx_for, interim, score_days)
    keep = [c for c in real.columns if c not in ("components",)]
    real[keep].to_csv(out / "observed_events.csv", index=False)
    outcomes = []
    for d, cb in zip(score_days, cbs, strict=True):
        ctx = ctx_for(d)
        outcomes.append(cvt.triple_outcomes(ctx.cov, cb.drop(columns=[c for c in ("day",) if c in cb.columns]), d))
    oc = pd.concat(outcomes, ignore_index=True)
    oc.to_csv(out / "observed_coverage_outcomes.csv", index=False)
    cs = cvt.summarize(oc)
    cs["false_coverage_ci_boot_days"] = cvt.bootstrap_over_days(oc, "false")
    cs["missed_coverage_ci_boot_days"] = cvt.bootstrap_over_days(oc, "missed")
    cs["next_bucket"] = cvt.next_bucket_check(pd.concat(cbs, ignore_index=True))
    (out / "observed_coverage_summary.json").write_text(json.dumps(cs, indent=1, default=float))

    # 3. thinning (SYNTHETIC receiver loss) on up to 4 days
    thin = []
    for d in score_days[:: max(1, len(score_days) // 4)][:4]:
        thin += cvt.thinning_test(build_ab(interim, d), ctx_for(d), d)
    pd.DataFrame(thin).to_csv(out / "synthetic_thinning.csv", index=False)

    # 4. sensitivity on dev days only
    if split_name == "dev" and do_sensitivity:
        from .sensitivity import SETTINGS, run_setting, summarize

        rows = []
        for label, ov, opts in SETTINGS:
            rows += run_setting(interim, score_days, label, ov, opts, {})
            print(f"sensitivity {label} done ({time.time() - t0:.0f}s)", flush=True)
        (out / "sensitivity_summary.json").write_text(json.dumps(summarize(rows), indent=1, default=float))

    # 5. daily counts of observed events
    daily = real.groupby("day").agg(n_events=("event_id", "size")).reindex(score_days, fill_value=0)
    daily.to_csv(out / "observed_daily_event_counts.csv")
    meta["finished"] = pd.Timestamp.now("UTC").isoformat()
    meta["seconds"] = time.time() - t0
    (out / "run_meta.json").write_text(json.dumps(meta, indent=1, default=str))
    if split_name == "held_out":
        (out / "DONE").write_text(meta["finished"])


def freeze(interim: Path, out_root: Path, reason: str = "") -> None:
    dev, held = split()
    if (out_root / "held_out" / "RUNNING").exists() or (out_root / "held_out" / "DONE").exists():
        raise SystemExit("the held-out run has started; the freeze can no longer be changed")
    if (out_root / "FREEZE.json").exists() and not reason:
        raise SystemExit("a freeze exists; to replace it pass --reason, which is recorded in FREEZE_LOG.jsonl")
    dev_all = [d.isoformat() for d in dev]
    held_all = [d.isoformat() for d in held]
    state = code_state()
    if state["dirty"]:
        raise SystemExit("working tree has uncommitted changes in src/ or tests/: commit first, then freeze")
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "FREEZE.json").write_text(json.dumps({**state, "frozen_at": pd.Timestamp.now("UTC").isoformat(),
                                                      "dev_days": dev_all, "held_out_days": held_all}, indent=1, default=str))  # fmt: skip
    with open(out_root / "FREEZE_LOG.jsonl", "a") as fh:
        fh.write(
            json.dumps(
                {
                    "at": pd.Timestamp.now("UTC").isoformat(),
                    "commit": state["commit"],
                    "reason": reason or "first freeze",
                }
            )
            + "\n"
        )
    print("frozen at", state["commit"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "held_out"])
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--reason", default="")
    ap.add_argument("--interim", default="data/interim")
    ap.add_argument("--out", default="results")
    ap.add_argument("--runs", type=int, default=4)
    ap.add_argument("--max-days", type=int)
    ap.add_argument("--sensitivity", action="store_true")
    a = ap.parse_args()
    if a.freeze:
        freeze(Path(a.interim), Path(a.out), a.reason)
        return
    run(a.split, Path(a.interim), Path(a.out), a.runs, DEFAULT_MIX, a.max_days, a.sensitivity)


if __name__ == "__main__":
    main()
