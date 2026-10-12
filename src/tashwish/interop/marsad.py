"""Regional interference CONTEXT PRIOR export (`tashwish.interference.v1`), written for a per vehicle position trust layer.

The export is a prior about the regional signal environment, never a verdict on a vehicle, and never an attribution.
Three rules are enforced in code, not only in prose:

  * a cell-bucket that is not testable (`insufficient` or `coverage_lost`) carries NULL estimates and kind `unknown`,
    never a zero and never `none`;
  * `none` only ever means "tested, no event detected at the detector's thresholds", and only in the stratum the
    detectors were run on (`EVENT_STRATUM`); it is not a statement that interference is absent;
  * synthetic data is labelled in the collection (`data_class`, `notice`) and, by convention, in the file name.

Layouts: a GeoJSON FeatureCollection (`to_geojson`) and an equivalent Parquet table (`to_parquet`). `validate_feature_collection`
checks a collection against the schema. `ContextIndex` is a reference implementation of the query contract
(`GET /v1/context`) over a collection. See docs/MARSAD_INTERFACE.md. This module does not import or depend on Marsad.
"""

from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .. import __version__
from .. import config as cfg
from ..attribution import attribution_for

SCHEMA_ID = "tashwish.interference.v1"
SCHEMA_MAJOR = 1

EVENT_KINDS = ("jamming_like", "spoofing_like", "both")
KINDS = (*EVENT_KINDS, "none", "unknown")
STATUSES = ("ok", "insufficient", "coverage_lost")
COVERAGE_CLASSES = ("covered", "marginal", "no_coverage")
DATA_QUALITIES = ("good", "limited", "poor")
ALT_BANDS = cfg.STRATA  # ("enroute", "high", "mid", "low")
DATA_CLASSES = (cfg.DATA_CLASS_OBSERVED, cfg.DATA_CLASS_SYNTHETIC)

# The detectors are run on this stratum only; `none` is therefore only asserted for rows of this stratum.
EVENT_STRATUM = "enroute"

# Default staleness limit written into each collection (a design choice, not a standard). Consumers must read the value
# from the collection (`max_age_hours`) and not hard code it.
STALENESS_MAX_AGE_HOURS = 48

# data_quality "good" needs an ok row in a covered cell with at least this many aircraft (a design choice).
GOOD_MIN_AIRCRAFT = 2 * cfg.MIN_AIRCRAFT_PER_CELL

NOTICE_OBSERVED = (
    "Regional interference context prior, aggregated over aircraft ADS-B broadcasts at altitude. It is not a verdict on any "
    "vehicle, it does not attribute interference to any actor, and 'insufficient' or 'coverage_lost' is not the same as 'clear'."
)
NOTICE_SYNTHETIC = (
    "SYNTHETIC DATA. Invented for tests and demonstrations, not observed, and not to be used as a prior. "
    + NOTICE_OBSERVED
)

RECORD_FIELDS = (
    "h3", "bucket_start", "bucket_end", "alt_band", "p_interference", "ci_lo", "ci_hi", "kind", "event_id", "n_obs",
    "coverage_class", "status", "data_quality", "data_class",
)  # fmt: skip

REQUIRED_CB_COLUMNS = ("cell", "bucket", "stratum", "n_aircraft", "share_strong", "ci_lo_strong", "ci_hi_strong",
                       "status", "coverage_class")  # fmt: skip

PARQUET_SCHEMA = pa.schema(
    [
        ("h3", pa.string()),
        ("bucket_start", pa.timestamp("ms", tz="UTC")),
        ("bucket_end", pa.timestamp("ms", tz="UTC")),
        ("alt_band", pa.string()),
        ("p_interference", pa.float64()),
        ("ci_lo", pa.float64()),
        ("ci_hi", pa.float64()),
        ("kind", pa.string()),
        ("event_id", pa.string()),
        ("n_obs", pa.int32()),
        ("coverage_class", pa.string()),
        ("status", pa.string()),
        ("data_quality", pa.string()),
        ("data_class", pa.string()),
        ("attribution", pa.string()),
        ("dataset_version", pa.string()),
        ("generated_at", pa.timestamp("ms", tz="UTC")),
    ]
)


def _iso(ts: pd.Timestamp | datetime) -> str:
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    if not isinstance(s, str) or not s.endswith("Z"):
        raise ValueError(f"timestamp must be an ISO 8601 UTC string ending in Z, got {s!r}")
    return datetime.fromisoformat(s[:-1] + "+00:00")


def code_commit(repo: Path | None = None) -> str:
    """Short git commit of the code, with '+dirty' if the working tree has changes; 'unknown' if git is unavailable."""
    cwd = str(repo or Path(__file__).resolve().parent)
    try:
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=cwd, capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True, check=True)
        return h.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _event_cells(events: pd.DataFrame, grid: cfg.Grid) -> pd.DataFrame:
    """One row per (event, cell) at the grid resolution. Events without cells (spoofing-like only) use their lat/lon cell."""
    rows = []
    for e in events.itertuples(index=False):
        if e.kind not in EVENT_KINDS:
            raise ValueError(f"event {e.event_id}: kind {e.kind!r} is not one of {EVENT_KINDS}")
        raw = getattr(e, "cells", "")
        cells = [c for c in str(raw).split(",") if c] if isinstance(raw, str) else []
        if not cells:
            cells = [h3.latlng_to_cell(float(e.lat), float(e.lon), grid.h3_res)]
        for c in cells:
            res = h3.get_resolution(c)
            if res < grid.h3_res:
                raise ValueError(f"event {e.event_id}: cell {c} is coarser than the export grid")
            if res > grid.h3_res:
                c = h3.cell_to_parent(c, grid.h3_res)
            rows.append((e.event_id, e.kind, pd.Timestamp(e.start), pd.Timestamp(e.end), c))
    return pd.DataFrame(rows, columns=["event_id", "ekind", "estart", "eend", "cell"])


def _combine_kinds(kinds: Iterable[str]) -> str:
    s = set(kinds)
    if "both" in s or {"jamming_like", "spoofing_like"} <= s:
        return "both"
    return next(iter(s))


def build_records(
    cb: pd.DataFrame,
    events: pd.DataFrame | None,
    *,
    grid: cfg.Grid = cfg.GRID_MAIN,
    event_stratum: str = EVENT_STRATUM,
) -> pd.DataFrame:
    """Turn cell-bucket metrics (after `apply_coverage`) and events into one record per (cell, bucket, stratum).

    Estimates are the degraded-aircraft share `share_strong` with its Wilson interval. They are set to NULL unless the row
    status is `ok`. `kind` is `unknown` for rows that cannot be classified and `none` only for ok rows of `event_stratum`
    with no overlapping event. If several events overlap a row, `event_id` is the smallest id and `kind` is merged.
    """
    missing = [c for c in REQUIRED_CB_COLUMNS if c not in cb.columns]
    if missing:
        raise ValueError(f"cell-bucket table is missing columns {missing}; run apply_coverage first")
    if not set(cb["status"].unique()) <= set(STATUSES):
        raise ValueError(f"unknown status values {set(cb['status'].unique()) - set(STATUSES)}")
    if not set(cb["coverage_class"].unique()) <= set(COVERAGE_CLASSES):
        raise ValueError("unknown coverage_class values")
    if not set(cb["stratum"].unique()) <= set(ALT_BANDS):
        raise ValueError("unknown stratum values")
    step = pd.Timedelta(hours=grid.bucket_hours)
    r = pd.DataFrame(
        {
            "h3": cb["cell"].astype(str).to_numpy(),
            "bucket_start": pd.to_datetime(cb["bucket"], utc=True).to_numpy(),
            "alt_band": cb["stratum"].astype(str).to_numpy(),
            "n_obs": cb["n_aircraft"].fillna(0).astype(int).to_numpy(),
            "coverage_class": cb["coverage_class"].astype(str).to_numpy(),
            "status": cb["status"].astype(str).to_numpy(),
        }
    )
    r["bucket_start"] = pd.to_datetime(r["bucket_start"], utc=True)
    r["bucket_end"] = r["bucket_start"] + step
    ok = (r["status"] == "ok").to_numpy()
    for out, src in (("p_interference", "share_strong"), ("ci_lo", "ci_lo_strong"), ("ci_hi", "ci_hi_strong")):
        v = cb[src].astype(float).to_numpy()
        if np.isnan(v[ok]).any():
            raise ValueError(f"status ok rows must have a non-null {src}")
        r[out] = np.where(ok, np.round(v, 6), np.nan)

    r["kind"] = np.where(ok & (r["alt_band"] == event_stratum), "none", "unknown")
    r["event_id"] = None
    if events is not None and len(events):
        ev = _event_cells(events, grid)
        ev = ev.assign(_k=1)
        m = (
            r[r["alt_band"] == event_stratum][["h3", "bucket_start", "bucket_end"]]
            .reset_index()
            .rename(columns={"h3": "cell"})
        )
        m = m.merge(ev, on="cell")
        m = m[(m["estart"] < m["bucket_end"]) & (m["eend"] > m["bucket_start"])]
        for idx, g in m.groupby("index"):
            r.loc[idx, "kind"] = _combine_kinds(g["ekind"])
            r.loc[idx, "event_id"] = sorted(g["event_id"])[0]
    good = ok & (r["coverage_class"] == "covered").to_numpy() & (r["n_obs"] >= GOOD_MIN_AIRCRAFT).to_numpy()
    r["data_quality"] = np.select([good, ok], ["good", "limited"], "poor")
    r = r.sort_values(["bucket_start", "alt_band", "h3"]).reset_index(drop=True)
    return r


def _ring(cell: str) -> list[list[float]]:
    pts = [[round(lng, 6), round(lat, 6)] for lat, lng in h3.cell_to_boundary(cell)]
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    if area < 0:  # RFC 7946: exterior rings counterclockwise
        pts.reverse()
    return [*pts, pts[0]]


def _none_if_nan(x: Any) -> Any:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return x


def _resolve_meta(data_class: str, generated_at, notice: str | None, commit: str | None):
    if data_class not in DATA_CLASSES:
        raise ValueError(f"data_class must be one of {DATA_CLASSES}")
    gen = _iso(generated_at if generated_at is not None else datetime.now(UTC))
    if notice is None:
        notice = NOTICE_SYNTHETIC if data_class == cfg.DATA_CLASS_SYNTHETIC else NOTICE_OBSERVED
    return gen, notice, commit if commit is not None else code_commit()


def to_geojson(
    cb: pd.DataFrame,
    events: pd.DataFrame | None,
    *,
    dataset_version: str,
    data_class: str = cfg.DATA_CLASS_OBSERVED,
    grid: cfg.Grid = cfg.GRID_MAIN,
    generated_at: str | datetime | pd.Timestamp | None = None,
    notice: str | None = None,
    commit: str | None = None,
    max_age_hours: int = STALENESS_MAX_AGE_HOURS,
    path: Path | str | None = None,
) -> dict:
    """Build the GeoJSON FeatureCollection (H3 cell polygons). Writes it to `path` when given. Returns the dict."""
    rec = build_records(cb, events, grid=grid)
    gen, notice, commit = _resolve_meta(data_class, generated_at, notice, commit)
    feats = []
    for row in rec.itertuples(index=False):
        props = {
            "h3": row.h3,
            "bucket_start": _iso(row.bucket_start),
            "bucket_end": _iso(row.bucket_end),
            "alt_band": row.alt_band,
            "p_interference": _none_if_nan(float(row.p_interference)),
            "ci_lo": _none_if_nan(float(row.ci_lo)),
            "ci_hi": _none_if_nan(float(row.ci_hi)),
            "kind": row.kind,
            "event_id": row.event_id,
            "n_obs": int(row.n_obs),
            "coverage_class": row.coverage_class,
            "status": row.status,
            "data_quality": row.data_quality,
            "data_class": data_class,
        }
        feats.append(
            {
                "type": "Feature",
                "id": f"{row.h3}|{props['bucket_start']}|{row.alt_band}",
                "geometry": {"type": "Polygon", "coordinates": [_ring(row.h3)]},
                "properties": props,
            }
        )
    fc = {
        "type": "FeatureCollection",
        "schema": SCHEMA_ID,
        "data_class": data_class,
        "notice": notice,
        "dataset_version": dataset_version,
        "generated_at": gen,
        "code_commit": commit,
        "tashwish_version": __version__,
        "attribution": attribution_for(data_class),
        "grid": {"h3_res": grid.h3_res, "bucket_hours": grid.bucket_hours},
        "max_age_hours": int(max_age_hours),
        "features": feats,
    }
    if path is not None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        head = {k: v for k, v in fc.items() if k != "features"}
        lines = [json.dumps(head, ensure_ascii=False, allow_nan=False)[:-1] + ', "features": [']
        lines += [
            json.dumps(f, ensure_ascii=False, allow_nan=False) + ("," if i < len(fc["features"]) - 1 else "")
            for i, f in enumerate(fc["features"])
        ]
        lines.append("]}")
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")  # one feature per line, still plain valid JSON
    return fc


def to_parquet(
    cb: pd.DataFrame,
    events: pd.DataFrame | None,
    path: Path | str,
    *,
    dataset_version: str,
    data_class: str = cfg.DATA_CLASS_OBSERVED,
    grid: cfg.Grid = cfg.GRID_MAIN,
    generated_at: str | datetime | pd.Timestamp | None = None,
    notice: str | None = None,
    commit: str | None = None,
    max_age_hours: int = STALENESS_MAX_AGE_HOURS,
) -> Path:
    """Write the equivalent Parquet layout (same rows and fields as the GeoJSON, geometry omitted, constants as columns)."""
    rec = build_records(cb, events, grid=grid)
    gen, notice, commit = _resolve_meta(data_class, generated_at, notice, commit)
    t = pa.table(
        {
            "h3": rec["h3"].astype(str),
            "bucket_start": pa.array(rec["bucket_start"], type=pa.timestamp("ms", tz="UTC")),
            "bucket_end": pa.array(rec["bucket_end"], type=pa.timestamp("ms", tz="UTC")),
            "alt_band": rec["alt_band"].astype(str),
            "p_interference": pa.array(rec["p_interference"].astype(float), from_pandas=True),
            "ci_lo": pa.array(rec["ci_lo"].astype(float), from_pandas=True),
            "ci_hi": pa.array(rec["ci_hi"].astype(float), from_pandas=True),
            "kind": rec["kind"].astype(str),
            "event_id": pa.array(list(rec["event_id"]), type=pa.string()),
            "n_obs": pa.array(rec["n_obs"].astype("int32"), type=pa.int32()),
            "coverage_class": rec["coverage_class"].astype(str),
            "status": rec["status"].astype(str),
            "data_quality": rec["data_quality"].astype(str),
            "data_class": pa.array([data_class] * len(rec), type=pa.string()),
            "attribution": pa.array([attribution_for(data_class)] * len(rec), type=pa.string()),
            "dataset_version": pa.array([dataset_version] * len(rec), type=pa.string()),
            "generated_at": pa.array([pd.Timestamp(gen)] * len(rec), type=pa.timestamp("ms", tz="UTC")),
        },
        schema=PARQUET_SCHEMA,
    )
    meta = {
        b"tashwish.schema": SCHEMA_ID.encode(),
        b"tashwish.grid": json.dumps({"h3_res": grid.h3_res, "bucket_hours": grid.bucket_hours}).encode(),
        b"tashwish.max_age_hours": str(int(max_age_hours)).encode(),
        b"tashwish.notice": notice.encode(),
        b"tashwish.code_commit": commit.encode(),
        b"tashwish.generated_at": gen.encode(),
    }
    t = t.replace_schema_metadata(meta)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(t, p, compression="zstd")
    return p


def read_parquet_records(path: Path | str) -> tuple[pd.DataFrame, dict]:
    """Read a Parquet export; returns (records, collection-level metadata incl. grid, max_age_hours, notice)."""
    t = pq.read_table(path)
    md = {k.decode(): v.decode() for k, v in (t.schema.metadata or {}).items()}
    if md.get("tashwish.schema") != SCHEMA_ID:
        raise ValueError(f"not a {SCHEMA_ID} file")
    return t.to_pandas(), md


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_feature_collection(fc: dict, *, strict_attribution: bool = True) -> list[str]:
    """Check a collection against `tashwish.interference.v1`. Returns a list of problems; an empty list means valid."""
    errs: list[str] = []

    def err(msg: str):
        if len(errs) < 200:
            errs.append(msg)

    if not isinstance(fc, dict):
        return ["collection must be a JSON object"]
    if fc.get("type") != "FeatureCollection":
        err("type must be 'FeatureCollection'")
    schema = fc.get("schema")
    if schema != SCHEMA_ID:
        err(f"schema must be {SCHEMA_ID!r}, got {schema!r}")
    dc = fc.get("data_class")
    if dc not in DATA_CLASSES:
        err(f"data_class must be one of {DATA_CLASSES}")
    for key in ("dataset_version", "code_commit", "notice", "attribution", "generated_at"):
        if not isinstance(fc.get(key), str) or not fc.get(key):
            err(f"{key} must be a non-empty string")
    if strict_attribution and fc.get("attribution") != attribution_for(str(dc)):
        err("attribution must equal tashwish.attribution.attribution_for(data_class)")
    if dc == cfg.DATA_CLASS_SYNTHETIC and "SYNTHETIC" not in str(fc.get("notice", "")):
        err("synthetic collections need a notice containing 'SYNTHETIC'")
    try:
        _parse_iso(fc.get("generated_at"))
    except (ValueError, TypeError):
        err("generated_at must be an ISO 8601 UTC string ending in Z")
    grid = fc.get("grid")
    if not (
        isinstance(grid, dict) and isinstance(grid.get("h3_res"), int) and isinstance(grid.get("bucket_hours"), int)
    ):
        err("grid must hold integer h3_res and bucket_hours")
        grid = None
    elif grid["bucket_hours"] <= 0 or 24 % grid["bucket_hours"]:
        err("grid.bucket_hours must divide 24")
        grid = None
    mah = fc.get("max_age_hours")
    if not (isinstance(mah, int) and not isinstance(mah, bool) and mah > 0):
        err("max_age_hours must be a positive integer")
    feats = fc.get("features")
    if not isinstance(feats, list):
        err("features must be a list")
        return errs

    seen: set[tuple] = set()
    for i, f in enumerate(feats):
        where = f"features[{i}]"
        if not isinstance(f, dict) or f.get("type") != "Feature":
            err(f"{where}: must be a Feature")
            continue
        props = f.get("properties")
        if not isinstance(props, dict):
            err(f"{where}: properties must be an object")
            continue
        missing = [k for k in RECORD_FIELDS if k not in props]
        extra = [k for k in props if k not in RECORD_FIELDS]
        if missing:
            err(f"{where}: missing properties {missing}")
            continue
        if extra:
            err(f"{where}: unknown properties {extra} (additions need a minor schema version)")
        cell = props["h3"]
        if not (isinstance(cell, str) and h3.is_valid_cell(cell)):
            err(f"{where}: h3 is not a valid cell")
        elif grid and h3.get_resolution(cell) != grid["h3_res"]:
            err(f"{where}: h3 resolution differs from grid.h3_res")
        geom = f.get("geometry")
        ok_geom = (
            isinstance(geom, dict)
            and geom.get("type") == "Polygon"
            and isinstance(geom.get("coordinates"), list)
            and len(geom["coordinates"]) == 1
            and isinstance(geom["coordinates"][0], list)
            and len(geom["coordinates"][0]) >= 4
            and geom["coordinates"][0][0] == geom["coordinates"][0][-1]
            and all(isinstance(p, list) and len(p) == 2 and all(_num(c) for c in p) for p in geom["coordinates"][0])
        )
        if not ok_geom:
            err(f"{where}: geometry must be a closed Polygon with one ring")
        elif isinstance(cell, str) and h3.is_valid_cell(cell):
            clat, clng = h3.cell_to_latlng(cell)
            ring = geom["coordinates"][0][:-1]
            mlng = sum(p[0] for p in ring) / len(ring)
            mlat = sum(p[1] for p in ring) / len(ring)
            if abs(mlat - clat) > 0.5 or abs(mlng - clng) > 0.5:
                err(f"{where}: polygon does not match the h3 cell")
        try:
            bs, be = _parse_iso(props["bucket_start"]), _parse_iso(props["bucket_end"])
            if grid:
                if be - bs != timedelta(hours=grid["bucket_hours"]):
                    err(f"{where}: bucket length differs from grid.bucket_hours")
                if bs.hour % grid["bucket_hours"] or bs.minute or bs.second:
                    err(f"{where}: bucket_start is not aligned to the UTC bucket grid")
        except (ValueError, TypeError):
            err(f"{where}: bucket_start and bucket_end must be ISO 8601 UTC strings ending in Z")
        band, status, kind = props["alt_band"], props["status"], props["kind"]
        if band not in ALT_BANDS:
            err(f"{where}: alt_band {band!r} not in {ALT_BANDS}")
        if status not in STATUSES:
            err(f"{where}: status {status!r} not in {STATUSES}")
        if kind not in KINDS:
            err(f"{where}: kind {kind!r} not in {KINDS}")
        if props["coverage_class"] not in COVERAGE_CLASSES:
            err(f"{where}: coverage_class not in {COVERAGE_CLASSES}")
        if props["data_quality"] not in DATA_QUALITIES:
            err(f"{where}: data_quality not in {DATA_QUALITIES}")
        if props["data_class"] != dc:
            err(f"{where}: data_class differs from the collection data_class")
        n = props["n_obs"]
        if not (isinstance(n, int) and not isinstance(n, bool) and n >= 0):
            err(f"{where}: n_obs must be a non-negative integer")
            n = None
        p, lo, hi = props["p_interference"], props["ci_lo"], props["ci_hi"]
        if status == "ok":
            if not all(_num(v) for v in (p, lo, hi)):
                err(f"{where}: status ok needs numeric p_interference, ci_lo, ci_hi")
            elif not (0.0 <= lo <= p <= hi <= 1.0):
                err(f"{where}: need 0 <= ci_lo <= p_interference <= ci_hi <= 1")
            if n is not None and n < cfg.MIN_AIRCRAFT_PER_CELL:
                err(f"{where}: status ok needs n_obs >= {cfg.MIN_AIRCRAFT_PER_CELL}")
        else:
            if any(v is not None for v in (p, lo, hi)):
                err(f"{where}: estimates must be null unless status is ok (never report a number, never a zero)")
            if kind == "none":
                err(f"{where}: a row that is not ok must not have kind 'none'")
            if props["data_quality"] != "poor":
                err(f"{where}: a row that is not ok must have data_quality 'poor'")
        if kind == "none" and band != EVENT_STRATUM:
            err(f"{where}: kind 'none' is only allowed for alt_band {EVENT_STRATUM!r}")
        eid = props["event_id"]
        if kind in EVENT_KINDS:
            if not (isinstance(eid, str) and eid):
                err(f"{where}: kind {kind!r} needs an event_id")
        elif eid is not None:
            err(f"{where}: event_id must be null when kind is {kind!r}")
        key = (props["h3"], props["bucket_start"], band)
        if key in seen:
            err(f"{where}: duplicate (h3, bucket_start, alt_band)")
        seen.add(key)
        if f.get("id") not in (None, f"{props['h3']}|{props['bucket_start']}|{band}"):
            err(f"{where}: id must be 'h3|bucket_start|alt_band'")
    return errs


def band_for_altitude(alt_ft: float | None) -> list[str]:
    """Bands to try, most specific first, for a barometric altitude in feet. None means any en-route altitude."""
    if alt_ft is None:
        return ["enroute"]
    if alt_ft >= cfg.HIGH_MIN_FT:
        return ["high", "enroute"]
    if alt_ft >= cfg.ENROUTE_MIN_FT:
        return ["mid", "enroute"]
    return ["low"]


class ContextIndex:
    """Reference implementation of the query contract over one collection (see docs/MARSAD_INTERFACE.md section 4)."""

    def __init__(self, fc: dict):
        problems = validate_feature_collection(fc)
        if problems:
            raise ValueError(f"invalid collection: {problems[:3]}")
        self.meta = {
            k: fc[k] for k in ("schema", "data_class", "notice", "dataset_version", "generated_at", "attribution")
        }
        self.meta["max_age_hours"] = fc["max_age_hours"]
        self.grid = cfg.Grid(h3_res=fc["grid"]["h3_res"], bucket_hours=fc["grid"]["bucket_hours"])
        self._by: dict[tuple[str, str], list[dict]] = {}
        for f in fc["features"]:
            p = f["properties"]
            self._by.setdefault((p["h3"], p["alt_band"]), []).append(p)
        for v in self._by.values():
            v.sort(key=lambda p: p["bucket_start"])

    def _response(self, status: str, reason: str, query: dict, record: dict | None = None, age: float | None = None):
        return {
            "schema": SCHEMA_ID,
            "status": status,
            "usable_as_prior": status == "ok",
            "reason": reason,
            "query": query,
            "record": record,
            "age_hours": age,
            "max_age_hours": self.meta["max_age_hours"],
            "dataset_version": self.meta["dataset_version"],
            "generated_at": self.meta["generated_at"],
            "data_class": self.meta["data_class"],
            "attribution": self.meta["attribution"],
            "notice": self.meta["notice"],
        }

    def query(
        self,
        lat: float,
        lon: float,
        t: str | datetime,
        alt_ft: float | None = None,
        *,
        mode: str = "retrospective",
    ) -> dict:
        """Context for a position and time. Raises ValueError for malformed input (HTTP 400). Never returns a zero for missing data.

        retrospective: the record whose bucket contains `t`.
        nowcast: the latest completed bucket with bucket_end <= `t`; stale if older than max_age_hours.
        """
        if mode not in ("retrospective", "nowcast"):
            raise ValueError("mode must be 'retrospective' or 'nowcast'")
        if not (_num(lat) and _num(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("lat and lon must be finite numbers in range")
        if alt_ft is not None and not _num(alt_ft):
            raise ValueError("alt_ft must be a finite number or omitted")
        tt = _parse_iso(t) if isinstance(t, str) else t.astimezone(UTC)
        q = {"lat": lat, "lon": lon, "t": _iso(tt), "alt_ft": alt_ft, "mode": mode}
        if not cfg.REGION.contains(lat, lon):
            return self._response("out_of_region", "position is outside the study region", q)
        cell = h3.latlng_to_cell(lat, lon, self.grid.h3_res)
        cands = None
        for band in band_for_altitude(alt_ft):
            if (cell, band) in self._by:
                cands = self._by[(cell, band)]
                break
        if not cands:
            return self._response("no_record", "no record for this cell and altitude band; treat as insufficient", q)
        tz = tt.astimezone(UTC)
        pick = None
        for p in cands:
            bs, be = _parse_iso(p["bucket_start"]), _parse_iso(p["bucket_end"])
            if mode == "retrospective" and bs <= tz < be:
                pick = p
            if mode == "nowcast" and be <= tz:
                pick = p  # sorted by start, so the last match is the latest completed bucket
        if pick is None:
            return self._response("no_record", "no record covers this time; treat as insufficient", q)
        age = (tz - _parse_iso(pick["bucket_end"])).total_seconds() / 3600.0
        age = max(age, 0.0)
        if mode == "nowcast" and age > self.meta["max_age_hours"]:
            return self._response(
                "stale", "latest record is older than max_age_hours; treat as insufficient", q, pick, age
            )
        reason = {
            "ok": "tested, estimate with interval",
            "insufficient": "too few aircraft to test; this is not 'clear'",
            "coverage_lost": "receiver coverage normally present is missing; this is not 'clear'",
        }[pick["status"]]
        return self._response(pick["status"], reason, q, pick, age)
