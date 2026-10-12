"""Release builder on a tiny SYNTHETIC processed directory (invented numbers, test only)."""

import hashlib
import json
import re
import sys

import numpy as np
import pandas as pd
import pytest

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


def _setup(tmp_path, monkeypatch, ev_fn=_ev):
    proc = tmp_path / "processed"
    for d in ("2026-02-08", "2026-02-09"):
        write_day(
            proc, d, _cb(d), ev_fn(d), split="dev", mode="m", rows=10, aircraft=5, ingested_at="2026-02-10T00:00:00Z"
        )
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    argv = ["x", "--processed", str(proc), "--web", str(tmp_path / "web"), "--release", str(tmp_path / "rel"), "--state", str(state), "--results", str(tmp_path / "res")]  # fmt: skip
    monkeypatch.setattr(sys, "argv", argv)
    return proc


def _snapshot(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_failed_build_leaves_previous_outputs_intact_and_exits_nonzero(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    build.main()
    before = (_snapshot(tmp_path / "web"), _snapshot(tmp_path / "rel"))

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(build, "data_card", boom)
    with pytest.raises(SystemExit) as e:
        build.main()
    assert e.value.code == 1
    assert (_snapshot(tmp_path / "web"), _snapshot(tmp_path / "rel")) == before
    assert not [p for p in tmp_path.iterdir() if ".new-" in p.name or ".old-" in p.name]


def test_dataset_version_changes_when_data_changes(tmp_path, monkeypatch):
    proc = _setup(tmp_path, monkeypatch)
    build.main()
    v1 = json.loads((tmp_path / "rel" / "manifest.json").read_text())["dataset_version"]
    assert re.fullmatch(r"observed-2026-02-09-[0-9a-f]{8}", v1)
    assert json.loads((tmp_path / "web" / "manifest.json").read_text())["dataset_version"] == v1
    build.main()
    assert json.loads((tmp_path / "rel" / "manifest.json").read_text())["dataset_version"] == v1  # stable
    cb = _cb("2026-02-08")
    cb.loc[0, "k_strong"] = 4  # a correction of an old day; latest_day is unchanged
    write_day(proc, "2026-02-08", cb, _ev("2026-02-08"), split="dev", mode="m", rows=10, aircraft=5, ingested_at=None)
    build.main()
    v2 = json.loads((tmp_path / "rel" / "manifest.json").read_text())["dataset_version"]
    assert v2 != v1 and v2.startswith("observed-2026-02-09-")


def _spoof_events(day):
    def row(i, n):
        t = pd.Timestamp(day, tz="UTC") + pd.Timedelta(hours=1, minutes=17, seconds=18)
        return {
            "event_id": f"S-{day}-{i}", "kind": "spoofing_like", "label_uncertain": False, "confidence": "low",
            "start": t, "end": t + pd.Timedelta(hours=3, minutes=5, seconds=3), "lat": 25.0, "lon": 55.0,
            "n_cells": 1, "cells": "84436e3ffffffff", "n_aircraft": 9, "k_degraded": 3, "peak_share": 0.33,
            "peak_ci_lo": 0.12, "min_p": 0.001, "n_spoof_aircraft": n, "dest_lat": 25.5, "dest_lon": 56.5,
            "dest_spread_km": 2.0, "median_implied_kt": 900.0, "share_nominal_accuracy": 0.1,
        }  # fmt: skip

    return pd.DataFrame([row(0, 3), row(1, 5)])


def test_event_times_are_bucket_rounded_and_small_groups_lose_destination(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, _spoof_events)
    build.main()
    ev = pd.read_parquet(tmp_path / "rel" / "events.parquet")
    ev = ev[ev["event_id"].str.startswith("S-2026-02-08")].sort_values("event_id")
    small, large = ev.iloc[0], ev.iloc[1]
    assert small["start"] == pd.Timestamp("2026-02-08 00:00", tz="UTC")  # floor of 01:17:18 to the 3 hour bucket
    assert small["end"] == pd.Timestamp("2026-02-08 06:00", tz="UTC")  # ceil of 04:22:21
    assert pd.isna(small["dest_lat"]) and pd.isna(small["dest_lon"])
    assert large["dest_lat"] == 25.5 and large["dest_lon"] == 56.5
    web = json.loads((tmp_path / "web" / "events.json").read_text())["events"]
    assert all(e["start"].endswith(":00:00Z") and e["end"].endswith(":00:00Z") for e in web)
    assert "Event times are rounded to the 3 hour bucket" in (tmp_path / "rel" / "DATA_CARD.md").read_text()


def test_non_observed_data_class_fails_the_build():
    with pytest.raises(ValueError):
        build.release_events(_ev("2026-02-08").assign(data_class="synthetic"))
    with pytest.raises(ValueError):
        build.release_cb(_cb("2026-02-08").assign(data_class="synthetic"))
