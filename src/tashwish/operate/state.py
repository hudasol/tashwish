"""Frozen baseline state used to score new days. Small files; the persistent emitter list is keyed with a secret.

The state holds, per regime (see `tashwish.regime`), the coverage model and the per cell baseline share p0, the reference traffic
level, and the list of persistent low emitters. The persistent list is stored only as HMAC-SHA256 values under a secret key
(environment variable TASHWISH_STATE_KEY, a GitHub Actions secret in production). A public salt would not protect it: ICAO24
addresses form a space of about 16.7 million values that can be enumerated in seconds. Without the key the list cannot be
reversed from the repository, and a third party can rebuild it from public data with their own key (`tashwish.operate.refit`).
Scoring a new day with this state is the same mode as the held-out evaluation: nothing is fitted on the new day.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .. import config as cfg
from .. import regime as rg
from ..coverage.model import apply_coverage
from ..detect.discriminate import combine
from ..detect.jamming import detect_jamming
from ..detect.spoofing import build_spoof_events, find_jumps
from ..metrics.loader import load_points
from ..pipeline import build_ab, metrics_for_day

SCHEMA = "tashwish.state.v2"
KEY_ENV = "TASHWISH_STATE_KEY"
GRID = cfg.GRID_MAIN


def state_key() -> bytes:
    k = os.environ.get(KEY_ENV, "")
    if len(k) < 16:
        raise RuntimeError(f"{KEY_ENV} must be set (at least 16 characters); it keys the persistent emitter list")
    return k.encode()


def hash_ids(ids: pd.Series, key: bytes | None = None) -> pd.Series:
    key = key or state_key()
    m = {u: hmac.new(key, str(u).encode(), hashlib.sha256).hexdigest()[:24] for u in ids.unique()}
    return ids.map(m)


@dataclass
class FrozenState:
    persistent_h: pd.DataFrame  # column icao24 holds KEYED hashes
    cov: dict[str, pd.DataFrame]  # traffic regime -> coverage model
    p0: dict[str, pd.DataFrame]  # degraded regime -> baseline shares
    cov_days: dict[str, list[str]]
    p0_days: dict[str, list[str]]
    meta: dict

    def save(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.persistent_h.to_parquet(root / "persistent_keyed.parquet", index=False)
        pd.concat([c.assign(regime=r) for r, c in self.cov.items()], ignore_index=True).to_parquet(
            root / "coverage.parquet", index=False
        )
        pd.concat([c.assign(regime=r) for r, c in self.p0.items()], ignore_index=True).to_parquet(
            root / "p0.parquet", index=False
        )
        meta = {**self.meta, "schema": SCHEMA, "cov_days": self.cov_days, "p0_days": self.p0_days}
        (root / "state.json").write_text(json.dumps(meta, indent=1, sort_keys=True))

    @classmethod
    def load(cls, root: Path) -> FrozenState:
        meta = json.loads((root / "state.json").read_text())
        if meta.get("schema") != SCHEMA:
            raise ValueError(f"unexpected state schema {meta.get('schema')!r}")

        def split(df):
            return {r: g.drop(columns="regime").reset_index(drop=True) for r, g in df.groupby("regime")}

        return cls(
            pd.read_parquet(root / "persistent_keyed.parquet"),
            split(pd.read_parquet(root / "coverage.parquet")),
            split(pd.read_parquet(root / "p0.parquet")),
            meta["cov_days"],
            meta["p0_days"],
            meta,
        )

    @property
    def ref_units(self) -> float:
        return float(self.meta["ref_units"])


def score_day_frozen(interim: Path, day: str, st: FrozenState) -> dict:
    """Ingested day (points parquet in `interim`) -> cell-bucket metrics with coverage status, events, regimes."""
    from .score import window_buckets

    ab = build_ab(interim, day, GRID)
    ab = ab.assign(icao24=hash_ids(ab["icao24"]))
    cb0 = metrics_for_day(ab, st.persistent_h)
    stats = rg.day_stats(cb0)
    tr, dr = rg.traffic_regime(stats["units"], st.ref_units), rg.degraded_regime(stats["share"])
    if tr not in st.cov or dr not in st.p0:
        raise rg.RegimeError(f"{day}: regime ({tr}, {dr}) has no baseline in the frozen state")
    cb = apply_coverage(cb0, st.cov[tr], GRID, st.cov_days[tr], window_buckets=window_buckets(day))
    _flags, jam = detect_jamming(cb, st.p0_days[dr], GRID, p0=st.p0[dr])
    pts = load_points(interim, [day])
    spoof = build_spoof_events(find_jumps(pts))
    ev = combine(jam, spoof)
    n_rows, n_ac = len(pts), int(pts["icao24"].nunique())
    return {
        "cb": cb,
        "events": ev,
        "rows": n_rows,
        "aircraft": n_ac,
        "regime": {"traffic": tr, "degraded": dr, **stats},
    }
