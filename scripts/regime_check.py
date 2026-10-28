"""DEV-only diagnostic: did the degraded share change for the SAME aircraft between the early and the late dev days?

Early dev days (before 2026-03-01) are quiet and have normal traffic; late dev days (from 2026-03-02) have far fewer aircraft and
many more flagged events. The question is whether the rise is a fleet-mix effect (different aircraft flying) or a change
affecting aircraft seen in both periods. Uses aircraft-bucket rows (en route stratum), dev days only, no held-out data.
Output: results/dev/regime_check.json. No aircraft identifiers are written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tashwish.pipeline import build_ab
from tashwish.split import split

MIN_SAMPLES = 50
LATE_FROM = "2026-03-02"


def main() -> None:
    interim, out = Path("data/interim"), Path("results/dev/regime_check.json")
    dev, _ = split()
    days = [d.isoformat() for d in dev]
    rows = []
    for d in days:
        ab = build_ab(interim, d)
        e = (
            ab[ab["stratum"] == "enroute"]
            .groupby("icao24", as_index=False)
            .agg(n=("n_samples", "sum"), k=("n_strong", "sum"))
        )
        e["period"] = "late" if d >= LATE_FROM else "early"
        rows.append(e)
    a = pd.concat(rows)
    g = a.groupby(["icao24", "period"], as_index=False).agg(n=("n", "sum"), k=("k", "sum"))
    w = g.pivot(index="icao24", columns="period", values=["n", "k"]).fillna(0)
    w.columns = [f"{x}_{y}" for x, y in w.columns]
    res: dict = {"early_days": [d for d in days if d < LATE_FROM], "late_days": [d for d in days if d >= LATE_FROM]}
    for per in ("early", "late"):
        res[f"{per}_aircraft_with_samples"] = int((w[f"n_{per}"] >= MIN_SAMPLES).sum())
        res[f"{per}_sample_share_all"] = float(w[f"k_{per}"].sum() / w[f"n_{per}"].sum())
    both = w[(w["n_early"] >= MIN_SAMPLES) & (w["n_late"] >= MIN_SAMPLES)].copy()
    both["s_early"], both["s_late"] = both["k_early"] / both["n_early"], both["k_late"] / both["n_late"]
    res["n_aircraft_in_both_periods"] = int(len(both))
    res["same_aircraft_sample_share_early"] = float(both["k_early"].sum() / both["n_early"].sum())
    res["same_aircraft_sample_share_late"] = float(both["k_late"].sum() / both["n_late"].sum())
    d = both["s_late"] - both["s_early"]
    res["paired_diff_median"] = float(d.median())
    res["share_aircraft_rise_gt_0.2"] = float((d > 0.2).mean())
    res["share_aircraft_fall_gt_0.2"] = float((d < -0.2).mean())
    only_late = w[(w["n_late"] >= MIN_SAMPLES) & (w["n_early"] < MIN_SAMPLES)]
    only_early = w[(w["n_early"] >= MIN_SAMPLES) & (w["n_late"] < MIN_SAMPLES)]
    res["only_late_aircraft"] = int(len(only_late))
    res["only_late_sample_share"] = float(only_late["k_late"].sum() / max(only_late["n_late"].sum(), 1))
    res["only_early_aircraft"] = int(len(only_early))
    res["only_early_sample_share"] = float(only_early["k_early"].sum() / max(only_early["n_early"].sum(), 1))
    res["note"] = ("Descriptive, dev days only. A rise for the same aircraft argues against a pure fleet mix explanation but does not "
                   "identify a cause. No attribution to any actor.")  # fmt: skip
    out.write_text(json.dumps(res, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
