"""Release builder on a tiny SYNTHETIC processed directory (invented numbers, test only)."""

import hashlib
import json
import sys

import numpy as np
import pandas as pd

from tashwish.api.release import Release
from tashwish.operate.processed import write_day
from tashwish.release import build


def _cb(day):
    b = pd.Timestamp(day, tz="UTC")
    rows = []
    for i, st in enumerate(("ok", "insufficient", "coverage_lost")):
        ok = st == "ok"
        rows.append({
            "cell": "84436e3ffffffff", "bucket": b + pd.Timedelta(hours=3 * i), "stratum": "enroute", "n_aircraft": 9 if ok else 2 * (i == 1),
            "k_strong": 3 if ok else 0, "share_strong": 1 / 3 if ok else np.nan, "ci_lo_strong": 0.12 if ok else np.nan,
            "ci_hi_strong": 0.65 if ok else np.nan, "status": st, "coverage_class": "covered", "slot": i,
        })  # fmt: skip
    return pd.DataFrame(rows)


def _ev(day):
    return pd.DataFrame([{
        "event_id": f"J-{day}", "kind": "jamming_like", "label_uncertain": True, "confidence": "low",
        "start": pd.Timestamp(day, tz="UTC"), "end": pd.Timestamp(day, tz="UTC") + pd.Timedelta(hours=3), "lat": 25.0, "lon": 55.0,
        "n_cells": 1, "cells": "84436e3ffffffff", "n_aircraft": 9, "k_degraded": 3, "peak_share": 0.33, "peak_ci_lo": 0.12,
        "min_p": 0.001, "n_spoof_aircraft": np.nan, "dest_lat": np.nan, "dest_lon": np.nan, "dest_spread_km": np.nan,
        "median_implied_kt": np.nan, "share_nominal_accuracy": np.nan,
    }])  # fmt: skip


def test_build_is_idempotent_and_release_loads(tmp_path, monkeypatch):
    proc = tmp_path / "processed"
    for d, sp in (("2026-02-08", "dev"), ("2026-02-09", "held_out")):
        write_day(proc, d, _cb(d), _ev(d), split=sp, mode="m", rows=10, aircraft=5, ingested_at="2026-02-10T00:00:00Z")
    state = tmp_path / "state"
    state.mkdir()
    pd.DataFrame(
        [
            {
                "cell": "84436e3ffffffff",
                "slot": 0,
                "stratum": "enroute",
                "presence": 0.9,
                "mean_n": 9.0,
                "coverage_class": "covered",
            }
        ]
    ).to_parquet(state / "coverage.parquet")
    argv = ["x", "--processed", str(proc), "--web", str(tmp_path / "web"), "--release", str(tmp_path / "rel"), "--state", str(state), "--results", str(tmp_path / "res")]  # fmt: skip
    monkeypatch.setattr(sys, "argv", argv)
    build.main()
    first = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp_path / "rel").glob("*.parquet")}
    build.main()
    second = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp_path / "rel").glob("*.parquet")}
    assert first == second
    cbo = pd.read_parquet(tmp_path / "rel" / "cell_buckets.parquet")
    assert cbo.loc[cbo.status != "ok", ["share", "ci_lo", "ci_hi"]].isna().all().all()
    assert not any("icao" in c.lower() for c in cbo.columns)
    day = json.loads((tmp_path / "web" / "days" / "2026-02-08.json").read_text())
    assert day["data_class"] == "observed" and len(day["cells"]) == 3
    assert [r for r in day["cells"] if r[6] != "ok"][0][4] is None
    Release(tmp_path / "rel", verify_hashes=True)  # the API accepts the builder's output and the checksums match
