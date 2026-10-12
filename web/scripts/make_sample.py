"""Generate the labelled SYNTHETIC sample dataset for the dashboard (web/data/sample_synthetic/).

Everything here is invented with a seeded random generator. It exists only so the dashboard can be built and tested
against the contract in docs/WEB_DATA_CONTRACT.md before real data exists. It must never be shown as observed data:
every file carries data_class = "synthetic".

usage (from the repo root):
    .venv/bin/python web/scripts/make_sample.py            # write the sample
    .venv/bin/python web/scripts/make_sample.py --check    # verify attribution text and data_class in web/data/**

The attribution string is imported from src/tashwish/attribution.py (single source of truth) and copied verbatim
into every file.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import subprocess
import sys
from pathlib import Path

import h3
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tashwish.attribution import DATASET_ATTRIBUTION  # noqa: E402

OUT = ROOT / "web" / "data" / "sample_synthetic"
SCHEMA = "tashwish.web.v1"
SEED = 20261012
H3_RES = 4
BUCKET_HOURS = 3
SLOTS = 8
N_DAYS = 7
MIN_N = 6  # synthetic minimum sample rule for status "ok"
BASELINE_P = 0.04
SOUTH, NORTH, WEST, EAST = 22.0, 31.0, 46.0, 60.0

# Hub positions (lat, lon, strength). Invented traffic only; no claim about real traffic levels.
HUBS = [
    (25.25, 55.36, 9.0),
    (24.45, 54.65, 7.0),
    (25.27, 51.56, 6.0),
    (26.27, 50.63, 4.5),
    (29.23, 47.97, 5.0),
    (23.59, 58.28, 4.0),
    (26.47, 49.80, 3.5),
    (24.96, 46.70, 3.0),
]
DIURNAL = np.array([0.35, 0.30, 0.7, 1.0, 1.1, 1.0, 0.8, 0.55])

# Invented interference patterns: (id, kind, centre lat, centre lon, radius deg, day idx list, slots, peak p, confidence_hint)
HOTSPOTS = [
    ("SYN-0001", "jamming_like", 26.4, 52.2, 0.95, [2, 3], [3, 4, 5, 6], 0.60, "high", False),
    ("SYN-0002", "both", 28.7, 48.7, 0.85, [4, 5, 6], [0, 1, 2], 0.34, "medium", False),
    ("SYN-0003", "spoofing_like", 25.9, 53.8, 0.65, [5], [4, 5], 0.30, "low", True),
    ("SYN-0004", "uncertain", 27.9, 50.4, 0.60, [1], [2, 3], 0.28, "low", True),
]
OUTAGE = {"day": 3, "slots": [4, 5], "lat": 25.2, "lon": 55.3, "radius": 0.9}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def binom_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return float(sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def dist_deg(lat1, lon1, lat2, lon2) -> float:
    return math.hypot(lat1 - lat2, (lon1 - lon2) * math.cos(math.radians(26)))


def envelope(now: str, commit: str) -> dict:
    return {
        "schema": SCHEMA,
        "data_class": "synthetic",
        "generated_at": now,
        "code_commit": commit,
        "attribution": DATASET_ATTRIBUTION,
    }


def build(now: dt.datetime) -> None:
    rng = np.random.default_rng(SEED)
    try:
        commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        commit = "unknown"
    now_s = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    env = envelope(now_s, commit)

    # Universe of res-4 cells over the lattice.
    cells: dict[str, tuple[float, float]] = {}
    for lat in np.arange(SOUTH, NORTH, 0.08):
        for lon in np.arange(WEST, EAST, 0.08):
            c = h3.latlng_to_cell(float(lat), float(lon), H3_RES)
            if c not in cells:
                cells[c] = h3.cell_to_latlng(c)
    ids = sorted(cells)

    # Static intensity and receiver coverage per cell.
    lam = {}
    cov = {}
    for c in ids:
        lat, lon = cells[c]
        w = sum(s * math.exp(-((dist_deg(lat, lon, hl, ho) / 1.1) ** 2)) for hl, ho, s in HUBS)
        # corridor along the Gulf axis
        ax0, ay0, ax1, ay1 = 29.5, 48.5, 25.8, 56.5
        t = max(
            0.0,
            min(1.0, ((lat - ax0) * (ax1 - ax0) + (lon - ay0) * (ay1 - ay0)) / ((ax1 - ax0) ** 2 + (ay1 - ay0) ** 2)),
        )
        d = dist_deg(lat, lon, ax0 + t * (ax1 - ax0), ay0 + t * (ay1 - ay0))
        w += 4.0 * math.exp(-((d / 0.55) ** 2))
        lam[c] = 3.2 * w
        cov[c] = max(math.exp(-((dist_deg(lat, lon, hl, ho) / 1.5) ** 2)) for hl, ho, _ in HUBS)
    base_p = {c: float(np.clip(BASELINE_P + rng.normal(0, 0.012), 0.005, 0.12)) for c in ids}

    last_day = (now - dt.timedelta(days=1)).date()
    days = [last_day - dt.timedelta(days=N_DAYS - 1 - i) for i in range(N_DAYS)]
    daily_factor = rng.uniform(0.9, 1.1, size=N_DAYS)

    # Simulate observations.
    obs: dict[int, dict[tuple[str, int], tuple[int, int]]] = {i: {} for i in range(N_DAYS)}
    for di in range(N_DAYS):
        for c in ids:
            lat, lon = cells[c]
            for s in range(SLOTS):
                mean = lam[c] * cov[c] * DIURNAL[s] * daily_factor[di]
                n = int(rng.poisson(mean))
                p = base_p[c]
                for _, _, hl, ho, rad, dlist, slots, peak, _, _ in HOTSPOTS:
                    if di in dlist and s in slots:
                        dd = dist_deg(lat, lon, hl, ho)
                        if dd < rad:
                            p = max(p, peak * (1 - (dd / rad) ** 2) + base_p[c])
                k = int(rng.binomial(n, min(p, 0.95))) if n else 0
                obs[di][(c, s)] = (n, k)

    # Coverage fitted on dev days (first N_DAYS-2 days).
    dev_idx = list(range(N_DAYS - 2))
    cov_rows = []
    cov_class: dict[tuple[str, int], str] = {}
    for c in ids:
        for s in range(SLOTS):
            presence = float(np.mean([obs[di][(c, s)][0] for di in dev_idx]))
            cls = "covered" if presence >= 4 else ("marginal" if presence >= 1 else "no_coverage")
            cov_class[(c, s)] = cls
            cov_rows.append({"h3": c, "slot": s, "presence": round(presence, 2), "class": cls})

    # Day files.
    manifest_days = []
    all_rows: dict[int, list] = {}
    for di, day in enumerate(days):
        rows = []
        for c in ids:
            lat, lon = cells[c]
            for s in range(SLOTS):
                n, k = obs[di][(c, s)]
                cls = cov_class[(c, s)]
                in_outage = (
                    di == OUTAGE["day"]
                    and s in OUTAGE["slots"]
                    and dist_deg(lat, lon, OUTAGE["lat"], OUTAGE["lon"]) < OUTAGE["radius"]
                )
                if in_outage and cls in ("covered", "marginal"):
                    rows.append([c, s, 0, 0, None, None, "coverage_lost", cls])
                    continue
                if n == 0:
                    continue
                if cls == "no_coverage" or n < MIN_N:
                    status = "insufficient"
                else:
                    status = "ok"
                lo, hi = wilson(k, n) if status == "ok" else (None, None)
                rows.append(
                    [
                        c,
                        s,
                        n,
                        k,
                        None if lo is None else round(lo, 4),
                        None if hi is None else round(hi, 4),
                        status,
                        cls,
                    ]
                )
        all_rows[di] = rows
        sum_n = sum(r[2] for r in rows)
        manifest_days.append(
            {
                "day": day.isoformat(),
                "split": "dev" if di in dev_idx else "held_out",
                "rows": int(sum_n * 410),
                "aircraft": int(sum_n / 3.1),
                "ingested_at": (
                    dt.datetime.combine(day, dt.time(0), dt.UTC)
                    + dt.timedelta(days=1, hours=2, minutes=int(rng.integers(0, 40)))
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

    # Events derived from the generated data so the numbers agree with the day files.
    events = []
    for eid, kind, hl, ho, rad, dlist, slots, peak, conf, uncertain in HOTSPOTS:
        sel = []
        for di in dlist:
            for r in all_rows[di]:
                c, s, n, k, lo, hi, status, _ = r
                if s in slots and status == "ok" and dist_deg(cells[c][0], cells[c][1], hl, ho) < rad and k / n >= 0.15:
                    sel.append((di, r))
        if not sel:
            continue
        first = min((di, r[1]) for di, r in sel)
        last = max((di, r[1]) for di, r in sel)
        cset = sorted({r[0] for _, r in sel})
        n_air = sum(r[2] for _, r in sel)
        k_deg = sum(r[3] for _, r in sel)
        best = max(sel, key=lambda x: x[1][3] / x[1][2])
        shares = [r[3] / r[2] for _, r in sel]
        min_p = min(binom_tail(r[3], r[2], BASELINE_P) for _, r in sel)

        def stamp(di, s, end=False):
            base = dt.datetime.combine(days[di], dt.time(0), dt.UTC) + dt.timedelta(
                hours=BUCKET_HOURS * (s + (1 if end else 0))
            )
            return base.strftime("%Y-%m-%dT%H:%M:%SZ")

        events.append(
            {
                "event_id": eid,
                "kind": kind,
                "label_uncertain": uncertain,
                "confidence": conf,
                "start": stamp(*first),
                "end": stamp(*last, end=True),
                "n_cells": len(cset),
                "cells": cset,
                "lat": round(float(np.mean([cells[c][0] for c in cset])), 4),
                "lon": round(float(np.mean([cells[c][1] for c in cset])), 4),
                "n_aircraft": int(n_air),
                "k_degraded": int(k_deg),
                "peak_share": round(best[1][3] / best[1][2], 4),
                "peak_ci_lo": best[1][4],
                "min_p": float(f"{min_p:.3e}"),
                "evidence": {
                    "cell_buckets_flagged": len(sel),
                    "persistence_buckets": len({(di, r[1]) for di, r in sel}),
                    "median_share": round(float(np.median(shares)), 4),
                    "baseline_share": BASELINE_P,
                },
                "methods": ["event-definition", "wilson-interval", "fdr-control"],
            }
        )

    # Validation (invented numbers, clearly synthetic).
    def vrow(metric, k, n, scenario):
        lo, hi = wilson(k, n)
        return {
            "metric": metric,
            "scenario": scenario,
            "value": round(k / n, 4),
            "ci_lo": round(lo, 4),
            "ci_hi": round(hi, 4),
            "n": n,
        }

    validation = dict(env)
    validation["results"] = [
        vrow("precision", 41, 48, "synthetic_injection"),
        vrow("recall", 37, 50, "synthetic_injection"),
        {
            "metric": "detection_delay_hours",
            "scenario": "synthetic_injection",
            "value": 3.0,
            "ci_lo": 3.0,
            "ci_hi": 6.0,
            "n": 37,
        },
        vrow("false_alarm_day_share", 2, 14, "held_out_days"),
    ]

    A = {
        "grid-and-buckets": "grid-and-buckets",
        "unique": "unique-aircraft-count",
        "degraded": "degraded-definition",
        "wilson": "wilson-interval",
        "minn": "minimum-sample-rule",
        "cov": "coverage-model",
        "event": "event-definition",
        "fdr": "fdr-control",
        "conf": "confidence-grading",
        "prov": "data-provenance",
        "val": "validation-design",
    }

    def m(en, ar, anchor):
        return {"label_en": en, "label_ar": ar, "method_anchor": A[anchor]}

    metrics = {
        "h3_res": m("H3 resolution", "دقة شبكة H3", "grid-and-buckets"),
        "bucket_hours": m("Bucket length (hours)", "طول الفترة الزمنية (ساعات)", "grid-and-buckets"),
        "slot": m("Time slot (3 hour UTC bucket)", "الفترة الزمنية (3 ساعات بالتوقيت العالمي)", "grid-and-buckets"),
        "n_aircraft": m("Unique aircraft", "عدد الطائرات المميزة", "unique"),
        "k_strong": m("Aircraft with strongly degraded accuracy", "طائرات بدقة متدنية بشكل واضح", "degraded"),
        "degraded_share": m("Degraded share (k / n)", "نسبة التدني (ك / ن)", "degraded"),
        "ci_lo": m("Lower bound of 95% interval", "الحد الأدنى للفترة 95%", "wilson"),
        "ci_hi": m("Upper bound of 95% interval", "الحد الأعلى للفترة 95%", "wilson"),
        "status": m("Cell status", "حالة الخلية", "minn"),
        "coverage_class": m("Coverage class", "فئة التغطية", "cov"),
        "presence": m("Typical aircraft presence", "الحضور المعتاد للطائرات", "cov"),
        "kind": m("Event kind", "نوع الحدث", "event"),
        "label_uncertain": m("Label uncertain", "التصنيف غير مؤكد", "event"),
        "confidence": m("Confidence", "مستوى الثقة", "conf"),
        "n_cells": m("Cells in event", "عدد خلايا الحدث", "event"),
        "lat": m("Event centre latitude", "خط عرض مركز الحدث", "event"),
        "lon": m("Event centre longitude", "خط طول مركز الحدث", "event"),
        "k_degraded": m("Degraded aircraft in event", "الطائرات المتدنية الدقة في الحدث", "degraded"),
        "peak_share": m("Peak degraded share", "ذروة نسبة التدني", "degraded"),
        "peak_ci_lo": m("Lower bound at peak", "الحد الأدنى عند الذروة", "wilson"),
        "min_p": m("Smallest p value", "أصغر قيمة p", "fdr"),
        "evidence.cell_buckets_flagged": m("Flagged cell buckets", "فترات الخلايا المرصودة", "event"),
        "evidence.persistence_buckets": m("Persistence (buckets)", "الاستمرارية (فترات)", "event"),
        "evidence.median_share": m("Median degraded share", "وسيط نسبة التدني", "degraded"),
        "evidence.baseline_share": m("Baseline degraded share", "نسبة التدني المرجعية", "degraded"),
        "rows": m("Rows ingested", "عدد السجلات المستوردة", "prov"),
        "aircraft": m("Unique aircraft in day", "الطائرات المميزة في اليوم", "unique"),
        "generated_at": m("Generated at", "وقت الإنشاء", "prov"),
        "latest_day": m("Latest day", "آخر يوم", "prov"),
        "freshness_hours_hint": m("Expected refresh interval (hours)", "الفاصل المتوقع للتحديث (ساعات)", "prov"),
        "precision": m("Precision", "الدقة (precision)", "val"),
        "recall": m("Recall", "الاستدعاء (recall)", "val"),
        "detection_delay_hours": m("Detection delay (hours)", "زمن الكشف (ساعات)", "val"),
        "false_alarm_day_share": m(
            "Share of held out days with a false alarm", "نسبة الأيام المحجوبة ذات الإنذار الكاذب", "val"
        ),
    }
    methods = dict(env)
    methods["metrics"] = metrics

    manifest = dict(env)
    manifest.update(
        {
            "dataset_version": "sample-synthetic-0.1.0",
            "grid": {"h3_res": H3_RES, "bucket_hours": BUCKET_HOURS},
            "bbox": {"south": SOUTH, "west": WEST, "north": NORTH, "east": EAST},
            "days": manifest_days,
            "latest_day": days[-1].isoformat(),
            "freshness_hours_hint": 24,
        }
    )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "days").mkdir(exist_ok=True)

    def dump(path: Path, obj: dict) -> None:
        path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")

    dump(OUT / "manifest.json", manifest)
    for di, day in enumerate(days):
        d = dict(env)
        d["day"] = day.isoformat()
        d["cells"] = all_rows[di]
        dump(OUT / "days" / f"{day.isoformat()}.json", d)
    ev = dict(env)
    ev["events"] = events
    dump(OUT / "events.json", ev)
    co = dict(env)
    co["cells"] = cov_rows
    dump(OUT / "coverage.json", co)
    dump(OUT / "validation.json", validation)
    dump(OUT / "methods.json", methods)
    print(f"wrote sample to {OUT}: {len(ids)} cells, {N_DAYS} days, {len(events)} events")


def check() -> int:
    bad = 0
    for p in sorted((ROOT / "web" / "data").rglob("*.json")):
        if p.name.startswith("ne_"):
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("attribution") != DATASET_ATTRIBUTION:
            print(f"ATTRIBUTION MISMATCH {p}")
            bad += 1
        if d.get("schema") != SCHEMA:
            print(f"SCHEMA MISMATCH {p}")
            bad += 1
        if "sample_synthetic" in p.parts and d.get("data_class") != "synthetic":
            print(f"DATA_CLASS not synthetic in sample {p}")
            bad += 1
    print("ok" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--now", help="UTC ISO time to use as generation time (default: now)")
    a = ap.parse_args()
    if a.check:
        sys.exit(check())
    t = (
        dt.datetime.fromisoformat(a.now.replace("Z", "+00:00"))
        if a.now
        else dt.datetime.now(dt.UTC).replace(microsecond=0)
    )
    build(t)
