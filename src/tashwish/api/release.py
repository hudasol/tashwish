"""Loading, validating and querying one release directory (no HTTP concerns here).

A release directory is written by the release builder and is treated as immutable: this module never writes to it.
Cheap metadata (manifest, freshness) is cached in memory. Big tables stay in Parquet and are queried through DuckDB
with parameterised SQL. Values that come from a request are always bound parameters, never interpolated; the only
interpolated text is the release directory path (operator configuration) and fixed column lists.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from .. import config as cfg
from ..attribution import DATASET_ATTRIBUTION, SYNTHETIC_ATTRIBUTION
from ..interop.marsad import NOTICE_OBSERVED, NOTICE_SYNTHETIC

RELEASE_SCHEMA = "tashwish.release.v1"
API_SCHEMA = "tashwish.api.v1"

REQUIRED_PARQUET = {
    "cell_buckets.parquet": (
        "h3", "bucket_start", "slot", "stratum", "n_aircraft", "k_strong", "share", "ci_lo", "ci_hi", "status",
        "coverage_class", "data_class",
    ),
    "events.parquet": (
        "event_id", "kind", "label_uncertain", "confidence", "start", "end", "lat", "lon", "n_cells", "cells",
        "n_aircraft", "k_degraded", "peak_share", "peak_ci_lo", "min_p", "n_spoof_aircraft", "dest_lat", "dest_lon",
        "dest_spread_km", "median_implied_kt", "share_nominal_accuracy", "day", "data_class",
    ),
    "coverage.parquet": ("h3", "slot", "stratum", "presence", "mean_n", "coverage_class"),
}  # fmt: skip
OPTIONAL_JSON = ("validation.json", "freshness.json")
MANIFEST_KEYS = ("schema", "dataset_version", "generated_at", "code_commit", "data_class", "attribution", "grid", "bbox",
                 "days", "latest_day", "files")  # fmt: skip


class ReleaseError(Exception):
    """The release directory is missing, incomplete or inconsistent. The service refuses to start on it."""


def parse_utc(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (trailing Z or offset) into an aware datetime."""
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def iso_z(d: datetime) -> str:
    """Format a datetime as `YYYY-MM-DDTHH:MM:SSZ` (naive values are taken as UTC)."""
    d = d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sql_literal(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


class Release:
    """One loaded release. `refresh()` reloads when manifest.json changed on disk (an atomic swap by the builder)."""

    def __init__(self, root: str | Path, *, verify_hashes: bool | None = None):
        self.root = Path(root).resolve()
        self.verify_hashes = bool(os.environ.get("TASHWISH_VERIFY_HASHES")) if verify_hashes is None else verify_hashes
        self._lock = threading.RLock()
        self._sig: tuple[int, int] | None = None
        self._fresh_cache: tuple[tuple[int, int] | None, dict] = (None, {})
        self._json_cache: dict[str, tuple[tuple[int, int], Any]] = {}
        self._event_index: dict | None = None
        self.last_reload_error: str | None = None
        self._load()

    # ------------------------------------------------------------------ loading
    def _manifest_sig(self) -> tuple[int, int]:
        st = (self.root / "manifest.json").stat()
        return (st.st_mtime_ns, st.st_size)

    def _load(self) -> None:
        mp = self.root / "manifest.json"
        if not mp.is_file():
            raise ReleaseError(f"manifest.json not found in release directory {self.root}")
        sig = self._manifest_sig()
        try:
            manifest = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ReleaseError(f"manifest.json is not valid JSON: {e}") from e
        self._check_manifest(manifest)
        files = manifest["files"]
        for name, info in files.items():
            p = self._safe_path(info.get("path", ""))
            if not p.is_file():
                raise ReleaseError(f"manifest lists {name!r} but {p} does not exist")
            if p.stat().st_size != info.get("bytes"):
                raise ReleaseError(f"{name!r}: size on disk differs from manifest bytes")
            if self.verify_hashes and _sha256(p) != info.get("sha256"):
                raise ReleaseError(f"{name!r}: sha256 differs from manifest")
        for fname, cols in REQUIRED_PARQUET.items():
            if fname not in files:
                raise ReleaseError(f"manifest.files must list {fname!r}")
            have = set(pq.read_schema(self._safe_path(files[fname]["path"])).names)  # footer only
            missing = [c for c in cols if c not in have]
            if missing:
                raise ReleaseError(f"{fname} is missing columns {missing}")
        con = duckdb.connect(":memory:")
        threads = int(os.environ.get("TASHWISH_DUCKDB_THREADS", "1"))
        con.execute(f"SET threads TO {max(1, threads)}")
        con.execute(f"SET memory_limit = {_sql_literal(os.environ.get('TASHWISH_DUCKDB_MEMORY', '256MB'))}")
        con.execute("SET TimeZone = 'UTC'")
        cb = _sql_literal(str(self._safe_path(files["cell_buckets.parquet"]["path"])))
        ev = _sql_literal(str(self._safe_path(files["events.parquet"]["path"])))
        co = _sql_literal(str(self._safe_path(files["coverage.parquet"]["path"])))
        con.execute(
            "CREATE VIEW cell_buckets AS SELECT h3, CAST(bucket_start AS TIMESTAMP) AS bucket_start, "
            "CAST(slot AS INTEGER) AS slot, stratum, CAST(n_aircraft AS INTEGER) AS n_aircraft, "
            "CAST(k_strong AS INTEGER) AS k_strong, CAST(share AS DOUBLE) AS share, CAST(ci_lo AS DOUBLE) AS ci_lo, "
            f"CAST(ci_hi AS DOUBLE) AS ci_hi, status, coverage_class, data_class FROM read_parquet({cb})"
        )
        con.execute(
            "CREATE VIEW events AS SELECT event_id, kind, CAST(label_uncertain AS BOOLEAN) AS label_uncertain, "
            'confidence, CAST(start AS TIMESTAMP) AS start, CAST("end" AS TIMESTAMP) AS "end", '
            "CAST(lat AS DOUBLE) AS lat, CAST(lon AS DOUBLE) AS lon, n_cells, cells, n_aircraft, k_degraded, "
            "peak_share, peak_ci_lo, min_p, n_spoof_aircraft, dest_lat, dest_lon, dest_spread_km, median_implied_kt, "
            f"share_nominal_accuracy, CAST(day AS VARCHAR) AS day, data_class FROM read_parquet({ev})"
        )
        con.execute(
            "CREATE VIEW coverage AS SELECT h3, CAST(slot AS INTEGER) AS slot, stratum, presence, mean_n, "
            f"coverage_class FROM read_parquet({co})"
        )
        for table in ("cell_buckets", "events"):
            classes = {r[0] for r in con.execute(f"SELECT DISTINCT data_class FROM {table}").fetchall()}
            if not classes <= {manifest["data_class"]}:
                raise ReleaseError(
                    f"{table}.data_class values {sorted(map(str, classes))} do not match manifest data_class "
                    f"{manifest['data_class']!r}; refusing to mix synthetic and observed data"
                )
        with self._lock:
            self.manifest = manifest
            self.con = con
            self._sig = sig
            self._event_index = None
            self._json_cache = {}

    def _check_manifest(self, m: Any) -> None:
        if not isinstance(m, dict):
            raise ReleaseError("manifest.json must be a JSON object")
        missing = [k for k in MANIFEST_KEYS if k not in m]
        if missing:
            raise ReleaseError(f"manifest.json is missing keys {missing}")
        if m["schema"] != RELEASE_SCHEMA:
            raise ReleaseError(f"manifest schema must be {RELEASE_SCHEMA!r}, got {m['schema']!r}")
        if m["data_class"] not in (cfg.DATA_CLASS_OBSERVED, cfg.DATA_CLASS_SYNTHETIC):
            raise ReleaseError("manifest data_class must be 'observed' or 'synthetic'")
        allowed = {DATASET_ATTRIBUTION}
        if m["data_class"] == cfg.DATA_CLASS_SYNTHETIC:
            allowed.add(SYNTHETIC_ATTRIBUTION)  # the synthetic notice is valid only for synthetic releases
        if m["attribution"] not in allowed:
            raise ReleaseError(
                "manifest attribution must equal tashwish.attribution.DATASET_ATTRIBUTION "
                "(or SYNTHETIC_ATTRIBUTION when data_class is synthetic)"
            )
        g = m["grid"]
        if not (isinstance(g, dict) and isinstance(g.get("h3_res"), int) and isinstance(g.get("bucket_hours"), int)):
            raise ReleaseError("manifest grid must hold integer h3_res and bucket_hours")
        if g["bucket_hours"] <= 0 or 24 % g["bucket_hours"]:
            raise ReleaseError("manifest grid.bucket_hours must divide 24")
        if not isinstance(m["files"], dict) or not isinstance(m["days"], list):
            raise ReleaseError("manifest files must be an object and days a list")
        try:
            parse_utc(m["generated_at"])
        except (ValueError, TypeError, AttributeError) as e:
            raise ReleaseError("manifest generated_at must be an ISO 8601 UTC timestamp") from e

    def _safe_path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not str(rel) or self.root not in p.parents:
            raise ReleaseError(f"path {rel!r} escapes the release directory")
        return p

    def refresh(self) -> None:
        """Reload when manifest.json changed. A failed reload keeps serving the last good release."""
        try:
            sig = self._manifest_sig()
        except OSError:
            return
        if sig != self._sig:
            with self._lock:
                if sig != self._sig:
                    try:
                        self._load()
                        self.last_reload_error = None
                    except (ReleaseError, duckdb.Error, OSError) as e:
                        self._sig = sig  # do not retry on every request; the next manifest write retriggers
                        self.last_reload_error = str(e)

    # ------------------------------------------------------------------ simple accessors
    @property
    def dataset_version(self) -> str:
        return self.manifest["dataset_version"]

    @property
    def checksums_sha256(self) -> str:
        """SHA-256 of checksums.sha256 as listed in the manifest. It covers every other release file, so it changes
        whenever any content changes. Empty string if the manifest does not list it."""
        return str((self.manifest["files"].get("checksums.sha256") or {}).get("sha256", ""))

    @property
    def data_class(self) -> str:
        return self.manifest["data_class"]

    @property
    def attribution(self) -> str:
        return self.manifest["attribution"]

    @property
    def synthetic(self) -> bool:
        return self.data_class == cfg.DATA_CLASS_SYNTHETIC

    @property
    def grid(self) -> cfg.Grid:
        g = self.manifest["grid"]
        return cfg.Grid(h3_res=g["h3_res"], bucket_hours=g["bucket_hours"])

    @property
    def slots(self) -> int:
        return 24 // self.grid.bucket_hours

    @property
    def notice(self) -> str:
        return NOTICE_SYNTHETIC if self.synthetic else NOTICE_OBSERVED

    @property
    def day_set(self) -> set[str]:
        return {d["day"] for d in self.manifest["days"]}

    def cursor(self):
        """A private DuckDB cursor (cheap; one per request, safe across threads)."""
        cur = self.con.cursor()
        cur.execute("SET TimeZone = 'UTC'")  # session settings are per connection; TIMESTAMPTZ casts depend on it
        return cur

    def file_info(self, name: str) -> dict | None:
        info = self.manifest["files"].get(name)
        if info is None:
            return None
        return {**info, "abs_path": self._safe_path(info["path"]), "name": name}

    def _read_json(self, name: str) -> Any | None:
        info = self.manifest["files"].get(name)
        p = self.root / (info["path"] if info else name)
        try:
            st = p.stat()
        except OSError:
            return None
        key = (st.st_mtime_ns, st.st_size)
        hit = self._json_cache.get(name)
        if hit and hit[0] == key:
            return hit[1]
        try:
            val = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        self._json_cache[name] = (key, val)
        return val

    def validation(self) -> dict | None:
        return self._read_json("validation.json")

    def freshness(self) -> dict:
        """freshness.json, or a derived record that says so when the file is absent."""
        f = self._read_json("freshness.json")
        if isinstance(f, dict):
            return f
        return {
            "generated_at": self.manifest["generated_at"],
            "latest_day": self.manifest["latest_day"],
            "last_run_status": "unknown",
            "last_success_at": None,
            "fallback_active": None,
        }

    def age_hours(self, now: datetime | None = None) -> float:
        """Hours since the last successful run (freshness.last_success_at), else since manifest generated_at."""
        f = self.freshness()
        ref = f.get("last_success_at") or f.get("generated_at") or self.manifest["generated_at"]
        try:
            t = parse_utc(ref)
        except (ValueError, TypeError):
            t = parse_utc(self.manifest["generated_at"])
        return round(max(((now or datetime.now(UTC)) - t).total_seconds() / 3600.0, 0.0), 2)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
