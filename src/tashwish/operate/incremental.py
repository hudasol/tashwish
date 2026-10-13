"""Scheduled incremental run: ingest the next archive day(s), score against the frozen baseline, append to processed/.

  python -m tashwish.operate.incremental --state state --processed processed --spool SPOOL --max-days 1

Exit 0 when nothing is due or the newest day is not yet published (status noop). Exit 1 on a failure or a permanently
missing day (a gap), in which case freshness.json is marked failed with fallback_active = true and
latest_day/generated_at are left unchanged, so the dashboard keeps serving the last good data and says so. Exit 2 when
the request itself is refused (a day inside the study window, or a gap before the requested start day); a refusal
changes nothing and does not touch freshness.json.

Guards:
  * Days inside the study window (tashwish.split STUDY_START to STUDY_END) are refused unless --allow-study-window is
    given. Held out days are scored once through the run once harness, never through this path.
  * latest_day never moves backwards.
  * A requested start day must follow the last processed day directly (no gap).
  * Every processed day records provenance in day.json: code commit, sha256 of state/state.json and the sha256 of the
    ingest manifest record of that day.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import traceback
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ..ingest.pipeline import IngestConfig, ingest_day
from ..ingest.source import DayNotAvailable, DownloadError
from ..split import STUDY_END, STUDY_START
from .processed import list_days, write_day
from .state import FrozenState, score_day_frozen

FRESH_SCHEMA = "tashwish.freshness.v1"
GAP_GRACE_DAYS = 2  # a day older than this many days that is still unpublished counts as permanently missing
ROOT = Path(__file__).resolve().parents[3]


class Refused(Exception):
    """The request is refused before any work; nothing is changed."""


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


def code_commit() -> str:
    sha = os.environ.get("GITHUB_SHA", "").strip()
    if sha:
        return sha
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=20)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def sha256_file(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest_manifest_sha256(work: Path, day: str) -> str | None:
    """sha256 of the last manifest.jsonl record of `day` (the record the ingest wrote for this scoring), if any."""
    p = work / "manifest.jsonl"
    if not p.is_file():
        return None
    last = None
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                if json.loads(line).get("day") == day:
                    last = line.strip()
            except ValueError:
                continue
    return hashlib.sha256(last.encode()).hexdigest() if last else None


def provenance(state_dir: Path, work: Path, day: str) -> dict:
    return {
        "code_commit": code_commit(),
        "state_sha256": sha256_file(state_dir / "state.json"),
        "ingest_manifest_sha256": ingest_manifest_sha256(work, day),
    }


def in_study_window(d: date) -> bool:
    return STUDY_START <= d <= STUDY_END


def next_days(
    processed: Path, st: FrozenState, max_days: int, start_day: str | None, allow_study_window: bool = False
) -> list[str]:
    """Days to process now. Raises `Refused` for a study window day (unless allowed) or a gap before the start day."""
    have = list_days(processed)
    last = date.fromisoformat(max([st.meta["baseline_end"], *have]))
    if start_day:
        first = date.fromisoformat(start_day)
        if first > last + timedelta(days=1):
            raise Refused(
                f"gap: the last processed day is {last.isoformat()} but the start day is {first.isoformat()}; "
                f"start at {(last + timedelta(days=1)).isoformat()} or earlier so that no day is skipped"
            )
    else:
        first = last + timedelta(days=1)
    horizon = datetime.now(UTC).date() - timedelta(days=1)  # a UTC day is only complete after midnight
    out, d = [], first
    while d <= horizon and len(out) < max_days:
        if in_study_window(d) and not allow_study_window:
            raise Refused(
                f"{d.isoformat()} lies inside the study window {STUDY_START.isoformat()} to {STUDY_END.isoformat()}; "
                "refused. Study days are scored by the frozen validation harness (held out days only after the "
                "freeze). Pass --allow-study-window only for a deliberate, documented exception."
            )
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
    ap.add_argument("--allow-study-window", action="store_true", help="permit days inside the study window")
    ap.add_argument(
        "--append-status",
        action="store_true",
        help="keep days_added and an earlier ok status of the same workflow run (use for slots after the first)",
    )
    a = ap.parse_args(argv)
    fpath = a.processed / "freshness.json"
    fresh = read_fresh(fpath)
    prev_added = fresh.get("days_added") if a.append_status else None
    prev_added = list(prev_added) if isinstance(prev_added, list) else []
    prev_status = fresh.get("last_run_status") if a.append_status else None
    old_latest = fresh.get("latest_day")
    fresh.update({"schema": FRESH_SCHEMA, "last_run_at": now_z(), "days_added": prev_added})
    try:
        st = FrozenState.load(a.state)
        todo = next_days(a.processed, st, max(1, a.max_days), a.start_day, a.allow_study_window)
        if not todo:
            status = "ok" if prev_status == "ok" else "noop"
            fresh.update({"last_run_status": status, "fallback_active": False, "last_error": None})
            write_fresh(fpath, fresh)
            print("nothing due")
            return 0
        work = a.spool / "interim"
        horizon = datetime.now(UTC).date() - timedelta(days=1)
        added: list[str] = []
        for day in todo:
            icfg = IngestConfig(out_dir=work, spool_dir=a.spool / "raw", workers=2)
            try:
                ingest_day(day, icfg)
            except DayNotAvailable as e:
                if date.fromisoformat(day) <= horizon - timedelta(days=GAP_GRACE_DAYS):
                    raise RuntimeError(f"gap: {day} is still unpublished after {GAP_GRACE_DAYS} days ({e!r})") from e
                print(f"{day}: not published yet ({e!r}); stopping")
                break
            r = score_day_frozen(work, day, st)
            write_day(
                a.processed,
                day,
                r["cb"],
                r["events"],
                split="incremental",
                mode="frozen_baseline",
                rows=r["rows"],
                aircraft=r["aircraft"],
                ingested_at=now_z(),
                provenance=provenance(a.state, work, day),
            )
            for p in work.glob(f"points_{day}*"):
                p.unlink()
            shutil.rmtree(work / "ab", ignore_errors=True)
            added.append(day)
            fresh["days_added"] = [*fresh["days_added"], day]
            old_latest = max(day, old_latest) if old_latest else day  # never move backwards
            fresh.update({"generated_at": now_z(), "latest_day": old_latest})
        status = "ok" if (added or prev_status == "ok") else "noop"
        fresh.update({"last_run_status": status, "fallback_active": False, "last_error": None})
        write_fresh(fpath, fresh)
        print(f"added {len(added)} day(s): {', '.join(added) or 'none'}")
        return 0
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, DownloadError, Exception) as e:  # noqa: BLE001
        traceback.print_exc()
        fresh.update(
            {"last_run_status": "failed", "fallback_active": True, "last_error": f"{type(e).__name__}: {e}"[:500]}
        )
        write_fresh(fpath, fresh)
        return 1


if __name__ == "__main__":
    sys.exit(main())
