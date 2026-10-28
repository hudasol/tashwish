"""Generate docs/research/PREDICTIONS_RESULTS.md, docs/research/VALIDATION.md and results/headline.json from result files.

  python scripts/make_results_docs.py [--dev results/dev] [--held results/held_out] [--interim data/interim]

Nothing in the generated files is typed by hand. Preregistered pass criteria are copied from docs/PREDICTIONS.md and
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


def load_regimes() -> pd.DataFrame | None:
    p = ROOT / "results/regimes.csv"
    return pd.read_csv(p) if p.exists() else None


def with_regimes(scen: pd.DataFrame, reg: pd.DataFrame | None) -> pd.DataFrame:
    """Attach the traffic and degraded labels of the scored day to each scenario row."""
    if reg is None:
        return scen.assign(traffic="unknown", degraded="unknown")
    return scen.merge(reg[["day", "traffic", "degraded"]], on="day", how="left")


def regime_false_coverage(sp, regimes: pd.DataFrame) -> dict:
    """Pooled class level false coverage by traffic regime, with a day bootstrap inside each regime."""
    out = {}
    cov = sp.cov.merge(regimes[["day", "traffic"]], on="day", how="left")
    c = cov[cov["coverage_class"] == "covered"].assign(fail=lambda d: (~d["enough"]).astype(float))
    for tr, g in c.groupby("traffic"):
        days = g["day"].nunique()
        lo, hi = cluster_bootstrap_rate(g, "fail") if days >= 2 else (float("nan"), float("nan"))
        out[tr] = {"rate": float(g["fail"].mean()), "units": len(g), "days": days, "lo": lo, "hi": hi}
    return out


def pooled_false_coverage(sp) -> dict:
    """Class level false coverage pooled across regimes, with a day bootstrap interval (no Wilson interval on pooled units)."""
    c = sp.cov[sp.cov["coverage_class"] == "covered"].assign(fail=lambda d: (~d["enough"]).astype(float))
    lo, hi = cluster_bootstrap_rate(c, "fail")
    return {"rate": float(c["fail"].mean()), "units": len(c), "days": c["day"].nunique(), "lo": lo, "hi": hi}


def f(x, d=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def rnd(x, d=3):
    """Round a float (or a list of floats) for display; NaN becomes None."""
    if isinstance(x, (list, tuple)):
        return [rnd(v, d) for v in x]
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), d)


def span(lo, hi) -> str:
    return f"{f(lo)} to {f(hi)}"


def rate_row(df: pd.DataFrame, col: str) -> dict:
    n, k = len(df), int(df[col].sum()) if len(df) else 0
    lo, hi = wilson_interval(k, n) if n else (float("nan"), float("nan"))
    days = int(df["day"].nunique()) if n and "day" in df else 0
    blo, bhi = (
        cluster_bootstrap_rate(df.assign(**{col: df[col].astype(float)}), col)
        if n and days >= 2
        else (float("nan"), float("nan"))
    )
    return {
        "days": days,
        "n": n,
        "k": k,
        "rate": k / n if n else float("nan"),
        "lo": float(lo),
        "hi": float(hi),
        "blo": blo,
        "bhi": bhi,
    }


def fmt_rate(r: dict) -> str:
    return (
        f"{f(r['rate'])} ({r['k']}/{r['n']}; day bootstrap {span(r['blo'], r['bhi'])}; Wilson {span(r['lo'], r['hi'])})"
    )


class Split:
    def __init__(self, path: Path):
        self.path = path
        self.ok = (path / "synthetic_scenarios.csv").exists()
        if not self.ok:
            return
        self.scen = pd.read_csv(path / "synthetic_scenarios.csv", keep_default_na=False, na_values=[""])
        self.ev = pd.read_csv(path / "observed_events.csv")
        self.cov = pd.read_csv(path / "observed_coverage_outcomes.csv")
        self.covsum = json.loads((path / "observed_coverage_summary.json").read_text(encoding="utf-8"))
        self.inj = json.loads((path / "synthetic_injection_summary.json").read_text(encoding="utf-8"))
        self.meta = json.loads((path / "run_meta.json").read_text(encoding="utf-8"))
        self.daily = pd.read_csv(path / "observed_daily_event_counts.csv")
        self.thin = pd.read_csv(path / "synthetic_thinning.csv")
        self.sev = pd.read_csv(path / "synthetic_scenario_events.csv")
        self.days = self.meta["score_days"]
        sp = path / "sensitivity_summary.json"
        self.sens = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else None


def jam_subsets(s: pd.DataFrame) -> dict[str, pd.DataFrame]:
    j = s[s["kind"] == "jam_only"]
    return {
        "J1": j[(j.intensity == 0.8) & (j.area >= 3) & (j.duration >= 2) & (j.traffic_median >= 10)],
        "J2": j[(j.intensity == 0.5) & (j.area == 3) & (j.duration == 2) & (j.traffic_median >= 10)],
        "J3": j[(j.area == 1) & (j.duration == 1) & ((j.intensity == 0.3) | (j.traffic_median < 8))],
    }


def monotone(vals: list[float]) -> bool:
    return all(b >= a - 1e-12 for a, b in zip(vals, vals[1:], strict=False))


AXIS_LABEL = {
    "intensity": "intensity",
    "area": "area",
    "duration": "duration",
    "tb": "traffic bin (0 under 5, 1 for 5 to 9, 2 for 10 or more)",
}


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
            f"{AXIS_LABEL[ax]}: "
            + ", ".join(f"{lv}={f(r['rate'], 2)} (n={r['n']})" for lv, r in zip(levels, rs, strict=True))
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
            + str(all(pooled))
            + ".",
        )
    return ok_all, txt


# Data class of each preregistered row. SYNTHETIC: injected scenarios, not accuracy against real interference.
# OBSERVED: a count or rate on real days. MODEL: a property of the coverage model, the regime labels or the detector
# settings, checked on real days.
DATA_CLASS = {
    "D1": "OBSERVED", "D2": "OBSERVED",
    "C1": "MODEL", "C2": "MODEL", "C3": "MODEL", "C4": "MODEL",
    "J1": "SYNTHETIC", "J2": "SYNTHETIC", "J3": "SYNTHETIC", "J4": "SYNTHETIC", "J5": "OBSERVED", "J6": "SYNTHETIC", "J3t": "SYNTHETIC",
    "S1": "SYNTHETIC", "S2": "SYNTHETIC", "S3": "SYNTHETIC", "S4": "SYNTHETIC", "S5": "SYNTHETIC",
    "R1": "OBSERVED", "R2": "OBSERVED", "R3": "OBSERVED", "R4": "OBSERVED",
    "X1": "MODEL", "X2": "MODEL", "X3": "MODEL",
    "A1": "MODEL", "A2": "MODEL", "A3": "OBSERVED", "A4": "SYNTHETIC",
}  # fmt: skip


def at_bar(value: float, bar: float) -> str:
    return ", at threshold" if abs(value - bar) < 1e-9 else ""


def evaluate(held: Split, dev: Split, ingest: pd.DataFrame | None) -> list[dict]:
    out = []

    def add(pid, claim, crit, observed, hit, conf, note="", short=None, scored=True):
        out.append(
            {"id": pid, "data_class": DATA_CLASS.get(pid, "OBSERVED"), "claim": claim, "criterion": crit,
             "observed": observed, "short": short or observed, "hit": hit, "conf": conf, "note": note, "scored": scored}
        )  # fmt: skip

    # D
    if ingest is not None and held.ok:
        hd = ingest[ingest["day"].isin(held.days)]
        add(
            "D1",
            "Every held out day ingests",
            "14 of 14 complete",
            f"{len(hd)} of {len(held.days)}",
            len(hd) == len(held.days) == 14,
            0.90,
        )
        inrange = hd[(hd.rows.between(1.2e6, 2.6e6)) & (hd.aircraft.between(1600, 2800))]
        bad = hd[~hd["day"].isin(inrange["day"])]
        add("D2", "Held out volume resembles the two days I saw", "every day 1.2 to 2.6 M rows and 1,600 to 2,800 aircraft",
            f"{len(inrange)} of {len(hd)} in range; outside: " + ", ".join(f"{r.day} ({r.rows / 1e6:.2f} M rows, {r.aircraft} aircraft)" for r in bad.itertuples()),
            len(inrange) == len(hd), 0.80, short=f"{len(inrange)} of {len(hd)} days in range")  # fmt: skip
    # C
    cs = held.covsum
    pc, pn = cs["covered"]["p_enough"], cs["no_coverage"]["p_enough"]
    add("C1", "Covered cells mostly enough on a new day", "P(enough given covered) >= 0.70",
        f"{f(pc)} pooled across regimes (day bootstrap of the failure rate {span(*cs['false_coverage_ci_boot_days'])})", pc >= 0.70, 0.65)  # fmt: skip
    add("C2", "no_coverage rarely enough", "P(enough given no_coverage) <= 0.15", f"{f(pn)} (Wilson {span(cs['no_coverage']['ci_lo'], cs['no_coverage']['ci_hi'])}; pooled across regimes)", pn <= 0.15, 0.70)  # fmt: skip
    fc = 1 - pc
    sl = cs["covered_by_slot"]
    early = np.mean([sl[str(s)]["false_coverage"] for s in (0, 1) if str(s) in sl])
    mid = np.mean([sl[str(s)]["false_coverage"] for s in (3, 4, 5) if str(s) in sl])
    add("C3", "Some false coverage, mostly at low traffic hours", "0.10 <= P(not enough given covered) <= 0.35 and rate in slots 0,1 > rate in slots 3 to 5",
        f"failure rate {f(fc)} pooled across regimes; slots 0,1 mean {f(early)}; slots 3 to 5 mean {f(mid)}", (0.10 <= fc <= 0.35) and early > mid, 0.55)  # fmt: skip
    nb = cs["next_bucket"]
    add("C4", "coverage_lost carries information", "P(enough next given coverage_lost) < P(enough next given ok)",
        f"coverage_lost {f(nb['coverage_lost']['p_enough_next'])} (n={nb['coverage_lost']['n']}) versus ok {f(nb['ok']['p_enough_next'])} (n={nb['ok']['n']})",
        nb["coverage_lost"]["p_enough_next"] < nb["ok"]["p_enough_next"], 0.60)  # fmt: skip
    # J
    subs = jam_subsets(held.scen)
    r1, r2, r3 = (rate_row(subs[k], "jam_detected") for k in ("J1", "J2", "J3"))
    tj = held.scen[held.scen.kind == "jam_only"]
    tier_r = {t: rate_row(tj[tj.tier == t], "jam_detected") for t in ("easy", "medium", "hard")}
    ptr = (
        f" Criterion subset only; the tier recall over all scenarios of the tier is {f(tier_r['easy']['rate'])}, "
        f"{f(tier_r['medium']['rate'])} and {f(tier_r['hard']['rate'])} for easy, medium and hard (VALIDATION.md section 2)."
    )
    add("J1", "Criterion subset of easy scenarios found", "recall >= 0.95", fmt_rate(r1), r1["rate"] >= 0.95, 0.80,
        "Criterion subset: intensity 0.8, 3 or more cells, 2 or more buckets, median traffic 10 or more." + ptr)  # fmt: skip
    add("J2", "Criterion subset of medium scenarios mostly found", "0.70 <= recall <= 0.95", fmt_rate(r2), 0.70 <= r2["rate"] <= 0.95, 0.55,
        "Criterion subset: intensity 0.5, 3 cells, 2 buckets, median traffic 10 or more." + ptr)  # fmt: skip
    add("J3", "Criterion subset of hard scenarios mostly missed", "recall <= 0.50", fmt_rate(r3), r3["rate"] <= 0.50, 0.75,
        "Criterion subset: 1 cell, 1 bucket, intensity 0.3 or median traffic below 8, all scenarios (as worded)." + ptr)  # fmt: skip
    j3t = subs["J3"][subs["J3"].traffic_median >= 5]
    r3t = rate_row(j3t, "jam_detected")
    add("J3t", "J3 on testable scenarios (median traffic 5 or more)", "recall <= 0.50", fmt_rate(r3t), r3t["rate"] <= 0.50, 0.75,
        "Reported as promised in the amendment; not part of the verdict or the Brier score.", scored=False)  # fmt: skip
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
    add("J5", "Few medium or high events per uninjected held out day", "<= 0.5 per day on average",
        f"{f(per_day, 2)} per day{at_bar(per_day, 0.5)} ({len(mh)} events over {len(held.days)} days)", per_day <= 0.5, 0.55)  # fmt: skip
    hit6, txt6 = j6(held.scen)
    add("J6", "Recall rises with each axis", "non decreasing along each axis with the others at medium", txt6, hit6, 0.85,
        "Deviation: cells at fixed medium values are small; see the text." if hit6 is None else "",
        short="Not evaluable as worded (cells under 10 scenarios); pooled marginals monotone")  # fmt: skip
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
        "mean events per day on report days > mean on the other 12",
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
        f"{int((ev.lat > 26).sum())} of {len(ev)} events north of 26 N ({f(north)})",
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
            "Implemented settings: gate 0.15 and 0.25 (about 25 percent either way), min aircraft 4 and 6 (20 percent either way), q 0.01 and 0.10 (wider than 25 percent). Development days only.")  # fmt: skip
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
            f"minimum share kept over the threshold settings: {f(share)}", share >= 0.70, 0.60, "Development days only.")  # fmt: skip
        cv = dev.sens["day_to_day"]["cv"]
        add("X3", "Day to day variation is large", "standard deviation over mean of daily event count > 0.5", f"{f(cv)} (mean {f(dev.sens['day_to_day']['mean'], 2)}, std {f(dev.sens['day_to_day']['std'], 2)})", cv > 0.5, 0.60, "Development days only.")  # fmt: skip
    reg = load_regimes()
    notes = {
        "J4": "Amendment: this is the first bucket detection rate; delay is clipped at zero on a bucket grid.",
        "J5": "Amendment: this is the real event rate of medium or high confidence events per held out day; such events are not necessarily false.",
        "S2": "Amendment: pipeline separation check, true close to by construction (each injection changes one input of one detector).",
        "S3": "Amendment: pipeline separation check, true close to by construction.",
        "S4": "Amendment: the committed label accuracy part is a pipeline separation check; uncertain share is per detected scenario event.",
        "C4": "Amendment: close to tautological, because coverage_lost requires too few aircraft now.",
    }
    if reg is not None:
        rfc = regime_false_coverage(held, reg)
        txt = "; ".join(
            f"traffic {k}: {f(v['rate'])} over {v['units']} units, {v['days']} days, day bootstrap {f(v['lo'])} to {f(v['hi'])}"
            for k, v in rfc.items()
        )
        for pid in ("C1", "C3"):
            notes[pid] = "Amendment, by traffic regime (class level false coverage): " + txt + "."
        hreg = reg[reg["split"] == "held_out"].set_index("day")
        evh = held.ev.merge(reg[["day", "degraded"]], on="day", how="left")
        per_reg = []
        for dg, days in hreg.groupby("degraded").groups.items():
            e = evh[evh["day"].isin(days)]
            per_reg.append(f"degraded {dg}: {len(e)} events over {len(days)} days ({f(len(e) / len(days), 2)} per day)")
        for pid in ("R2", "R3", "R4"):
            notes[pid] = "Amendment, events by degraded regime: " + "; ".join(per_reg) + "."
        # A1
        feb = [d for d in held.days if d <= "2026-02-26"]
        late = [d for d in ("2026-03-03", "2026-03-08", "2026-03-10", "2026-03-13") if d in hreg.index]
        okf = all(hreg.loc[d, "traffic"] == "normal" and hreg.loc[d, "degraded"] == "baseline" for d in feb)
        okl = all(hreg.loc[d, "traffic"] == "reduced" and hreg.loc[d, "degraded"] == "elevated" for d in late)
        add("A1", "Regime labels follow the development calendar", "held out days to 02-26 normal and baseline; 03-03, 03-08, 03-10, 03-13 reduced and elevated",
            f"February days matching: {sum(hreg.loc[d, 'traffic'] == 'normal' and hreg.loc[d, 'degraded'] == 'baseline' for d in feb)} of {len(feb)}; March days matching: {sum(hreg.loc[d, 'traffic'] == 'reduced' and hreg.loc[d, 'degraded'] == 'elevated' for d in late)} of {len(late)}. 02-28: {hreg.loc['2026-02-28', 'traffic']} traffic and {hreg.loc['2026-02-28', 'degraded']}, 03-01: {hreg.loc['2026-03-01', 'traffic']} traffic and {hreg.loc['2026-03-01', 'degraded']} (not predicted)",
            okf and okl, 0.70, short="All predicted days match")  # fmt: skip
        ok_all = all(v["rate"] <= 0.10 for v in rfc.values())
        add("A2", "Within regime, covered cells rarely lack data", "class level false coverage <= 0.10 in each traffic regime",
            txt, ok_all, 0.60, short="; ".join(f"{k} {f(v['rate'])}" for k, v in rfc.items()))  # fmt: skip
        bl = hreg[hreg["degraded"] == "baseline"].index
        mhb = held.ev[held.ev.day.isin(bl) & held.ev.confidence.isin(["medium", "high"])]
        rate_b = len(mhb) / max(len(bl), 1)
        add("A3", "Few medium or high events on degraded baseline days", "<= 0.5 per day on average",
            f"{f(rate_b, 2)} per day{at_bar(rate_b, 0.5)} ({len(mhb)} events over {len(bl)} days)", rate_b <= 0.5, 0.50)  # fmt: skip
    ej = held.scen[(held.scen.kind == "jam_only") & (held.scen.tier == "easy")]
    ra = rate_row(ej, "jam_detected")
    add(
        "A4",
        "Easy tier recall not lowered by the new placement rule",
        "easy tier recall >= 0.90",
        fmt_rate(ra),
        ra["rate"] >= 0.90,
        0.75,
    )
    for r in out:
        if r["id"] in notes:
            r["note"] = (r["note"] + " " + notes[r["id"]]).strip()
    return out


def cell(x) -> str:
    """Make text safe for a Markdown table cell."""
    return str(x).replace("|", "/").replace("\n", " ")


def predictions_md(rows: list[dict], freeze: dict | None, held: Split) -> str:
    counted = [r for r in rows if r.get("scored", True)]
    hits = [r for r in counted if r["hit"] is True]
    scored = [r for r in counted if r["hit"] is not None]
    brier = np.mean([(r["conf"] - float(r["hit"])) ** 2 for r in scored]) if scored else float("nan")
    L = [
        "# Preregistered predictions: results",
        "",
        "Generated by `scripts/make_results_docs.py` from `results/held_out` and `results/dev`. The prediction file `docs/PREDICTIONS.md` was not edited.",
        f"Frozen code commit: `{(freeze or {}).get('commit', 'unknown')}`; held out run finished {held.meta.get('finished', 'unknown')}.",
        "",
        "**Rows marked SYNTHETIC are tests on injected scenarios, not accuracy against real interference.** "
        "Rows marked OBSERVED are counts or rates on real days. Rows marked MODEL check a property of the coverage model, the regime labels or the "
        "detector settings on real days. The data class column is added by the generator and is not part of the preregistered text.",
        "",
        f"**{len(hits)} HIT, {len(scored) - len(hits)} MISS** out of {len(scored)} evaluated, {len(counted) - len(scored)} not evaluable as worded. "
        f"Mean Brier score of my stated confidences: {f(brier)} (0 is perfect; 0.25 is the score of always saying 0.5).",
        "",
        "| ID | Data class | Prediction | Pass criterion | Observed | Confidence | Result |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if not r.get("scored", True):
            continue
        res = "HIT" if r["hit"] is True else "MISS" if r["hit"] is False else "NOT EVALUABLE"
        L.append(
            f"| {r['id']} | {r['data_class']} | {cell(r['claim'])} | {cell(r['criterion'])} | {cell(r['short'])} | {r['conf']:.2f} | **{res}** |"
        )
    L += [
        "",
        "Recall figures in rows J1 to J3 are for criterion subsets written in `docs/PREDICTIONS.md`. They differ from the tier recall in "
        "`docs/research/VALIDATION.md` section 2, which uses every scenario of a tier. Values are rounded to three decimals; "
        "a row marked at threshold passed with a value equal to its bar.",
        "",
        "### Reported alongside, not scored",
        "",
    ]
    for r in rows:
        if not r.get("scored", True):
            res = "meets the bar" if r["hit"] else "does not meet the bar"
            L.append(
                f"- {r['id']} ({r['data_class']}): {r['claim']}. Observed {cell(r['observed'])}; {res}. {r['note']}"
            )
    L += ["", "### Notes on rows", ""]
    for r in rows:
        if r.get("scored", True) and (r["note"] or r["short"] != r["observed"]):
            body = cell(r["observed"]) if r["short"] != r["observed"] else ""
            L.append(f"- **{r['id']}**: {(body + ' ' + r['note']).strip()}")
    L += ["", "Misses are not explained away here; the discussion is in `docs/research/VALIDATION.md` section 7.", ""]
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
    L = [f"| {label} | n | recall (day bootstrap 95%) |", "|---|---|---|"]
    for v, d in j.groupby(col):
        r = rate_row(d, "jam_detected")
        L.append(f"| {v} | {r['n']} | {f(r['rate'])} ({r['k']}/{r['n']}; {span(r['blo'], r['bhi'])}) |")
    return L + [""]


def confusion_md(inj: dict, key: str, title: str) -> list[str]:
    c = inj[key]
    cols = c["columns"]
    L = [
        f"**{title}** (rows: what was injected, columns: what the system said; a trailing question mark marks an uncertain call, and none means no event)",
        "",
        "| Injected | " + " | ".join(cols) + " |",
        "|---|" + "---|" * len(cols),
    ]
    for k, v in c["rows"].items():
        L.append(f"| {k} | " + " | ".join(str(x) for x in v) + " |")
    return L + [""]


REGIME_SETS = (
    ("pooled across regimes", None, None),
    ("traffic normal", "traffic", "normal"),
    ("traffic reduced", "traffic", "reduced"),
    ("degraded baseline", "degraded", "baseline"),
    ("degraded elevated", "degraded", "elevated"),
)


def regime_subsets(df: pd.DataFrame):
    for name, col, val in REGIME_SETS:
        yield name, df if col is None else df[df[col] == val]


def regime_recall_table(groups: list[tuple[str, pd.DataFrame]], col: str, first: str) -> list[str]:
    """Recall of `col` for each group, pooled across regimes and then by traffic and degraded regime (day bootstrap)."""
    L = [f"| {first} | Regime | Days | Scenarios | Recall | Day bootstrap 95% |", "|---|---|---|---|---|---|"]
    for gname, g in groups:
        for rname, d in regime_subsets(g):
            r = rate_row(d, col)
            L.append(
                f"| {gname} | {rname} | {r['days']} | {r['n']} | {f(r['rate'])} ({r['k']}/{r['n']}) | {span(r['blo'], r['bhi'])} |"
            )
    return L + [""]


def study_facts(held: Split, dev: Split, reg: pd.DataFrame | None, ingest: pd.DataFrame | None) -> dict:
    """Numbers quoted in the summary box and the discussion; all computed from result files."""
    out: dict = {}
    if reg is not None:
        feb = reg[reg["day"] <= "2026-02-27"]
        mar = reg[reg["day"] >= "2026-03-01"]
        out["share_feb"] = (feb["share"].min(), feb["share"].max())
        out["share_mar"] = (mar["share"].min(), mar["share"].max())
    if ingest is not None:
        early = ingest[ingest["day"] <= "2026-02-27"]
        late = ingest[ingest["day"] >= "2026-03-03"]
        out["ac_early"], out["ac_late"] = float(early["aircraft"].median()), float(late["aircraft"].median())
    ev = pd.concat([dev.ev, held.ev])
    sp = ev[ev["kind"].isin(["spoofing_like", "both"])]
    out["n_events"], out["n_uncertain"] = len(ev), int(ev["label_uncertain"].sum())
    out["n_spoofish"], out["n_min3"] = len(sp), int((sp["n_spoof_aircraft"] == 3).sum())
    return out


GLOSSARY = [
    (
        "SYNTHETIC",
        "A test in which known degradation or displaced positions are injected into real traffic. It measures whether the detector finds what was injected. It is not accuracy against real interference.",
    ),
    ("OBSERVED", "A count or rate on real days, with nothing injected."),
    ("MODEL", "A property of the coverage model, the regime labels or the detector settings, checked on real days."),
    (
        "ADS-B, GNSS",
        "ADS-B is the broadcast in which aircraft report their own position. GNSS is satellite navigation, the source of that position.",
    ),
    (
        "NIC, NACp",
        "ADS-B fields in which an aircraft states how good its own position is. Low values count as degraded accuracy here.",
    ),
    ("Cell bucket", "One grid cell during one 3 hour UTC bucket. All counts are per cell bucket."),
    ("Held out day", "A day scored once, after the freeze, and never used for fitting or tuning."),
    ("Development day", "A day used to design the system, fit baselines and choose thresholds."),
    (
        "Tier",
        "Difficulty class of an injected jamming scenario. Easy: intensity 0.8, 3 or 7 cells, 2 or 3 buckets, high traffic. Medium: intensity 0.5, 3 cells, 2 buckets, high traffic. Hard: intensity 0.3 or 0.5, 1 cell, 1 bucket, mostly low or mid traffic. Random: intensity, area, duration and traffic drawn at random.",
    ),
    (
        "Intensity",
        "Target degraded share: the share of aircraft in the target cell buckets made to report degraded accuracy (0.3, 0.5 or 0.8).",
    ),
    ("Area", "Number of grid cells an injected scenario covers (1, 3 or 7)."),
    ("Duration", "Number of consecutive 3 hour buckets an injected scenario lasts (1, 2 or 3)."),
    (
        "Traffic bin",
        "Median aircraft per target cell bucket: low is 3 to 4, mid is 5 to 9, high is 10 or more, none is a median outside those bins.",
    ),
    (
        "Recall",
        "The share of injected scenarios that the detector found. Found means at least one event overlaps the scenario in space and time.",
    ),
    (
        "Traffic regime",
        "Normal when the scored day has at least half of the reference en route aircraft per cell bucket (the reference is the development median); reduced otherwise.",
    ),
    ("Degraded regime", "Baseline when the scored day's tested degraded share is below 0.05; elevated otherwise."),
    (
        "Tested degraded share",
        "Share of aircraft reporting degraded accuracy among cell buckets with at least 5 aircraft.",
    ),
    (
        "Covered, enough",
        "A cell hour the coverage model expects to be seen is class covered. Enough means at least 5 aircraft were present. False coverage is a covered unit with fewer than 5 aircraft.",
    ),
    (
        "Day bootstrap",
        "Interval from resampling whole days, because scenarios and cells within a day share traffic and are not independent. It is the interval to use.",
    ),
    (
        "Wilson interval",
        "Formula interval for a rate that treats every unit as independent. Shown only where marked and not used as an uncertainty statement for pooled units.",
    ),
    (
        "HIT, MISS",
        "A preregistered prediction met, or did not meet, the pass criterion written before any held out result existed.",
    ),
]


def validation_md(
    held: Split,
    dev: Split,
    freeze: dict | None,
    rows: list[dict],
    regime: dict | None,
    daily: pd.DataFrame | None,
    ingest: pd.DataFrame | None,
) -> str:
    reg = load_regimes()
    facts = study_facts(held, dev, reg, ingest)
    sc = with_regimes(held.scen, reg)
    scd = with_regimes(dev.scen, reg)
    jam = sc[sc.kind == "jam_only"]
    sj = sc[sc.kind == "spoof_jump"]
    s3, s12 = sj[sj.n_spoofed >= 3], sj[sj.n_spoofed.isin([1, 2])]
    cs = held.covsum
    rfc = regime_false_coverage(held, reg) if reg is not None else {}
    pooled_fc = pooled_false_coverage(held)

    def rr(df, col="jam_detected"):
        return rate_row(df, col)

    def reg_rate(df, col, tr):
        return rate_row(df[df["traffic"] == tr], col)

    tiers = {t: rr(jam[jam.tier == t]) for t in ("easy", "medium", "hard", "random")}
    tn = {t: reg_rate(jam[jam.tier == t], "jam_detected", "normal") for t in tiers}
    tr_ = {t: reg_rate(jam[jam.tier == t], "jam_detected", "reduced") for t in tiers}
    sp_all, sp_n, sp_r = (
        rr(s3, "spoof_detected"),
        reg_rate(s3, "spoof_detected", "normal"),
        reg_rate(s3, "spoof_detected", "reduced"),
    )
    sp12 = rr(s12, "spoof_detected")
    fe = held.inj["false_events"]
    sev = held.sev
    matched, n_ev = int(sev["matches_scenario"].sum()), len(sev)
    n_runs = fe["n_runs"]
    n_bg = int(sev.groupby(["day", "run"])["n_background_dropped"].max().sum())
    n_inj = int((held.scen.kind != "null").sum())
    mh_all = sev[sev.confidence.isin(["medium", "high"])]
    mh_unmatched = int((~mh_all["matches_scenario"]).sum())
    mh_real = held.ev[held.ev.confidence.isin(["medium", "high"])]

    def rng_(t):
        return f"{f(t[0], 2)} to {f(t[1], 2)}"

    box = [
        "> **What this repository shows**",
        ">",
        "> 1. OBSERVED. Study window 2026-02-07 to 2026-03-13 (35 UTC days of public ADS-B). The data change sharply from about 2026-03-02: "
        + (
            f"median aircraft per day {facts['ac_early']:.0f} before and {facts['ac_late']:.0f} after, tested degraded share {rng_(facts['share_feb'])} in February and {rng_(facts['share_mar'])} from 1 March. "
            if "share_feb" in facts and "ac_early" in facts
            else ""
        )
        + "No cause is identified or asserted.",
        f"> 2. SYNTHETIC. On injected jamming-like scenarios the detector found easy {f(tiers['easy']['rate'], 2)}, medium {f(tiers['medium']['rate'], 2)} and hard {f(tiers['hard']['rate'], 2)} "
        f"(pooled across regimes). By traffic regime, easy was {f(tn['easy']['rate'], 2)} on normal days and {f(tr_['easy']['rate'], 2)} on reduced days; medium {f(tn['medium']['rate'], 2)} and {f(tr_['medium']['rate'], 2)}.",
        f"> 3. SYNTHETIC. Injected spoofing with 3 or more aircraft was found {f(sp_all['rate'], 2)} of the time (normal days {f(sp_n['rate'], 2)}, reduced days {f(sp_r['rate'], 2)}) and with 1 or 2 aircraft {f(sp12['rate'], 2)}.",
        "> 4. OBSERVED. Cells the coverage model called covered lacked enough aircraft "
        + (
            f"{f(rfc['normal']['rate'])} of the time on normal days and {f(rfc['reduced']['rate'])} on reduced days "
            if rfc
            else ""
        )
        + f"(pooled across regimes {f(pooled_fc['rate'])}, which describes neither regime).",
        f"> 5. OBSERVED. {facts['n_events']} events were flagged over the 35 days; {facts['n_uncertain']} have an uncertain label and {facts['n_min3']} of the {facts['n_spoofish']} spoofing-like or both events involve only the minimum 3 aircraft, "
        "so a data error is a live explanation. Events are evidence of degraded position quality, not proof of interference.",
        "",
    ]
    L = [
        "# Validation",
        "",
        "Generated by `scripts/make_results_docs.py` from result files in `results/`. Nothing here is typed by hand. There is no ground truth for GNSS "
        "interference in public ADS-B data, so every number below is either (a) a controlled test on SYNTHETIC injections into real traffic, "
        "(b) a property of the coverage model, or (c) a description of events on real days. Real day events are evidence of degraded position "
        "quality, not proof of interference, and say nothing about who or what caused them. Numbers are rounded to three decimals.",
        "",
    ]
    L += box
    L += ["## Glossary", "", "| Term | Meaning |", "|---|---|"]
    L += [f"| {a} | {cell(b)} |" for a, b in GLOSSARY]
    L += [
        "",
        "## 1. Design and discipline",
        "",
        f"- Study window 2026-02-07 to 2026-03-13 (35 UTC days). Split rule `tashwish-heldout-v1`: {len(freeze['dev_days']) if freeze else '?'} development days and "
        f"{len(freeze['held_out_days']) if freeze else '?'} held out days, listed in `docs/PREDICTIONS.md` before any held out result existed.",
        f"- Frozen at commit `{(freeze or {}).get('commit', 'unknown')}`; held out run executed once ({held.meta.get('finished', '?')}). "
        "Baselines, coverage and the persistent emitter list were fitted on development days only.",
        f"- Held out synthetic scenarios: {len(held.scen)} (runs per day {held.meta['runs_per_day']}); development scenarios: {len(dev.scen)}. "
        "Scenarios within a day share traffic, so intervals marked day bootstrap resample whole days.",
        "- Caveat 1, the regime label uses the scored day's own data. A day is labelled elevated when its own tested degraded share is at least 0.05, "
        "and the baseline used for that day is then chosen by the label. Events on an elevated day are therefore measured against a baseline selected using "
        "the same day's outcome, which mutes events by construction. The rule and its threshold come from development days only, so this is not tuning on held out days. "
        "Read the results on events, R2 to R4 and A3 with this in mind.",
    ]
    if reg is not None:
        sh = reg[(reg["day"] >= "2026-03-01") & (reg["day"] <= "2026-03-07")]["share"].tolist()
        L += [
            "- Caveat 2, held out is not the future. The hash split interleaves development and held out days inside a series whose level changes over time "
            f"(tested degraded share on 1 to 7 March: {', '.join(f(v, 2) for v in sh)}). Development days next to a held out day carry its level into the fitted baseline. "
            "Held out here means never used for fitting or tuning. It does not mean later in time than the training data, and the days are not independent samples.",
        ]
    L += [
        "- Forward chained check: not done. It would fit on days up to 2026-03-02 and score 2026-03-08 to 2026-03-13. It needs a refit and a second run of the system, "
        "and the held out run is single use, so no such number exists in this repository. A forward evaluation on days after the study window is preregistered in `docs/PREDICTIONS_FORWARD.md` and has not been run.",
        "",
        "## 2. Jamming-like detector on synthetic injection (SYNTHETIC)",
        "",
        "Recall is the share of injected scenarios found (see the glossary). The tier rows pool all regimes; the regime table below splits them.",
        "",
    ]
    L += tier_table(held.scen, "Held out days, pooled across regimes") + tier_table(
        dev.scen, "Development days, pooled across regimes (for comparison)"
    )
    L += ["**Recall by tier and regime (held out days, day bootstrap within the regime)**", ""]
    L += regime_recall_table(
        [(t, jam[jam.tier == t]) for t in ("easy", "medium", "hard", "random")], "jam_detected", "Tier"
    )
    L += [
        f"The pooled tier rows describe neither regime well: easy scenarios were found {f(tn['easy']['rate'], 2)} of the time on normal days and {f(tr_['easy']['rate'], 2)} on reduced days, "
        f"medium {f(tn['medium']['rate'], 2)} and {f(tr_['medium']['rate'], 2)}. Traffic regime and degraded regime overlap strongly (every elevated day is a reduced traffic day), so they cannot be separated here. "
        "A day bootstrap interval of 1.000 to 1.000 means every resampled set of days was perfect; it is not a statement of certainty.",
        "",
        "Held out recall by intensity (pooled across regimes):",
        "",
    ] + axis_table(held.scen, "intensity", "Target degraded share")
    L += (
        ["By area in cells (pooled across regimes):", ""]
        + axis_table(held.scen, "area", "Cells")
        + ["By duration in buckets (pooled across regimes):", ""]
        + axis_table(held.scen, "duration", "Buckets")
    )
    L += ["By traffic bin (pooled across regimes):", ""] + axis_table(held.scen, "traffic_bin", "Traffic")
    L += ["By coverage class of the target cells (pooled across regimes):", ""] + axis_table(
        held.scen, "coverage_class", "Coverage class"
    )
    L += ["## 3. Spoofing-like detector and discrimination (SYNTHETIC)", ""]
    L += ["| Displaced aircraft | n | spoofing-like recall (pooled across regimes) |", "|---|---|---|"]
    for v, d in sj.groupby("n_spoofed"):
        r = rate_row(d, "spoof_detected")
        L.append(f"| {v} | {r['n']} | {f(r['rate'])} ({r['k']}/{r['n']}; day bootstrap {span(r['blo'], r['bhi'])}) |")
    L += ["", "**Spoofing-like recall by regime (held out days, day bootstrap within the regime)**", ""]
    L += regime_recall_table(
        [("3 or more aircraft", s3), ("1 or 2 aircraft", s12)], "spoof_detected", "Displaced aircraft"
    )
    L += [
        f"For 3 or more aircraft, recall is {f(sp_n['rate'], 2)} on normal days and {f(sp_r['rate'], 2)} on reduced days, the opposite direction to jamming-like recall. "
        "This is not explained here and no cause was tested.",
        "",
        "| Displacement (km), 3 or more aircraft | n | recall (pooled across regimes) |",
        "|---|---|---|",
    ]
    for v, d in s3.groupby("displacement_km"):
        r = rate_row(d, "spoof_detected")
        L.append(f"| {v:g} | {r['n']} | {f(r['rate'])} ({r['k']}/{r['n']}; day bootstrap {span(r['blo'], r['bhi'])}) |")
    disp = s3.groupby("displacement_km")["spoof_detected"].mean()
    L += [
        "",
        f"Spoofing-like recall falls from {f(disp.iloc[0])} at {disp.index[0]:g} km to {f(disp.iloc[-1])} at {disp.index[-1]:g} km with displacement. The cause is unexplained: "
        "the sequence is not monotone, each row has few scenarios, and displacement is mixed with the number of displaced aircraft, which also drives recall. No mechanism was tested.",
        "",
    ]
    L += confusion_md(held.inj, "confusion_all", "Held out confusion matrix, all scenarios")
    L += confusion_md(dev.inj, "confusion_all", "Development confusion matrix, all scenarios")
    for k, lab in (
        ("spoof_flag_rate_on_null", "spoofing flag rate on null scenarios"),
        ("jam_flag_rate_on_null", "jamming flag rate on null scenarios"),
    ):
        d = held.inj[k]
        L.append(f"- Held out {lab}: {f(d['rate'])} ({d['k']}/{d['n']}; Wilson {span(d['ci_lo'], d['ci_hi'])})")
    unm = sev[~sev["matches_scenario"]]
    by_kind = ", ".join(f"{k} {v}" for k, v in unm["kind"].value_counts().items())
    L += [
        "",
        "**Events in scenario runs and a precision style number (SYNTHETIC)**",
        "",
        f"- Scenario runs: {n_runs}, each with {n_inj / n_runs:.1f} injected scenarios on average. After removing the {n_bg} events whose id is also present in the uninjected run of the same day "
        f"(real background events), {n_ev} events remain, {n_ev / n_runs:.1f} per run.",
        f"- Matched events (overlapping an injected scenario) over all remaining events: **{f(matched / n_ev)}** ({matched}/{n_ev}). This is a share of events in synthetic runs, "
        "not a precision for real interference, because the injected truth is known only here.",
        f"- Events matching no injected scenario: {fe['n_unmatched_events']} of {fe['n_events']} ({by_kind}); of these {fe['unmatched_medium_or_high']} have medium or high confidence, "
        f"that is {fe['unmatched_medium_or_high'] / n_runs:.2f} per run. Without injection the real rate of medium or high events is {len(mh_real) / max(len(held.days), 1):.2f} per day ({len(mh_real)} over {len(held.days)} days).",
        "- Discussion: the unmatched medium or high rate per run is higher than the real background rate, so most unmatched events are not explained by background events that kept their id. "
        "Two readings are possible and the data cannot separate them: an injection changes the id or extent of a real event so that the removal by id misses it, or an injection causes a new event "
        "outside the scenario footprint. Neither reading has been tested. The matched share is a descriptive number for synthetic runs only.",
        "",
    ]
    L += ["## 4. Coverage model failure test", ""]
    L += [
        "Unit: (cell, 3 h slot, en route) on a held out day; enough means at least 5 aircraft.",
        "",
        "| Class | Units | P(enough) | Wilson 95% (units treated as independent) |",
        "|---|---|---|---|",
    ]
    for c in ("covered", "marginal", "no_coverage"):
        L.append(f"| {c} | {cs[c]['n_units']} | {f(cs[c]['p_enough'])} | {span(cs[c]['ci_lo'], cs[c]['ci_hi'])} |")
    L += [
        "",
        "**False coverage by traffic regime (class covered, not enough aircraft; day bootstrap within the regime)**",
        "",
        "| Regime | Days | Covered units | False coverage | Day bootstrap 95% |",
        "|---|---|---|---|---|",
        f"| pooled across regimes | {pooled_fc['days']} | {pooled_fc['units']} | {f(pooled_fc['rate'])} | {span(pooled_fc['lo'], pooled_fc['hi'])} |",
    ]
    for k, v in rfc.items():
        L.append(f"| traffic {k} | {v['days']} | {v['units']} | {f(v['rate'])} | {span(v['lo'], v['hi'])} |")
    L += [
        "",
        "The pooled row is a mixture of two regimes and describes neither. No Wilson interval is shown for pooled units.",
        f"- Missed coverage (class no_coverage, enough aircraft): **{f(cs['missed_coverage_rate'])}**, day bootstrap {span(*cs['missed_coverage_ci_boot_days'])}, pooled across regimes.",
    ]
    if "covered_not_enough_status" in cs:
        cn = cs["covered_not_enough_status"]
        L.append(
            f"- What the system finally reports for the {cs['covered_not_enough_total']} covered units that lacked data: "
            + ", ".join(f"{k} {v}" for k, v in cn.items())
            + f". Units reported `ok` without enough aircraft: {cs['wrongly_ok']} (must be 0 by construction)."
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
    L += [
        "",
        "By slot of day (covered units, pooled across regimes):",
        "",
        "| Slot (UTC hours) | n | False coverage |",
        "|---|---|---|",
    ]
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
        sh_ = g.groupby("status")["share"].mean()
        L.append(f"| {kf} | {f(sh_.get('ok'))} | {f(sh_.get('insufficient'))} | {f(sh_.get('coverage_lost'))} |")
    L += [
        "",
        "## 5. Real days: events (OBSERVED)",
        "",
        f"Of the {facts['n_events']} events on the 35 days, {facts['n_uncertain']} carry an uncertain label and {facts['n_min3']} of the {facts['n_spoofish']} spoofing-like or both events involve only the minimum 3 aircraft. "
        "A position jump seen by 3 aircraft can be a data error, for example from multilateration. Event counts on elevated days are measured against a baseline selected by that day's own share (caveat 1 in section 1).",
        "",
        "| Day | Split | Events | Jamming-like | Spoofing-like | Both | Uncertain |",
        "|---|---|---|---|---|---|---|",
    ]
    for sp_, name in ((dev, "dev"), (held, "held_out")):
        for d in sp_.days:
            e = sp_.ev[sp_.ev.day == d]
            L.append(
                f"| {d} | {name} | {len(e)} | {(e.kind == 'jamming_like').sum()} | {(e.kind == 'spoofing_like').sum()} | {(e.kind == 'both').sum()} | {int(e.label_uncertain.sum())} |"
            )
    if reg is not None:
        L += [
            "",
            "### Regime labels per day (OBSERVED)",
            "",
            "Mechanical labels from `src/tashwish/regime.py`; baselines are fitted per label on development days only. The traffic regime is reduced from 2026-02-28 and the degraded regime is elevated from 2026-03-01.",
            "",
            "| Day | Split | Traffic | Degraded | En route units | Tested degraded share |",
            "|---|---|---|---|---|---|",
        ]
        for r in reg.itertuples():
            L.append(f"| {r.day} | {r.split} | {r.traffic} | {r.degraded} | {int(r.units)} | {f(r.share)} |")
        L += ["", "Class level false coverage by traffic regime (held out days; day bootstrap within regime):", ""]
        for k, v in rfc.items():
            L.append(
                f"- {k}: {f(v['rate'])} over {v['units']} units on {v['days']} days (day bootstrap {span(v['lo'], v['hi'])})"
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
        sp_, name = (held, "held_out") if d in held.days else (dev, "dev")
        e = sp_.ev[sp_.ev.day == d]
        top = max(e.confidence, key=lambda c: order[c]) if len(e) else "none"
        L.append(f"| {d} | {name} | {len(e)} | {top} | {int(e.n_aircraft.max()) if len(e) else 0} |")
    if daily is not None:
        L += [
            "",
            "### Region wide degraded share per day (OBSERVED)",
            "",
            "Sum over testable (`ok`) en route cell buckets of aircraft counts, so one aircraft can count in several cells. This is the plain level "
            "indicator; event counts are relative to a regime baseline and understate a region wide change.",
            "",
            "| Day | Split | Cell bucket aircraft (ok) | Degraded | Share | Wilson 95% |",
            "|---|---|---|---|---|---|",
        ]
        for r in daily.itertuples():
            L.append(f"| {r.day} | {r.split} | {int(r.n)} | {int(r.k)} | {f(r.share)} | {span(r.ci_lo, r.ci_hi)} |")
    if regime:
        L += [
            "",
            "### Same aircraft, early versus late development days (OBSERVED, development days only)",
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
    L += where_it_fails(held, dev, rows, reg, ingest, locals())
    return "\n".join(L)


def where_it_fails(held, dev, rows, reg, ingest, ctx) -> list[str]:
    """Section 7: a generated list of threshold checks over the tables above, then a factual paragraph for each miss."""
    tiers, tn, tr_ = ctx["tiers"], ctx["tn"], ctx["tr_"]
    sp_all, sp_n, sp_r, sp12 = ctx["sp_all"], ctx["sp_n"], ctx["sp_r"], ctx["sp12"]
    rfc, pooled_fc, facts = ctx["rfc"], ctx["pooled_fc"], ctx["facts"]
    matched, n_ev, fe = ctx["matched"], ctx["n_ev"], ctx["fe"]
    jam, s3 = ctx["jam"], ctx["s3"]
    L = ["## 7. Where it fails (generated from threshold checks over the tables above)", ""]
    L.append(
        "Each line is printed only when its check fails. Thresholds: recall below 0.50, a drop of more than 0.20 between regimes, a rate above 0.10, or a share kept below 0.50."
    )
    L.append("")
    for t in ("easy", "medium", "hard", "random"):
        if tiers[t]["rate"] < 0.5:
            L.append(
                f"- Jamming-like scenarios of tier `{t}` are found less than half the time ({f(tiers[t]['rate'])}, pooled across regimes)."
            )
    for t in ("easy", "medium", "hard", "random"):
        if tn[t]["n"] and tr_[t]["n"] and tn[t]["rate"] - tr_[t]["rate"] > 0.2:
            L.append(
                f"- Tier `{t}` recall drops from {f(tn[t]['rate'])} on normal traffic days to {f(tr_[t]['rate'])} on reduced traffic days."
            )
    for col, val, label in (
        ("traffic_bin", "low", "low traffic cells"),
        ("area", 1, "single cell scenarios"),
        ("intensity", 0.3, "intensity 0.3 scenarios"),
        ("duration", 1, "single bucket scenarios"),
    ):
        r = rate_row(jam[jam[col] == val], "jam_detected")
        if r["rate"] < 0.5:
            L.append(f"- Recall for {label} is {f(r['rate'])} ({r['k']}/{r['n']}, pooled across regimes).")
    if sp12["rate"] <= 0.30:
        L.append(
            f"- Spoofing of one or two aircraft is not found (recall {f(sp12['rate'])}); at least three aircraft are needed by design."
        )
    if sp_all["rate"] < 0.8:
        by = s3.groupby("n_spoofed")["spoof_detected"].mean()
        L.append(
            f"- Spoofing with 3 or more aircraft is found {f(sp_all['rate'])} of the time (normal days {f(sp_n['rate'])}, reduced days {f(sp_r['rate'])}); "
            f"with exactly 3 aircraft {f(by.get(3, float('nan')))}."
        )
    for k, v in rfc.items():
        if v["rate"] > 0.10:
            L.append(
                f"- Class covered lacks enough aircraft {f(v['rate'])} of the time on {k} traffic days (day bootstrap {span(v['lo'], v['hi'])}); the pooled value {f(pooled_fc['rate'])} describes neither regime."
            )
    if matched / n_ev < 0.95:
        L.append(
            f"- {n_ev - matched} of {n_ev} events in synthetic runs match no injected scenario (matched share {f(matched / n_ev)}); {fe['unmatched_medium_or_high']} of them have medium or high confidence."
        )
    if dev.sens:
        frag = [
            (k, v)
            for k, v in dev.sens["settings"].items()
            if v["share_kept"] < 0.5 or abs(v["rel_change_vs_default"]) >= 0.25
        ]
        if frag:
            L.append(
                "- Development day event count changes by 25 percent or more, or fewer than half of baseline events are kept, under: "
                + "; ".join(
                    f"`{k}` ({v['abs_change_vs_default']:+d} events, {f(v['share_kept'], 2)} of baseline events kept)"
                    for k, v in frag
                )
                + "."
            )
    if facts["n_min3"] / max(facts["n_spoofish"], 1) > 0.5:
        L.append(
            f"- {facts['n_min3']} of {facts['n_spoofish']} observed spoofing-like or both events involve only the minimum 3 aircraft, and {facts['n_uncertain']} of {facts['n_events']} events carry an uncertain label."
        )
    misses = [r for r in rows if r["hit"] is False]
    L += [
        "",
        f"Misses against the preregistered predictions: {', '.join(r['id'] for r in misses) or 'none'}.",
        "",
        "### Discussion of each miss",
        "",
    ]
    for r in misses:
        L.append(
            f"- **{r['id']}** ({r['data_class']}; {r['claim']}). {miss_text(r['id'], held, dev, rows, reg, ingest, ctx)}"
        )
    L.append("")
    return L


def miss_text(pid: str, held, dev, rows, reg, ingest, ctx) -> str:
    byid = {r["id"]: r for r in rows}
    rfc, cs, sp_all = ctx["rfc"], ctx["cs"], ctx["sp_all"]
    ev = held.ev
    if pid == "D2":
        hd = ingest[ingest["day"].isin(held.days)]
        bad = hd[~((hd.rows.between(1.2e6, 2.6e6)) & (hd.aircraft.between(1600, 2800)))]["day"].tolist()
        redu = (
            reg[(reg["split"] == "held_out") & (reg["traffic"] == "reduced")]["day"].tolist() if reg is not None else []
        )
        return (
            f"{len(bad)} of {len(hd)} held out days fall outside the written volume range ({', '.join(bad)}). "
            + ("These are exactly the days of the reduced traffic regime. " if sorted(bad) == sorted(redu) else "")
            + "The range was set from the two days seen before the freeze (see `docs/PREDICTIONS.md`). No cause for the volume change is identified or asserted."
        )
    if pid == "C3":
        return (
            (
                f"The pooled failure rate {f(1 - cs['covered']['p_enough'])} is below the written band of 0.10 to 0.35, and the slot ordering is the opposite of the prediction "
                f"(see the row in PREDICTIONS_RESULTS.md). The pooled rate mixes {f(rfc['normal']['rate'])} on normal days with {f(rfc['reduced']['rate'])} on reduced days, so it is not a typical rate for either. "
                "No explanation of the slot ordering was tested."
            )
            if rfc
            else "No regime split available."
        )
    if pid == "S1":
        by = ctx["s3"].groupby("n_spoofed")["spoof_detected"].mean()
        return (
            f"Recall {f(sp_all['rate'])} is below the 0.80 bar. It rises with the number of displaced aircraft (3 aircraft {f(by.get(3, float('nan')))}, 5 aircraft {f(by.get(5, float('nan')))}, 8 aircraft {f(by.get(8, float('nan')))}), "
            f"so the minimum cluster size of 3 is where the detector is weakest. By regime, recall is {f(ctx['sp_n']['rate'])} on normal days and {f(ctx['sp_r']['rate'])} on reduced days. The reason was not tested."
        )
    if pid == "S4":
        c = held.inj["confusion_all"]
        cols, rws = c["columns"], c["rows"]
        idx = {k: i for i, k in enumerate(cols)}
        wrong = rws["spoof_and_jam"][idx["jamming_like"]] if "spoof_and_jam" in rws else 0
        u = held.inj["uncertain_share_of_detected"]
        a = held.inj["label_accuracy_when_committed"]
        return (
            f"The uncertain share {f(u['rate'])} is above the written upper bound of 0.30 and the committed accuracy {f(a['rate'])} is below 0.85. "
            f"Of {a['n'] - a['k']} committed errors, {wrong} are spoof and jam scenarios that were committed to jamming-like only. The reason the spoofing part of those scenarios is missed was not tested."
        )
    if pid == "R3":
        return (
            f"{byid['R3']['observed']} against a bar of 4. The held out days contain {len(ev)} events in total, so the sample is small and one more day with an event would have met the bar. "
            "A background rate of events is therefore not demonstrated at this sample size."
        )
    if pid == "R4":
        return (
            f"Events north of 26 N: {int((ev.lat > 26).sum())} of {len(ev)} (latitudes {ev.lat.min():.1f} to {ev.lat.max():.1f}). The prediction of a northern concentration was not supported; "
            "no explanation of the location was tested."
        )
    if pid == "X1":
        return (
            (
                f"{byid['X1']['observed']}. The event count on development days is small ({dev.sens['settings']['default']['n_events']} events), so a change of one to three events decides the ordering. "
                "The false discovery level q changed the count at least as much as the gate and the minimum aircraft, so the predicted ordering did not hold."
            )
            if dev.sens
            else "No sensitivity file."
        )
    if pid == "A2":
        nd = int(((reg["split"] == "dev") & (reg["traffic"] == "reduced")).sum()) if reg is not None else 0
        return (
            f"On normal traffic days class level false coverage is {f(rfc['normal']['rate'])}, inside the bar of 0.10. On reduced traffic days it is {f(rfc['reduced']['rate'])} "
            f"over {rfc['reduced']['units']} covered units on {rfc['reduced']['days']} days. The reduced regime coverage model was fitted on {nd} development days with that label. "
            "Why the fitted model fails on those days was not tested."
        )
    return "No discussion has been written for this row."


def headline(held: Split, rows: list[dict]) -> dict:
    """Headline rows. Every interval is a day bootstrap; pooled rows are labelled pooled and are kept for continuity."""
    res: list[dict] = []
    reg = load_regimes()

    def add(metric, scen, cls, regime, r, method="day_bootstrap"):
        lo, hi = (r["blo"], r["bhi"]) if method == "day_bootstrap" else (r["lo"], r["hi"])
        res.append(
            {
                "metric": metric,
                "scenario": scen,
                "data_class": cls,
                "regime": regime,
                "value": rnd(r["rate"], 4),
                "ci_lo": rnd(lo, 4),
                "ci_hi": rnd(hi, 4),
                "n": int(r["n"]),
                "n_days": int(r["days"]),
                "ci_method": method,
            }
        )

    scen = with_regimes(held.scen, reg)
    j = scen[scen.kind == "jam_only"]
    sj = scen[(scen.kind == "spoof_jump") & (scen.n_spoofed >= 3)]
    syn = "synthetic_injection_held_out_days"
    subsets = [("pooled", ""), ("traffic_normal", "_normal"), ("traffic_reduced", "_reduced")]

    def pick(df, regime):
        return df if regime == "pooled" else df[df["traffic"] == regime.replace("traffic_", "")]

    for t in ("easy", "medium", "hard"):
        for regime, suf in subsets:
            add(
                f"jamming_recall_{t}{suf}",
                syn,
                "synthetic",
                regime,
                rate_row(pick(j[j.tier == t], regime), "jam_detected"),
            )
    for regime, suf in subsets:
        add(
            f"spoofing_recall_3plus_aircraft{suf}",
            syn,
            "synthetic",
            regime,
            rate_row(pick(sj, regime), "spoof_detected"),
        )
    obs = "observed_held_out_days"
    pf = pooled_false_coverage(held)
    fcs = [("pooled", "", pf)]
    if reg is not None:
        fcs += [(f"traffic_{k}", f"_{k}", v) for k, v in regime_false_coverage(held, reg).items()]
    for regime, suf, v in fcs:
        res.append(
            {
                "metric": f"false_coverage_rate{suf}",
                "scenario": obs,
                "data_class": "observed",
                "regime": regime,
                "value": rnd(v["rate"], 4),
                "ci_lo": rnd(v["lo"], 4),
                "ci_hi": rnd(v["hi"], 4),
                "n": int(v["units"]),
                "n_days": int(v["days"]),
                "ci_method": "day_bootstrap",
            }
        )
    return {
        "results": res,
        "note": "Rows with data_class synthetic are recall on SYNTHETIC scenarios injected into real held out traffic; they are not accuracy against real interference. "
        "Rows with regime pooled mix the normal and reduced traffic regimes of the study window and describe neither; use the regime rows. "
        "All intervals are day bootstrap intervals (whole days resampled). n counts scenarios, or covered units for false coverage; n_days counts days.",
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
    freeze = (
        json.loads((ROOT / "results/FREEZE.json").read_text(encoding="utf-8"))
        if (ROOT / "results/FREEZE.json").exists()
        else None
    )
    ingest = None
    mp = a.interim / "manifest.jsonl"
    if mp.exists():
        recs = {}
        for line in mp.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("status") == "complete":
                recs[r["day"]] = {"day": r["day"], "rows": r["rows"], "aircraft": r["aircraft"]}
        ingest = pd.DataFrame(recs.values())
        ingest[ingest["day"].isin(held.days + dev.days)].to_csv(
            ROOT / "results/ingest_days.csv", index=False, lineterminator="\n"
        )
    elif (ROOT / "results/ingest_days.csv").exists():
        ingest = pd.read_csv(ROOT / "results/ingest_days.csv")
    rows = evaluate(held, dev, ingest)
    regime = (
        json.loads((a.dev / "regime_check.json").read_text(encoding="utf-8"))
        if (a.dev / "regime_check.json").exists()
        else None
    )
    daily = pd.read_csv(a.daily) if a.daily.exists() else None
    (ROOT / "docs/research/PREDICTIONS_RESULTS.md").write_text(
        predictions_md(rows, freeze, held), encoding="utf-8", newline="\n"
    )
    (ROOT / "docs/research/VALIDATION.md").write_text(
        validation_md(held, dev, freeze, rows, regime, daily, ingest), encoding="utf-8", newline="\n"
    )
    (ROOT / "results/headline.json").write_text(
        json.dumps(headline(held, rows), indent=1, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )
    (ROOT / "results/predictions_scored.json").write_text(
        json.dumps(rows, indent=1, default=str) + "\n", encoding="utf-8", newline="\n"
    )
    print("written")


if __name__ == "__main__":
    main()
