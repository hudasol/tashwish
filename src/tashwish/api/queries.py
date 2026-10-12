"""Parameterised queries and row shaping for the list endpoints and /v1/context.

Rules enforced here, not only documented:
  * every request value is a bound parameter; column lists and ORDER BY clauses are fixed text;
  * estimates (share and its interval) are NULL unless status is `ok`, so a missing or untestable cell is never a zero;
  * only whitelisted columns are ever selected, and none identifies an aircraft;
  * every list is paged, hard capped, and ordered by a unique key so that cursors are stable (keyset pagination).
"""

from __future__ import annotations

import base64
import json
import math
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import h3

from .. import config as cfg
from ..interop.marsad import EVENT_KINDS, EVENT_STRATUM, GOOD_MIN_AIRCRAFT, SCHEMA_ID, band_for_altitude
from .release import Release, iso_z, parse_utc

MAX_CELLS_PAGE = 5000
DEFAULT_CELLS_PAGE = 1000
MAX_EVENTS_PAGE = 1000
DEFAULT_EVENTS_PAGE = 200
MAX_COVERAGE_PAGE = 5000
DEFAULT_COVERAGE_PAGE = 1000

STRATA = cfg.STRATA
STATUSES = ("ok", "insufficient", "coverage_lost")
EVENT_KIND_FILTER = (*EVENT_KINDS, "uncertain")
CONFIDENCE = ("low", "medium", "high")

CELL_COLS = (
    "h3, bucket_start, slot, stratum, n_aircraft, k_strong, share, ci_lo, ci_hi, status, coverage_class, data_class"
)
EVENT_COLS = (
    'event_id, kind, label_uncertain, confidence, start, "end", lat, lon, n_cells, cells, n_aircraft, k_degraded, '
    "peak_share, peak_ci_lo, min_p, n_spoof_aircraft, dest_lat, dest_lon, dest_spread_km, median_implied_kt, "
    "share_nominal_accuracy, day, data_class"
)
COVERAGE_COLS = "h3, slot, stratum, presence, mean_n, coverage_class"

_H3_RE = re.compile(r"^[0-9a-f]{15}$")
_NAIVE_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?Z)?$")


class ApiError(Exception):
    """An error with an HTTP status and a stable machine readable code."""

    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def clean(v: Any) -> Any:
    """JSON safe value: NaN and inf become None, datetimes become ISO UTC strings."""
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, datetime):
        return iso_z(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


# ---------------------------------------------------------------------- cursors
def encode_cursor(release: Release, kind: str, key: list[Any], fingerprint: str) -> str:
    raw = json.dumps({"v": release.dataset_version, "k": kind, "f": fingerprint, "key": key}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(release: Release, kind: str, cursor: str, fingerprint: str) -> list[Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        obj = json.loads(raw)
        if not (isinstance(obj, dict) and isinstance(obj.get("key"), list)):
            raise ValueError
    except (ValueError, TypeError):
        raise ApiError(422, "invalid_cursor", "cursor is not a value returned by this API as next_cursor") from None
    if obj.get("v") != release.dataset_version:
        raise ApiError(409, "stale_cursor", "cursor belongs to a different dataset_version; restart paging")
    if obj.get("k") != kind or obj.get("f") != fingerprint:
        raise ApiError(422, "invalid_cursor", "cursor was issued for a different endpoint or different filters")
    return obj["key"]


def _fp(**filters: Any) -> str:
    return json.dumps({k: filters[k] for k in sorted(filters)}, separators=(",", ":"), default=str)


def _rows(cur, sql: str, params: list[Any]) -> list[dict]:
    res = cur.execute(sql, params)
    names = [d[0] for d in res.description]
    return [dict(zip(names, r, strict=True)) for r in res.fetchall()]


# ---------------------------------------------------------------------- cells
def shape_cell(r: dict) -> dict:
    ok = r["status"] == "ok"
    return {
        "h3": r["h3"],
        "bucket_start": iso_z(r["bucket_start"]),
        "slot": r["slot"],
        "stratum": r["stratum"],
        "n_aircraft": r["n_aircraft"],
        "k_strong": r["k_strong"] if ok else None,
        "share": clean(r["share"]) if ok else None,
        "ci_lo": clean(r["ci_lo"]) if ok else None,
        "ci_hi": clean(r["ci_hi"]) if ok else None,
        "status": r["status"],
        "coverage_class": r["coverage_class"],
        "data_class": r["data_class"],
    }


def query_cells(
    rel: Release,
    *,
    day: str | None,
    slot: int | None,
    stratum: str | None,
    status: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[dict], str | None]:
    if day is not None and day not in rel.day_set:
        raise ApiError(404, "day_not_in_release", f"day {day} is not in this release; see /v1/days")
    if slot is not None and not 0 <= slot < rel.slots:
        raise ApiError(422, "invalid_slot", f"slot must be between 0 and {rel.slots - 1} for this grid")
    fp = _fp(day=day, slot=slot, stratum=stratum, status=status)
    where, params = [], []
    if day is not None:
        d0 = date.fromisoformat(day)
        where.append("bucket_start >= CAST(? AS TIMESTAMP) AND bucket_start < CAST(? AS TIMESTAMP)")
        params += [d0.isoformat(), (d0 + timedelta(days=1)).isoformat()]
    if slot is not None:
        where.append("slot = ?")
        params.append(slot)
    if stratum is not None:
        where.append("stratum = ?")
        params.append(stratum)
    if status is not None:
        where.append("status = ?")
        params.append(status)
    if cursor:
        k = decode_cursor(rel, "cells", cursor, fp)
        if not (
            len(k) == 3
            and all(isinstance(x, str) for x in k)
            and _NAIVE_TS_RE.match(k[0])
            and _H3_RE.match(k[1])
            and k[2] in STRATA
        ):
            raise ApiError(422, "invalid_cursor", "cursor is not a value returned by this API as next_cursor")
        where.append("(bucket_start, h3, stratum) > (CAST(? AS TIMESTAMP), ?, ?)")
        params += k
    sql = f"SELECT {CELL_COLS} FROM cell_buckets"  # noqa: S608 (fixed text; values are bound)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY bucket_start, h3, stratum LIMIT ?"
    rows = _rows(rel.cursor(), sql, [*params, limit + 1])
    nxt = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        nxt = encode_cursor(rel, "cells", [last["bucket_start"].isoformat(), last["h3"], last["stratum"]], fp)
    return [shape_cell(r) for r in rows], nxt


# ---------------------------------------------------------------------- coverage
def query_coverage(
    rel: Release, *, slot: int | None, stratum: str | None, limit: int, cursor: str | None
) -> tuple[list[dict], str | None]:
    if slot is not None and not 0 <= slot < rel.slots:
        raise ApiError(422, "invalid_slot", f"slot must be between 0 and {rel.slots - 1} for this grid")
    fp = _fp(slot=slot, stratum=stratum)
    where, params = [], []
    if slot is not None:
        where.append("slot = ?")
        params.append(slot)
    if stratum is not None:
        where.append("stratum = ?")
        params.append(stratum)
    if cursor:
        k = decode_cursor(rel, "coverage", cursor, fp)
        if not (
            len(k) == 3
            and isinstance(k[0], str)
            and _H3_RE.match(k[0])
            and isinstance(k[1], int)
            and not isinstance(k[1], bool)
            and k[2] in STRATA
        ):
            raise ApiError(422, "invalid_cursor", "cursor is not a value returned by this API as next_cursor")
        where.append("(h3, slot, stratum) > (?, ?, ?)")
        params += k
    sql = f"SELECT {COVERAGE_COLS} FROM coverage"  # noqa: S608
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY h3, slot, stratum LIMIT ?"
    rows = _rows(rel.cursor(), sql, [*params, limit + 1])
    nxt = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        nxt = encode_cursor(rel, "coverage", [last["h3"], last["slot"], last["stratum"]], fp)
    return [{k: clean(v) for k, v in r.items()} for r in rows], nxt


# ---------------------------------------------------------------------- events
def shape_event(r: dict) -> dict:
    out = {k: clean(v) for k, v in r.items()}
    cells = r.get("cells")
    out["cells"] = [c for c in str(cells).split(",") if c] if isinstance(cells, str) else []
    return out


def _bound_ts(s: str, *, end: bool) -> str:
    """A date means the whole UTC day: start of the day for `from`, start of the next day for `to`."""
    if "T" not in s:
        d = date.fromisoformat(s)
        return ((d + timedelta(days=1)) if end else d).isoformat() + "T00:00:00"
    return parse_utc(s).astimezone(UTC).replace(tzinfo=None).isoformat()


def parse_range_value(name: str, s: str) -> None:
    """Validate a from/to value; raises ApiError(422) with a clear message."""
    try:
        if not TS_RE.match(s):
            raise ValueError
        _bound_ts(s, end=False)
    except ValueError:
        raise ApiError(
            422, "invalid_timestamp", f"{name} must be YYYY-MM-DD or an ISO 8601 UTC time ending in Z, got {s!r}"
        ) from None


def query_events(
    rel: Release,
    *,
    t_from: str | None,
    t_to: str | None,
    kind: str | None,
    min_confidence: str | None,
    uncertain: bool | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[dict], str | None]:
    fp = _fp(f=t_from, t=t_to, kind=kind, c=min_confidence, u=uncertain)
    where, params = [], []
    lo = hi = None
    if t_from is not None:
        parse_range_value("from", t_from)
        lo = _bound_ts(t_from, end=False)
        where.append('"end" >= CAST(? AS TIMESTAMP)')
        params.append(lo)
    if t_to is not None:
        parse_range_value("to", t_to)
        hi = _bound_ts(t_to, end="T" not in t_to)
        where.append("start < CAST(? AS TIMESTAMP)" if "T" not in t_to else "start <= CAST(? AS TIMESTAMP)")
        params.append(hi)
    if lo and hi and (lo > hi or (lo == hi and "T" not in t_to)):
        raise ApiError(422, "invalid_range", "from must not be later than to")
    if kind is not None:
        where.append("kind = ?")
        params.append(kind)
    if min_confidence is not None:
        keep = list(CONFIDENCE[CONFIDENCE.index(min_confidence) :])
        where.append(f"confidence IN ({', '.join('?' for _ in keep)})")
        params += keep
    if uncertain is not None:
        where.append("label_uncertain = ?")
        params.append(uncertain)
    if cursor:
        k = decode_cursor(rel, "events", cursor, fp)
        if not (
            len(k) == 2 and all(isinstance(x, str) for x in k) and _NAIVE_TS_RE.match(k[0]) and 0 < len(k[1]) <= 200
        ):
            raise ApiError(422, "invalid_cursor", "cursor is not a value returned by this API as next_cursor")
        where.append("(start, event_id) > (CAST(? AS TIMESTAMP), ?)")
        params += k
    sql = f"SELECT {EVENT_COLS} FROM events"  # noqa: S608
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY start, event_id LIMIT ?"
    rows = _rows(rel.cursor(), sql, [*params, limit + 1])
    nxt = None
    if len(rows) > limit:
        rows = rows[:limit]
        nxt = encode_cursor(rel, "events", [rows[-1]["start"].isoformat(), rows[-1]["event_id"]], fp)
    return [shape_event(r) for r in rows], nxt


def get_event(rel: Release, event_id: str) -> dict | None:
    rows = _rows(rel.cursor(), f"SELECT {EVENT_COLS} FROM events WHERE event_id = ? LIMIT 2", [event_id])  # noqa: S608
    return shape_event(rows[0]) if rows else None


# ---------------------------------------------------------------------- context
def _event_index(rel: Release) -> dict[str, list[tuple[str, str, datetime, datetime]]]:
    """cell -> [(event_id, kind, start, end)] at the grid resolution (built once per loaded release)."""
    if rel._event_index is not None:
        return rel._event_index
    rows = _rows(rel.cursor(), 'SELECT event_id, kind, start, "end", lat, lon, cells FROM events', [])
    idx: dict[str, list] = {}
    res = rel.grid.h3_res
    for r in rows:
        cells = [c for c in str(r["cells"] or "").split(",") if c]
        if not cells and r["lat"] is not None and r["lon"] is not None:
            cells = [h3.latlng_to_cell(float(r["lat"]), float(r["lon"]), res)]
        for c in cells:
            if not h3.is_valid_cell(c):
                continue
            cr = h3.get_resolution(c)
            if cr < res:
                continue  # coarser than the grid: cannot be assigned to a cell without guessing
            if cr > res:
                c = h3.cell_to_parent(c, res)
            idx.setdefault(c, []).append(
                (r["event_id"], r["kind"], r["start"].replace(tzinfo=UTC), r["end"].replace(tzinfo=UTC))
            )
    rel._event_index = idx
    return idx


def _combine_kinds(kinds: list[str]) -> str:
    s = set(kinds)
    if "both" in s or {"jamming_like", "spoofing_like"} <= s:
        return "both"
    return next(iter(s))


def _record(rel: Release, r: dict) -> dict:
    ok = r["status"] == "ok"
    bs = r["bucket_start"].replace(tzinfo=UTC)
    be = bs + timedelta(hours=rel.grid.bucket_hours)
    kind, event_id = ("none" if ok and r["stratum"] == EVENT_STRATUM else "unknown"), None
    if r["stratum"] == EVENT_STRATUM:
        hits = [e for e in _event_index(rel).get(r["h3"], []) if e[2] < be and e[3] > bs]
        real = [e for e in hits if e[1] in EVENT_KINDS]
        if real:
            kind = _combine_kinds([e[1] for e in real])
            event_id = sorted(e[0] for e in real)[0]
        elif hits:
            kind = "unknown"  # only events of kind 'uncertain' overlap: never report this as clear
    n = int(r["n_aircraft"] or 0)
    good = ok and r["coverage_class"] == "covered" and n >= GOOD_MIN_AIRCRAFT
    return {
        "h3": r["h3"],
        "bucket_start": iso_z(bs),
        "bucket_end": iso_z(be),
        "alt_band": r["stratum"],
        "p_interference": round(float(r["share"]), 6) if ok and r["share"] is not None else None,
        "ci_lo": round(float(r["ci_lo"]), 6) if ok and r["ci_lo"] is not None else None,
        "ci_hi": round(float(r["ci_hi"]), 6) if ok and r["ci_hi"] is not None else None,
        "kind": kind,
        "event_id": event_id,
        "n_obs": n,
        "coverage_class": r["coverage_class"],
        "status": r["status"],
        "data_quality": "good" if good else ("limited" if ok else "poor"),
        "data_class": r["data_class"],
    }


def query_context(
    rel: Release, lat: float, lon: float, t: datetime, alt_ft: float | None, mode: str, *, max_age_hours: int
) -> dict:
    """Same semantics as `tashwish.interop.marsad.ContextIndex.query` (see docs/MARSAD_INTERFACE.md section 4).

    Every non `ok` outcome is an explicit status. Estimates are null unless status is `ok`. A synthetic release is
    never usable as a prior.
    """
    tz = t.astimezone(UTC)
    q = {"lat": lat, "lon": lon, "t": iso_z(tz), "alt_ft": alt_ft, "mode": mode}

    def respond(status: str, reason: str, record: dict | None = None, age: float | None = None) -> dict:
        usable = status == "ok" and not rel.synthetic
        if status == "ok" and rel.synthetic:
            reason += "; SYNTHETIC data is not usable as a prior"
        return {
            "schema": SCHEMA_ID,
            "status": status,
            "usable_as_prior": usable,
            "reason": reason,
            "query": q,
            "record": record,
            "age_hours": age,
            "max_age_hours": max_age_hours,
            "dataset_version": rel.dataset_version,
            "generated_at": rel.manifest["generated_at"],
            "data_class": rel.data_class,
            "attribution": rel.manifest["attribution"],
            "notice": rel.notice,
        }

    if not cfg.REGION.contains(lat, lon):
        return respond("out_of_region", "position is outside the study region")
    cell = h3.latlng_to_cell(lat, lon, rel.grid.h3_res)
    bands = band_for_altitude(alt_ft)
    rows = _rows(
        rel.cursor(),
        f"SELECT {CELL_COLS} FROM cell_buckets WHERE h3 = ? AND stratum IN ({', '.join('?' for _ in bands)}) "  # noqa: S608
        "ORDER BY bucket_start",
        [cell, *bands],
    )
    cands: list[dict] = []
    for band in bands:  # first band that has any record for the cell, as in ContextIndex
        cands = [r for r in rows if r["stratum"] == band]
        if cands:
            break
    if not cands:
        return respond("no_record", "no record for this cell and altitude band; treat as insufficient")
    step = timedelta(hours=rel.grid.bucket_hours)
    pick = None
    for p in cands:
        bs = p["bucket_start"].replace(tzinfo=UTC)
        be = bs + step
        if mode == "retrospective" and bs <= tz < be:
            pick = p
        if mode == "nowcast" and be <= tz:
            pick = p
    if pick is None:
        return respond("no_record", "no record covers this time; treat as insufficient")
    age = max((tz - (pick["bucket_start"].replace(tzinfo=UTC) + step)).total_seconds() / 3600.0, 0.0)
    rec = _record(rel, pick)
    if mode == "nowcast" and age > max_age_hours:
        return respond("stale", "latest record is older than max_age_hours; treat as insufficient", rec, age)
    reason = {
        "ok": "tested, estimate with interval",
        "insufficient": "too few aircraft to test; this is not 'clear'",
        "coverage_lost": "receiver coverage normally present is missing; this is not 'clear'",
    }.get(pick["status"], "unrecognised status; treat as insufficient")
    return respond(pick["status"], reason, rec, age)
