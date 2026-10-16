"""Secondary analysis: how many jamming-like flags survive when the binomial test allows day to day overdispersion.

The detector compares the degraded count k of a tested cell bucket (n aircraft) with Binomial(n, p0). That treats p0 as known
and every aircraft as independent. If degraded reports cluster (aircraft in one cell bucket share conditions), the binomial
tail is too thin and too many cell buckets look significant. This script replaces the binomial tail by a beta binomial tail with
the same mean p0 and an intra cell bucket correlation rho, keeps every other rule of `tashwish.detect.jamming` (Benjamini and
Yekutieli per day at the same q, at least the same minimum degraded aircraft, the same Wilson lower bound gate), and counts the
flags that survive.

DEVELOPMENT days only (held out days are not read). Data class OBSERVED: real days, nothing injected. This is a sensitivity
analysis; it does not change the detector, any threshold or any published result.

  1. For each development day, p0 is refitted exactly as the validation harness does: `fit_p0` on the other development days
     with the same degraded regime label. The binomial flags and events are rebuilt and compared with the committed events.
  2. rho is estimated per degraded regime by moments, E[(k - n p0)^2 / (n p0 (1 - p0))] = 1 + (n - 1) rho, over tested
     units that the binomial test did not flag (so that the flags being tested do not inflate their own rho). A day bootstrap
     (whole days resampled within the regime) gives an interval for rho.
  3. Flags and events are recounted under the beta binomial tail at the point estimate and at both ends of the rho interval.

Usage: python scripts/beta_binomial_sensitivity.py   (writes results/secondary/beta_binomial.json)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.stats as sps

from tashwish import config as cfg
from tashwish.detect.jamming import build_events, fit_p0, flag_buckets
from tashwish.metrics.stats import benjamini_hochberg
from tashwish.split import split

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "secondary" / "beta_binomial.json"
GRID = cfg.GRID_MAIN
JAM_KINDS = ("jamming_like", "both")
REPS, SEED = 2000, 20261016
RHO_GRID = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05)  # how much overdispersion removes the flags


def load(day: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = ROOT / "processed" / "days" / day
    return pd.read_parquet(d / "cb.parquet"), pd.read_parquet(d / "events.parquet")


def tested_with_p0(dev: list[str], labels: dict[str, str], cbs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Binomial flag table of every development day, with p0 fitted on the other same label development days."""
    out = []
    for d in dev:
        p0_days = [x for x in dev if x != d and labels[x] == labels[d]]
        p0 = fit_p0(pd.concat([cbs[x] for x in p0_days], ignore_index=True), p0_days)
        f = flag_buckets(cbs[d], p0_days, p0=p0)
        out.append(f.assign(day=d, degraded=labels[d]))
    return pd.concat(out, ignore_index=True)


def rho_moments(t: pd.DataFrame) -> float:
    n, k, p = t["n_aircraft"].to_numpy(float), t["k"].to_numpy(float), t["p0"].to_numpy(float)
    chi = (k - n * p) ** 2 / (n * p * (1 - p))
    return float(max(0.0, (chi - 1).sum() / (n - 1).sum()))


def rho_bootstrap(t: pd.DataFrame) -> tuple[float, float]:
    days = sorted(t["day"].unique())
    groups = {d: t[t["day"] == d] for d in days}
    rng = np.random.default_rng(SEED)
    vals = [
        rho_moments(pd.concat([groups[days[i]] for i in rng.integers(0, len(days), len(days))])) for _ in range(REPS)
    ]
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def betabinom_flags(t: pd.DataFrame, rho: float) -> pd.Series:
    """Same rules as the detector, with a beta binomial tail of mean p0 and intra unit correlation rho."""
    if rho <= 0:
        p = sps.binom.sf(t["k"] - 1, t["n_aircraft"], t["p0"])
    else:
        a = t["p0"] * (1 - rho) / rho
        b = (1 - t["p0"]) * (1 - rho) / rho
        p = sps.betabinom.sf(t["k"] - 1, t["n_aircraft"], a, b)
    p = pd.Series(np.asarray(p, dtype=float), index=t.index)
    ok = pd.Series(False, index=t.index)
    for _, idx in t.groupby("day").groups.items():
        ok.loc[idx] = benjamini_hochberg(p.loc[idx].to_numpy(), cfg.DETECT_FDR_Q, dependent=True)
    return ok & (t["k"] >= cfg.DETECT_MIN_BAD) & (t["ci_lo"] >= cfg.DETECT_MIN_LOWER_BOUND)


def count_events(t: pd.DataFrame, flag: pd.Series) -> int:
    return int(sum(len(build_events(g.assign(flag=flag.loc[g.index]), GRID)) for _, g in t.groupby("day")))


def main() -> None:
    dev = [d.isoformat() for d in split()[0]]
    reg = pd.read_csv(ROOT / "results" / "regimes.csv").set_index("day")
    labels = {d: reg.loc[d, "degraded"] for d in dev}
    cbs, evs = {}, {}
    for d in dev:
        cbs[d], evs[d] = load(d)
    t = tested_with_p0(dev, labels, cbs)

    # 1. reproduction check against committed events
    rebuilt = {d: len(build_events(t[t["day"] == d], GRID)) for d in dev}
    # a jamming event joined to two spoofing events appears in two `both` rows: count distinct jamming components (cells, degraded count, p value)
    committed = {
        d: len(evs[d].loc[evs[d]["kind"].isin(JAM_KINDS), ["cells", "k_degraded", "min_p"]].drop_duplicates())
        for d in dev
    }
    repro = {"rebuilt_jamming_events": sum(rebuilt.values()), "committed_distinct_jamming_components": sum(committed.values()),
             "days_differing": [d for d in dev if rebuilt[d] != committed[d]]}  # fmt: skip

    res = {"schema": "tashwish.beta_binomial.v1", "data_class": "OBSERVED", "days": "development days only",
           "n_days": len(dev), "reproduction": repro, "by_degraded_regime": {}}  # fmt: skip
    for r, g in t.groupby("degraded"):
        rho = rho_moments(g[~g["flag"]])
        lo, hi = rho_bootstrap(g[~g["flag"]])
        rows = {}
        for name, val in (("binomial", 0.0), ("rho_low", lo), ("rho_point", rho), ("rho_high", hi)):
            f = g["flag"] if name == "binomial" else betabinom_flags(g, val)
            rows[name] = {"rho": val, "flags": int(f.sum()), "events": count_events(g, f)}
        u = g[~g["flag"]]
        chi = (u["k"] - u["n_aircraft"] * u["p0"]) ** 2 / (u["n_aircraft"] * u["p0"] * (1 - u["p0"]))
        res["by_degraded_regime"][r] = {
            "n_days": int(g["day"].nunique()),
            "n_tested_units": int(len(g)),
            "mean_dispersion_ratio": float(chi.mean()),
            "flags_by_rho_grid": {str(x): int(betabinom_flags(g, x).sum()) for x in RHO_GRID},
            "rho": rho,
            "rho_ci": [lo, hi],
            "rho_interval": "day bootstrap 95%, 2000 resamples, units not flagged by the binomial test",
            "counts": rows,
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
