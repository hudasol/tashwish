"""Forward evaluation: score the preregistered predictions of docs/PREDICTIONS_FORWARD.md on days after the study window.

Written and committed before any day after 2026-03-13 was downloaded. It reads only processed day outputs (`cb.parquet`,
`events.parquet`, `day.json`) and the frozen state (`state/state.json`); it fits nothing and changes no threshold.

  calibrate  per day measures on DEVELOPMENT days only (the anchor the predictions were written against), written to
             results/forward/dev_calibration.json. Held out days are never read.
  score      per day measures on the forward block of results/forward/predictions_forward.json, HIT or MISS per
             prediction, Brier score, the first day each daily check fails, and docs/FORWARD_RESULTS.md. Refuses any day
             inside the study window and any day not scored in `frozen_baseline` mode with the current frozen state.

Every measure here is OBSERVED (real days, nothing injected). Day bootstrap intervals resample whole days.

Usage:
  python scripts/score_forward.py calibrate --processed processed
  python scripts/score_forward.py score --processed <processed folder of the incremental run>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from tashwish import config as cfg
from tashwish import regime as rg
from tashwish.metrics.stats import wilson_interval
from tashwish.split import STUDY_END, split

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "results" / "forward" / "predictions_forward.json"
CALIB = ROOT / "results" / "forward" / "dev_calibration.json"
SCORED = ROOT / "results" / "forward" / "forward_scored.json"
DOC = ROOT / "docs" / "FORWARD_RESULTS.md"
JAM_KINDS = ("jamming_like", "both")
SPOOF_KINDS = ("spoofing_like", "both")


def day_measures(processed: Path, day: str, ref_units: float) -> dict:
    """OBSERVED measures of one processed day. Regime labels are recomputed with the frozen rules of `tashwish.regime`."""
    d = processed / "days" / day
    cb = pd.read_parquet(d / "cb.parquet")
    ev = pd.read_parquet(d / "events.parquet")
    stats = rg.day_stats(cb)
    cov = cb[(cb["stratum"] == "enroute") & (cb["coverage_class"] == "covered")]
    spoof = ev[ev["kind"].isin(SPOOF_KINDS)]
    return {
        "day": day,
        "traffic": rg.traffic_regime(stats["units"], ref_units),
        "degraded": rg.degraded_regime(stats["share"]),
        "units": stats["units"],
        "share": stats["share"],
        "n_covered": int(len(cov)),
        "n_covered_not_enough": int((cov["n_aircraft"] < cfg.MIN_AIRCRAFT_PER_CELL).sum()),
        "false_coverage": float((cov["n_aircraft"] < cfg.MIN_AIRCRAFT_PER_CELL).mean()) if len(cov) else float("nan"),
        "events": int(len(ev)),
        "events_medium_high": int(ev["confidence"].isin(["medium", "high"]).sum()),
        "jamming_like_events": int(ev["kind"].isin(JAM_KINDS).sum()),
        "spoofing_like_events": int(len(spoof)),
        "spoofing_like_uncertain": int(spoof["label_uncertain"].sum()),
    }


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- metrics over a set of days


def _share_days(t: pd.DataFrame, col: str, value: str) -> float:
    return float((t[col] == value).mean())


METRICS = {
    "share_days_elevated": lambda t: _share_days(t, "degraded", "elevated"),
    "share_days_reduced": lambda t: _share_days(t, "traffic", "reduced"),
    "share_days_coupled": lambda t: float(((t["traffic"] == "reduced") == (t["degraded"] == "elevated")).mean()),
    "median_share": lambda t: float(t["share"].median()),
    "false_coverage_pooled": lambda t: (
        float(t["n_covered_not_enough"].sum() / t["n_covered"].sum()) if t["n_covered"].sum() else float("nan")
    ),
    "events_per_day": lambda t: float(t["events"].mean()),
    "jamming_like_events_per_day": lambda t: float(t["jamming_like_events"].mean()),
    "spoofing_like_uncertain_share": lambda t: (
        float(t["spoofing_like_uncertain"].sum() / t["spoofing_like_events"].sum())
        if t["spoofing_like_events"].sum()
        else float("nan")
    ),
}


def label_switches(t: pd.DataFrame) -> int:
    lab = t.sort_values("day")["degraded"].tolist()
    return int(sum(a != b for a, b in zip(lab, lab[1:], strict=False)))


def subset(t: pd.DataFrame, name: str, first_week_end: str) -> pd.DataFrame:
    if name == "all":
        return t
    if name == "first_week":
        return t[t["day"] <= first_week_end]
    col = "traffic" if name in ("normal", "reduced") else "degraded"
    return t[t[col] == name]


def day_bootstrap(t: pd.DataFrame, fn, reps: int, seed: int) -> tuple[float, float]:
    """Percentile interval of `fn` when whole days are resampled."""
    if len(t) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    rows = t.reset_index(drop=True)
    vals = [fn(rows.iloc[rng.integers(0, len(rows), len(rows))]) for _ in range(reps)]
    return float(np.nanpercentile(vals, 2.5)), float(np.nanpercentile(vals, 97.5))


def passes(value: float, op: str, threshold) -> bool:
    if op == "between":
        return threshold[0] <= value <= threshold[1]
    return {"<=": value <= threshold, ">=": value >= threshold}[op]


def score_prediction(p: dict, t: pd.DataFrame, spec: dict) -> dict:
    s = subset(t, p["subset"], spec["first_week_end"])
    need = spec["min_days"] if p["subset"] == "all" else spec["min_subset_days"]
    out = {"id": p["id"], "subset": p["subset"], "n_days": int(len(s)), "p": p["p"], "data_class": "OBSERVED"}
    if p["subset"] == "first_week":
        need = spec["first_week_min_days"]
    if len(s) < need:
        return {**out, "verdict": "NOT EVALUABLE", "reason": f"{len(s)} days in subset, at least {need} needed"}
    n_spoof = int(s["spoofing_like_events"].sum())
    if n_spoof < p.get("min_spoofing_like_events", 0):
        return {
            **out,
            "verdict": "NOT EVALUABLE",
            "reason": f"{n_spoof} spoofing-like events, at least {p['min_spoofing_like_events']} needed",
        }
    if p["metric"] == "label_switches":
        v = float(label_switches(s))
        lo = hi = float("nan")
        interval = "none (a count over the ordered block)"
    else:
        fn = METRICS[p["metric"]]
        v = fn(s)
        if np.isnan(v):
            return {**out, "verdict": "NOT EVALUABLE", "reason": "measure undefined on this subset"}
        if p["metric"].startswith("share_days"):
            k = int(round(v * len(s)))
            lo, hi = (float(x) for x in wilson_interval(k, len(s)))
            interval = "Wilson on days (days are not independent; descriptive only)"
        else:
            lo, hi = day_bootstrap(s, fn, spec["bootstrap"]["reps"], spec["bootstrap"]["seed"])
            interval = "day bootstrap 95%"
    hit = passes(v, p["op"], p["threshold"])
    return {**out, "value": v, "ci_lo": lo, "ci_hi": hi, "interval": interval, "verdict": "HIT" if hit else "MISS"}


def first_failures(t: pd.DataFrame, spec: dict) -> dict:
    """First day (in date order) on which each preregistered daily check fails, or None."""
    dc = spec["daily_checks"]
    checks = {
        "label_pair": lambda r: (r["traffic"], r["degraded"]) == tuple(dc["label_pair"]),
        # a day with no covered unit cannot show the coverage model working, so it fails the check
        "false_coverage": lambda r: (
            not np.isnan(r["false_coverage"]) and r["false_coverage"] <= dc["false_coverage_max"][r["traffic"]]
        ),
        "events": lambda r: r["events"] <= dc["events_max"],
    }
    res = {}
    for name, ok in checks.items():
        bad = [r["day"] for _, r in t.sort_values("day").iterrows() if not ok(r)]
        res[name] = {"first_fail": bad[0] if bad else None, "n_fail": len(bad)}
    firsts = [v["first_fail"] for v in res.values() if v["first_fail"]]
    res["any"] = {"first_fail": min(firsts) if firsts else None}
    return res


# ---------------------------------------------------------------- commands


def calibrate(processed: Path, state: Path) -> dict:
    ref = float(json.loads((state / "state.json").read_text(encoding="utf-8"))["ref_units"])
    dev, _held = split()
    rows = [day_measures(processed, d.isoformat(), ref) for d in dev]
    t = pd.DataFrame(rows)
    by = {}
    boot = {"reps": 2000, "seed": 20260314}
    for name, g in t.groupby("traffic"):
        by[name] = {
            "n_days": int(len(g)),
            "false_coverage_pooled": METRICS["false_coverage_pooled"](g),
            "false_coverage_pooled_ci": day_bootstrap(g, METRICS["false_coverage_pooled"], **boot),
            "events_per_day_ci": day_bootstrap(g, METRICS["events_per_day"], **boot),
            "false_coverage_day_max": float(g["false_coverage"].max()),
            "events_per_day": METRICS["events_per_day"](g),
            "events_day_max": int(g["events"].max()),
            "jamming_like_events_per_day": METRICS["jamming_like_events_per_day"](g),
            "share_median": METRICS["median_share"](g),
            "share_max": float(g["share"].max()),
        }
    return {
        "schema": "tashwish.forward_calibration.v1",
        "data_class": "OBSERVED",
        "days": "development days only (held out days not read)",
        "intervals": "day bootstrap 95%, 2000 resamples of whole days within the traffic regime, seed 20260314",
        "processed_mode": "dev_leave_one_day_out",
        "by_traffic_regime": by,
        "per_day": rows,
    }


def score(
    processed: Path, state: Path, spec: dict, spec_sha256: str | None = None, incomplete_reason: str | None = None
) -> dict:
    """Score the block. Refuses: a block touching the study window, a state other than the one pinned in the spec, and
    (run once) a block whose last day is not processed, unless `incomplete_reason` records why it never will be."""
    meta = json.loads((state / "state.json").read_text(encoding="utf-8"))
    state_sha = sha256_file(state / "state.json")
    if state_sha != spec["state_sha256"]:
        raise SystemExit(f"refused: state/state.json sha256 {state_sha} is not the frozen state pinned in the spec")
    first, last = date.fromisoformat(spec["block"]["first"]), date.fromisoformat(spec["block"]["last"])
    if first <= STUDY_END or last < first:
        raise SystemExit("refused: the forward block must lie after the study window")
    if not (processed / "days" / last.isoformat() / "day.json").exists() and not incomplete_reason:
        raise SystemExit(f"refused: {last.isoformat()} is not processed; score once, when the block is complete")
    block = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    rows, missing, rejected = [], [], []
    for day in block:
        d = processed / "days" / day
        if not (d / "day.json").exists():
            missing.append(day)
            continue
        m = json.loads((d / "day.json").read_text(encoding="utf-8"))
        prov = m.get("provenance") or {}
        why = [
            *(["mode is not frozen_baseline"] if m.get("mode") != "frozen_baseline" else []),
            *(["scored with another state"] if prov.get("state_sha256") != state_sha else []),
            *(["data_class is not observed"] if m.get("data_class") != "observed" else []),
            *(["ingested before the preregistration"] if (m.get("ingested_at") or "") <= spec["registered_at"] else []),
        ]
        if why:
            rejected.append({"day": day, "reasons": why})
            continue
        rows.append({**day_measures(processed, day, float(meta["ref_units"])), "code_commit": prov.get("code_commit"),
                     "ingested_at": m["ingested_at"]})  # fmt: skip
    t = pd.DataFrame(rows)
    preds = [score_prediction(p, t, spec) if len(t) else
             {"id": p["id"], "p": p["p"], "verdict": "NOT EVALUABLE", "reason": "no scored days", "data_class": "OBSERVED"}
             for p in spec["predictions"]]  # fmt: skip
    ev = [r for r in preds if r["verdict"] in ("HIT", "MISS")]
    brier = float(np.mean([(r["p"] - (r["verdict"] == "HIT")) ** 2 for r in ev])) if ev else float("nan")
    return {
        "schema": "tashwish.forward_scored.v1",
        "data_class": "OBSERVED",
        "spec_sha256": spec_sha256,
        "scorer_sha256": sha256_file(Path(__file__)),
        "incomplete_reason": incomplete_reason,
        "state_sha256": state_sha,
        "block": spec["block"],
        "n_days_scored": len(rows),
        "missing_days": missing,
        "rejected_days": rejected,
        "predictions": preds,
        "n_hit": sum(r["verdict"] == "HIT" for r in preds),
        "n_miss": sum(r["verdict"] == "MISS" for r in preds),
        "n_not_evaluable": sum(r["verdict"] == "NOT EVALUABLE" for r in preds),
        "brier": brier,
        "brier_reference_constant_half": 0.25,
        "first_failures": first_failures(t, spec) if len(t) else None,
        "per_day": rows,
    }


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def render(res: dict, spec: dict) -> str:
    text = {p["id"]: p for p in spec["predictions"]}
    lines = [
        "# Forward evaluation results",
        "",
        "Generated by `scripts/score_forward.py` from `results/forward/forward_scored.json`. Nothing here is typed by hand. The",
        "predictions are in `docs/PREDICTIONS_FORWARD.md`, committed before any day of the block was downloaded. Every measure is",
        "OBSERVED: real days scored with the frozen state, nothing injected. Research and monitoring tool, not for navigation or",
        "safety of life; nothing here attributes anything to any state or actor.",
        "",
        f"Block {res['block']['first']} to {res['block']['last']}: {res['n_days_scored']} days scored, "
        f"{len(res['missing_days'])} missing, {len(res['rejected_days'])} rejected (not scored with the frozen state).",
        f"Result: {res['n_miss']} MISS, {res['n_hit']} HIT, {res['n_not_evaluable']} not evaluable. Brier score "
        f"{_fmt(res['brier'])} (a constant forecast of 0.5 scores 0.250; lower is better).",
        "",
        "Misses are listed first.",
        "",
        "| ID | Verdict | Data class | Prediction | Value | Interval | Days | Stated probability |",
        "|---|---|---|---|---|---|---|---|",
    ]
    order = {"MISS": 0, "HIT": 1, "NOT EVALUABLE": 2}
    for r in sorted(res["predictions"], key=lambda r: (order[r["verdict"]], r["id"])):
        iv = f"{_fmt(r.get('ci_lo'))} to {_fmt(r.get('ci_hi'))} ({r.get('interval', r.get('reason', ''))})"
        lines.append(
            f"| {r['id']} | {r['verdict']} | {r['data_class']} | {text[r['id']]['text']} | {_fmt(r.get('value'))} | {iv} | "
            f"{r.get('n_days', 0)} | {r['p']:.2f} |"
        )
    ff = res.get("first_failures") or {}
    lines += ["", "## Where it fails first", "", "| Daily check | First failing day | Days failing |", "|---|---|---|"]
    for k in ("label_pair", "false_coverage", "events"):
        if k in ff:
            lines.append(f"| {k} | {ff[k]['first_fail'] or 'none'} | {ff[k]['n_fail']} |")
    lines.append("")
    if res["missing_days"]:
        lines += [f"Missing days: {', '.join(res['missing_days'])}.", ""]
    dev = ROOT / "results" / "forward" / "deviations.json"
    if dev.exists():
        lines += ["## Deviations from the plan", ""]
        for d in json.loads(dev.read_text(encoding="utf-8")):
            lines += [f"* {d['day']}: {d['what']} {d['mechanism']} {d['effect']}"]
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("calibrate", "score"))
    ap.add_argument("--processed", type=Path, default=ROOT / "processed")
    ap.add_argument("--state", type=Path, default=ROOT / "state")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--doc", type=Path, default=DOC)
    ap.add_argument("--incomplete-reason", help="score a block whose last day will never be processed, and record why")
    a = ap.parse_args(argv)
    if a.command == "calibrate":
        res, out = calibrate(a.processed, a.state), a.out or CALIB
    else:
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        res, out = score(a.processed, a.state, spec, sha256_file(SPEC), a.incomplete_reason), a.out or SCORED
        a.doc.write_text(render(res, spec), encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, sort_keys=True, default=float) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
