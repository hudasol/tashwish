"""Generate docs/PREDICTIONS_RESULTS.md, docs/VALIDATION.md and results/headline.json from result files.

  python scripts/make_results_docs.py [--dev results/dev] [--held results/held_out] [--interim data/interim]

Nothing in the generated files is typed by hand. Pre-registered pass criteria are copied from docs/PREDICTIONS.md and
implemented below; where an implementation had to deviate from the wording, the deviation is printed next to the result.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from tashwish.metrics.stats import wilson_interval
from tashwish.validate.summary import cluster_bootstrap_rate

ROOT = Path(__file__).resolve().parents[1]
REPORT_DAYS = ["2026-02-28", "2026-03-13"]
DEV_INCIDENT_DAYS = ["2026-03-02", "2026-03-07"]


def f(x, d=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def rate_row(df: pd.DataFrame, col: str) -> dict:
    n, k = len(df), int(df[col].sum()) if len(df) else 0
    lo, hi = wilson_interval(k, n) if n else (float("nan"), float("nan"))
    blo, bhi = (
        cluster_bootstrap_rate(df.assign(**{col: df[col].astype(float)}), col) if n else (float("nan"), float("nan"))
    )
    return {
        "n": n,
        "k": k,
        "rate": k / n if n else float("nan"),
        "lo": float(lo),
        "hi": float(hi),
        "blo": blo,
        "bhi": bhi,
    }


def fmt_rate(r: dict) -> str:
    return f"{f(r['rate'])} ({r['k']}/{r['n']}; Wilson {f(r['lo'])} to {f(r['hi'])}; day bootstrap {f(r['blo'])} to {f(r['bhi'])})"


class Split:
    def __init__(self, path: Path):
        self.path = path
        self.ok = (path / "synthetic_scenarios.csv").exists()
        if not self.ok:
            return
        self.scen = pd.read_csv(path / "synthetic_scenarios.csv")
        self.ev = pd.read_csv(path / "observed_events.csv")
        self.cov = pd.read_csv(path / "observed_coverage_outcomes.csv")
        self.covsum = json.loads((path / "observed_coverage_summary.json").read_text())
        self.inj = json.loads((path / "synthetic_injection_summary.json").read_text())
        self.meta = json.loads((path / "run_meta.json").read_text())
        self.daily = pd.read_csv(path / "observed_daily_event_counts.csv")
        self.thin = pd.read_csv(path / "synthetic_thinning.csv")
        self.days = self.meta["score_days"]
        sp = path / "sensitivity_summary.json"
        self.sens = json.loads(sp.read_text()) if sp.exists() else None


def jam_subsets(s: pd.DataFrame) -> dict[str, pd.DataFrame]:
    j = s[s["kind"] == "jam_only"]
    return {
        "J1": j[(j.intensity == 0.8) & (j.area >= 3) & (j.duration >= 2) & (j.traffic_median >= 10)],
        "J2": j[(j.intensity == 0.5) & (j.area == 3) & (j.duration == 2) & (j.traffic_median >= 10)],
        "J3": j[(j.area == 1) & (j.duration == 1) & ((j.intensity == 0.3) | (j.traffic_median < 8))],
    }


def monotone(vals: list[float]) -> bool:
    return all(b >= a - 1e-12 for a, b in zip(vals, vals[1:], strict=False))


def j6(s: pd.DataFrame) -> tuple[bool | None, str]:
    j = s[s["kind"] == "jam_only"].copy()
    j["tb"] = np.select([j.traffic_median >= 10, j.traffic_median >= 5], [2, 1], 0)
    med = {"intensity": 0.5, "area": 3, "duration": 2, "tb": 1}
    axes = {"intensity": [0.3, 0.5, 0.8], "area": [1, 3, 7], "duration": [1, 2, 3], "tb": [0, 1, 2]}
    lines, ok_all, evaluable = [], True, True
    for ax, levels in axes.items():
        sub = j
        for other, v in med.items():
            if other != ax:
                sub = sub[sub[other] == v]
        rs = [rate_row(sub[sub[ax] == lv], "jam_detected") for lv in levels]
        ns = [r["n"] for r in rs]
        lines.append(
            f"{ax}: " + ", ".join(f"{lv}={f(r['rate'], 2)} (n={r['n']})" for lv, r in zip(levels, rs, strict=True))
        )
        if min(ns) < 10:
            evaluable = False
        ok_all &= monotone([r["rate"] for r in rs if r["n"]])
    pooled = []
    for ax, levels in axes.items():
        rs = [rate_row(j[j[ax] == lv], "jam_detected")["rate"] for lv in levels]
        pooled.append(monotone(rs))
    txt = "fixed at medium: " + "; ".join(lines) + f". Pooled marginals monotone on all axes: {all(pooled)}."
    if not evaluable:
        return (
            None,
            txt
            + " Not evaluable as worded (fewer than 10 scenarios in at least one cell); pooled version: "
            + str(all(pooled)),
        )
    return ok_all, txt


def evaluate(held: Split, dev: Split, ingest: pd.DataFrame | None) -> list[dict]:
    out = []

    def add(pid, claim, crit, observed, hit, conf, note=""):
        out.append(
            {"id": pid, "claim": claim, "criterion": crit, "observed": observed, "hit": hit, "conf": conf, "note": note}
        )

    # D
    if ingest is not None and held.ok:
        hd = ingest[ingest["day"].isin(held.days)]
        add(
            "D1",
            "Every held-out day ingests",
            "14 of 14 complete",
            f"{len(hd)} of {len(held.days)}",
            len(hd) == len(held.days) == 14,
            0.90,
        )
        inrange = hd[(hd.rows.between(1.2e6, 2.6e6)) & (hd.aircraft.between(1600, 2800))]
        bad = hd[~hd["day"].isin(inrange["day"])]
        add("D2", "Held-out volume resembles the two days I saw", "every day 1.2 to 2.6 M rows and 1,600 to 2,800 aircraft",
            f"{len(inrange)} of {len(hd)} in range; outside: " + ", ".join(f"{r.day} ({r.rows / 1e6:.2f} M rows, {r.aircraft} aircraft)" for r in bad.itertuples()),
            len(inrange) == len(hd), 0.80)  # fmt: skip
    # C
    cs = held.covsum
    pc, pn = cs["covered"]["p_enough"], cs["no_coverage"]["p_enough"]
    add("C1", "Covered cells mostly enough on a new day", "P(enough | covered) >= 0.70",
        f"{f(pc)} (Wilson {f(cs['covered']['ci_lo'])} to {f(cs['covered']['ci_hi'])}; day bootstrap of the failure rate {cs['false_coverage_ci_boot_days']})", pc >= 0.70, 0.65)  # fmt: skip
    add("C2", "no_coverage rarely enough", "P(enough | no_coverage) <= 0.15", f"{f(pn)} (Wilson {f(cs['no_coverage']['ci_lo'])} to {f(cs['no_coverage']['ci_hi'])})", pn <= 0.15, 0.70)  # fmt: skip
    fc = 1 - pc
    sl = cs["covered_by_slot"]
    early = np.mean([sl[str(s)]["false_coverage"] for s in (0, 1) if str(s) in sl])
    mid = np.mean([sl[str(s)]["false_coverage"] for s in (3, 4, 5) if str(s) in sl])
    add("C3", "Some false coverage, mostly at low traffic hours", "0.10 <= P(not enough | covered) <= 0.35 and rate in slots 0,1 > rate in slots 3 to 5",
        f"failure rate {f(fc)}; slots 0,1 mean {f(early)}; slots 3 to 5 mean {f(mid)}", (0.10 <= fc <= 0.35) and early > mid, 0.55)  # fmt: skip
    nb = cs["next_bucket"]
    add("C4", "coverage_lost carries information", "P(enough next | coverage_lost) < P(enough next | ok)",
        f"coverage_lost {f(nb['coverage_lost']['p_enough_next'])} (n={nb['coverage_lost']['n']}) versus ok {f(nb['ok']['p_enough_next'])} (n={nb['ok']['n']})",
        nb["coverage_lost"]["p_enough_next"] < nb["ok"]["p_enough_next"], 0.60)  # fmt: skip
    # J
    subs = jam_subsets(held.scen)
    r1, r2, r3 = (rate_row(subs[k], "jam_detected") for k in ("J1", "J2", "J3"))
    add("J1", "Easy scenarios found", "recall >= 0.95", fmt_rate(r1), r1["rate"] >= 0.95, 0.80)
    add("J2", "Medium mostly found", "0.70 <= recall <= 0.95", fmt_rate(r2), 0.70 <= r2["rate"] <= 0.95, 0.55)
    add("J3", "Hard mostly missed", "recall <= 0.50", fmt_rate(r3), r3["rate"] <= 0.50, 0.75)
    jt = held.scen[(held.scen.kind == "jam_only") & held.scen.jam_detected]
    me = jt[jt.tier == "easy"]["jam_delay_buckets"].median()
    mm = jt[jt.tier == "medium"]["jam_delay_buckets"].median()
    add(
        "J4",
        "Short delay",
        "median delay <= 0 buckets (easy), <= 1 (medium)",
        f"easy {f(me, 1)}, medium {f(mm, 1)} buckets",
        bool(me <= 0 and mm <= 1),
        0.70,
    )
    ev = held.ev
    mh = ev[ev.confidence.isin(["medium", "high"])]
    per_day = len(mh) / max(len(held.days), 1)
    add("J5", "Few medium or high events per un-injected held-out day", "<= 0.5 per day on average",
        f"{f(per_day, 2)} per day ({len(mh)} events over {len(held.days)} days)", per_day <= 0.5, 0.55)  # fmt: skip
    hit6, txt6 = j6(held.scen)
    add("J6", "Recall rises with each axis", "non-decreasing along each axis with the others at medium", txt6, hit6, 0.85,
        "Deviation: cells at fixed medium values are small; see the text." if hit6 is None else "")  # fmt: skip
    # S
    sj = held.scen[held.scen.kind == "spoof_jump"]
    s3 = sj[sj.n_spoofed >= 3]
    s12 = sj[sj.n_spoofed.isin([1, 2])]
    jo = held.scen[held.scen.kind == "jam_only"]
    rr = rate_row(s3, "spoof_detected")
    add("S1", "Spoof jumps with 3 or more aircraft detected", "recall >= 0.80", fmt_rate(rr), rr["rate"] >= 0.80, 0.65)
    rj = rate_row(s3, "jam_detected")
    add(
        "S2",
        "Spoof jumps not flagged by the jamming detector",
        "jamming flag rate <= 0.10",
        fmt_rate(rj),
        rj["rate"] <= 0.10,
        0.85,
    )
    rs = rate_row(jo, "spoof_detected")
    add("S3", "Jam only not called spoofing", "spoofing flag rate <= 0.10", fmt_rate(rs), rs["rate"] <= 0.10, 0.80)
    u = held.inj["uncertain_share_of_detected"]
    a = held.inj["label_accuracy_when_committed"]
    add("S4", "Uncertain is a meaningful minority; committed labels are right", "uncertain share 0.05 to 0.30 and committed accuracy >= 0.85",
        f"uncertain share {f(u['rate'])} ({u['k']}/{u['n']}); committed accuracy {f(a['rate'])} ({a['k']}/{a['n']})",
        0.05 <= u["rate"] <= 0.30 and a["rate"] >= 0.85, 0.50)  # fmt: skip
    r12 = rate_row(s12, "spoof_detected")
    add("S5", "1 or 2 spoofed aircraft mostly missed", "recall <= 0.30", fmt_rate(r12), r12["rate"] <= 0.30, 0.80)

    # R
    def qualifies(e):
        return (e.kind.isin(["spoofing_like", "both"])) | (
            (e.kind == "jamming_like") & e.confidence.isin(["medium", "high"])
        )

    per = {d: ev[ev.day == d] for d in held.days}
    rep = [d for d in REPORT_DAYS if d in per]
    has = {d: bool(qualifies(per[d]).any()) for d in rep}
    add("R1", "Some activity on report days", "each of 02-28 and 03-13 has at least one qualifying event",
        ", ".join(f"{d}: {int(qualifies(per[d]).sum())} qualifying of {len(per[d])}" for d in rep), all(has.values()) and len(rep) == 2, 0.55)  # fmt: skip
    others = [d for d in held.days if d not in REPORT_DAYS]
    m_rep = np.mean([len(per[d]) for d in rep]) if rep else float("nan")
    m_oth = np.mean([len(per[d]) for d in others]) if others else float("nan")
    add(
        "R2",
        "Report days busier",
        "mean events/day on report days > mean on the other 12",
        f"{f(m_rep, 2)} versus {f(m_oth, 2)}",
        bool(m_rep > m_oth),
        0.55,
    )
    n_with = sum(len(per[d]) > 0 for d in others)
    add(
        "R3",
        "A background rate exists",
        ">= 4 of 12 non report days have an event",
        f"{n_with} of {len(others)}",
        n_with >= 4,
        0.65,
    )
    north = float((ev.lat > 26).mean()) if len(ev) else float("nan")
    add(
        "R4",
        "Gulf north carries most events",
        "share with lat > 26 >= 0.5",
        f"{f(north)} of {len(ev)} events",
        north >= 0.5,
        0.60,
    )
    # X (dev)
    if dev.ok and dev.sens:
        st = dev.sens["settings"]

        def mx(*labels):
            return max(abs(st[l]["abs_change_vs_default"]) for l in labels if l in st)

        g, ma, q = (
            mx("lower_bound=0.15", "lower_bound=0.25"),
            mx("min_aircraft=4", "min_aircraft=6"),
            mx("fdr_q=0.01", "fdr_q=0.10"),
        )
        add("X1", "Count most sensitive to gate and min aircraft, least to q", "gate and min aircraft both above q",
            f"max abs change in event count: gate {g}, min aircraft {ma}, q {q}", g > q and ma > q, 0.65,
            "Implemented settings: gate 0.15/0.25 (about +/-25%), min aircraft 4/6 (+/-20%), q 0.01/0.10 (wider than +/-25%). Dev days only.")  # fmt: skip
        share = min(
            st[l]["share_kept"]
            for l in (
                "lower_bound=0.15",
                "lower_bound=0.25",
                "min_bad=2",
                "min_bad=4",
                "min_aircraft=4",
                "min_aircraft=6",
                "p0_floor=0.015",
                "p0_floor=0.025",
            )
            if l in st
        )
        add("X2", "Locations stable under threshold changes", ">= 70% of baseline events keep Jaccard >= 0.5",
            f"minimum share kept over the threshold settings: {f(share)}", share >= 0.70, 0.60, "Dev days only.")  # fmt: skip
        cv = dev.sens["day_to_day"]["cv"]
        add("X3", "Day to day variation is large", "std/mean of daily event count > 0.5", f"{f(cv)} (mean {f(dev.sens['day_to_day']['mean'], 2)}, std {f(dev.sens['day_to_day']['std'], 2)})", cv > 0.5, 0.60, "Dev days only.")  # fmt: skip
    return out


def predictions_md(rows: list[dict], freeze: dict | None, held: Split) -> str:
    hits = [r for r in rows if r["hit"] is True]
    scored = [r for r in rows if r["hit"] is not None]
    brier = np.mean([(r["conf"] - float(r["hit"])) ** 2 for r in scored]) if scored else float("nan")
    L = [
        "# Pre-registered predictions: results",
        "",
        "Generated by `scripts/make_results_docs.py` from `results/held_out` and `results/dev`. The prediction file `docs/PREDICTIONS.md` was not edited.",
        f"Frozen code commit: `{(freeze or {}).get('commit', 'unknown')}`; held-out run finished {held.meta.get('finished', 'unknown')}.",
        "",
        f"**{len(hits)} HIT, {len(scored) - len(hits)} MISS** out of {len(scored)} evaluated, {len(rows) - len(scored)} not evaluable as worded. "
        f"Mean Brier score of my stated confidences: {f(brier)} (0 is perfect; 0.25 is the score of always saying 0.5).",
        "",
        "| ID | Prediction | Pass criterion | Observed | Confidence | Result |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        res = "HIT" if r["hit"] is True else "MISS" if r["hit"] is False else "NOT EVALUABLE"
        L.append(
            f"| {r['id']} | {r['claim']} | {r['criterion']} | {r['observed']}{(' ' + r['note']) if r['note'] else ''} | {r['conf']:.2f} | **{res}** |"
        )
    L += ["", "Misses are not explained away here; the discussion is in `docs/VALIDATION.md`.", ""]
    return "\n".join(L)


def tier_table(s: pd.DataFrame, title: str) -> list[str]:
    j = s[s["kind"] == "jam_only"]
    L = [f"**{title}**", "", "| Tier | Scenarios | Event recall | Median delay (buckets) |", "|---|---|---|---|"]
    for t in ("easy", "medium", "hard", "random"):
        d = j[j.tier == t]
        r = rate_row(d, "jam_detected")
        dl = d[d.jam_detected]["jam_delay_buckets"].median()
        L.append(f"| {t} | {len(d)} | {fmt_rate(r)} | {f(dl, 1)} |")
    return L + [""]


def axis_table(s: pd.DataFrame, col: str, label: str, subset=None) -> list[str]:
    j = s[(s["kind"] == "jam_only")]
    L = [f"| {label} | n | recall |", "|---|---|---|"]
    for v, d in j.groupby(col):
        r = rate_row(d, "jam_detected")
        L.append(f"| {v} | {r['n']} | {f(r['rate'])} (Wilson {f(r['lo'])} to {f(r['hi'])}) |")
    return L + [""]


def confusion_md(inj: dict, key: str, title: str) -> list[str]:
    c = inj[key]
    cols = c["columns"]
    L = [
        f"**{title}** (rows: what was injected, columns: what the system said; `?` marks an uncertain call)",
        "",
        "| Injected | " + " | ".join(cols) + " |",
        "|---|" + "---|" * len(cols),
    ]
    for k, v in c["rows"].items():
        L.append(f"| {k} | " + " | ".join(str(x) for x in v) + " |")
    return L + [""]


def validation_md(
    held: Split,
    dev: Split,
    freeze: dict | None,
    rows: list[dict],
    regime: dict | None,
    daily: pd.DataFrame | None,
    ingest: pd.DataFrame | None,
) -> str:
    L = [
        "# Validation",
        "",
        "Generated by `scripts/make_results_docs.py` from result files in `results/`. Nothing here is typed by hand. There is no ground truth for GNSS "
        "interference in public ADS-B data, so every number below is either (a) a controlled test on SYNTHETIC injections into real traffic, "
        "(b) a property of the coverage model, or (c) a description of events on real days. Real-day events are evidence of degraded position "
        "quality, not proof of interference, and say nothing about who or what caused them.",
        "",
        "## 1. Design and discipline",
        "",
        f"- Study window 2026-02-07 to 2026-03-13 (35 UTC days). Split rule `tashwish-heldout-v1`: {len(freeze['dev_days']) if freeze else '?'} development days and "
        f"{len(freeze['held_out_days']) if freeze else '?'} held-out days, listed in `docs/PREDICTIONS.md` before any held-out result existed.",
        f"- Frozen at commit `{(freeze or {}).get('commit', 'unknown')}`; held-out run executed once ({held.meta.get('finished', '?')}). "
        "Baselines, coverage and the persistent emitter list were fitted on development days only.",
        f"- Held-out synthetic scenarios: {len(held.scen)} (runs per day {held.meta['runs_per_day']}); development scenarios: {len(dev.scen)}. "
        "Scenarios within a day share traffic, so intervals marked day bootstrap resample whole days.",
        "",
        "## 2. Jamming-like detector on synthetic injection (SYNTHETIC)",
        "",
    ]
    L += tier_table(held.scen, "Held-out days") + tier_table(dev.scen, "Development days (for comparison)")
    L += ["Held-out recall by intensity:", ""] + axis_table(held.scen, "intensity", "Target degraded share")
    L += (
        ["By area (cells):", ""]
        + axis_table(held.scen, "area", "Cells")
        + ["By duration (buckets):", ""]
        + axis_table(held.scen, "duration", "Buckets")
    )
    L += ["By traffic bin:", ""] + axis_table(held.scen, "traffic_bin", "Traffic")
    L += ["By coverage class of the target cells:", ""] + axis_table(held.scen, "coverage_class", "Coverage class")
    L += ["## 3. Spoofing-like detector and discrimination (SYNTHETIC)", ""]
    sj = held.scen[held.scen.kind == "spoof_jump"]
    L += ["| Displaced aircraft | n | spoofing-like recall |", "|---|---|---|"]
    for v, d in sj.groupby("n_spoofed"):
        r = rate_row(d, "spoof_detected")
        L.append(f"| {v} | {r['n']} | {f(r['rate'])} (Wilson {f(r['lo'])} to {f(r['hi'])}) |")
    L += ["", "| Displacement (km), 3 or more aircraft | n | recall |", "|---|---|---|"]
    for v, d in sj[sj.n_spoofed >= 3].groupby("displacement_km"):
        r = rate_row(d, "spoof_detected")
        L.append(f"| {v:g} | {r['n']} | {f(r['rate'])} (Wilson {f(r['lo'])} to {f(r['hi'])}) |")
    L += [""] + confusion_md(held.inj, "confusion_all", "Held-out confusion matrix, all scenarios")
    L += confusion_md(dev.inj, "confusion_all", "Development confusion matrix, all scenarios")
    for k, lab in (
        ("spoof_flag_rate_on_null", "spoofing flag rate on null scenarios"),
        ("jam_flag_rate_on_null", "jamming flag rate on null scenarios"),
    ):
        d = held.inj[k]
        L.append(f"- Held-out {lab}: {f(d['rate'])} ({d['k']}/{d['n']}; Wilson {f(d['ci_lo'])} to {f(d['ci_hi'])})")
    fe = held.inj["false_events"]
    L += [
        f"- Held-out events that matched no injected scenario in scenario runs: {fe['n_unmatched_events']} of {fe['n_events']} (medium or high confidence: {fe['unmatched_medium_or_high']}). "
        "These include real background events on the day, which are removed from scoring only if their id is in the un-injected run.",
        "",
    ]
    L += ["## 4. Coverage model failure test", ""]
    cs = held.covsum
    L += [
        "Unit: (cell, 3 h slot, en route) on a held-out day; enough = at least 5 aircraft.",
        "",
        "| Class | Units | P(enough) | Wilson 95% |",
        "|---|---|---|---|",
    ]
    for c in ("covered", "marginal", "no_coverage"):
        L.append(f"| {c} | {cs[c]['n_units']} | {f(cs[c]['p_enough'])} | {f(cs[c]['ci_lo'])} to {f(cs[c]['ci_hi'])} |")
    L += [
        "",
        f"- False coverage (class covered, not enough aircraft): **{f(cs['false_coverage_rate'])}**, day bootstrap {cs['false_coverage_ci_boot_days']}.",
        f"- Missed coverage (class no_coverage, enough aircraft): **{f(cs['missed_coverage_rate'])}**, day bootstrap {cs['missed_coverage_ci_boot_days']}.",
    ]
    if "covered_not_enough_status" in cs:
        L.append(
            f"- What the system finally reports for the {cs['covered_not_enough_total']} covered units that lacked data: {cs['covered_not_enough_status']}. "
            f"Units reported `ok` without enough aircraft: {cs['wrongly_ok']} (must be 0 by construction)."
        )
    L += [
        "",
        "Per day false coverage (class level):",
        "",
        "| Day | Covered units | False coverage | Missed coverage |",
        "|---|---|---|---|",
    ]
    for r in cs["per_day"]:
        L.append(f"| {r['day']} | {int(r['n_covered'])} | {f(r['false_coverage'])} | {f(r['missed_coverage'])} |")
    L += ["", "By slot of day (covered units):", "", "| Slot (UTC hours) | n | False coverage |", "|---|---|---|"]
    for s, v in sorted(cs["covered_by_slot"].items(), key=lambda kv: int(kv[0])):
        L.append(f"| {int(s) * 3:02d} to {int(s) * 3 + 3:02d} | {v['n']} | {f(v['false_coverage'])} |")
    nb = cs["next_bucket"]
    L += [
        "",
        "P(enough on the next bucket) by the status now: "
        + "; ".join(f"{k} {f(v['p_enough_next'])} (n={v['n']})" for k, v in nb.items())
        + ".",
        "",
    ]
    th = held.thin
    L += [
        "Synthetic receiver loss (random thinning of real days; SYNTHETIC for fractions below 1): share of covered units by final status.",
        "",
        "| Aircraft kept | ok | insufficient | coverage_lost |",
        "|---|---|---|---|",
    ]
    for kf, g in th.groupby("keep_fraction", sort=False):
        sh = g.groupby("status")["share"].mean()
        L.append(f"| {kf} | {f(sh.get('ok'))} | {f(sh.get('insufficient'))} | {f(sh.get('coverage_lost'))} |")
    L += [
        "",
        "## 5. Real days: events (OBSERVED)",
        "",
        "| Day | Split | Events | Jamming-like | Spoofing-like | Both | Uncertain |",
        "|---|---|---|---|---|---|---|",
    ]
    for sp, name in ((dev, "dev"), (held, "held_out")):
        for d in sp.days:
            e = sp.ev[sp.ev.day == d]
            L.append(
                f"| {d} | {name} | {len(e)} | {(e.kind == 'jamming_like').sum()} | {(e.kind == 'spoofing_like').sum()} | {(e.kind == 'both').sum()} | {int(e.label_uncertain.sum())} |"
            )
    L += [
        "",
        "### Documented incident windows used as weak labels",
        "",
        "Public reports for 2026-02-28, 2026-03-02, 2026-03-07 and 2026-03-13 are context only. They are not ground truth and are not used for tuning. "
        "Events found on those days (no attribution is made):",
        "",
        "| Day | Split | Events | Highest confidence | Largest event (aircraft) |",
        "|---|---|---|---|---|",
    ]
    order = {"low": 0, "medium": 1, "high": 2}
    for d in sorted(REPORT_DAYS + DEV_INCIDENT_DAYS):
        sp, name = (held, "held_out") if d in held.days else (dev, "dev")
        e = sp.ev[sp.ev.day == d]
        top = max(e.confidence, key=lambda c: order[c]) if len(e) else "none"
        L.append(f"| {d} | {name} | {len(e)} | {top} | {int(e.n_aircraft.max()) if len(e) else 0} |")
    if daily is not None:
        L += [
            "",
            "### Region wide degraded share per day (OBSERVED)",
            "",
            "Sum over testable (`ok`) en route cell-buckets of aircraft counts, so one aircraft can count in several cells. This is the plain level "
            "indicator; event counts are relative to a pooled baseline and understate a region wide change.",
            "",
            "| Day | Split | Cell-bucket aircraft (ok) | Degraded | Share | Wilson 95% |",
            "|---|---|---|---|---|---|",
        ]
        for r in daily.itertuples():
            L.append(f"| {r.day} | {r.split} | {int(r.n)} | {int(r.k)} | {f(r.share)} | {f(r.ci_lo)} to {f(r.ci_hi)} |")
    if regime:
        L += [
            "",
            "### Same aircraft, early versus late development days (OBSERVED, dev only)",
            "",
            f"From {regime['late_days'][0]} the degraded share of en route samples rises sharply and traffic falls. For the {regime['n_aircraft_in_both_periods']} aircraft seen "
            f"with at least 50 samples in both periods, their degraded sample share rose from {f(regime['same_aircraft_sample_share_early'])} to {f(regime['same_aircraft_sample_share_late'])} "
            f"(median paired change {f(regime['paired_diff_median'])}). So the change is not only a different mix of aircraft. "
            "The cause cannot be identified from this data and no cause is asserted here.",
            "",
        ]
    if ingest is not None:
        L += ["### Daily volume", "", "| Day | Rows | Aircraft |", "|---|---|---|"]
        for r in ingest.sort_values("day").itertuples():
            L.append(f"| {r.day} | {r.rows} | {r.aircraft} |")
        L.append("")
    if dev.sens:
        L += [
            "## 6. Sensitivity (development days only)",
            "",
            "| Setting | Events | Change vs default | Baseline events kept (Jaccard >= 0.5) |",
            "|---|---|---|---|",
        ]
        for k, v in dev.sens["settings"].items():
            L.append(f"| {k} | {v['n_events']} | {v['abs_change_vs_default']} | {f(v['share_kept'])} |")
        dd = dev.sens["day_to_day"]
        L += [
            "",
            f"Day to day: mean {f(dd['mean'], 2)} events per day, std {f(dd['std'], 2)}, coefficient of variation {f(dd['cv'], 2)}.",
            "",
        ]
    L += ["## 7. Where it fails (derived from the numbers above)", ""]
    for t in ("easy", "medium", "hard", "random"):
        r = rate_row(held.scen[(held.scen.kind == "jam_only") & (held.scen.tier == t)], "jam_detected")
        if r["rate"] < 0.5:
            L.append(f"- Jamming-like scenarios of tier `{t}` are found less than half the time ({f(r['rate'])}).")
    r12 = rate_row(held.scen[(held.scen.kind == "spoof_jump") & held.scen.n_spoofed.isin([1, 2])], "spoof_detected")
    L.append(
        f"- Spoofing of one or two aircraft is invisible by design (recall {f(r12['rate'])}); at least three aircraft are needed."
    )
    if cs["false_coverage_rate"] > 0.10:
        L.append(
            f"- The coverage class claims `covered` where fewer than 5 aircraft appear {f(cs['false_coverage_rate'])} of the time on held-out days; "
            "per day table shows where."
        )
    L.append(
        f"- Misses against my own pre-registered predictions: {', '.join(r['id'] for r in rows if r['hit'] is False) or 'none'}."
    )
    L.append("")
    return "\n".join(L)


def headline(held: Split, rows: list[dict]) -> dict:
    res = []

    def add(metric, scen, r, extra=""):
        res.append({"metric": metric, "scenario": scen, "value": None if math.isnan(r["rate"]) else round(r["rate"], 4),
                    "ci_lo": round(r["lo"], 4), "ci_hi": round(r["hi"], 4), "n": r["n"]})  # fmt: skip

    j = held.scen[held.scen.kind == "jam_only"]
    for t in ("easy", "medium", "hard"):
        add(f"jamming_recall_{t}", "synthetic_injection_held_out_days", rate_row(j[j.tier == t], "jam_detected"))
    sj = held.scen[held.scen.kind == "spoof_jump"]
    add(
        "spoofing_recall_3plus_aircraft",
        "synthetic_injection_held_out_days",
        rate_row(sj[sj.n_spoofed >= 3], "spoof_detected"),
    )
    cs = held.covsum["covered"]
    res.append(
        {
            "metric": "false_coverage_rate",
            "scenario": "observed_held_out_days",
            "value": round(1 - cs["p_enough"], 4),
            "ci_lo": round(1 - cs["ci_hi"], 4),
            "ci_hi": round(1 - cs["ci_lo"], 4),
            "n": cs["n_units"],
        }
    )
    return {
        "results": res,
        "note": "Precision-style and recall numbers marked synthetic_injection are measured on SYNTHETIC scenarios injected into real held-out traffic; they are not accuracy against real interference.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", type=Path, default=ROOT / "results/dev")
    ap.add_argument("--held", type=Path, default=ROOT / "results/held_out")
    ap.add_argument("--interim", type=Path, default=ROOT / "data/interim")
    ap.add_argument("--daily", type=Path, default=ROOT / "results/daily_region.csv")
    a = ap.parse_args()
    dev, held = Split(a.dev), Split(a.held)
    if not (dev.ok and held.ok):
        raise SystemExit("need results/dev and results/held_out")
    freeze = json.loads((ROOT / "results/FREEZE.json").read_text()) if (ROOT / "results/FREEZE.json").exists() else None
    ingest = None
    mp = a.interim / "manifest.jsonl"
    if mp.exists():
        recs = {}
        for line in mp.read_text().splitlines():
            r = json.loads(line)
            if r.get("status") == "complete":
                recs[r["day"]] = {"day": r["day"], "rows": r["rows"], "aircraft": r["aircraft"]}
        ingest = pd.DataFrame(recs.values())
        ingest[ingest["day"].isin(held.days + dev.days)].to_csv(ROOT / "results/ingest_days.csv", index=False)
    elif (ROOT / "results/ingest_days.csv").exists():
        ingest = pd.read_csv(ROOT / "results/ingest_days.csv")
    rows = evaluate(held, dev, ingest)
    regime = json.loads((a.dev / "regime_check.json").read_text()) if (a.dev / "regime_check.json").exists() else None
    daily = pd.read_csv(a.daily) if a.daily.exists() else None
    (ROOT / "docs/PREDICTIONS_RESULTS.md").write_text(predictions_md(rows, freeze, held), encoding="utf-8")
    (ROOT / "docs/VALIDATION.md").write_text(
        validation_md(held, dev, freeze, rows, regime, daily, ingest), encoding="utf-8"
    )
    (ROOT / "results/headline.json").write_text(json.dumps(headline(held, rows), indent=1))
    (ROOT / "results/predictions_scored.json").write_text(json.dumps(rows, indent=1, default=str))
    print("written")


if __name__ == "__main__":
    main()
