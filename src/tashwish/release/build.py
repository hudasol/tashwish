"""Build the dataset release and the dashboard JSON from processed/ (idempotent).

  python -m tashwish.release.build --processed processed --web web/data --release release [--state state] [--results results]

Inputs hold no aircraft identifiers. Everything written here is derived from files, never typed by hand: the data card
numbers, the validation block and the manifest all come from processed/ and results/.
Estimates (share, interval) exist only for status `ok`; every other status is written with null estimates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config as cfg
from ..attribution import DATASET_ATTRIBUTION
from ..operate.processed import list_days, read_day_meta

ROOT = Path(__file__).resolve().parents[3]
WEB_SCHEMA = "tashwish.web.v1"
REL_SCHEMA = "tashwish.release.v1"
SCHEMA_VALIDATION = "tashwish.validation.v1"
GRID = cfg.GRID_MAIN


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def code_commit() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
            ).stdout.strip()
            or "unknown"
        )
    except OSError:
        return "unknown"


def iso(t) -> str:
    return pd.Timestamp(t).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":"), allow_nan=False, default=_json_default), encoding="utf-8")
    tmp.replace(p)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return iso(o)
    raise TypeError(type(o))


def _clean(v):
    return None if (isinstance(v, float) and np.isnan(v)) else v


def load_processed(processed: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    cbs, evs, metas = [], [], []
    for d in list_days(processed):
        base = processed / "days" / d
        meta = read_day_meta(processed, d)
        cb = pd.read_parquet(base / "cb.parquet")
        cb["day"] = d
        ev = pd.read_parquet(base / "events.parquet")
        ev["day"] = d
        cbs.append(cb)
        evs.append(ev)
        metas.append(meta)
    return (
        pd.concat(cbs, ignore_index=True) if cbs else pd.DataFrame(),
        pd.concat(evs, ignore_index=True) if evs else pd.DataFrame(),
        metas,
    )


def _assert_observed(df: pd.DataFrame, name: str) -> None:
    """The release builder only publishes observed data; a synthetic processed tree must not be relabelled."""
    if "data_class" in df.columns:
        bad = sorted(str(x) for x in set(df["data_class"].dropna().unique()) - {"observed"})
        if bad:
            raise ValueError(f"{name} carries data_class {bad}; the release builder accepts only 'observed' data")


def release_cb(cb: pd.DataFrame) -> pd.DataFrame:
    _assert_observed(cb, "cell buckets")
    ok = cb["status"] == "ok"
    out = pd.DataFrame({
        "h3": cb["cell"], "bucket_start": cb["bucket"], "slot": cb["slot"].astype(int), "stratum": cb["stratum"],
        "n_aircraft": cb["n_aircraft"].astype(int), "k_strong": cb["k_strong"].astype(int),
        "share": cb["share_strong"].where(ok), "ci_lo": cb["ci_lo_strong"].where(ok), "ci_hi": cb["ci_hi_strong"].where(ok),
        "status": cb["status"], "coverage_class": cb["coverage_class"], "data_class": "observed",
    })  # fmt: skip
    out["day"] = out["bucket_start"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d")
    return out.sort_values(["bucket_start", "stratum", "h3"]).reset_index(drop=True)


def daily_region(cb: pd.DataFrame, metas: list[dict]) -> pd.DataFrame:
    """Region wide en route degraded share per day over testable (`ok`) cell-buckets. Units are aircraft per cell-bucket."""
    from ..metrics.stats import wilson_interval

    split = {m["day"]: m["split"] for m in metas}
    e = cb[(cb["stratum"] == "enroute") & (cb["status"] == "ok")]
    g = e.groupby("day", as_index=False).agg(n=("n_aircraft", "sum"), k=("k_strong", "sum"))
    lo, hi = wilson_interval(g["k"].to_numpy(), g["n"].to_numpy())
    g["share"], g["ci_lo"], g["ci_hi"] = g["k"] / g["n"], lo, hi
    g["split"] = g["day"].map(split)
    return g[["day", "split", "n", "k", "share", "ci_lo", "ci_hi"]]


def release_events(ev: pd.DataFrame) -> pd.DataFrame:
    if ev.empty:
        return ev
    _assert_observed(ev, "events")
    out = ev.copy()
    out["data_class"] = "observed"
    return out.sort_values(["start", "event_id"]).reset_index(drop=True)


def write_web(web: Path, cb: pd.DataFrame, ev: pd.DataFrame, metas: list[dict], cov: pd.DataFrame | None,
              generated_at: str, latest_day: str | None, results_block: dict, methods: dict,
              daily: pd.DataFrame | None = None) -> None:  # fmt: skip
    common = {"schema": WEB_SCHEMA, "data_class": "observed", "generated_at": generated_at,
              "code_commit": code_commit(), "attribution": DATASET_ATTRIBUTION}  # fmt: skip
    shutil.rmtree(web / "days", ignore_errors=True)
    for d, g in cb[cb["stratum"] == "enroute"].groupby("day"):
        rows = []
        for r in g.itertuples():
            ok = r.status == "ok"
            rows.append([r.h3, int(r.slot), int(r.n_aircraft), int(r.k_strong),
                         _clean(round(float(r.ci_lo), 4)) if ok else None, _clean(round(float(r.ci_hi), 4)) if ok else None,
                         r.status, r.coverage_class])  # fmt: skip
        _dump(web / "days" / f"{d}.json", {**common, "day": d, "cells": rows})
    events = []
    for r in ev.itertuples():
        evidence = {k: _clean(getattr(r, k)) for k in ("n_spoof_aircraft", "dest_spread_km", "median_implied_kt",
                    "share_nominal_accuracy") if hasattr(r, k)}  # fmt: skip
        events.append({
            "event_id": r.event_id, "kind": r.kind, "label_uncertain": bool(r.label_uncertain), "confidence": r.confidence,
            "start": iso(r.start), "end": iso(r.end), "n_cells": int(r.n_cells) if not pd.isna(r.n_cells) else 0,
            "cells": [c for c in str(r.cells).split(",") if c] if isinstance(r.cells, str) else [],
            "lat": _clean(round(float(r.lat), 4)), "lon": _clean(round(float(r.lon), 4)),
            "n_aircraft": _clean(r.n_aircraft), "k_degraded": _clean(r.k_degraded), "peak_share": _clean(r.peak_share),
            "peak_ci_lo": _clean(r.peak_ci_lo), "min_p": _clean(r.min_p),
            "evidence": evidence, "methods": ["event-definition", "wilson-interval", "fdr-control"],
        })  # fmt: skip
    _dump(web / "events.json", {**common, "events": events})
    cov_rows = []
    if cov is not None and len(cov):
        c = cov[cov["stratum"] == "enroute"]
        cov_rows = [{"h3": r.cell, "slot": int(r.slot), "presence": round(float(r.presence), 3), "class": r.coverage_class}
                    for r in c.itertuples()]  # fmt: skip
    _dump(web / "coverage.json", {**common, "cells": cov_rows})
    _dump(web / "validation.json", {**common, "results": results_block.get("results", [])})
    _dump(web / "methods.json", {**common, "metrics": methods})
    if daily is not None:
        _dump(web / "daily.json", {**common, "days": daily.round(4).to_dict(orient="records")})
    _dump(web / "manifest.json", {**common, "dataset_version": f"observed-{latest_day}" if latest_day else "empty",
          "grid": {"h3_res": GRID.h3_res, "bucket_hours": GRID.bucket_hours},
          "bbox": {"south": cfg.REGION.lat_min, "west": cfg.REGION.lon_min, "north": cfg.REGION.lat_max, "east": cfg.REGION.lon_max},
          "days": metas, "latest_day": latest_day, "freshness_hours_hint": 24})  # fmt: skip


def data_card(template: Path, metas: list[dict], cb: pd.DataFrame, ev: pd.DataFrame, latest_day: str | None,
              commit: str, validation_note: str) -> str:  # fmt: skip
    head = template.read_text(encoding="utf-8").split("## Files, schema")[0]
    head = head.replace(
        "**Status: DRAFT template. No dataset has been released.**", "**Status: generated for a release candidate.**"
    )
    head = head.replace("- Source release tags and build commit: `FROM RESULTS`.", f"- Build commit: `{commit}`. Source: adsb.lol globe_history daily releases (the release kind and tag are in the ingest manifest).")  # fmt: skip
    n_by_split = pd.Series([m["split"] for m in metas]).value_counts().to_dict()
    st = cb["status"].value_counts().to_dict()
    kinds = ev["kind"].value_counts().to_dict() if len(ev) else {}
    unc = int(ev["label_uncertain"].sum()) if len(ev) else 0
    lines = [
        "## Files, schema, coverage, validation numbers, known biases",
        "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} from processed result files. Latest day: {latest_day}. "
        f"Days: {len(metas)} ({', '.join(f'{k} {v}' for k, v in sorted(n_by_split.items()))}).",
        "",
        "- `cell_buckets.parquet` and `.csv.gz`: h3, bucket_start, slot, stratum, n_aircraft, k_strong, share, ci_lo, ci_hi, status, coverage_class, data_class.",
        "  `share`, `ci_lo`, `ci_hi` are empty unless status is `ok`.",
        "- `events.parquet` and `.csv.gz`: jamming-like, spoofing-like, both, and uncertain events. No identifiers.",
        "- `coverage.parquet`: baseline coverage per (cell, slot, stratum), fitted on development days only.",
        "- `validation.json`, `freshness.json`, `manifest.json`, `checksums.sha256`, `NOTICE`, `ODbL-1.0.txt`.",
        "",
        f"Cell-bucket rows by status: {', '.join(f'{k} {v}' for k, v in sorted(st.items()))}.",
        f"Events by kind: {', '.join(f'{k} {v}' for k, v in sorted(kinds.items())) or 'none'}; marked uncertain: {unc}.",
        "",
        validation_note,
        "",
        "Known biases: coverage follows volunteer receivers and changes over time; a missing or insufficient cell is not a quiet cell; "
        "degraded accuracy indicators have non interference causes; the window is short and not representative of other seasons; "
        "dates are not independent samples.",
        "Days scored `dev_leave_one_day_out` were also used to fit the baseline (each day excluded from its own baseline). "
        "Days marked `held_out` were scored once with a baseline fitted on development days only.",
        "",
        "## Synthetic data",
        "",
        "None of the files above contains synthetic data. Synthetic scenario outputs are kept separate and are not part of this release.",
        "",
    ]
    return head + "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--processed", type=Path, default=Path("processed"))
    ap.add_argument("--web", type=Path, default=Path("web/data"))
    ap.add_argument("--release", type=Path, default=Path("release"))
    ap.add_argument("--state", type=Path, default=ROOT / "state")
    ap.add_argument("--results", type=Path, default=ROOT / "results")
    a = ap.parse_args()

    cb_raw, ev_raw, metas = load_processed(a.processed)
    fresh_p = a.processed / "freshness.json"
    fresh = json.loads(fresh_p.read_text()) if fresh_p.exists() else {}
    days = [m["day"] for m in metas]
    latest_day = max(days) if days else None
    generated_at = fresh.get("generated_at") or (iso(pd.Timestamp.now("UTC")) if days else None)
    if not days:
        print("no processed days; nothing to build")
        return
    cov = pd.read_parquet(a.state / "coverage.parquet") if (a.state / "coverage.parquet").exists() else None
    headline_p = a.results / "headline.json"
    results_block = json.loads(headline_p.read_text()) if headline_p.exists() else {"results": []}
    sample = ROOT / "web" / "data" / "sample_synthetic" / "methods.json"
    methods = json.loads(sample.read_text())["metrics"] if sample.exists() else {}

    cb = release_cb(cb_raw)
    ev = release_events(ev_raw)
    dr = daily_region(cb, metas)
    a.results.mkdir(parents=True, exist_ok=True)
    dr.to_csv(a.results / "daily_region.csv", index=False)
    write_web(a.web, cb, ev, metas, cov, generated_at, latest_day, results_block, methods, dr)

    rel = a.release
    rel.mkdir(parents=True, exist_ok=True)
    dr.to_csv(rel / "daily_region.csv", index=False)
    cbo = cb.drop(columns=["day"])
    cbo.to_parquet(rel / "cell_buckets.parquet", index=False, compression="zstd")
    cbo.to_csv(rel / "cell_buckets.csv.gz", index=False)
    ev_out = ev.copy()
    ev_out.to_parquet(rel / "events.parquet", index=False, compression="zstd")
    ev_out.to_csv(rel / "events.csv.gz", index=False)
    if cov is not None:
        cov_out = cov.rename(columns={"cell": "h3"})[["h3", "slot", "stratum", "presence", "mean_n", "coverage_class"]]
        cov_out.to_parquet(rel / "coverage.parquet", index=False)
    val = {"schema": SCHEMA_VALIDATION, "data_class": "observed", **results_block}
    (rel / "validation.json").write_text(json.dumps(val, indent=1, default=_json_default, allow_nan=False))
    (rel / "freshness.json").write_text(
        json.dumps({**fresh, "generated_at": generated_at, "latest_day": latest_day}, indent=1)
    )
    note = (
        "Validation numbers: see `validation.json` and docs/VALIDATION.md in the repository (generated from result files)."
        if results_block.get("results")
        else "Validation numbers: not yet attached to this build."
    )
    (rel / "DATA_CARD.md").write_text(
        data_card(ROOT / "docs" / "DATA_CARD.md", metas, cb_raw, ev_raw, latest_day, code_commit(), note),
        encoding="utf-8",
    )
    shutil.copy(ROOT / "NOTICE", rel / "NOTICE")
    shutil.copy(ROOT / "licenses" / "ODbL-1.0.txt", rel / "ODbL-1.0.txt")
    names = sorted(p.name for p in rel.iterdir() if p.is_file() and p.name not in ("manifest.json", "checksums.sha256"))
    (rel / "checksums.sha256").write_text("".join(f"{sha256_file(rel / n)}  {n}\n" for n in names))
    files = {
        n: {"path": n, "sha256": sha256_file(rel / n), "bytes": (rel / n).stat().st_size}
        for n in [*names, "checksums.sha256"]
    }
    manifest = {
        "schema": REL_SCHEMA, "dataset_version": f"observed-{latest_day}", "generated_at": generated_at,
        "code_commit": code_commit(), "data_class": "observed", "attribution": DATASET_ATTRIBUTION,
        "grid": {"h3_res": GRID.h3_res, "bucket_hours": GRID.bucket_hours},
        "bbox": {"south": cfg.REGION.lat_min, "west": cfg.REGION.lon_min, "north": cfg.REGION.lat_max, "east": cfg.REGION.lon_max},
        "days": metas, "latest_day": latest_day, "files": files,
    }  # fmt: skip
    (rel / "manifest.json").write_text(json.dumps(manifest, indent=1, default=_json_default))
    print(f"built release for {len(days)} days, latest {latest_day}")


if __name__ == "__main__":
    main()
