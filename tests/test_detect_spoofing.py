"""Spoofing detector tests. All trajectories here are SYNTHETIC, generated in the test."""

import numpy as np
import pandas as pd

from tashwish import config as cfg
from tashwish.detect.spoofing import build_spoof_events, find_jumps

T0 = pd.Timestamp("2026-03-05 10:00:00", tz="UTC")


def _flight(icao, lat0=24.0, lon0=52.0, hdg_lon_per_s=0.0022, n=60, dt=10, src="adsb_icao", nic=8, nacp=9):
    """Straight east-bound flight at about 450 kt: 0.0022 deg lon/s is about 0.22 km/s at 24N."""
    t = [T0 + pd.Timedelta(seconds=dt * i) for i in range(n)]
    return pd.DataFrame({
        "icao24": icao, "ts": t, "lat": lat0, "lon": [lon0 + hdg_lon_per_s * dt * i for i in range(n)],
        "gs_kt": 450.0, "on_ground": False, "src_type": src, "nic": nic, "nac_p": nacp,
    })  # fmt: skip


def _spoof(df, start_idx, to_lat, to_lon):
    df = df.copy()
    df.loc[df.index >= start_idx, ["lat", "lon"]] = [to_lat, to_lon]
    return df


def _points(k_spoofed, k_honest=3, spoof_lat=25.1, spoof_lon=55.2):
    frames = []
    for i in range(k_honest):
        frames.append(_flight(f"h{i:05d}", lat0=26.0 + 0.1 * i))
    for i in range(k_spoofed):
        f = _flight(f"s{i:05d}", lat0=24.0 + 0.1 * i)
        frames.append(_spoof(f, 30, spoof_lat + 0.01 * i, spoof_lon + 0.01 * i))
    return pd.concat(frames, ignore_index=True)


def test_honest_traffic_has_no_jumps():
    assert find_jumps(_points(0)).empty


def test_three_spoofed_aircraft_make_one_event():
    p = _points(3)
    j = find_jumps(p)
    assert len(j) == 3
    e = build_spoof_events(j)
    assert len(e) == 1 and e.iloc[0]["n_aircraft"] == 3 and e.iloc[0]["kind"] == "spoofing_like"
    assert e.iloc[0]["share_nominal_accuracy"] == 1.0  # accuracy fields stayed nominal in the injected scenario


def test_two_aircraft_are_not_an_event():
    assert build_spoof_events(find_jumps(_points(2))).empty


def test_high_confidence_needs_five_tight():
    e = build_spoof_events(find_jumps(_points(5)))
    assert e.iloc[0]["confidence"] == "high"


def test_mlat_jumps_are_ignored():
    p = _points(4)
    p.loc[p["icao24"].str.startswith("s"), "src_type"] = "mlat"
    assert find_jumps(p).empty


def test_ground_vehicles_ignored():
    p = _points(4)
    p.loc[p["icao24"].str.startswith("s"), "src_type"] = cfg.SRC_NON_TRANSPONDER
    assert find_jumps(p).empty


def test_slow_displacement_is_not_a_jump():
    # same 10 s cadence but only about 3 km displaced: below the distance gate
    p = _points(0)
    f = _spoof(_flight("x00001"), 30, 24.0, 52.0 + 0.0022 * 300 + 0.03)
    assert find_jumps(pd.concat([p, f])).empty


def test_gap_longer_than_dt_max_is_not_a_jump():
    f = _flight("g00001", dt=130)
    f = _spoof(f, 30, 25.1, 55.2)
    assert find_jumps(f).empty


def test_fast_aircraft_that_really_flies_fast_is_not_a_jump():
    # reported speed 1,200 kt and implied about 1,200 kt: ratio gate rejects
    f = _flight("fast01", hdg_lon_per_s=0.0059)
    f["gs_kt"] = 1200.0
    assert find_jumps(f).empty


def test_two_distant_clusters_make_two_events():
    p = pd.concat([_points(3, 0, 25.1, 55.2), _points(3, 0, 27.5, 49.5).assign(icao24=lambda d: "z" + d["icao24"])])
    e = build_spoof_events(find_jumps(p))
    assert len(e) == 2


def test_deterministic_and_row_order_independent():
    p = _points(4)
    a = build_spoof_events(find_jumps(p))
    b = build_spoof_events(find_jumps(p.sample(frac=1, random_state=3).reset_index(drop=True)))
    pd.testing.assert_frame_equal(a, b)


def test_no_aircraft_identifiers_in_event_table():
    e = build_spoof_events(find_jumps(_points(4)))
    assert not any("icao" in c for c in e.columns)


def test_implied_speed_is_physically_impossible_in_injection():
    j = find_jumps(_points(3))
    assert (j["implied_kt"] > cfg.SPOOF_JUMP_MIN_KT).all() and np.isfinite(j["implied_kt"]).all()
