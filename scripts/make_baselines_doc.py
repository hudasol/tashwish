"""Generate the results part of docs/BASELINES.md and results/baselines/summary.json from result files.

  python scripts/make_baselines_doc.py [--root results/baselines] [--doc docs/BASELINES.md]

Inputs: results/baselines/<split>/synthetic_scenarios_baselines.csv, observed_days_baselines.csv, run_meta.json, and
results/regimes.csv for the regime labels. Nothing in the generated text is typed by hand: every number comes from those files.
Only the block between the two marker lines in docs/BASELINES.md is replaced; the Specification section is left as written.
Synthetic results are SYNTHETIC. Real day results are OBSERVED and have no ground truth.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "<!-- BEGIN GENERATED RESULTS -->"
END = "<!-- END GENERATED RESULTS -->"
TIERS = ("easy", "medium", "hard", "random")
REGIMES = ("all", "normal", "reduced")
JAM = ("system", "B1", "B1b", "B2", "B3a", "B3b", "B3c")
SPOOF = ("system", "B4")
DESC = {
    "system": "the system (frozen detector)",
    "B1": "fixed fraction, share at least a constant",
    "B1b": "fixed fraction with the sparsity correction",
    "B2": "climatology z score per cell and slot",
    "B3a": "binomial test, no regime aware baselines",
    "B3b": "binomial test, no coverage gating",
    "B3c": "binomial test, no false discovery control",
    "B4": "naive speed threshold on single jumps",
}
REPS, SEED = 2000, 5


def fnum(x, d=2) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def sub(df: pd.DataFrame, regime: str) -> pd.DataFrame:
    return df if regime == "all" else df[df["traffic"] == regime]


def rate(df: pd.DataFrame, col: str) -> dict:
    """Pooled rate with a day bootstrap interval. Same estimator as `cluster_bootstrap_rate`, vectorised over repetitions."""
    n = int(len(df))
    k = int(df[col].astype(bool).sum()) if n else 0
    lo = hi = float("nan")
    if n and df["day"].nunique() >= 2:
        g = df.assign(v=df[col].astype(float)).groupby("day")["v"]
        ks, ns = g.sum().to_numpy(), g.size().to_numpy().astype(float)
        idx = np.random.default_rng(SEED).integers(0, len(ks), size=(REPS, len(ks)))
        r = ks[idx].sum(axis=1) / ns[idx].sum(axis=1)
        lo, hi = float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))
    return {"k": k, "n": n, "days": int(df["day"].nunique()), "rate": k / n if n else float("nan"), "lo": lo, "hi": hi}


def paired(df: pd.DataFrame, col_a: str, col_b: str) -> dict:
    """Rate of `col_a` minus rate of `col_b` on the same scenarios, with a day bootstrap interval of the difference."""
    n = int(len(df))
    if not n:
        return {"n": 0, "diff": float("nan"), "lo": float("nan"), "hi": float("nan"), "verdict": "n/a"}
    g = df.assign(a=df[col_a].astype(float), b=df[col_b].astype(float)).groupby("day")
    a, b, c = g["a"].sum().to_numpy(), g["b"].sum().to_numpy(), g.size().to_numpy().astype(float)
    diff = float(a.sum() / c.sum() - b.sum() / c.sum())
    lo = hi = float("nan")
    if len(c) >= 2:
        idx = np.random.default_rng(SEED).integers(0, len(c), size=(REPS, len(c)))
        d = (a[idx].sum(axis=1) - b[idx].sum(axis=1)) / c[idx].sum(axis=1)
        lo, hi = float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))
    if math.isnan(lo):
        verdict = "n/a"
    elif lo > 0:
        verdict = "above"
    elif hi < 0:
        verdict = "below"
    else:
        verdict = "tied"
    return {"n": n, "diff": diff, "lo": lo, "hi": hi, "verdict": verdict}


def cell(r: dict) -> str:
    if r["n"] == 0:
        return "n/a"
    return f"{fnum(r['rate'])} [{fnum(r['lo'])}, {fnum(r['hi'])}]"


def md_table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def boot_mean(per_day: np.ndarray) -> tuple[float, float]:
    if len(per_day) < 2:
        return float("nan"), float("nan")
    idx = np.random.default_rng(SEED).integers(0, len(per_day), size=(REPS, len(per_day)))
    m = per_day[idx].mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


# ---------------------------------------------------------------- loading


def load_split(root: Path, split: str, regimes: pd.DataFrame) -> dict | None:
    d = root / split
    if not (d / "synthetic_scenarios_baselines.csv").exists():
        return None
    # the scenario kind "null" must not be read as a missing value
    scen = pd.read_csv(d / "synthetic_scenarios_baselines.csv", keep_default_na=False, na_values=[""])
    real = pd.read_csv(d / "observed_days_baselines.csv")
    meta = json.loads((d / "run_meta.json").read_text())
    for df in (scen, real):
        if "traffic" not in df.columns:
            df["traffic"] = df["day"].map(regimes.set_index("day")["traffic"])
    return {"scen": scen, "real": real, "meta": meta}


def split_label(split: str, meta: dict) -> str:
    if split == "dev":
        return "Development days (the system was developed on these days; the baselines were not tuned on any day)"
    c = str(meta.get("baselines_fixed_before_run_commit", "unknown"))[:10]
    return f"Held out days: post hoc, not preregistered, baselines fixed before run ({c})"


# ---------------------------------------------------------------- sections


def jam_recall_section(split: str, s: dict, rule: str, out: dict) -> str:
    col = "__jam" if rule == "harness" else "__jam_strict"
    jo = s["scen"][s["scen"]["kind"] == "jam_only"]
    parts = []
    for reg in REGIMES:
        d = sub(jo, reg)
        if d.empty:
            continue
        header = ["Detector"] + [f"{t} (n={int((d['tier'] == t).sum())})" for t in TIERS]
        rows = []
        for det in JAM:
            row = [det]
            for t in TIERS:
                r = rate(d[d["tier"] == t], det + col)
                out.setdefault(split, {}).setdefault("jam_recall", {}).setdefault(rule, {}).setdefault(
                    reg, {}
                ).setdefault(det, {})[t] = r
                row.append(cell(r))
            rows.append(row)
        parts.append(f"Traffic regime: {reg} ({d['day'].nunique()} days)\n\n" + md_table(header, rows))
    return "\n\n".join(parts)


def spoof_section(split: str, s: dict, out: dict) -> str:
    sj = s["scen"][(s["scen"]["kind"] == "spoof_jump") & (s["scen"]["n_spoofed"] >= 3)]
    header = ["Traffic regime", "Scenarios"] + list(SPOOF)
    rows = []
    for reg in REGIMES:
        d = sub(sj, reg)
        if d.empty:
            continue
        row = [reg, str(len(d))]
        for det in SPOOF:
            r = rate(d, det + "__spoof")
            out.setdefault(split, {}).setdefault("spoof_recall_n_ge_3", {}).setdefault(reg, {})[det] = r
            row.append(cell(r))
        rows.append(row)
    return md_table(header, rows)


def null_section(split: str, s: dict, out: dict) -> str:
    nl = s["scen"][s["scen"]["kind"] == "null"]
    cols = [(det, "__jam", "harness") for det in JAM] + [(det, "__jam_strict", "strict") for det in JAM]
    cols += [(det, "__spoof", "harness") for det in SPOOF]
    header = ["Traffic regime", "Null scenarios"] + [f"{d} {k} {'jam' if 'jam' in c else 'spoof'}" for d, c, k in cols]
    rows = []
    for reg in REGIMES:
        d = sub(nl, reg)
        if d.empty:
            continue
        row = [reg, str(len(d))]
        for det, c, _k in cols:
            r = rate(d, det + c)
            out.setdefault(split, {}).setdefault("null_flag_rate", {}).setdefault(reg, {})[f"{det}{c}"] = r
            row.append(fnum(r["rate"], 3))
        rows.append(row)
    return md_table(header, rows)


def real_section(split: str, s: dict, out: dict) -> tuple[str, str]:
    real = s["real"]
    jr = real[real["kind"] == "jamming_like"]
    header = ["Traffic regime", "Detector", "Days", "Tested per day", "Flagged per day [day bootstrap]", "Flagged share of tested",
              "Events per day", "Jaccard with system", "Share of system flags also flagged", "Flagged but not by system per day"]  # fmt: skip
    rows = []
    for reg in REGIMES:
        d = sub(jr, reg)
        if d.empty:
            continue
        for det in JAM:
            x = d[d["detector"] == det]
            per = x["n_flagged"].to_numpy(dtype=float)
            lo, hi = boot_mean(per)
            tested = float(x["n_tested"].sum())
            rec = {"days": int(len(x)), "tested_per_day": float(x["n_tested"].mean()), "flagged_per_day": float(per.mean()),
                   "flagged_per_day_lo": lo, "flagged_per_day_hi": hi,
                   "flagged_share_of_tested": float(x["n_flagged"].sum() / tested) if tested else float("nan"),
                   "events_per_day": float(x["n_events"].mean()),
                   "jaccard": float(x["n_both"].sum() / x["n_union"].sum()) if x["n_union"].sum() else float("nan"),
                   "system_flags_also_flagged": float(x["n_both"].sum() / x["n_system"].sum()) if x["n_system"].sum() else float("nan"),
                   "extra_per_day": float((x["n_flagged"] - x["n_both"]).mean())}  # fmt: skip
            out.setdefault(split, {}).setdefault("real_days_jamming_like", {}).setdefault(reg, {})[det] = rec
            rows.append([reg, det, str(rec["days"]), fnum(rec["tested_per_day"], 0),
                         f"{fnum(rec['flagged_per_day'], 1)} [{fnum(lo, 1)}, {fnum(hi, 1)}]", fnum(rec["flagged_share_of_tested"], 3),
                         fnum(rec["events_per_day"], 1), fnum(rec["jaccard"], 3), fnum(rec["system_flags_also_flagged"], 2),
                         fnum(rec["extra_per_day"], 1)])  # fmt: skip
    jam_t = md_table(header, rows)
    sr = real[real["kind"] == "spoofing_like"]
    header = ["Traffic regime", "Detector", "Days", "Flagged origin units per day [day bootstrap]", "Events per day", "Jaccard with system",
              "Share of system units also flagged"]  # fmt: skip
    rows = []
    for reg in REGIMES:
        d = sub(sr, reg)
        if d.empty:
            continue
        for det in SPOOF:
            x = d[d["detector"] == det]
            per = x["n_flagged"].to_numpy(dtype=float)
            lo, hi = boot_mean(per)
            rec = {"days": int(len(x)), "flagged_per_day": float(per.mean()), "flagged_per_day_lo": lo, "flagged_per_day_hi": hi,
                   "events_per_day": float(x["n_events"].mean()),
                   "jaccard": float(x["n_both"].sum() / x["n_union"].sum()) if x["n_union"].sum() else float("nan"),
                   "system_units_also_flagged": float(x["n_both"].sum() / x["n_system"].sum()) if x["n_system"].sum() else float("nan")}  # fmt: skip
            out.setdefault(split, {}).setdefault("real_days_spoofing_like", {}).setdefault(reg, {})[det] = rec
            rows.append([reg, det, str(rec["days"]), f"{fnum(rec['flagged_per_day'], 1)} [{fnum(lo, 1)}, {fnum(hi, 1)}]",
                         fnum(rec["events_per_day"], 1), fnum(rec["jaccard"], 3), fnum(rec["system_units_also_flagged"], 2)])  # fmt: skip
    return jam_t, md_table(header, rows)


def verdict_section(split: str, s: dict, out: dict) -> str:
    """Baseline minus system on identical scenarios, with the verdict from the day bootstrap interval of the difference."""
    scen = s["scen"]
    jo = scen[scen["kind"] == "jam_only"]
    header = [
        "Metric",
        "Traffic regime",
        "Detector",
        "Scenarios",
        "Rule",
        "Baseline minus system [day bootstrap]",
        "Verdict",
    ]
    rows = []
    store = out.setdefault(split, {}).setdefault("paired_vs_system", [])
    for reg in REGIMES:
        for rule, col in (("harness", "__jam"), ("strict", "__jam_strict")):
            for t in (*TIERS, "all tiers"):
                d = sub(jo, reg)
                d = d if t == "all tiers" else d[d["tier"] == t]
                if d.empty:
                    continue
                for det in JAM[1:]:
                    p = paired(d, det + col, "system" + col)
                    store.append({"metric": f"jamming recall {t}", "regime": reg, "detector": det, "rule": rule, **p})
                    rows.append([f"jamming recall, {t}", reg, det, str(p["n"]), rule,
                                 f"{p['diff']:+.2f} [{p['lo']:+.2f}, {p['hi']:+.2f}]" if p["verdict"] != "n/a" else "n/a", p["verdict"]])  # fmt: skip
        sj = sub(scen[(scen["kind"] == "spoof_jump") & (scen["n_spoofed"] >= 3)], reg)
        if len(sj):
            p = paired(sj, "B4__spoof", "system__spoof")
            store.append(
                {
                    "metric": "spoofing recall, 3 or more displaced",
                    "regime": reg,
                    "detector": "B4",
                    "rule": "harness",
                    **p,
                }
            )
            rows.append(["spoofing recall, 3 or more displaced", reg, "B4", str(p["n"]), "harness",
                         f"{p['diff']:+.2f} [{p['lo']:+.2f}, {p['hi']:+.2f}]" if p["verdict"] != "n/a" else "n/a", p["verdict"]])  # fmt: skip
    return md_table(header, rows)


def _cells(x: pd.DataFrame) -> str:
    names = {"spoofing recall, 3 or more displaced": "spoofing", "jamming recall ": ""}
    out = []
    for r in x.itertuples():
        m = r.metric
        for k, v in names.items():
            m = m.replace(k, v)
        out.append(f"{m} on {r.regime} days ({r.diff:+.2f})")
    return "; ".join(out)


def reading_section(split: str, out: dict) -> str:
    """Plain sentences built from the paired and real day tables: where each baseline is above, tied with, or below the system."""
    pairs = out.get(split, {}).get("paired_vs_system", [])
    if not pairs:
        return ""
    df = pd.DataFrame(pairs)
    lines = []
    for det in (*JAM[1:], "B4"):
        for metric_kind, mask in (
            (
                "jamming recall by tier",
                df["metric"].str.startswith("jamming recall") & (df["metric"] != "jamming recall all tiers"),
            ),
            ("spoofing recall", df["metric"].str.startswith("spoofing")),
        ):
            d = df[(df["detector"] == det) & mask & (df["regime"] != "all")]
            if d.empty:
                continue
            for rule in sorted(d["rule"].unique()):
                x = d[d["rule"] == rule]
                above, below, tied = x[x["verdict"] == "above"], x[x["verdict"] == "below"], x[x["verdict"] == "tied"]
                text = f"{det}, {metric_kind}, {rule} rule: above the system in {len(above)} of {len(x)} tier and regime cells"
                text += f" ({_cells(above)})" if len(above) else ""
                text += f", tied in {len(tied)}, below in {len(below)}"
                text += f" ({_cells(below)})" if len(below) else ""
                lines.append(text + ".")
    rj = out.get(split, {}).get("real_days_jamming_like", {})
    for reg in ("normal", "reduced"):
        if reg not in rj:
            continue
        sysrec = rj[reg]["system"]
        for det in JAM[1:]:
            r = rj[reg][det]
            lines.append(
                f"OBSERVED, {reg} days: {det} flagged {fnum(r['flagged_per_day'], 1)} cell buckets per day against "
                f"{fnum(sysrec['flagged_per_day'], 1)} for the system; the share of the system's own flags that it also flagged was {fnum(r['system_flags_also_flagged'], 2)}."
            )
    rs = out.get(split, {}).get("real_days_spoofing_like", {})
    for reg in ("normal", "reduced"):
        if reg in rs:
            lines.append(
                f"OBSERVED, {reg} days: B4 gave {fnum(rs[reg]['B4']['events_per_day'], 1)} events per day against "
                f"{fnum(rs[reg]['system']['events_per_day'], 1)} for the system."
            )
    return "\n\n".join(lines)


def provenance_section(splits: dict, out: dict) -> str:
    rows = []
    for name, s in splits.items():
        m = s["meta"]
        rp = m["reproduction_of_system"]
        out.setdefault(name, {})["provenance"] = {
            k: m.get(k)
            for k in (
                "run_commit",
                "baselines_fixed_before_run_commit",
                "baseline_sources_sha256",
                "reproduction_of_system",
            )
        }
        rows.append([name, str(len(m["score_days"])), str(rp["scenarios_here"]), str(rp["matched_sid"]),
                     f"{rp['jam_detected_equal']} of {rp['matched_sid']}", f"{rp['spoof_detected_equal']} of {rp['matched_sid']}",
                     str(m.get("baselines_fixed_before_run_commit", m["run_commit"]))[:10]])  # fmt: skip
    return md_table(
        [
            "Split",
            "Days",
            "Scenarios here",
            "Matched to committed file",
            "System jam outcome equal",
            "System spoof outcome equal",
            "Commit",
        ],
        rows,
    )


CAVEATS = """\
1. Scenarios were generated for the system. They are placed away from real flags of the system, not of the baselines. A
   baseline with many real flags can therefore have injected scenarios land in or beside its own background flags. The harness
   rule drops events whose identifier also appears on the uninjected day. It can credit a baseline when an injection merges
   into a background flag and the merged event gets a new identifier, and it can hide an injection that adds flags to a
   background event without changing its identifier. The strict rule removes both effects by counting only cell buckets that
   were not flagged on the uninjected day. A detector that flags a large share of all units on a day cannot be given a
   meaningful recall by either rule.
2. Recall and the number of flags on real days must be read together. A baseline with a lower gate than the system, for
   example fewer degraded aircraft required, finds smaller injections, and the same lower gate flags more units on real days.
   Real day flags are not labelled false because there is no truth, so the real day tables describe burden, not error rate.
3. The flag rate on null scenarios is nearly empty by construction. Null scenarios inject nothing, and flags present without
   injection are removed before scoring, so a flag can appear on a null footprint only through event merging with a
   neighbouring injected scenario. It is reported because it was asked for, and it is not a measure of the false alarm rate.
4. The system was developed on the development days. The baselines were specified before any run and not tuned, so the
   development comparison favours the system slightly. The held out days were scored once for the system under a frozen
   state, and the baselines were scored on them afterwards without tuning.
5. Injection is a controlled test of sensitivity, not of real world accuracy. Synthetic recall says nothing about how often
   real interference would be detected, and OBSERVED flags are evidence of degraded position quality, not of interference or
   of anyone's actions.
6. Day level intervals resample whole days within the listed regime. With few days in a regime the intervals are wide, and
   regimes with fewer than 2 days have no interval.
7. B3a pools the coverage model as well as the baseline share, because both are regime specific in the system.
8. Tashwish is a research tool. It is not for navigation or for any safety of life use."""


def build(root: Path, regimes: pd.DataFrame) -> tuple[str, dict]:
    out: dict = {"data_class_note": "synthetic tables are SYNTHETIC; real day tables are OBSERVED with no ground truth"}
    splits = {n: s for n in ("dev", "held_out") if (s := load_split(root, n, regimes)) is not None}
    if not splits:
        return "Results have not been generated yet.", out
    txt = ["## Results", "",
           "Generated by `scripts/make_baselines_doc.py` from the files in `results/baselines/`. Rates are shown with 95 percent "
           "intervals from resampling whole days (2000 repetitions, seed 5). Tables of injected scenarios are SYNTHETIC. Tables of "
           "real days are OBSERVED and have no ground truth. Tashwish never attributes interference to an actor.", "",
           "### Run provenance and reproduction of the system", "",
           "The system is run again inside the same loop as the baselines. The two right hand count columns show how many of its "
           "scenario outcomes equal the committed result files of the original runs.", "", provenance_section(splits, out), ""]  # fmt: skip
    n = 1
    for name, s in splits.items():
        label = split_label(name, s["meta"])
        txt += [f"### {n}. Jamming recall by tier: {label}", "", "Harness rule (unchanged `drop_background` and `match_scenario`). SYNTHETIC.", "",
                jam_recall_section(name, s, "harness", out), "",
                "Strict rule (only flags caused by the injection can count). SYNTHETIC.", "", jam_recall_section(name, s, "strict", out), ""]  # fmt: skip
        txt += [
            f"### {n + 1}. Spoofing recall, 3 or more displaced aircraft: {label}",
            "",
            "SYNTHETIC.",
            "",
            spoof_section(name, s, out),
            "",
        ]
        txt += [f"### {n + 2}. Flag rate on null scenarios: {label}", "",
                "SYNTHETIC. Fraction of null scenarios overlapped by an event after background removal. See the limits on why this is "
                "close to zero by construction.", "", null_section(name, s, out), ""]  # fmt: skip
        jt, st = real_section(name, s, out)
        txt += [f"### {n + 3}. Real days, jamming-like flags: {label}", "",
                "OBSERVED, no truth. Flagged cell buckets are not claimed to be false alarms or true events.", "", jt, "",
                f"### {n + 4}. Real days, spoofing-like jumps: {label}", "", "OBSERVED, no truth.", "", st, ""]  # fmt: skip
        txt += [f"### {n + 5}. Baseline minus system on identical scenarios: {label}", "",
                "Differences in recall on the same scenarios. The verdict is above when the whole day bootstrap interval of the "
                "difference is positive, below when it is negative, and tied otherwise. A baseline that is above or tied with the "
                "system is reported as such.", "", verdict_section(name, s, out), ""]  # fmt: skip
        rd = reading_section(name, out)
        if rd:
            txt += [
                f"### {n + 6}. Summary of where baselines are above, tied with or below the system: {label}",
                "",
                rd,
                "",
            ]
        n += 7
    txt += ["### Limits", "", CAVEATS, "",
            "Sources: docs/RESEARCH.md, docs/METHODOLOGY.md, docs/PREDICTIONS_AMENDMENT.md, docs/VALIDATION.md, results/dev/synthetic_scenarios.csv, "
            "results/held_out/synthetic_scenarios.csv, results/regimes.csv, results/baselines/summary.json."]  # fmt: skip
    return "\n".join(txt), out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT / "results/baselines"))
    ap.add_argument("--doc", default=str(ROOT / "docs/BASELINES.md"))
    ap.add_argument("--regimes", default=str(ROOT / "results/regimes.csv"))
    a = ap.parse_args()
    root, doc = Path(a.root), Path(a.doc)
    regimes = pd.read_csv(a.regimes)
    body, summary = build(root, regimes)
    (root / "summary.json").write_text(json.dumps(summary, indent=1, default=float, allow_nan=True))
    text = doc.read_text()
    pat = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    new = f"{BEGIN}\n{body}\n{END}"
    text = pat.sub(lambda _m: new, text) if pat.search(text) else text.rstrip() + "\n\n" + new + "\n"
    doc.write_text(text)


if __name__ == "__main__":
    main()
