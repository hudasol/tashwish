"""Build the frozen baseline state from the DEV days and write processed per-day outputs for the study window.

  python -m tashwish.operate.refit --interim data/interim --state state --processed processed

DEV days are scored leave-one-day-out (a day never vouches for itself). HELD-OUT days are scored with the frozen state.
Held-out days are scored here only after the one-time held-out evaluation has run (results/held_out/DONE), so this step
can never be used to peek at them earlier. Processed outputs hold no aircraft identifiers.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ..coverage.model import apply_coverage, fit_coverage
from ..detect.discriminate import combine
from ..detect.jamming import detect_jamming, fit_p0
from ..detect.spoofing import build_spoof_events, find_jumps
from ..metrics.loader import load_points
from ..split import split
from ..validate.harness import ContextFactory
from .processed import write_day
from .score import window_buckets
from .state import GRID, FrozenState, hash_ids, score_day_frozen


def ingested_manifest(interim: Path) -> dict[str, dict]:
    out = {}
    p = interim / "manifest.jsonl"
    if p.exists():
        for line in p.read_text().splitlines():
            r = json.loads(line)
            if r.get("status") == "complete":
                out[r["day"]] = r
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interim", default="data/interim", type=Path)
    ap.add_argument("--state", default="state", type=Path)
    ap.add_argument("--processed", default="processed", type=Path)
    ap.add_argument("--results", default="results", type=Path)
    ap.add_argument("--no-held-out", action="store_true")
    a = ap.parse_args()
    dev, held = split()
    dev_days = [d.isoformat() for d in dev]
    held_days = [d.isoformat() for d in held]
    man = ingested_manifest(a.interim)
    missing = [d for d in dev_days if d not in man]
    if missing:
        raise SystemExit(f"dev days not ingested: {missing}")
    fac = ContextFactory(a.interim, dev_days)
    cb_all = pd.concat([fac.cb[d] for d in dev_days], ignore_index=True)
    persistent_h = fac.persistent.assign(icao24=hash_ids(fac.persistent["icao24"]))[["icao24"]]
    st = FrozenState(
        dev_days,
        persistent_h,
        fit_coverage(cb_all, dev_days, GRID),
        fit_p0(cb_all, dev_days),
        {"baseline_end": max(dev_days + held_days), "study_start": min(dev_days + held_days),
         "n_persistent": int(len(persistent_h)), "fitted_on": "dev days only"},
    )  # fmt: skip
    st.save(a.state)
    print(f"state written: {len(dev_days)} baseline days, {len(persistent_h)} persistent emitters")
    for d in dev_days:
        ctx = fac.context(d)
        cb = apply_coverage(fac.cb[d], ctx.cov, GRID, ctx.base_days, window_buckets=window_buckets(d))
        _f, jam = detect_jamming(cb, ctx.base_days, GRID, p0=ctx.p0)
        pts = load_points(a.interim, [d])
        ev = combine(jam, build_spoof_events(find_jumps(pts)))
        write_day(a.processed, d, cb, ev, split="dev", mode="dev_leave_one_day_out",
                  rows=len(pts), aircraft=int(pts["icao24"].nunique()), ingested_at=man[d].get("ingested_utc"))  # fmt: skip
        print("processed", d, flush=True)
    if a.no_held_out:
        return
    if not (a.results / "held_out" / "DONE").exists():
        raise SystemExit("held-out evaluation has not run yet; refusing to score held-out days (use --no-held-out)")
    for d in held_days:
        if d not in man:
            raise SystemExit(f"held-out day not ingested: {d}")
        r = score_day_frozen(a.interim, d, st)
        write_day(a.processed, d, r["cb"], r["events"], split="held_out", mode="frozen_baseline",
                  rows=r["rows"], aircraft=r["aircraft"], ingested_at=man[d].get("ingested_utc"))  # fmt: skip
        print("processed", d, flush=True)


if __name__ == "__main__":
    main()
