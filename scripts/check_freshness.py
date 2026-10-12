#!/usr/bin/env python3
"""Report dataset freshness from processed/freshness.json as ok, amber or red.

Same rule as the dashboard (web/js/common.js, freshness()): age is the larger of the hours since `generated_at` and the
hours since the end of `latest_day` (UTC); amber above 48 h, red above 7 days. Exit code 0 ok, 1 amber, 2 red, 3 the file is
missing or unreadable (treated as worse than red so a broken pipeline cannot look healthy).

    python scripts/check_freshness.py processed/freshness.json
    python scripts/check_freshness.py processed/freshness.json --mark-failed "reason"   # failure handler: keeps last good data
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

AMBER_HOURS = 48.0
RED_HOURS = 7 * 24.0
EXIT = {"ok": 0, "amber": 1, "red": 2, "unknown": 3}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)


def evaluate(doc: dict, now: datetime | None = None) -> dict:
    """Return level, ages in hours and the run status fields. Raises ValueError/KeyError on a malformed document."""
    now = now or datetime.now(UTC)
    gen = _parse(doc["generated_at"])
    latest_end = datetime.fromisoformat(doc["latest_day"]).replace(tzinfo=UTC) + timedelta(days=1)
    gen_age = (now - gen).total_seconds() / 3600
    day_age = (now - latest_end).total_seconds() / 3600
    age = max(gen_age, day_age)
    level = "red" if age > RED_HOURS else "amber" if age > AMBER_HOURS else "ok"
    return {
        "level": level,
        "age_hours": round(age, 1),
        "generated_age_hours": round(gen_age, 1),
        "latest_day_age_hours": round(day_age, 1),
        "latest_day": doc["latest_day"],
        "last_run_status": doc.get("last_run_status", "unknown"),
        "fallback_active": bool(doc.get("fallback_active", False)),
    }


def mark_failed(path: Path, reason: str, now: datetime | None = None) -> dict:
    """Set last_run_status=failed and fallback_active=true, keep everything else (the last good dataset stays served)."""
    now = now or datetime.now(UTC)
    doc = json.loads(path.read_text()) if path.exists() else {}
    doc.update(
        {
            "last_run_status": "failed",
            "fallback_active": True,
            "last_run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_error": reason[:500],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path, nargs="?", default=Path("processed/freshness.json"))
    ap.add_argument("--mark-failed", metavar="REASON", help="record a failed run in the file and exit 0")
    args = ap.parse_args(argv)
    if args.mark_failed is not None:
        mark_failed(args.path, args.mark_failed)
        print(f"marked failed: {args.path}")
        return 0
    try:
        res = evaluate(json.loads(args.path.read_text()))
    except (OSError, ValueError, KeyError) as e:
        print(f"unknown: cannot evaluate {args.path}: {e}")
        return EXIT["unknown"]
    print(
        f"{res['level']}: age {res['age_hours']} h (generated {res['generated_age_hours']} h ago, latest day "
        f"{res['latest_day']} ended {res['latest_day_age_hours']} h ago), last_run_status={res['last_run_status']}, "
        f"fallback_active={str(res['fallback_active']).lower()}"
    )
    return EXIT[res["level"]]


if __name__ == "__main__":
    sys.exit(main())
