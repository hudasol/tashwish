"""Scheduled incremental run: ingest the next archive day(s), score against the frozen baseline, append to processed/.

  python -m tashwish.operate.incremental --state state --processed processed --spool SPOOL --max-days 1

Exit 0 when nothing is due or the next day is not yet published (status noop). Exit non-zero on failure, in which case
freshness.json is marked failed with fallback_active = true and latest_day/generated_at are left unchanged, so the
dashboard keeps serving the last good data and says so.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ..ingest.pipeline import IngestConfig, ingest_day
from ..ingest.source import DayNotAvailable, DownloadError
from .processed import list_days, write_day
from .state import FrozenState, score_day_frozen

FRESH_SCHEMA = "tashwish.freshness.v1"


def now_z() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_fresh(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"schema": FRESH_SCHEMA, "generated_at": None, "latest_day": None}


def write_fresh(path: Path, f: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(f, indent=1, sort_keys=True))
    tmp.replace(path)


def next_days(processed: Path, st: FrozenState, max_days: int, start_day: str | None) -> list[str]:
    if start_day:
        first = date.fromisoformat(start_day)
    else:
        have = list_days(processed)
        last = date.fromisoformat(max([st.meta["baseline_end"], *have]))
        first = last + timedelta(days=1)
    horizon = datetime.now(UTC).date() - timedelta(days=1)  # a UTC day is only complete after midnight
    out, d = [], first
    while d <= horizon and len(out) < max_days:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", type=Path, default=Path("state"))
    ap.add_argument("--processed", type=Path, default=Path("processed"))
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--max-days", type=int, default=1)
    ap.add_argument("--start-day")
    a = ap.parse_args(argv)
    fpath = a.processed / "freshness.json"
    fresh = read_fresh(fpath)
    fresh.update({"schema": FRESH_SCHEMA, "last_run_at": now_z(), "days_added": 0})
    try:
        st = FrozenState.load(a.state)
        todo = next_days(a.processed, st, max(1, a.max_days), a.start_day)
        if not todo:
            fresh.update({"last_run_status": "noop", "fallback_active": False, "last_error": None})
            write_fresh(fpath, fresh)
            print("nothing due")
            return 0
        work = a.spool / "interim"
        added = 0
        for day in todo:
            icfg = IngestConfig(out_dir=work, spool_dir=a.spool / "raw", workers=2)
            try:
                ingest_day(day, icfg)
            except DayNotAvailable as e:
                print(f"{day}: not published yet ({e!r}); stopping")
                break
            r = score_day_frozen(work, day, st)
            write_day(a.processed, day, r["cb"], r["events"], split="incremental", mode="frozen_baseline",
                      rows=r["rows"], aircraft=r["aircraft"], ingested_at=now_z())  # fmt: skip
            for p in work.glob(f"points_{day}*"):
                p.unlink()
            shutil.rmtree(work / "ab", ignore_errors=True)
            added += 1
            fresh.update({"generated_at": now_z(), "latest_day": day})
        fresh.update({"last_run_status": "ok" if added else "noop", "fallback_active": False, "days_added": added,
                      "last_error": None})  # fmt: skip
        write_fresh(fpath, fresh)
        print(f"added {added} day(s)")
        return 0
    except (DownloadError, Exception) as e:  # noqa: BLE001
        traceback.print_exc()
        fresh.update(
            {"last_run_status": "failed", "fallback_active": True, "last_error": f"{type(e).__name__}: {e}"[:500]}
        )
        write_fresh(fpath, fresh)
        return 1


if __name__ == "__main__":
    sys.exit(main())
