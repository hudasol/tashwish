"""CLI: python -m tashwish.ingest --day 2026-03-02 [--to 2026-03-06] --out data/interim"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from pathlib import Path

from ..config import DATA_CLASS_OBSERVED
from .pipeline import IngestConfig, ingest_day
from .source import DayNotAvailable, DownloadError


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest adsb.lol globe_history days (Gulf box) to Parquet.")
    ap.add_argument("--day", required=True, help="YYYY-MM-DD (first day)")
    ap.add_argument("--to", help="YYYY-MM-DD (last day, inclusive); default: same as --day")
    ap.add_argument("--out", default="data/interim", type=Path)
    ap.add_argument("--spool", default="data/raw/spool", type=Path)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--keep-spool", action="store_true")
    a = ap.parse_args()
    d = date.fromisoformat(a.day)
    last = date.fromisoformat(a.to) if a.to else d
    cfg = IngestConfig(out_dir=a.out, spool_dir=a.spool, workers=a.workers, keep_spool=a.keep_spool,
                       data_class=DATA_CLASS_OBSERVED)  # fmt: skip
    rc = 0
    while d <= last:
        try:
            ingest_day(d.isoformat(), cfg)
        except (DayNotAvailable, DownloadError) as e:
            print(f"{d}: FAILED: {e!r}")
            rc = 1
        d += timedelta(days=1)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
