"""Day level regimes, so that baselines are fitted to comparable days.

The development window contains a sharp change: from 2026-03-02 the share of degraded en route reports rises from about 1 percent
to well above 10 percent for the same aircraft, and traffic falls to a fraction of its earlier level (see
`results/dev/regime_check.json`). A single pooled baseline is wrong on both sides of that change. Two mechanical regime labels
are therefore computed from the scored day itself, before any detection:

  traffic regime   `reduced` when total en route aircraft per cell-bucket for the day is below TRAFFIC_REDUCED_RATIO times the
                   reference, `normal` otherwise. Selects the coverage model (which cells can be seen at all).
  degraded regime  `elevated` when the region wide degraded share among tested en route cell-buckets is at least
                   DEGRADED_ELEVATED_SHARE, `baseline` otherwise. Selects the per cell baseline share p0.

The reference traffic level is the median over DEVELOPMENT days. Labels use only aggregate counts of the scored day; no cell level
or event information. Baselines for a label are fitted on development days with the same label only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as cfg

TRAFFIC_REDUCED_RATIO = 0.5
DEGRADED_ELEVATED_SHARE = 0.05
MIN_REGIME_DAYS = 3  # fewer development days than this and a regime cannot be scored


class RegimeError(Exception):
    pass


def day_stats(cb: pd.DataFrame) -> dict:
    """Aggregates of one day's cell-bucket metrics (before coverage): en route units and tested degraded share."""
    e = cb[cb["stratum"] == "enroute"]
    units = float(e["n_aircraft"].sum())
    t = e[e["n_aircraft"] >= cfg.MIN_AIRCRAFT_PER_CELL]
    n = float(t["n_aircraft"].sum())
    share = float(t["k_strong"].sum() / n) if n else float("nan")
    return {"units": units, "share": share}


def traffic_regime(units: float, ref_units: float) -> str:
    return "reduced" if units < TRAFFIC_REDUCED_RATIO * ref_units else "normal"


def degraded_regime(share: float) -> str:
    return "elevated" if (not np.isnan(share) and share >= DEGRADED_ELEVATED_SHARE) else "baseline"
