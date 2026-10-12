from __future__ import annotations

import pandas as pd

from .. import config as cfg


def window_buckets(day: str, grid: cfg.Grid = cfg.GRID_MAIN) -> list[pd.Timestamp]:
    t0 = pd.Timestamp(day, tz="UTC")
    return [t0 + pd.Timedelta(hours=grid.bucket_hours * i) for i in range(24 // grid.bucket_hours)]
