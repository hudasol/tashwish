"""B4 naive speed threshold on SYNTHETIC trajectories with known answers."""

import pandas as pd

from tashwish import config as cfg
from tashwish.baselines import constants as bc
from tashwish.baselines.jamming import flag_fixed_fraction
from tashwish.baselines.spoofing import detect_naive_spoofing, find_naive_jumps, naive_spoof_events
from tashwish.detect.discriminate import combine
from tashwish.detect.jamming import build_events
from tashwish.detect.spoofing import build_spoof_events, find_jumps

T0 = pd.Timestamp("2026-03-05 10:00:00", tz="UTC")


def _flight(icao, lat0=24.0, lon0=52.0, dlon_per_s=0.0022, n=60, dt=10.0, src="adsb_icao"):
    """Straight east bound flight at about 430 kt (0.0022 degrees of longitude per second at 24 N)."""
    t = [T0 + pd.Timedelta(seconds=dt * i) for i in range(n)]
    return pd.DataFrame({
        "icao24": icao, "ts": t, "lat": lat0, "lon": [lon0 + dlon_per_s * dt * i for i in range(n)], "gs_kt": 450.0,
        "on_ground": False, "src_type": src, "nic": 8, "nac_p": 9,
    })  # fmt: skip


def _jump(df, idx, d_lon):
    df = df.copy()
    df.loc[df.index >= idx, "lon"] += d_lon
    return df


def test_constants_match_the_specification():
    assert (bc.B4_MIN_KT, bc.B4_DT_MAX_S, bc.B4_DT_FLOOR_S) == (800.0, 120.0, 1.0)


def test_honest_traffic_has_no_naive_jumps():
    assert find_naive_jumps(_flight("a00001")).empty


def test_a_single_aircraft_jump_is_an_event_unlike_the_system():
    p = _jump(_flight("a00001"), 30, 1.0)  # about 100 km in 10 s: far above 800 kt
    jumps, events = detect_naive_spoofing(p)
    assert len(jumps) == 1 and len(events) == 1
    assert events.iloc[0]["n_aircraft"] == 1
    assert build_spoof_events(find_jumps(p)).empty  # the system needs 3 aircraft


def test_a_small_fast_jump_is_flagged_by_b4_but_not_by_the_system_filter():
    p = _flight("a00002", dt=1.0, dlon_per_s=0.0022)
    p = _jump(
        p, 30, 0.003
    )  # extra 0.3 km in 1 s on top of 0.22 km per second: about 1000 kt over 0.5 km, under the system's 5 km minimum
    assert len(find_naive_jumps(p)) == 1
    assert find_jumps(p).empty


def test_the_speed_threshold_is_800_knots():
    # base speed is about 430 kt (2.2 km per 10 s); an extra 0.02 degrees (about 2 km) gives about 816 kt, an extra 0.012
    # degrees (about 1.2 km) gives about 660 kt
    above = _jump(_flight("a00004"), 30, 0.02)
    below = _jump(_flight("a00005"), 30, 0.012)
    assert len(find_naive_jumps(above)) == 1
    assert find_naive_jumps(below).empty


def test_mlat_ground_and_long_gaps_are_ignored():
    mlat = _jump(_flight("a00006", src="mlat"), 30, 1.0)
    assert find_naive_jumps(mlat).empty
    ground = _jump(_flight("a00007"), 30, 1.0).assign(on_ground=True)
    assert find_naive_jumps(ground).empty
    gap = _jump(_flight("a00008", dt=200.0), 30, 1.0)  # fixes 200 s apart exceed the 120 s window
    assert find_naive_jumps(gap).empty


def test_events_have_the_columns_the_harness_reads_and_pass_through_combine():
    p = pd.concat([_jump(_flight(f"b{i:05d}", lat0=24.0 + 0.1 * i), 30, 1.0) for i in range(3)], ignore_index=True)
    events = naive_spoof_events(find_naive_jumps(p))
    assert len(events) == 3 and events["event_id"].is_unique
    assert {"origin_lat", "origin_lon", "dest_lat", "dest_lon", "start", "end"} <= set(events.columns)
    empty_jam = build_events(
        flag_fixed_fraction(pd.DataFrame({"cell": [], "bucket": [], "stratum": [], "n_aircraft": [], "k_strong": []})),
        cfg.GRID_MAIN,
    )
    out = combine(empty_jam, events)
    assert len(out) == 3 and set(out["kind"]) == {"spoofing_like"}


def test_empty_input():
    assert detect_naive_spoofing(_flight("a00009", n=1))[1].empty
