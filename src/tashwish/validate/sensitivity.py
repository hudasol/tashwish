"""Sensitivity study on REAL observed DEV days only (never held-out days).

For each setting we re-run the full detection chain on every dev day (each scored with baselines fitted on the other dev days)
and compare event counts and event locations with the default configuration. One parameter changes at a time, +/- about 25%
or the nearest sensible step, plus traffic thinning (drop aircraft, a density stress) and a smaller coverage/baseline fit.
Day to day variation is the spread of the default configuration's daily counts.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pandas as pd

from .. import config as cfg
from ..metrics.loader import load_points
from ..pipeline import build_ab
from .coverage_test import thin_ab
from .harness import GRID, build_context, score_ab

SETTINGS: list[tuple[str, dict, dict]] = [
    # (label, cfg overrides, extra options)
    ("default", {}, {}),
    ("min_bad=2", {"DETECT_MIN_BAD": 2}, {}),
    ("min_bad=4", {"DETECT_MIN_BAD": 4}, {}),
    ("lower_bound=0.15", {"DETECT_MIN_LOWER_BOUND": 0.15}, {}),
    ("lower_bound=0.25", {"DETECT_MIN_LOWER_BOUND": 0.25}, {}),
    ("fdr_q=0.01", {"DETECT_FDR_Q": 0.01}, {}),
    ("fdr_q=0.10", {"DETECT_FDR_Q": 0.10}, {}),
    ("p0_floor=0.015", {"DETECT_P0_FLOOR": 0.015}, {}),
    ("p0_floor=0.025", {"DETECT_P0_FLOOR": 0.025}, {}),
    ("min_aircraft=4", {"MIN_AIRCRAFT_PER_CELL": 4}, {}),
    ("min_aircraft=6", {"MIN_AIRCRAFT_PER_CELL": 6}, {}),
    ("spoof_min_kt=490", {"SPOOF_JUMP_MIN_KT": 490.0}, {}),
    ("spoof_min_kt=810", {"SPOOF_JUMP_MIN_KT": 810.0}, {}),
    ("spoof_cluster_km=15", {"SPOOF_CLUSTER_KM": 15.0}, {}),
    ("spoof_cluster_km=25", {"SPOOF_CLUSTER_KM": 25.0}, {}),
    ("spoof_min_aircraft=2", {"SPOOF_MIN_AIRCRAFT": 2}, {}),
    ("spoof_min_aircraft=4", {"SPOOF_MIN_AIRCRAFT": 4}, {}),
    ("traffic_keep=0.75", {}, {"keep": 0.75}),
    ("traffic_keep=0.50", {}, {"keep": 0.50}),
    ("baseline_days_half", {}, {"half_baseline": True}),
]


@contextlib.contextmanager
def patched(**kw):
    old = {k: getattr(cfg, k) for k in kw}
    try:
        for k, v in kw.items():
            setattr(cfg, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(cfg, k, v)


def event_footprint(ev_jam: pd.DataFrame, ev_spoof: pd.DataFrame) -> list[tuple[str, frozenset]]:
    """Each event as a set of space-time keys so overlap between settings can be measured (Jaccard)."""
    out = []
    step = pd.Timedelta(hours=GRID.bucket_hours)
    for e in ev_jam.itertuples():
        ts = pd.date_range(e.start, e.end - step, freq=step)
        out.append(("jam", frozenset((c, t) for c in e.cells.split(",") for t in ts)))
    for e in ev_spoof.itertuples():
        t0 = e.start.floor(f"{GRID.bucket_hours}h")
        out.append(("spoof", frozenset({(f"{round(e.origin_lat, 0)}:{round(e.origin_lon, 0)}", t0)})))
    return out


def jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if (a or b) else 1.0


def run_setting(
    interim: Path, dev_days: list[str], label: str, overrides: dict, opts: dict, ctx_cache: dict
) -> list[dict]:
    rows = []
    with patched(**overrides):
        for day in dev_days:
            base = dev_days
            if opts.get("half_baseline"):
                base = dev_days[::2] if day not in dev_days[::2] else dev_days[1::2] + [day]
            key = (day, tuple(base), tuple(sorted(overrides.items())))
            if key not in ctx_cache:
                ctx_cache.clear()  # keep memory bounded: one context at a time
                ctx_cache[key] = build_context(interim, base, day)
            ctx = ctx_cache[key]
            ab = build_ab(interim, day)
            pts = load_points(interim, [day])
            if "keep" in opts:
                ab = thin_ab(ab, opts["keep"], seed=3)
                keep_ids = set(ab["icao24"].unique())
                pts = pts[pts["icao24"].isin(keep_ids)]
            res = score_ab(ab, pts, ctx, day)
            fp = event_footprint(res["jam_events"], res["spoof_events"])
            rows.append({"setting": label, "day": day, "n_jam": len(res["jam_events"]), "n_spoof": len(res["spoof_events"]),
                         "n_events": len(res["events"]), "footprints": fp})  # fmt: skip
    return rows


def summarize(all_rows: list[dict]) -> dict:
    df = pd.DataFrame(all_rows)
    base = df[df["setting"] == "default"].set_index("day")
    out = {"settings": {}}
    daily = base["n_events"]
    out["day_to_day"] = {"mean": float(daily.mean()), "std": float(daily.std(ddof=1)) if len(daily) > 1 else float("nan"),
                         "cv": float(daily.std(ddof=1) / daily.mean()) if daily.mean() > 0 and len(daily) > 1 else float("nan"),
                         "per_day": {d: int(v) for d, v in daily.items()}}  # fmt: skip
    for label, g in df.groupby("setting", sort=False):
        g = g.set_index("day")
        kept = tot = 0
        for day, brow in base.iterrows():
            if day not in g.index:
                continue
            for kind, fp in brow["footprints"]:
                tot += 1
                best = max((jaccard(fp, f2) for k2, f2 in g.loc[day, "footprints"] if k2 == kind), default=0.0)
                kept += best >= 0.5
        out["settings"][label] = {
            "n_events": int(g["n_events"].sum()), "n_jam": int(g["n_jam"].sum()), "n_spoof": int(g["n_spoof"].sum()),
            "events_per_day_mean": float(g["n_events"].mean()),
            "baseline_events": tot, "baseline_events_kept_jaccard_ge_0.5": int(kept),
            "share_kept": kept / tot if tot else float("nan"),
        }  # fmt: skip
    d0 = out["settings"]["default"]["n_events"]
    for s in out["settings"].values():
        s["abs_change_vs_default"] = int(s["n_events"] - d0)
        s["rel_change_vs_default"] = (s["n_events"] - d0) / d0 if d0 else float("nan")
    return out
