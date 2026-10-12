"""Deterministic dev / held-out split of study days.

Rule (fixed before any held-out day was examined, see docs/PREDICTIONS.md):
  a day is HELD OUT if sha256("tashwish-heldout-v1|YYYY-MM-DD") read as a big-endian integer, modulo 3, equals 0,
  unless the day appears in PREVIOUSLY_EXAMINED, in which case it is DEV by declaration (it was looked at before the
  rule existed, so it cannot be a fair test).
No threshold, baseline, coverage fit or design choice may use a held-out day. Baselines and coverage are fitted on DEV days only.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

RULE_ID = "tashwish-heldout-v1"
MODULUS = 3
STUDY_START = date(2026, 2, 7)
STUDY_END = date(2026, 3, 13)  # inclusive
# Days whose data was inspected before the rule existed (exploratory analysis during M1 to M3).
PREVIOUSLY_EXAMINED = frozenset({date(2026, 3, 2)})


def study_days(start: date = STUDY_START, end: date = STUDY_END) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def hash_bucket(d: date) -> int:
    h = hashlib.sha256(f"{RULE_ID}|{d.isoformat()}".encode()).digest()
    return int.from_bytes(h, "big") % MODULUS


def is_held_out(d: date) -> bool:
    return d not in PREVIOUSLY_EXAMINED and hash_bucket(d) == 0


def split(days: list[date] | None = None) -> tuple[list[date], list[date]]:
    days = days or study_days()
    held = [d for d in days if is_held_out(d)]
    dev = [d for d in days if not is_held_out(d)]
    return dev, held
