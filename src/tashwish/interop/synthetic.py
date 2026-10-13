"""SYNTHETIC cell-bucket tables and events for the interop sample and tests. Everything here is invented, never observed.

The statuses and coverage classes are assigned by hand (not fitted), so the table exercises every state of the contract:
ok in a quiet cell, ok in a cell with a synthetic event, insufficient, coverage_lost and a non-en-route band.
"""

from __future__ import annotations

import h3
import numpy as np
import pandas as pd

from .. import config as cfg
from ..metrics.stats import wilson_interval

SYNTHETIC = True
SYNTH_DAY = "2026-01-01"  # outside the real study window on purpose
SYNTH_CENTRE = (25.2, 55.3)


def synthetic_cells(seed: int = 7, grid: cfg.Grid = cfg.GRID_MAIN) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (cell-bucket table with coverage columns, events table), seeded and fully synthetic."""
    rng = np.random.default_rng(seed)
    centre = h3.latlng_to_cell(*SYNTH_CENTRE, grid.h3_res)
    cells = sorted(h3.grid_disk(centre, 1))  # 7 cells
    t0 = pd.Timestamp(f"{SYNTH_DAY}T06:00:00Z")
    buckets = [t0, t0 + pd.Timedelta(hours=grid.bucket_hours)]
    rows = []
    for b in buckets:
        for i, c in enumerate(cells):
            n = int(rng.integers(12, 40))
            k = int(rng.binomial(n, 0.04))
            status, cov = "ok", "covered"
            if i == 5:
                n, k, status, cov = int(rng.integers(1, cfg.MIN_AIRCRAFT_PER_CELL)), 0, "insufficient", "marginal"
            if i == 6 and b == buckets[1]:
                n, k, status, cov = 0, 0, "coverage_lost", "covered"
            if i == 0 and b == buckets[1]:
                n = 30
                k = 17  # synthetic degraded cell
            rows.append({"cell": c, "bucket": b, "stratum": "enroute", "n_aircraft": n, "k_strong": k,
                         "status": status, "coverage_class": cov})  # fmt: skip
    # a second band for one cell, so the alt_band field is exercised
    rows.append({"cell": cells[1], "bucket": buckets[0], "stratum": "high", "n_aircraft": 14, "k_strong": 1,
                 "status": "ok", "coverage_class": "covered"})  # fmt: skip
    cb = pd.DataFrame(rows)
    cb["bucket"] = pd.to_datetime(cb["bucket"], utc=True)
    n = cb["n_aircraft"].to_numpy().astype(float)
    k = cb["k_strong"].to_numpy().astype(float)
    cb["share_strong"] = np.where(n > 0, k / np.where(n > 0, n, 1), np.nan)
    lo, hi = wilson_interval(k, n)
    cb["ci_lo_strong"], cb["ci_hi_strong"] = lo, hi
    events = pd.DataFrame(
        [
            {
                "event_id": "SYN-J-0001",
                "kind": "jamming_like",
                "start": buckets[1],
                "end": buckets[1] + pd.Timedelta(hours=grid.bucket_hours),
                "lat": SYNTH_CENTRE[0],
                "lon": SYNTH_CENTRE[1],
                "cells": cells[0],
            }
        ]
    )
    return cb, events
