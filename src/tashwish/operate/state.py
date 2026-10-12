"""Frozen baseline state used to score new days. Small files, safe to commit.

The state holds the coverage model, the per cell baseline share p0, the list of persistent low emitters (stored as
salted hashes; this is pseudonymisation, not anonymity, because ICAO24 addresses are enumerable) and the baseline day
list. Scoring a new day with this state is the same mode as the held-out evaluation: nothing is fitted on the new day.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .. import config as cfg
from ..coverage.model import apply_coverage
from ..detect.discriminate import combine
from ..detect.jamming import detect_jamming
from ..detect.spoofing import build_spoof_events, find_jumps
from ..metrics.loader import load_points
from ..pipeline import build_ab, metrics_for_day

SCHEMA = "tashwish.state.v1"
HASH_SALT = "tashwish-persist-v1|"
GRID = cfg.GRID_MAIN


def hash_ids(ids: pd.Series) -> pd.Series:
    uniq = ids.unique()
    m = {u: hashlib.sha256((HASH_SALT + str(u)).encode()).hexdigest()[:16] for u in uniq}
    return ids.map(m)


@dataclass
class FrozenState:
    base_days: list[str]
    persistent_h: pd.DataFrame  # column icao24 holds HASHED ids
    cov: pd.DataFrame
    p0: pd.DataFrame
    meta: dict

    def save(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.persistent_h.to_parquet(root / "persistent_hashed.parquet", index=False)
        self.cov.to_parquet(root / "coverage.parquet", index=False)
        self.p0.to_parquet(root / "p0.parquet", index=False)
        meta = {**self.meta, "schema": SCHEMA, "base_days": self.base_days}
        (root / "state.json").write_text(json.dumps(meta, indent=1, sort_keys=True))

    @classmethod
    def load(cls, root: Path) -> FrozenState:
        meta = json.loads((root / "state.json").read_text())
        if meta.get("schema") != SCHEMA:
            raise ValueError(f"unexpected state schema {meta.get('schema')!r}")
        return cls(
            meta["base_days"],
            pd.read_parquet(root / "persistent_hashed.parquet"),
            pd.read_parquet(root / "coverage.parquet"),
            pd.read_parquet(root / "p0.parquet"),
            meta,
        )


def score_day_frozen(interim: Path, day: str, st: FrozenState) -> dict:
    """Ingested day (points parquet in `interim`) -> cell-bucket metrics with coverage status, events."""
    from .score import window_buckets

    ab = build_ab(interim, day, GRID)
    ab = ab.assign(icao24=hash_ids(ab["icao24"]))
    cb = metrics_for_day(ab, st.persistent_h)
    cb = apply_coverage(cb, st.cov, GRID, st.base_days, window_buckets=window_buckets(day))
    _flags, jam = detect_jamming(cb, st.base_days, GRID, p0=st.p0)
    pts = load_points(interim, [day])
    spoof = build_spoof_events(find_jumps(pts))
    ev = combine(jam, spoof)
    n_rows, n_ac = len(pts), int(pts["icao24"].nunique())
    return {"cb": cb, "events": ev, "rows": n_rows, "aircraft": n_ac}
