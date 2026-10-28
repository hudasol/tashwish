"""Builds a tiny SYNTHETIC release directory for API tests.

Everything here is invented. Cell locations are real H3 cells over Gulf cities only so that lookups by latitude and
longitude work; the numbers say nothing about the real world. The manifest, data card and every row are labelled
`synthetic`. `data_class="observed"` exists only to exercise the observed code path of the API with invented numbers;
such a directory must never leave a test temp dir.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import h3
import pandas as pd

from tashwish import config as cfg
from tashwish.attribution import DATASET_ATTRIBUTION, NOTICE

DAYS = ("2026-01-10", "2026-01-11")
PLACES = {  # name -> (lat, lon), all inside cfg.REGION
    "dubai": (25.20, 55.30),
    "doha": (25.29, 51.53),
    "muscat": (23.59, 58.40),
    "bahrain": (26.22, 50.59),
    "kuwait": (29.37, 47.98),
    "abu_dhabi": (24.45, 54.38),
}
GRID = cfg.GRID_MAIN


@dataclass
class SynthRelease:
    path: Path
    cb: pd.DataFrame
    events: pd.DataFrame
    cells: dict[str, str]  # place name -> h3 cell
    generated_at: datetime


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_synthetic_release(
    root: Path,
    *,
    data_class: str = "synthetic",
    age_hours: float = 5.0,
    dataset_version: str = "synthetic-2026.01.11-test",
    leak_estimates: bool = False,
) -> SynthRelease:
    """Write a complete release layout under `root`. `leak_estimates` puts numbers on non-ok rows (a builder bug)."""
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).replace(microsecond=0)
    generated_at = now - timedelta(hours=age_hours)
    cells = {n: h3.latlng_to_cell(lat, lon, GRID.h3_res) for n, (lat, lon) in PLACES.items()}
    names = list(cells)

    rows = []
    for di, day in enumerate(DAYS):
        d0 = datetime.fromisoformat(day).replace(tzinfo=UTC)
        for slot in range(24 // GRID.bucket_hours):
            for ci, name in enumerate(names):
                for stratum in ("enroute", "high"):
                    if stratum == "high" and ci > 1:
                        continue
                    pattern = (ci + slot + di) % 5
                    status = "insufficient" if pattern == 0 else "coverage_lost" if pattern == 1 else "ok"
                    n = 2 if status == "insufficient" else 0 if status == "coverage_lost" else 8 + 3 * ci + slot
                    k = (slot + ci) % max(n, 1) if status == "ok" else 0
                    share = k / n if status == "ok" else float("nan")
                    lo = max(0.0, share - 0.15) if status == "ok" else float("nan")
                    hi = min(1.0, share + 0.15) if status == "ok" else float("nan")
                    if leak_estimates and status != "ok":
                        share, lo, hi, k = 0.0, 0.0, 0.1, 0
                    rows.append(
                        {
                            "h3": cells[name],
                            "bucket_start": pd.Timestamp(d0 + timedelta(hours=slot * GRID.bucket_hours)),
                            "slot": slot,
                            "stratum": stratum,
                            "n_aircraft": n,
                            "k_strong": k,
                            "share": share,
                            "ci_lo": lo,
                            "ci_hi": hi,
                            "status": status,
                            "coverage_class": {"ok": "covered", "insufficient": "marginal", "coverage_lost": "covered"}[
                                status
                            ],
                            "data_class": data_class,
                        }
                    )
    cb = pd.DataFrame(rows)

    def ev(i, kind, conf, unc, start, end, cell_names, place):
        lat, lon = PLACES[place]
        return {
            "event_id": f"synth-ev-{i:03d}", "kind": kind, "label_uncertain": unc, "confidence": conf,
            "start": pd.Timestamp(start, tz="UTC"), "end": pd.Timestamp(end, tz="UTC"), "lat": lat, "lon": lon,
            "n_cells": len(cell_names), "cells": ",".join(cells[c] for c in cell_names), "n_aircraft": 20 + i,
            "k_degraded": 10 + i, "peak_share": 0.5, "peak_ci_lo": 0.3, "min_p": 0.001 * i, "n_spoof_aircraft": i % 3,
            "dest_lat": lat + 0.5, "dest_lon": lon + 0.5, "dest_spread_km": 1.5, "median_implied_kt": 600.0,
            "share_nominal_accuracy": 0.9, "day": start[:10], "data_class": data_class,
        }  # fmt: skip

    events = pd.DataFrame(
        [
            ev(1, "jamming_like", "high", False, "2026-01-10T03:00:00", "2026-01-10T09:00:00", ["dubai", "abu_dhabi"], "dubai"),
            ev(2, "spoofing_like", "medium", False, "2026-01-10T12:00:00", "2026-01-10T15:00:00", [], "doha"),
            ev(3, "both", "low", True, "2026-01-11T00:00:00", "2026-01-11T06:00:00", ["muscat"], "muscat"),
            ev(4, "uncertain", "low", True, "2026-01-11T06:00:00", "2026-01-11T12:00:00", ["bahrain"], "bahrain"),
            ev(5, "jamming_like", "medium", False, "2026-01-11T15:00:00", "2026-01-11T21:00:00", ["kuwait"], "kuwait"),
        ]
    )  # fmt: skip

    cov = pd.DataFrame(
        [
            {"h3": c, "slot": s, "stratum": "enroute", "presence": round(0.5 + 0.05 * s, 3), "mean_n": 10.0 + s,
             "coverage_class": "covered" if s % 2 else "marginal"}
            for c in cells.values()
            for s in range(24 // GRID.bucket_hours)
        ]
    )  # fmt: skip

    cb.to_parquet(root / "cell_buckets.parquet", index=False)
    events.to_parquet(root / "events.parquet", index=False)
    cov.to_parquet(root / "coverage.parquet", index=False)
    banner = f"{data_class.upper()} TEST RELEASE. Invented for API tests, not observed."
    (root / "validation.json").write_text(
        json.dumps({"schema": "tashwish.validation.v1", "data_class": data_class, "note": banner,
                    "headline": {"precision": {"value": 0.8, "ci": [0.6, 0.9]}}}),
        encoding="utf-8", newline="\n",
    )  # fmt: skip
    (root / "freshness.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "latest_day": DAYS[-1],
                "last_run_status": "success",
                "last_success_at": generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "fallback_active": False,
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    (root / "DATA_CARD.md").write_text(f"# Data card\n\n{banner}\n\n{NOTICE}\n", encoding="utf-8", newline="\n")
    (root / "NOTICE").write_text(f"{DATASET_ATTRIBUTION}\n{banner}\n", encoding="utf-8", newline="\n")
    (root / "ODbL-1.0.txt").write_text("TEST PLACEHOLDER, not the licence text.\n", encoding="utf-8", newline="\n")

    data_files = [
        "cell_buckets.parquet", "events.parquet", "coverage.parquet", "validation.json", "freshness.json",
        "DATA_CARD.md", "NOTICE", "ODbL-1.0.txt",
    ]  # fmt: skip
    (root / "checksums.sha256").write_text(
        "".join(f"{_sha(root / f)}  {f}\n" for f in data_files), encoding="utf-8", newline="\n"
    )
    files = {
        f: {"path": f, "sha256": _sha(root / f), "bytes": (root / f).stat().st_size}
        for f in [*data_files, "checksums.sha256"]
    }

    manifest = {
        "schema": "tashwish.release.v1",
        "dataset_version": dataset_version,
        "generated_at": generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_commit": "test0000",
        "data_class": data_class,
        "attribution": DATASET_ATTRIBUTION,
        "grid": {"h3_res": GRID.h3_res, "bucket_hours": GRID.bucket_hours},
        "bbox": {"south": cfg.REGION.lat_min, "west": cfg.REGION.lon_min, "north": cfg.REGION.lat_max, "east": cfg.REGION.lon_max},
        "days": [
            {"day": d, "split": "dev" if i == 0 else "held_out", "rows": int((cb.bucket_start.dt.strftime("%Y-%m-%d") == d).sum()),
             "aircraft": 100 + i}
            for i, d in enumerate(DAYS)
        ],
        "latest_day": DAYS[-1],
        "files": files,
    }  # fmt: skip
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    return SynthRelease(root, cb, events, cells, generated_at)
