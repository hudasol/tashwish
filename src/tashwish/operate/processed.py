"""Per-day processed outputs (no aircraft identifiers). Written atomically; a day directory is complete or absent."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

CB_KEEP = ["cell", "bucket", "stratum", "n_aircraft", "k_strong", "share_strong", "ci_lo_strong", "ci_hi_strong",
           "status", "coverage_class", "slot"]  # fmt: skip


def write_day(root: Path, day: str, cb: pd.DataFrame, events: pd.DataFrame, *, split: str, mode: str, rows: int,
              aircraft: int, ingested_at: str | None, provenance: dict | None = None) -> None:  # fmt: skip
    d = root / "days" / day
    tmp = root / "days" / f".{day}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    cb[CB_KEEP].to_parquet(tmp / "cb.parquet", index=False)
    ev = events.drop(columns=[c for c in ("components",) if c in events.columns]).copy()
    ev.to_parquet(tmp / "events.parquet", index=False)
    meta = {"day": day, "split": split, "mode": mode, "data_class": "observed", "rows": int(rows),
            "aircraft": int(aircraft), "ingested_at": ingested_at, "n_events": int(len(ev))}  # fmt: skip
    if provenance:
        meta["provenance"] = provenance
    (tmp / "day.json").write_text(json.dumps(meta, indent=1, sort_keys=True))
    if d.exists():
        shutil.rmtree(d)
    tmp.replace(d)


def list_days(root: Path) -> list[str]:
    p = root / "days"
    return sorted(x.name for x in p.iterdir() if x.is_dir() and not x.name.startswith(".")) if p.exists() else []


def read_day_meta(root: Path, day: str) -> dict:
    return json.loads((root / "days" / day / "day.json").read_text())
