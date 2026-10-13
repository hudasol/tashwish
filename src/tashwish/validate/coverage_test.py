"""Coverage model failure test against held-back traffic.

Question: when the model fitted on baseline days says a (cell, slot, stratum) is covered, does a NEW day actually deliver
enough aircraft to test anything? And when it says no_coverage, is that true? Unit: (cell, 3 h slot, enroute) on a scoring day;
"enough" = at least MIN_AIRCRAFT_PER_CELL distinct aircraft observed (a missing row counts as zero aircraft).

Error types:
  false_coverage   class covered, new day NOT enough       (the dangerous error: a quiet map claims it could see)
  missed_coverage  class no_coverage, new day enough       (conservative error: we refuse to speak where we could have)
Also a SYNTHETIC thinning test: drop a fraction of aircraft from a real day (simulated receiver loss) and see whether the
status honestly degrades instead of staying `ok`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config as cfg
from ..coverage.model import apply_coverage, slot_of_day
from ..metrics.stats import wilson_interval
from ..pipeline import metrics_for_day
from .inject import mark_synthetic, seed_for

GRID = cfg.GRID_MAIN


def triple_outcomes(cov: pd.DataFrame, cb_day: pd.DataFrame, day: str, grid: cfg.Grid = GRID) -> pd.DataFrame:
    """One row per (cell, slot, enroute) known to the model OR observed on the day, with class and new-day count."""
    e = cb_day[cb_day["stratum"] == "enroute"].copy()
    e["slot"] = slot_of_day(e["bucket"], grid)
    agg = {"n_new": ("n_aircraft", "sum")}
    if "status" in e.columns:
        agg["status"] = ("status", "first")  # one row per (cell, slot) on a single day and stratum
    obs = e.groupby(["cell", "slot"], as_index=False).agg(**agg)
    base = cov[cov["stratum"] == "enroute"][["cell", "slot", "presence", "mean_n", "coverage_class"]]
    m = base.merge(obs, on=["cell", "slot"], how="outer")
    m["coverage_class"] = m["coverage_class"].fillna("no_coverage")  # never seen in baseline => no coverage
    m["presence"] = m["presence"].fillna(0.0)
    m["mean_n"] = m["mean_n"].fillna(0.0)
    m["n_new"] = m["n_new"].fillna(0).astype(int)
    m["enough"] = m["n_new"] >= cfg.MIN_AIRCRAFT_PER_CELL
    if "status" in m.columns:
        m["status"] = m["status"].fillna("no_row")
    m["day"] = day
    return m


def summarize(outcomes: pd.DataFrame) -> dict:
    """Pooled rates with Wilson intervals (units are not independent: also see per_day) and per-day dispersion."""
    res: dict = {}
    for cls in ("covered", "marginal", "no_coverage"):
        sub = outcomes[outcomes["coverage_class"] == cls]
        n, k = len(sub), int(sub["enough"].sum())
        lo, hi = wilson_interval(k, n) if n else (np.nan, np.nan)
        res[cls] = {"n_units": n, "n_enough": k, "p_enough": k / n if n else np.nan, "ci_lo": lo, "ci_hi": hi}
    cov = outcomes[outcomes["coverage_class"] == "covered"]
    nc = outcomes[outcomes["coverage_class"] == "no_coverage"]
    res["false_coverage_rate"] = float((~cov["enough"]).mean()) if len(cov) else np.nan
    res["missed_coverage_rate"] = float(nc["enough"].mean()) if len(nc) else np.nan
    per_day = outcomes.groupby("day").apply(
        lambda g: pd.Series(
            {
                "false_coverage": float((~g[g.coverage_class == "covered"]["enough"]).mean())
                if (g.coverage_class == "covered").any()
                else np.nan,
                "missed_coverage": float(g[g.coverage_class == "no_coverage"]["enough"].mean())
                if (g.coverage_class == "no_coverage").any()
                else np.nan,
                "n_covered": int((g.coverage_class == "covered").sum()),
            }
        ),
        include_groups=False,
    )
    res["per_day"] = per_day.reset_index().to_dict(orient="records")
    # by time of day (slot) for covered units
    by_slot = {}
    for slot, g in cov.groupby("slot"):
        k = int((~g["enough"]).sum())
        lo, hi = wilson_interval(k, len(g))
        by_slot[int(slot)] = {"n": len(g), "false_coverage": k / len(g), "ci_lo": lo, "ci_hi": hi}
    res["covered_by_slot"] = by_slot
    if "status" in outcomes.columns:
        # What the system finally SAYS about covered units that turned out not to have enough aircraft. `ok` would be
        # a wrong claim of testability; it cannot happen by construction (ok requires enough), and this verifies it.
        bad = cov[~cov["enough"]]
        res["covered_not_enough_status"] = {str(k): int(v) for k, v in bad["status"].value_counts().items()}
        res["covered_not_enough_total"] = int(len(bad))
        res["wrongly_ok"] = int(((outcomes["status"] == "ok") & ~outcomes["enough"]).sum())
    return res


def bootstrap_over_days(outcomes: pd.DataFrame, which: str, reps: int = 2000, seed: int = 11) -> tuple[float, float]:
    """Percentile interval of a pooled rate when whole days are resampled (accounts for within-day dependence)."""
    days = sorted(outcomes["day"].unique())
    rng = np.random.default_rng(seed)
    groups = {d: outcomes[outcomes["day"] == d] for d in days}
    vals = []
    for _ in range(reps):
        pick = rng.choice(len(days), size=len(days), replace=True)
        o = pd.concat([groups[days[i]] for i in pick])
        if which == "false":
            c = o[o["coverage_class"] == "covered"]
            vals.append(float((~c["enough"]).mean()) if len(c) else np.nan)
        else:
            c = o[o["coverage_class"] == "no_coverage"]
            vals.append(float(c["enough"].mean()) if len(c) else np.nan)
    return float(np.nanpercentile(vals, 2.5)), float(np.nanpercentile(vals, 97.5))


def next_bucket_check(cb_day_covered: pd.DataFrame, grid: cfg.Grid = GRID) -> dict:
    """C4: among covered triples, is `coverage_lost` now associated with fewer aircraft in the NEXT bucket than `ok` now?"""
    d = cb_day_covered[
        (cb_day_covered["stratum"] == "enroute") & (cb_day_covered["coverage_class"] == "covered")
    ].copy()
    step = pd.Timedelta(hours=grid.bucket_hours)
    nxt = d[["cell", "bucket", "n_aircraft"]].copy()
    nxt["bucket"] = nxt["bucket"] - step
    m = d.merge(nxt.rename(columns={"n_aircraft": "n_next"}), on=["cell", "bucket"], how="left")
    m["n_next"] = m["n_next"].fillna(0)
    out = {}
    for status in ("ok", "coverage_lost", "insufficient"):
        g = m[m["status"] == status]
        k = int((g["n_next"] >= cfg.MIN_AIRCRAFT_PER_CELL).sum())
        lo, hi = wilson_interval(k, len(g)) if len(g) else (np.nan, np.nan)
        out[status] = {"n": len(g), "p_enough_next": k / len(g) if len(g) else np.nan, "ci_lo": lo, "ci_hi": hi}
    return out


def thin_ab(ab: pd.DataFrame, keep: float, seed: int) -> pd.DataFrame:
    """SYNTHETIC receiver loss: keep a deterministic random fraction of aircraft (all their rows) in the day."""
    ids = np.array(sorted(ab["icao24"].unique()))
    rng = np.random.default_rng(seed_for("thin", seed, keep))
    kept = set(ids[rng.random(len(ids)) < keep])
    return mark_synthetic(ab[ab["icao24"].isin(kept)].copy())


def thinning_test(
    ab_day: pd.DataFrame, ctx, day: str, fractions=(1.0, 0.75, 0.5, 0.25), grid: cfg.Grid = GRID
) -> list[dict]:
    """For covered enroute triples: share that stay `ok`, turn `insufficient`, turn `coverage_lost` as traffic is thinned."""
    from .harness import day_buckets

    rows = []
    for f in fractions:
        ab = thin_ab(ab_day, f, seed=1) if f < 1 else ab_day
        cb = apply_coverage(
            metrics_for_day(ab, ctx.persistent), ctx.cov, grid, ctx.base_days, window_buckets=day_buckets(day, grid)
        )
        e = cb[(cb["stratum"] == "enroute") & (cb["coverage_class"] == "covered")]
        n = len(e)
        for status in ("ok", "insufficient", "coverage_lost"):
            k = int((e["status"] == status).sum())
            lo, hi = wilson_interval(k, n) if n else (np.nan, np.nan)
            rows.append({"day": day, "keep_fraction": f, "status": status, "n_covered_units": n, "share": k / n if n else np.nan,
                         "ci_lo": lo, "ci_hi": hi, "data_class": "synthetic" if f < 1 else "observed"})  # fmt: skip
    return rows
