"""Tests for M2 aggregation. All point data here is SYNTHETIC (see tests/synth.py); thresholds are checked at the edges."""

import h3
import numpy as np
import pandas as pd
import pytest

from tashwish import config as cfg
from tashwish.metrics.aggregate import (
    add_cells,
    aircraft_buckets,
    cell_bucket_metrics,
    metric_samples,
    persistent_low_aircraft,
    stratum_labels,
)
from tashwish.metrics.stats import wilson_interval

T0 = pd.Timestamp("2026-03-02T00:00:00Z")


def pts(rows):
    base = {
        "src_type": "adsb_icao",
        "on_ground": False,
        "nic": 8,
        "nac_p": 9,
        "alt_baro_ft": 35000,
        "lat": 25.0,
        "lon": 55.0,
    }
    df = pd.DataFrame([{**base, **r} for r in rows])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def run(rows, grid=cfg.GRID_MAIN):
    s = metric_samples(pts(rows))
    s = add_cells(s, grid)
    return cell_bucket_metrics(aircraft_buckets(s))


def aircraft(name, n, low, ts0=T0, **kw):
    """n samples a minute apart; the first `low` of them degraded (NIC 2)."""
    return [
        {"icao24": name, "ts": ts0 + pd.Timedelta(minutes=i), **({"nic": 2, "nac_p": 3} if i < low else {}), **kw}
        for i in range(n)
    ]


def test_metric_samples_filters_and_flags_thresholds():
    rows = [
        {"icao24": "a", "ts": T0, "nic": 3, "nac_p": 11},  # NIC 3 -> strong
        {"icao24": "b", "ts": T0, "nic": 4, "nac_p": 11},  # NIC 4 -> not strong
        {"icao24": "c", "ts": T0, "nic": 11, "nac_p": 4},  # NACp 4 -> strong, gpsjam
        {"icao24": "d", "ts": T0, "nic": 11, "nac_p": 5},  # NACp 5 -> not strong, but gpsjam (<8)
        {"icao24": "e", "ts": T0, "nic": 11, "nac_p": 7},  # NACp 7 -> gpsjam only
        {"icao24": "f", "ts": T0, "nic": 11, "nac_p": 8},  # NACp 8 -> neither
        {"icao24": "g", "ts": T0, "nic": 8, "nac_p": None},  # missing NACp -> not low via NACp
        {"icao24": "veh", "ts": T0, "src_type": "adsb_icao_nt"},  # vehicle: dropped
        {"icao24": "gnd", "ts": T0, "on_ground": True},  # on ground: dropped
        {"icao24": "noq", "ts": T0, "nic": None},  # no quality: dropped
        {"icao24": "noalt", "ts": T0, "alt_baro_ft": None},  # no altitude: dropped
    ]
    s = metric_samples(pts(rows)).set_index("icao24")
    assert set(s.index) == set("abcdefg")
    assert s.low_strong.to_dict() == dict(a=True, b=False, c=True, d=False, e=False, f=False, g=False)
    assert s.low_gpsjam.to_dict() == dict(a=False, b=False, c=True, d=True, e=True, f=False, g=False)


def test_buckets_and_cells():
    rows = [
        {"icao24": "a", "ts": "2026-03-02T02:59:59Z"},
        {"icao24": "a", "ts": "2026-03-02T03:00:00Z"},
    ]
    s = add_cells(metric_samples(pts(rows)), cfg.GRID_MAIN)
    assert list(s.bucket) == [pd.Timestamp("2026-03-02T00:00Z"), pd.Timestamp("2026-03-02T03:00Z")]
    assert s.cell.iloc[0] == h3.latlng_to_cell(25.0, 55.0, 4)
    s1 = add_cells(metric_samples(pts(rows)), cfg.Grid(3, 1))
    assert s1.bucket.iloc[0] == pd.Timestamp("2026-03-02T02:00Z")


def test_grid_validation():
    with pytest.raises(ValueError):
        cfg.Grid(4, 5)


def test_strata_edges():
    lab = stratum_labels(pd.Series([0, 9999, 10000, 24999, 25000, 41000]))
    assert list(lab) == ["low", "low", "mid", "mid", "high", "high"]


def test_aircraft_rule_fraction_and_min_samples():
    rows = (
        aircraft("half", 4, 2)  # 2/4 = 0.5 -> degraded (>=)
        + aircraft("under", 4, 1)  # 1/4 -> not degraded
        + aircraft("single", 1, 1)  # one sample -> not eligible at all
        + aircraft("x1", 4, 0) + aircraft("x2", 4, 0) + aircraft("x3", 4, 0)
    )  # fmt: skip
    m = run(rows)
    e = m[m.stratum == "enroute"].iloc[0]
    assert e.n_aircraft == 5 and e.k_strong == 1  # half, under, x1..x3 eligible; only 'half' degraded
    assert e.sufficient and e.status == "ok"


def test_cell_bucket_values_match_hand_computation():
    rows = []
    for i in range(6):
        rows += aircraft(f"a{i}", 5, 5 if i < 3 else 0)
    m = run(rows)
    e = m[m.stratum == "enroute"].iloc[0]
    assert (e.n_aircraft, e.k_strong, e.share_strong) == (6, 3, 0.5)
    lo, hi = wilson_interval(3, 6)
    assert (e.ci_lo_strong, e.ci_hi_strong) == pytest.approx((lo, hi))
    assert e.k_gpsjam == 3


def test_insufficient_cells_are_never_ok():
    rows = []
    for i in range(cfg.MIN_AIRCRAFT_PER_CELL - 1):
        rows += aircraft(f"a{i}", 5, 5)  # 100% degraded but too few aircraft
    m = run(rows)
    e = m[m.stratum == "enroute"].iloc[0]
    assert e.share_strong == 1.0 and not e.sufficient and e.status == "insufficient"


def test_counting_is_per_aircraft_not_per_message():
    base = []
    for i in range(6):
        base += aircraft(f"a{i}", 4, 4 if i == 0 else 0)
    chatty = base + [r for r in base if r["icao24"] == "a0"] * 50  # one aircraft sends 50x more messages
    a = run(base)
    b = run(chatty)
    ea, eb = a[a.stratum == "enroute"].iloc[0], b[b.stratum == "enroute"].iloc[0]
    assert (ea.n_aircraft, ea.k_strong) == (eb.n_aircraft, eb.k_strong) == (6, 1)


def test_strata_split_by_altitude_and_enroute_excludes_low():
    rows = []
    for i in range(5):
        rows += aircraft(f"h{i}", 3, 3, alt_baro_ft=30000)
        rows += aircraft(f"m{i}", 3, 0, alt_baro_ft=15000)
        rows += aircraft(f"l{i}", 3, 0, alt_baro_ft=2000)
    m = run(rows).set_index("stratum")
    assert (m.loc["high", "n_aircraft"], m.loc["high", "k_strong"]) == (5, 5)
    assert (m.loc["mid", "n_aircraft"], m.loc["mid", "k_strong"]) == (5, 0)
    assert (m.loc["low", "n_aircraft"], m.loc["low", "k_strong"]) == (5, 0)
    assert (m.loc["enroute", "n_aircraft"], m.loc["enroute", "k_strong"]) == (10, 5)


def test_empty_input_gives_empty_table_with_columns():
    samples = add_cells(metric_samples(pts([{"icao24": "gnd", "ts": T0, "on_ground": True}])), cfg.GRID_MAIN)
    assert samples.empty
    m = cell_bucket_metrics(aircraft_buckets(samples))
    assert m.empty and "share_strong" in m.columns


def test_traffic_ratio_is_relative_to_cell_median():
    rows = []
    for hour, n in ((0, 6), (3, 6), (6, 12)):
        for i in range(n):
            rows += aircraft(f"{hour}-{i}", 3, 0, ts0=T0 + pd.Timedelta(hours=hour))
    m = run(rows)
    e = m[m.stratum == "enroute"].sort_values("bucket")
    assert e.traffic_ratio.tolist() == pytest.approx([1.0, 1.0, 2.0])


def persistent_input(specs):
    rows = []
    for name, n_per_day, days, low_share in specs:
        for d in range(days):
            for i in range(n_per_day):
                low = i < int(round(n_per_day * low_share))
                rows.append(
                    {
                        "icao24": name,
                        "ts": T0 + pd.Timedelta(days=d, seconds=i),
                        **({"nic": 0, "nac_p": 0} if low else {}),
                    }
                )
    return metric_samples(pts(rows))


def test_persistent_low_rule():
    s = persistent_input(
        [
            ("always_low", 100, 3, 0.95),  # 300 samples, 3 days, 95% low -> flagged
            ("two_days", 150, 2, 1.0),  # too few days
            ("few_samples", 50, 3, 1.0),  # 150 samples < 200
            ("sometimes", 100, 3, 0.5),  # share too low
            ("healthy", 100, 3, 0.0),
        ]
    )
    flagged = persistent_low_aircraft(s)
    assert flagged.icao24.tolist() == ["always_low"]
    assert flagged.iloc[0].n == 300 and flagged.iloc[0].days == 3


def test_ok_status_requires_minimum_aircraft_property():
    rng = np.random.default_rng(1)
    rows = []
    for i in range(40):
        lat, lon = rng.uniform(24, 26), rng.uniform(54, 56)
        rows += aircraft(f"p{i}", 4, int(rng.integers(0, 5)), lat=lat, lon=lon)
    m = run(rows)
    assert ((m.status == "ok") == (m.n_aircraft >= cfg.MIN_AIRCRAFT_PER_CELL)).all()
    assert (m.k_strong <= m.n_aircraft).all()
    assert ((m.ci_lo_strong <= m.share_strong) & (m.share_strong <= m.ci_hi_strong)).all()
