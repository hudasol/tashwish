"""Resumable, idempotent ingestion of one archive day to Parquet.

Steps: choose release -> download parts to a spool directory (resuming from bytes on disk) -> stream the tar ->
parse every trace file -> concatenate, sort deterministically -> validate -> write Parquet atomically ->
append a manifest record and write the data-quality report -> delete the spool.
Re-running a day whose manifest record and output file are consistent is a no-op.
"""

from __future__ import annotations

import hashlib
import io
import json
import multiprocessing
import os
import subprocess
import tarfile
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .. import __version__
from ..config import DATA_CLASS_OBSERVED, QUALITY_MAX_AGE_S, REGION, SCHEMA_VERSION, Region
from ..schema import POINT_SCHEMA, assert_data_class_matches, points_filename
from .quality import quality_report
from .source import CHUNK_BYTES, Fetcher, HttpxFetcher, choose_release, download_part
from .trace import COLUMNS, parse_gz

FLUSH_ROWS = 250_000
# A compressed trace member above this size is skipped and counted, not parsed. The largest member of an ordinary
# day is under 1 MiB; one member of 2026-03-25 was 21 MiB and exhausted 8 GB of memory in a pool worker, which hung the pool.
MAX_MEMBER_BYTES = 8 * 2**20
PARSE_VERSION = "1"  # bump when parsing semantics change; part of the idempotency key


@dataclass(frozen=True)
class IngestConfig:
    out_dir: Path
    spool_dir: Path
    region: Region = REGION
    max_age_s: float = QUALITY_MAX_AGE_S
    workers: int = 1
    keep_spool: bool = False
    data_class: str = DATA_CLASS_OBSERVED
    chunk_bytes: int = CHUNK_BYTES

    def params_key(self) -> str:
        r = self.region
        blob = json.dumps(
            [
                PARSE_VERSION,
                SCHEMA_VERSION,
                r.lat_min,
                r.lat_max,
                r.lon_min,
                r.lon_max,
                self.max_age_s,
                self.data_class,
            ]
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


def day_bounds_ms(day: str) -> tuple[int, int]:
    d0 = datetime.fromisoformat(day).replace(tzinfo=UTC)
    return int(d0.timestamp() * 1000), int((d0 + timedelta(days=1)).timestamp() * 1000)


def code_version() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, encoding="utf-8", timeout=5,
            cwd=Path(__file__).parent,
        ).stdout.strip()  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        sha = ""
    return f"{__version__}+{sha}" if sha else __version__


class _ConcatReader(io.RawIOBase):
    """Read several files back to back as one stream (the split tar parts)."""

    def __init__(self, paths: list[Path]):
        self._paths, self._i, self._f = list(paths), 0, None

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        while True:
            if self._f is None:
                if self._i >= len(self._paths):
                    return 0
                self._f = open(self._paths[self._i], "rb")  # noqa: SIM115
                self._i += 1
            n = self._f.readinto(b)
            if n:
                return n
            self._f.close()
            self._f = None


def iter_trace_members(paths: list[Path]) -> Iterator[tuple[str, bytes]]:
    tf = tarfile.open(fileobj=io.BufferedReader(_ConcatReader(paths), 1 << 20), mode="r|")
    for m in tf:
        if m.isfile() and "trace_full_" in m.name and m.name.endswith(".json"):
            f = tf.extractfile(m)
            if f is not None:
                yield m.name, f.read()


def _parse_member(args) -> tuple[dict[str, list], Counter]:
    raw, d0, d1, region, max_age, data_class = args
    p = parse_gz(raw, d0, d1, region, max_age, data_class)
    return p.cols, p.stats


class _Accumulator:
    def __init__(self) -> None:
        self.tables: list[pa.Table] = []
        self._cols: dict[str, list] = {c: [] for c in COLUMNS}
        self._n = 0
        self.stats: Counter = Counter()

    def add(self, cols: dict[str, list], stats: Counter) -> None:
        self.stats.update(stats)
        k = len(cols["ts"])
        if not k:
            return
        for c in COLUMNS:
            self._cols[c].extend(cols[c])
        self._n += k
        if self._n >= FLUSH_ROWS:
            self.flush()

    def flush(self) -> None:
        if self._n:
            arrays = [pa.array(self._cols[f.name], type=f.type) for f in POINT_SCHEMA]
            self.tables.append(pa.Table.from_arrays(arrays, schema=POINT_SCHEMA))
            self._cols = {c: [] for c in COLUMNS}
            self._n = 0

    def result(self) -> pa.Table:
        self.flush()
        if not self.tables:
            return POINT_SCHEMA.empty_table()
        return pa.concat_tables(self.tables)


def parse_archive(paths: list[Path], day: str, cfg: IngestConfig) -> tuple[pa.Table, Counter]:
    d0, d1 = day_bounds_ms(day)
    acc = _Accumulator()
    skipped: Counter = Counter()

    def _members():
        for name, raw in iter_trace_members(paths):
            if len(raw) > MAX_MEMBER_BYTES:
                skipped["skipped_oversize"] += 1
                skipped["skipped_oversize_bytes"] += len(raw)
                continue
            yield name, raw

    jobs = ((raw, d0, d1, cfg.region, cfg.max_age_s, cfg.data_class) for _, raw in _members())
    n_files = 0
    if cfg.workers > 1:
        with multiprocessing.get_context("spawn").Pool(cfg.workers) as pool:
            for cols, stats in pool.imap_unordered(_parse_member, jobs, chunksize=32):
                n_files += 1
                acc.add(cols, stats)
    else:
        for job in jobs:
            n_files += 1
            acc.add(*_parse_member(job))
    acc.stats.update(skipped)
    acc.stats["trace_files"] = n_files
    return acc.result(), acc.stats


def finalize_table(table: pa.Table) -> pa.Table:
    """Deterministic order and exact-duplicate removal."""
    if table.num_rows == 0:
        return table
    table = table.sort_by([("ts", "ascending"), ("icao24", "ascending"), ("lat", "ascending"), ("lon", "ascending")])
    return table


def validate_table(table: pa.Table, day: str, data_class: str) -> None:
    if table.schema.remove_metadata() != POINT_SCHEMA.remove_metadata():
        raise ValueError("schema mismatch")
    if table.num_rows == 0:
        return
    d0, d1 = day_bounds_ms(day)
    ts = table.column("ts").cast(pa.int64()).to_numpy()
    if ts.min() < d0 or ts.max() >= d1:
        raise ValueError("timestamps outside the day")
    lat = table.column("lat").to_numpy()
    lon = table.column("lon").to_numpy()
    if not ((lat >= -90) & (lat <= 90) & (lon >= -180) & (lon <= 180)).all():
        raise ValueError("coordinates out of range")
    if set(table.column("data_class").unique().to_pylist()) != {data_class}:
        raise ValueError("data_class column mismatch")


def write_parquet(table: pa.Table, path: Path, data_class: str) -> str:
    """Atomic, deterministic Parquet write; returns sha256 of the written file."""
    assert_data_class_matches(table, path, data_class)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(
        table.replace_schema_metadata(POINT_SCHEMA.metadata),
        tmp,
        compression="zstd",
        compression_level=3,
        row_group_size=500_000,
        version="2.6",
        data_page_version="2.0",
        write_statistics=True,
    )
    os.replace(tmp, path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def read_manifest(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def is_complete(cfg: IngestConfig, day: str) -> bool:
    out = cfg.out_dir / points_filename(day, cfg.data_class)
    if not out.exists():
        return False
    for rec in reversed(read_manifest(cfg.out_dir / "manifest.jsonl")):
        if rec.get("day") == day and rec.get("data_class") == cfg.data_class:
            return (
                rec.get("status") == "complete"
                and rec.get("params_key") == cfg.params_key()
                and (rec.get("rows") is not None)
            )
    return False


def ingest_day(
    day: str,
    cfg: IngestConfig,
    fetch: Fetcher | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> dict:
    if is_complete(cfg, day):
        log(f"{day}: already complete, skipping")
        return {"day": day, "skipped": True}
    fetch = fetch or HttpxFetcher()
    t0 = time.time()
    kind, repo_year, parts = choose_release(fetch, day, sleep)
    log(f"{day}: release {kind} (repo {repo_year}), {len(parts)} parts, {sum(t for _, t in parts) / 2**20:.0f} MiB")
    spool = cfg.spool_dir / day
    paths: list[Path] = []
    for url, total in parts:
        dest = spool / url.rsplit(".", 1)[-1]
        download_part(fetch, url, dest, total, chunk=cfg.chunk_bytes, sleep=sleep)
        paths.append(dest)
    log(f"{day}: downloaded in {time.time() - t0:.0f}s, parsing")
    table, stats = parse_archive(paths, day, cfg)
    table = finalize_table(table)
    validate_table(table, day, cfg.data_class)
    out = cfg.out_dir / points_filename(day, cfg.data_class)
    sha = write_parquet(table, out, cfg.data_class)
    qdir = cfg.out_dir / "quality"
    qdir.mkdir(parents=True, exist_ok=True)
    report = quality_report(table, day, stats)
    (qdir / f"{day}{'_synthetic' if cfg.data_class != DATA_CLASS_OBSERVED else ''}.json").write_text(
        json.dumps(report, indent=1, sort_keys=True), encoding="utf-8", newline="\n"
    )
    rec = {
        "day": day,
        "status": "complete",
        "data_class": cfg.data_class,
        "source": "adsb.lol globe_history (ODbL 1.0)",
        "release_kind": kind,
        "repo_year": repo_year,
        "parts": [{"url": u, "bytes": t} for u, t in parts],
        "rows": table.num_rows,
        "aircraft": report.get("aircraft", 0),
        "trace_files": stats.get("trace_files", 0),
        "out_file": out.name,
        "out_sha256": sha,
        "params_key": cfg.params_key(),
        "schema_version": SCHEMA_VERSION,
        "code_version": code_version(),
        "ingested_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seconds": round(time.time() - t0, 1),
    }
    with open(cfg.out_dir / "manifest.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    if not cfg.keep_spool:
        for p in paths:
            p.unlink(missing_ok=True)
            p.with_suffix(p.suffix + ".meta").unlink(missing_ok=True)
        try:
            spool.rmdir()
        except OSError:
            pass
    log(f"{day}: done, {table.num_rows} rows, {rec['aircraft']} aircraft, {rec['seconds']}s")
    return rec
