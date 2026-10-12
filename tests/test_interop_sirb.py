"""Tests for the Sirb GNSS parameter file. All point data here is SYNTHETIC (invented, generated in this file)."""

import copy
import json

import numpy as np
import pandas as pd
import pytest

from tashwish import config as cfg
from tashwish.attribution import DATASET_ATTRIBUTION
from tashwish.interop import sirb
from tashwish.interop.sirb import SCHEMA_ID, build_params, main

SYNTHETIC = True
DAY = "2026-02-08"  # a dev day by tashwish.split
HELD = "2026-02-15"  # a held out day by tashwish.split
GEN = "2026-01-02T00:00:00Z"
META = [{"day": DAY, "split": "dev"}]
T0 = pd.Timestamp(f"{DAY}T10:00:00Z")


def make_points(n_ac=60, n_ep=20, ep_len=10, step=5.0, n=720, seed=1, day=DAY, jitter=False):
    """SYNTHETIC: n_ac aircraft, each n samples `step` s apart at 35000 ft. The first n_ep aircraft get one episode of ep_len samples."""
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp(f"{day}T10:00:00Z")
    rows = []
    for a in range(n_ac):
        start = int(rng.integers(50, n - 60)) if jitter else 300
        length = int(rng.integers(2, 30)) if jitter else ep_len
        for i in range(n):
            deg = a < n_ep and start <= i < start + length
            rows.append(
                (f"a{a:03d}", t0 + pd.Timedelta(seconds=i * step), 25.0, 55.0, 35000, False, "adsb_icao",
                 0 if deg else 8, 0 if deg else 9, 0, False)
            )  # fmt: skip
    cols = ["icao24", "ts", "lat", "lon", "alt_baro_ft", "on_ground", "src_type", "nic", "nac_p", "flags", "q_carried"]
    return pd.DataFrame(rows, columns=cols)


def run(pts, meta=META, **kw):
    kw.setdefault("n_boot", 60)
    return build_params(pts, meta, generated_at=GEN, commit="test", data_class="synthetic", **kw)


@pytest.fixture(scope="module")
def known():
    return run(make_points())


def en(p):
    return p["regions"]["gulf_box"]["strata"]["enroute"]


def test_schema_provenance_and_caveats(known):
    p = known
    assert p["schema"] == SCHEMA_ID == "tashwish.sirb_gnss_params.v1"
    pv = p["provenance"]
    assert pv["days"] == META and pv["dev_only"] is True and pv["code_commit"] == "test"
    assert (
        pv["attribution"] == DATASET_ATTRIBUTION
        and pv["generated_at"] == GEN
        and pv["split_rule"] == "tashwish-heldout-v1"
    )
    text = json.dumps(p)
    assert "SYNTHETIC" in p["notice"] and p["data_class"] == "synthetic"
    summ = p["caveats"]["summary"]
    for phrase in ("public aircraft ADS-B", "do NOT describe a drone-scale receiver", "low-altitude urban multipath",
                   "small antenna", "illustrative stress prior"):  # fmt: skip
        assert phrase in summ
    assert any("No attribution" in c for c in p["caveats"]["points"])
    assert chr(0x2014) not in text and not any(ord(ch) > 0x2FFF for ch in text)  # no em dash, no emoji
    assert json.loads(json.dumps(p, allow_nan=False)) == p


def test_known_episode_rate_duration_and_transitions(known):
    e = en(known)["degraded_episode"]["episodes"]
    assert e["status"] == "ok" and e["n_episodes"] == 20
    exposure_s = 60 * 719 * 5.0
    assert e["exposure_aircraft_hours"] == pytest.approx(exposure_s / 3600)
    r = e["rate_per_aircraft_hour"]
    assert r["value"] == pytest.approx(20 / (exposure_s / 3600))
    assert r["poisson_exact_lo"] < r["value"] < r["poisson_exact_hi"]
    q50 = e["duration_s"]["quantiles"]["q50"]
    assert q50["value"] == 45.0 and q50["boot_lo"] == 45.0 and q50["boot_hi"] == 45.0  # 10 samples, 5 s apart
    tr = en(known)["transitions"]
    d = tr["p_next_degraded_given_current_degraded"]
    assert (d["k"], d["n"]) == (180, 200) and d["share"] == pytest.approx(0.9)
    nom = tr["p_next_degraded_given_current_nominal"]
    assert nom["k"] == 20 and nom["n"] == 60 * 719 - 200


def test_known_categories_and_update_interval(known):
    base = en(known)["baseline"]["quality_categories"]
    assert base["status"] == "ok"
    assert base["nic"]["8"]["share"] == 1.0 and base["nic"]["0"]["k"] == 0
    assert base["nacp"]["9"]["share"] == 1.0
    assert base["nic"]["0"]["wilson_lo"] == 0.0 and base["nic"]["8"]["wilson_hi"] == 1.0
    deg = en(known)["degraded_episode"]["quality_categories"]
    assert deg["nic"]["0"]["k"] == 200 and deg["nacp"]["0"]["share"] == 1.0
    ui = en(known)["baseline"]["update_interval_and_dropout"]
    for q in ("q50", "q99"):
        assert 4.9 <= ui["update_interval_s"][q]["value"] <= 5.1
    assert ui["dropout"]["share_gt_20s"]["k"] == 0 and ui["dropout"]["share_gt_60s"]["share"] == 0.0
    assert en(known)["n"]["single_sample_runs"] == 0 and en(known)["n"]["aircraft"] == 60


def test_dropout_shares_and_exclusions():
    pts = make_points(n_ac=40, n_ep=0, n=100)
    # 10 aircraft get a 30 s gap and 5 of them also a 90 s gap (removing samples), all else nominal
    drop = []
    for a in range(10):
        drop += [
            (f"a{a:03d}", 20),
            (f"a{a:03d}", 21),
            (f"a{a:03d}", 22),
            (f"a{a:03d}", 23),
            (f"a{a:03d}", 24),
        ]  # 25 s gap -> 30 s
    keep = pts.copy()
    keep["i"] = keep.groupby("icao24").cumcount()
    mask = np.zeros(len(keep), bool)
    for a, i in drop:
        mask |= ((keep.icao24 == a) & (keep.i == i)).to_numpy()
    for a in range(5):
        mask |= ((keep.icao24 == f"a{a:03d}") & keep.i.between(50, 66)).to_numpy()  # 17 samples removed -> 90 s gap
    keep = keep[~mask].drop(columns="i")
    # rows that must be ignored: ground, mlat, non transponder, outside the region, duplicates
    junk = pts.iloc[:50].copy()
    junk["nic"] = 0
    junk["nac_p"] = 0
    extra = pd.concat([
        junk.assign(on_ground=True), junk.assign(src_type="mlat"), junk.assign(src_type="adsb_icao_nt"),
        junk.assign(lat=40.0), keep.iloc[:10],  # duplicates of kept rows
    ])  # fmt: skip
    p = run(pd.concat([keep, extra], ignore_index=True))
    d = en(p)["baseline"]["update_interval_and_dropout"]["dropout"]
    assert d["share_gt_60s"]["k"] == 5 and d["share_gt_20s"]["k"] == 5 + 10
    assert en(p)["degraded_episode"]["episodes"]["n_episodes"] == 0
    assert en(p)["n"]["quality_samples"] == len(keep)


def test_carried_quality_does_not_make_episodes_and_new_leg_and_horizon():
    pts = make_points(n_ac=30, n_ep=30, n=200)
    pts["q_carried"] = True  # every degraded value is carried forward from an old message
    pts.loc[pts.index[:5], "q_carried"] = False
    p = run(pts)
    assert en(p)["degraded_episode"]["episodes"]["n_episodes"] == 0
    # new leg flag and over-horizon gaps are excluded from update intervals
    pts = make_points(n_ac=30, n_ep=0, n=100)
    pts.loc[pts.groupby("icao24").head(1).index + 10, "flags"] = 2
    gap = pts["icao24"] == "a000"
    pts.loc[gap & (pts["ts"] > T0 + pd.Timedelta(seconds=250)), "ts"] += pd.Timedelta(seconds=1000)
    q = run(pts)
    n = en(q)["n"]
    assert n["intervals_over_horizon"] == 1
    assert n["intervals_used"] == 30 * 99 - 1 - 30


def test_episode_gap_tolerance_and_single_sample_run():
    rows = []
    t0 = T0
    cols = ["icao24", "ts", "lat", "lon", "alt_baro_ft", "on_ground", "src_type", "nic", "nac_p", "flags", "q_carried"]

    def ac(name, spec):
        for off, deg in spec:
            rows.append((name, t0 + pd.Timedelta(seconds=off), 25.0, 55.0, 35000, False, "adsb_icao",
                         0 if deg else 8, 0 if deg else 9, 0, False))  # fmt: skip

    for k in range(12):
        ac(f"b{k:02d}", [(0, 0), (10, 1), (20, 1), (130, 1), (140, 1), (150, 0)])  # 110 s gap: one episode of 4
        ac(f"c{k:02d}", [(0, 0), (10, 1), (20, 1), (141, 1), (151, 1), (161, 0)])  # 121 s gap: two episodes
        ac(f"d{k:02d}", [(0, 0), (10, 1), (20, 0), (30, 0)])  # single sample run only
    p = run(pd.DataFrame(rows, columns=cols))
    e = en(p)["degraded_episode"]["episodes"]
    assert e["n_episodes"] == 12 + 24
    assert en(p)["n"]["single_sample_runs"] == 12
    assert en(p)["n"]["isolated_degraded_samples"] == 12


def test_insufficient_blocks_never_report_numbers():
    p = run(make_points(n_ac=3, n_ep=1, n=50))
    b = en(p)["baseline"]["quality_categories"]
    assert b["status"] == "insufficient" and "nic" not in b
    assert en(p)["degraded_episode"]["episodes"]["status"] == "insufficient"
    assert en(p)["transitions"]["status"] == "insufficient"
    assert en(p)["baseline"]["update_interval_and_dropout"]["status"] == "insufficient"
    few = run(make_points(n_ac=40, n_ep=5, n=100))  # 5 episodes: rate reported, duration not
    d = en(few)["degraded_episode"]["episodes"]
    assert d["rate_per_aircraft_hour"]["value"] is not None and d["duration_s"] == {"status": "insufficient"}


def test_other_strata_are_separate():
    pts = make_points(n_ac=40, n_ep=0, n=60)
    pts["alt_baro_ft"] = 5000
    p = run(pts)
    assert en(p)["n"]["position_samples"] == 0
    assert p["regions"]["gulf_box"]["strata"]["low"]["n"]["position_samples"] == 40 * 60
    assert p["regions"]["gulf_box"]["strata"]["low"]["baseline"]["quality_categories"]["status"] == "ok"


def test_bootstrap_seed_determinism_and_coverage():
    pts = make_points(n_ac=80, n_ep=40, n=300, seed=3, jitter=True)
    a = run(pts, n_boot=80, seed=11)
    b = run(pts, n_boot=80, seed=11)
    c = run(pts, n_boot=80, seed=12)
    assert a == b and json.dumps(a) == json.dumps(b)
    assert a != c
    assert a["provenance"]["seed"] == 11 and c["provenance"]["seed"] == 12
    # point estimate sits inside its bootstrap interval; same point estimates for any seed
    e, ec = en(a)["degraded_episode"]["episodes"], en(c)["degraded_episode"]["episodes"]
    assert e["rate_per_aircraft_hour"]["value"] == ec["rate_per_aircraft_hour"]["value"]
    r = e["rate_per_aircraft_hour"]
    assert r["boot_lo"] <= r["value"] <= r["boot_hi"]
    for q in e["duration_s"]["quantiles"].values():
        assert q["boot_lo"] <= q["value"] <= q["boot_hi"]
    assert (r["boot_lo"], r["boot_hi"]) != (
        ec["rate_per_aircraft_hour"]["boot_lo"],
        ec["rate_per_aircraft_hour"]["boot_hi"],
    )
    # generating chunks day by day gives the same file as one table
    two = pd.concat(
        [make_points(n_ac=40, n_ep=20, n=100, seed=5), make_points(n_ac=40, n_ep=20, n=100, seed=6, day="2026-02-09")]
    )
    meta2 = [{"day": DAY, "split": "dev"}, {"day": "2026-02-09", "split": "dev"}]
    whole = run(two, meta2, seed=2)
    parts = run((g for _, g in two.groupby(two["ts"].dt.strftime("%Y-%m-%d"))), meta2, seed=2)
    assert whole == parts


def test_held_out_days_are_refused(tmp_path):
    pts = make_points(n_ac=10, n_ep=0, n=20, day=HELD)
    meta = [{"day": HELD, "split": "held_out"}]
    with pytest.raises(PermissionError):
        run(pts, meta)
    ok = run(pts, meta, allow_held_out=True)
    assert ok["provenance"]["dev_only"] is False and "HELD OUT" in ok["caveats"]["points"][0]
    with pytest.raises(ValueError):  # a wrong label cannot smuggle a held out day in
        run(pts, [{"day": HELD, "split": "dev"}])
    with pytest.raises(ValueError):  # points and metadata must name the same days
        run(make_points(n_ac=10, n_ep=0, n=20), [{"day": DAY, "split": "dev"}, {"day": "2026-02-09", "split": "dev"}])
    # CLI refuses before reading anything (no interim data exists here), exit code 2
    out = tmp_path / "x.json"
    assert main(["--days", HELD, "--interim", str(tmp_path), "--out", str(out)]) == 2 and not out.exists()
    assert main(["--days", DAY, HELD, "--interim", str(tmp_path), "--out", str(out)]) == 2


def test_cli_end_to_end_on_synthetic_interim(tmp_path):
    from tashwish.schema import points_filename

    # SYNTHETIC points written under the observed file name inside tmp_path only, to exercise the loader path
    make_points(n_ac=30, n_ep=10, n=400).assign(
        icao24=lambda d: d["icao24"], ts=lambda d: d["ts"].astype("datetime64[ms, UTC]")
    ).to_parquet(tmp_path / points_filename(DAY))
    out = tmp_path / "out" / "params.json"
    assert main(["--days", DAY, "--interim", str(tmp_path), "--out", str(out), "--n-boot", "20", "--seed", "5"]) == 0
    p = json.loads(out.read_text())
    assert p["schema"] == SCHEMA_ID and p["provenance"]["days"][0]["split"] == "dev" and p["provenance"]["seed"] == 5
    assert p["provenance"]["dataset_version"].startswith("draft-")
    assert p["regions"]["gulf_box"]["strata"]["enroute"]["degraded_episode"]["episodes"]["n_episodes"] == 10


def test_helpers_are_consistent():
    # histogram quantiles interpolate inside a bin; weighted quantiles are inverted-CDF
    h = np.zeros(len(sirb.DT_EDGES) - 1)
    h[50] = 10  # 5.0 to 5.1 s
    q = sirb._hist_quantiles(h, (0.5,))[0, 0]
    assert 5.0 <= q <= 5.1
    assert np.isnan(sirb._hist_quantiles(np.zeros_like(h), (0.5,))[0, 0])
    vals = np.array([1.0, 2.0, 3.0, 4.0])
    assert sirb._weighted_quantiles(vals, np.ones((1, 4)), (0.5,))[0, 0] == np.quantile(
        vals, 0.5, method="inverted_cdf"
    )
    assert sirb._weighted_quantiles(vals, np.array([[0, 0, 3, 1.0]]), (0.5,))[0, 0] == 3.0
    mutated = copy.deepcopy(sirb.CAVEATS)
    assert mutated == sirb.CAVEATS and cfg.NIC_STRONG_BELOW == 4
