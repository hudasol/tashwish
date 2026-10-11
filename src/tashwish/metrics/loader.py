"""Load ingested Parquet days into one DataFrame (observed data only unless a synthetic path is given explicitly)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ..config import DATA_CLASS_OBSERVED
from ..schema import points_filename

LOAD_COLS = ["icao24", "ts", "lat", "lon", "alt_baro_ft", "on_ground", "src_type", "nic", "nac_p", "flags", "gs_kt",
             "track_deg", "alt_geom_ft", "ac_type", "version", "q_age_s", "q_carried"]  # fmt: skip


def load_points(interim: Path, days: list[str], data_class: str = DATA_CLASS_OBSERVED, cols=None) -> pd.DataFrame:
    files = [str(interim / points_filename(d, data_class)) for d in days]
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        raise FileNotFoundError(f"missing ingested days: {missing[:3]}")
    if not files:
        raise ValueError("no days given")
    sel = ", ".join(cols or LOAD_COLS)
    lst = ", ".join(f"'{f}'" for f in files)
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")  # otherwise timestamps come back in the machine's local zone
    return con.sql(f"select {sel} from read_parquet([{lst}])").df()
