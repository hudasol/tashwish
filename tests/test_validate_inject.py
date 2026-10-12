"""Injection and discrimination tests. All frames are SYNTHETIC, built here."""

import h3
import numpy as np
import pandas as pd

from tashwish import config as cfg
from tashwish.detect.discriminate import combine
from tashwish.validate.inject import DATA_CLASS_SYNTHETIC, JamScenario, SpoofScenario, inject_jam, inject_spoof

GRID = cfg.GRID_MAIN
CELL = h3.latlng_to_cell(25.0, 55.0, GRID.h3_res)
OTHER = h3.latlng_to_cell(27.0, 58.0, GRID.h3_res)
B0 = pd.Timestamp("2026-03-05 06:00", tz="UTC")


def _ab(n=20):
    rows = []
    for cell in (CELL, OTHER):
        for i in range(n):
            for stratum in ("enroute", "high", "mid"):
                rows.append({"cell": cell, "bucket": B0, "icao24": f"a{i:05d}", "n_samples": 6, "n_strong": 0, "n_gpsjam": 0,
                             "first_ts": B0, "last_ts": B0, "stratum": stratum})  # fmt: skip
        rows.append({"cell": cell, "bucket": B0, "icao24": "low001", "n_samples": 6, "n_strong": 0, "n_gpsjam": 0,
                     "first_ts": B0, "last_ts": B0, "stratum": "low"})  # fmt: skip
    return pd.DataFrame(rows)


def test_inject_jam_degrades_exact_fraction_only_in_target():
    ab = _ab()
    sc = JamScenario("t", "2026-03-05", (CELL,), B0, 1, 0.5, seed=1)
    out, info = inject_jam(ab, sc, GRID)
    tgt = out[(out["cell"] == CELL) & (out["stratum"] == "enroute")]
    assert info == {"n_target": 20, "n_degraded": 10}
    assert (tgt["n_strong"] == tgt["n_samples"]).sum() == 10
    assert out[out["cell"] == OTHER]["n_strong"].sum() == 0  # other cell untouched
    assert out[out["stratum"] == "low"]["n_strong"].sum() == 0  # low stratum untouched
    assert ab["n_strong"].sum() == 0  # input not mutated
    assert out.attrs["data_class"] == DATA_CLASS_SYNTHETIC


def test_inject_jam_is_deterministic_and_consistent_across_strata():
    ab = _ab()
    sc = JamScenario("t", "2026-03-05", (CELL,), B0, 1, 0.3, seed=7)
    a, _ = inject_jam(ab, sc, GRID)
    b, _ = inject_jam(ab, sc, GRID)
    pd.testing.assert_frame_equal(a, b)
    deg = a[(a["n_strong"] > 0) & (a["cell"] == CELL)].groupby("stratum")["icao24"].apply(set)
    assert deg["enroute"] == deg["high"] == deg["mid"]


def _flight(icao, lat, n=40):
    t = [B0 + pd.Timedelta(seconds=10 * i) for i in range(n)]
    return pd.DataFrame({"icao24": icao, "ts": t, "lat": lat, "lon": [55.0 + 0.002 * i for i in range(n)], "gs_kt": 450.0,
                         "on_ground": False, "src_type": "adsb_icao", "nic": 8, "nac_p": 9})  # fmt: skip


def test_inject_spoof_displaces_requested_aircraft_only():
    pts = pd.concat([_flight(f"f{i:05d}", 25.0 + 0.05 * i) for i in range(6)], ignore_index=True)
    sc = SpoofScenario("s", "2026-03-05", 25.0, 55.0, B0, 300.0, 3, 28.0, 60.0, seed=3)
    out, info = inject_spoof(pts, sc)
    assert info["n_spoofed"] == 3
    moved = out.groupby("icao24")["lat"].max() > 27.0
    assert moved.sum() == 3
    assert pts["lat"].max() < 26.0  # original untouched
    assert out.attrs["data_class"] == DATA_CLASS_SYNTHETIC
    # accuracy fields stay nominal under spoof injection
    assert (out["nic"] == 8).all()


def test_inject_spoof_never_exceeds_available_aircraft():
    pts = pd.concat([_flight(f"f{i:05d}", 25.0 + 0.05 * i) for i in range(2)], ignore_index=True)
    sc = SpoofScenario("s", "2026-03-05", 25.0, 55.0, B0, 300.0, 8, 28.0, 60.0, seed=3)
    _, info = inject_spoof(pts, sc)
    assert info == {"n_spoofed": 2, "n_requested": 8}


def _jam_ev(cells, start, conf="high"):
    return pd.DataFrame([{"event_id": "J-aaa", "kind": "jamming_like", "tier": "strong", "start": start, "end": start + pd.Timedelta(hours=3),
                          "n_cells": len(cells), "n_buckets": 1, "cells": ",".join(cells), "k_total": 12, "n_total": 20,
                          "peak_share": 0.6, "peak_ci_lo": 0.4, "min_p": 1e-6, "lat": 25.0, "lon": 55.0, "confidence": conf}])  # fmt: skip


def _spoof_ev(lat, lon, start, conf="high"):
    return pd.DataFrame([{"event_id": "S-bbb", "kind": "spoofing_like", "start": start, "end": start + pd.Timedelta(minutes=30),
                          "n_aircraft": 6, "n_jumps": 6, "dest_lat": 27.0, "dest_lon": 58.0, "dest_spread_km": 3.0,
                          "origin_lat": lat, "origin_lon": lon, "origin_spread_km": 20.0, "median_implied_kt": 5000.0,
                          "median_gs_kt": 450.0, "share_nominal_accuracy": 0.9, "confidence": conf}])  # fmt: skip


def test_combine_overlap_gives_both_and_separate_gives_two():
    start = B0 + pd.Timedelta(minutes=30)
    both = combine(_jam_ev([CELL], B0), _spoof_ev(25.0, 55.0, start))
    assert len(both) == 1 and both.iloc[0]["kind"] == "both" and not both.iloc[0]["label_uncertain"]
    apart = combine(_jam_ev([OTHER], B0), _spoof_ev(23.0, 50.0, start))
    assert sorted(apart["kind"]) == ["jamming_like", "spoofing_like"]


def test_combine_uncertainty_flags():
    start = B0 + pd.Timedelta(minutes=30)
    assert (
        combine(_jam_ev([CELL], B0, "low"), _spoof_ev(0, 0, start, "high"))
        .query("kind == 'jamming_like'")
        .iloc[0]["label_uncertain"]
    )
    assert (
        combine(_jam_ev([OTHER], B0), _spoof_ev(23.0, 50.0, start, "medium"))
        .query("kind == 'spoofing_like'")
        .iloc[0]["label_uncertain"]
    )
    assert combine(_jam_ev([CELL], B0), _spoof_ev(25.0, 55.0, start, "medium")).iloc[0]["label_uncertain"]


def test_combine_empty():
    out = combine(pd.DataFrame(), pd.DataFrame())
    assert out.empty and "kind" in out.columns and not np.any(out.get("label_uncertain", []))
