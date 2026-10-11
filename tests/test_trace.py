import gzip
import json
from pathlib import Path

import pytest

from tashwish.config import Region
from tashwish.ingest.pipeline import day_bounds_ms
from tashwish.ingest.trace import parse_gz, parse_trace

from .synth import DAY, DAY0, ac_obj, gz, pt, trace_obj

D0, D1 = day_bounds_ms(DAY)
FIX = Path(__file__).parent / "fixtures"


def parse(points, **kw):
    return parse_trace(trace_obj("abc123", points), D0, D1, **kw)


def test_point_layout_and_units():
    r = parse(
        [pt(10.5, 25.0, 55.0, alt=36000, gs=451.2, trk=91.5, flags=1, vr=-64, galt=36300, ac=ac_obj(nic=8, nac_p=9))]
    )
    c = r.cols
    assert len(r) == 1
    assert c["icao24"] == ["abc123"] and c["ac_type"] == ["A320"]
    assert c["ts"] == [round((DAY0 + 10.5) * 1000)]
    assert (c["lat"][0], c["lon"][0]) == (25.0, 55.0)
    assert c["alt_baro_ft"] == [36000] and c["on_ground"] == [False] and c["alt_geom_ft"] == [36300]
    assert c["gs_kt"] == [451.2] and c["track_deg"] == [91.5] and c["flags"] == [1] and c["baro_rate_fpm"] == [-64]
    assert c["nic"] == [8] and c["nac_p"] == [9] and c["version"] == [2] and c["rc_m"] == [7]
    assert c["sil_type"] == ["perhour"] and c["q_age_s"] == [0.0] and c["q_carried"] == [False]


def test_ground_altitude():
    r = parse([pt(1, 25.0, 55.0, alt="ground", gs=20.0)])
    assert r.cols["on_ground"] == [True] and r.cols["alt_baro_ft"] == [None]


def test_quality_carry_forward_and_expiry():
    pts = [
        pt(0, 25.0, 55.0, ac=ac_obj(nic=3, nac_p=4)),
        pt(5, 25.0, 55.1),
        pt(119.9, 25.0, 55.2),
        pt(121, 25.0, 55.3),  # older than 120 s: must not inherit
    ]
    r = parse(pts)
    assert r.cols["nic"] == [3, 3, 3, None]
    assert r.cols["q_carried"] == [False, True, True, False]
    assert r.cols["q_age_s"][1] == pytest.approx(5.0) and r.cols["q_age_s"][3] is None
    assert r.stats["quality_too_old"] == 1


def test_carry_forward_uses_points_outside_the_region():
    pts = [pt(0, 10.0, 10.0, ac=ac_obj(nic=2, nac_p=3)), pt(10, 25.0, 55.0)]
    r = parse(pts)
    assert len(r) == 1 and r.cols["nic"] == [2] and r.cols["q_carried"] == [True] and r.cols["q_age_s"] == [10.0]


def test_new_object_replaces_old_snapshot_wholesale():
    pts = [pt(0, 25, 55, ac=ac_obj(nic=11, nac_p=11, sda=2)), pt(10, 25, 55.1, ac={"version": 2, "nic": 6})]
    r = parse(pts)
    assert r.cols["nic"] == [11, 6] and r.cols["nac_p"] == [11, None] and r.cols["sda"] == [2, None]


def test_category_is_sticky_but_quality_is_not():
    pts = [pt(0, 25, 55, ac=ac_obj(category="A3")), pt(500, 25, 55.1, ac=ac_obj(nic=7))]
    assert parse(pts).cols["category"] == ["A3", "A3"]


def test_day_bounds_are_enforced_and_counted():
    pts = [pt(-5, 25, 55), pt(100, 25, 55), pt(86400 + 1, 25, 55)]
    r = parse(pts)
    assert len(r) == 1 and r.stats["outside_day"] == 2


def test_region_filter_inclusive_edges():
    reg = Region(20, 30, 40, 50)
    r = parse([pt(1, 20.0, 40.0), pt(2, 30.0, 50.0), pt(3, 30.0001, 50.0)], region=reg)
    assert len(r) == 2


def test_malformed_points_are_counted_not_fatal():
    pts = [None, [1, 2], pt(1, "x", 55), pt(2, 25.0, 55.0)]
    r = parse(pts)
    assert len(r) == 1 and r.stats["malformed_point"] == 3


def test_malformed_and_undecodable_files():
    assert parse_gz(b"not gzip", D0, D1).stats["undecodable_file"] == 1
    assert parse_gz(gzip.compress(b"[1,2]"), D0, D1).stats["malformed_file"] == 1
    assert parse_gz(gzip.compress(b"{not json"), D0, D1).stats["undecodable_file"] == 1
    assert parse_gz(gz({"icao": "x"}), D0, D1).stats["malformed_file"] == 1


def test_non_monotonic_time_is_counted():
    r = parse([pt(10, 25, 55), pt(5, 25, 55.1)])
    assert r.stats["non_monotonic_time"] == 1


def test_data_class_is_stamped():
    r = parse_trace(trace_obj("a", [pt(1, 25, 55)]), D0, D1, data_class="synthetic")
    assert r.cols["data_class"] == ["synthetic"]


@pytest.mark.parametrize("name", sorted(p.name for p in FIX.glob("real_adsblol_2026-03-02_*.json.gz")))
def test_real_derived_fixtures_parse_with_invariants(name):
    """Fixtures are rebuilt from real adsb.lol points (ODbL) on 2026-03-02; checks shape invariants only."""
    obj = json.loads(gzip.decompress((FIX / name).read_bytes()))
    r = parse_trace(obj, D0, D1)
    assert len(r) > 0
    c = r.cols
    assert all(22 <= x <= 31 for x in c["lat"]) and all(46 <= x <= 62 for x in c["lon"])
    assert all(D0 <= t < D1 for t in c["ts"])
    assert all(n is None or 0 <= n <= 11 for n in c["nic"])
    assert all(n is None or 0 <= n <= 11 for n in c["nac_p"])
    assert set(c["src_type"]) <= {"adsb_icao", "adsb_icao_nt", "mlat", None}
    assert c["ts"] == sorted(c["ts"])
