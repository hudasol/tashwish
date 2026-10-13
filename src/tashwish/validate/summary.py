"""Summaries of validation outputs: rates with Wilson intervals, day-clustered bootstrap, confusion matrices."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..metrics.stats import wilson_interval


def rate(df: pd.DataFrame, col: str) -> dict:
    n = len(df)
    k = int(df[col].sum()) if n else 0
    lo, hi = wilson_interval(k, n) if n else (np.nan, np.nan)
    return {"n": n, "k": k, "rate": k / n if n else np.nan, "ci_lo": float(lo), "ci_hi": float(hi)}


def cluster_bootstrap_rate(
    df: pd.DataFrame, col: str, by: str = "day", reps: int = 2000, seed: int = 5
) -> tuple[float, float]:
    """95% percentile interval for a rate when whole days are resampled (scenarios within a day are not independent)."""
    if df.empty:
        return float("nan"), float("nan")
    groups = {k: g[col].to_numpy(dtype=float) for k, g in df.groupby(by)}
    keys = list(groups)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        arr = np.concatenate([groups[keys[i]] for i in pick])
        vals.append(arr.mean())
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def rate_with_both(df: pd.DataFrame, col: str) -> dict:
    r = rate(df, col)
    lo, hi = cluster_bootstrap_rate(df.assign(**{col: df[col].astype(float)}), col)
    r["boot_day_ci_lo"], r["boot_day_ci_hi"] = lo, hi
    return r


def median_ci(values: pd.Series, groups: pd.Series, reps: int = 2000, seed: int = 9) -> dict:
    v = values.dropna()
    if v.empty:
        return {"n": 0, "median": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan")}
    g = groups.loc[v.index]
    keys = list(g.unique())
    by = {k: v[g == k].to_numpy() for k in keys}
    rng = np.random.default_rng(seed)
    meds = []
    for _ in range(reps):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        meds.append(np.median(np.concatenate([by[keys[i]] for i in pick])))
    return {"n": int(len(v)), "median": float(v.median()), "ci_lo": float(np.percentile(meds, 2.5)),
            "ci_hi": float(np.percentile(meds, 97.5))}  # fmt: skip


def predicted_column(df: pd.DataFrame) -> pd.Series:
    """Predicted label with uncertain commitments marked: 'jamming_like?' means flagged as uncertain."""
    return df["label"].where(~df["label_uncertain"] | (df["label"] == "none"), df["label"] + "?")


def confusion(df: pd.DataFrame) -> dict:
    """Rows: injected kind. Columns: system label, with '?' marking an uncertain call. Counts only."""
    d = df.assign(pred=predicted_column(df))
    tab = pd.crosstab(d["kind"], d["pred"])
    cols = ["none", "jamming_like", "jamming_like?", "spoofing_like", "spoofing_like?", "both", "both?"]
    tab = tab.reindex(columns=cols, fill_value=0)
    return {"columns": cols, "rows": {k: [int(x) for x in tab.loc[k]] for k in tab.index}}


TIER_TEXT = {
    "easy": "intensity 0.8, 3 or 7 cells, 2 or 3 buckets, at least 10 aircraft",
    "medium": "intensity 0.5, 3 cells, 2 buckets, at least 10 aircraft",
    "hard": "1 cell, 1 bucket, intensity 0.3 or 0.5, often fewer than 8 aircraft",
    "random": "random design",
}


def summarize_injection(scen: pd.DataFrame, events: pd.DataFrame) -> dict:
    out: dict = {"data_class": "synthetic", "n_scenarios": int(len(scen))}
    jo = scen[scen["kind"] == "jam_only"]
    out["jam_recall_by_tier"] = {
        t: rate_with_both(jo[jo["tier"] == t], "jam_detected") for t in ("easy", "medium", "hard", "random")
    }
    for axis in ("intensity", "area", "duration", "traffic_bin", "coverage_class"):
        out[f"jam_recall_by_{axis}"] = {str(k): rate_with_both(g, "jam_detected") for k, g in jo.groupby(axis)}
    out["jam_recall_given_ok_share_ge_0.5"] = rate_with_both(jo[jo["ok_share"] >= 0.5], "jam_detected")
    out["jam_recall_given_ok_share_lt_0.5"] = rate_with_both(jo[jo["ok_share"] < 0.5], "jam_detected")
    out["jam_delay_buckets_by_tier"] = {
        t: median_ci(jo[jo["tier"] == t]["jam_delay_buckets"], jo[jo["tier"] == t]["day"])
        for t in ("easy", "medium", "hard")
    }
    sj = scen[scen["kind"] == "spoof_jump"]
    out["spoof_recall_by_n_spoofed"] = {
        str(int(k)): rate_with_both(g, "spoof_detected") for k, g in sj.groupby("n_spoofed")
    }
    out["spoof_recall_by_displacement_km"] = {
        str(int(k)): rate_with_both(g[g["n_spoofed"] >= 3], "spoof_detected") for k, g in sj.groupby("displacement_km")
    }
    out["spoof_recall_n_ge_3"] = rate_with_both(sj[sj["n_spoofed"] >= 3], "spoof_detected")
    out["spoof_recall_n_le_2"] = rate_with_both(sj[sj["n_spoofed"] <= 2], "spoof_detected")
    out["spoof_delay_min_n_ge_3"] = median_ci(
        sj[sj["n_spoofed"] >= 3]["spoof_delay_min"], sj[sj["n_spoofed"] >= 3]["day"]
    )
    out["jam_flag_rate_on_spoof_jump_n_ge_3"] = rate_with_both(sj[sj["n_spoofed"] >= 3], "jam_detected")
    out["spoof_flag_rate_on_jam_only"] = rate_with_both(jo, "spoof_detected")
    out["spoof_flag_rate_on_null"] = rate_with_both(scen[scen["kind"] == "null"], "spoof_detected")
    out["jam_flag_rate_on_null"] = rate_with_both(scen[scen["kind"] == "null"], "jam_detected")
    detected = scen[scen["label"] != "none"]
    out["uncertain_share_of_detected"] = (
        rate_with_both(detected.assign(u=detected["label_uncertain"]), "u") if len(detected) else {}
    )
    committed = detected[~detected["label_uncertain"]]
    truth_map = {"jam_only": "jamming_like", "spoof_jump": "spoofing_like", "spoof_and_jam": "both"}
    committed = committed[committed["kind"].isin(truth_map)]
    out["label_accuracy_when_committed"] = (
        rate_with_both(committed.assign(ok=committed["label"] == committed["kind"].map(truth_map)), "ok")
        if len(committed)
        else {}
    )
    out["confusion_all"] = confusion(scen)
    out["confusion_spoof_n_ge_3_or_not_spoof"] = confusion(
        scen[(scen["n_spoofed"] >= 3) | (~scen["kind"].isin(["spoof_jump", "spoof_and_jam"]))]
    )
    # false events: events left after removing pre-existing ones that match no scenario
    if len(events):
        fe = events[~events["matches_scenario"]]
        runs = events.groupby(["day", "run"]).ngroups
        out["false_events"] = {"n_unmatched_events": int(len(fe)), "n_events": int(len(events)), "n_runs": int(runs),
                               "unmatched_medium_or_high": int(fe["confidence"].isin(["medium", "high"]).sum())}  # fmt: skip
        tp = int(events["matches_scenario"].sum())
        out["event_precision_vs_injection"] = {"tp_events": tp, "fp_events": int(len(fe)),
                                               "precision": tp / (tp + len(fe)) if (tp + len(fe)) else float("nan")}  # fmt: skip
    return out
