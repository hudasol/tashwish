"""B3 ablations of the real jamming-like detector on SYNTHETIC cell bucket tables with known answers."""

import h3
import pandas as pd

from tashwish import config as cfg
from tashwish.baselines import constants as bc
from tashwish.baselines.jamming import detect_no_coverage, detect_no_fdr, detect_no_regime, fit_pooled
from tashwish.coverage.model import apply_coverage, fit_coverage
from tashwish.detect.jamming import detect_jamming, fit_p0

GRID = cfg.GRID_MAIN
CELL = h3.latlng_to_cell(25.0, 55.0, GRID.h3_res)
RING = sorted(h3.grid_disk(CELL, 1))
LOW_DAYS = [f"2026-02-{d:02d}" for d in (10, 11, 12)]  # a quiet regime
HIGH_DAYS = [f"2026-03-{d:02d}" for d in (4, 5, 6)]  # an elevated regime: 60 percent of aircraft degraded
SCORED = "2026-03-07"


def _row(cell, day, hour, n, k):
    return {"cell": cell, "bucket": pd.Timestamp(f"{day} {hour:02d}:00", tz="UTC"), "stratum": "enroute", "n_aircraft": n,
            "k_strong": k, "k_gpsjam": k, "n_samples": 4 * n, "sufficient": n >= 5, "status": "ok" if n >= 5 else "insufficient"}  # fmt: skip


def _days(days, k, cells=RING, n=20):
    return pd.DataFrame([_row(c, d, h, n, k) for d in days for c in cells for h in range(0, 24, 3)])


def test_constant_matches_the_specification():
    assert bc.B3C_ALPHA == 0.01


def test_pooled_fit_is_the_system_fit_on_all_days():
    cb = pd.concat([_days(LOW_DAYS, 0), _days(HIGH_DAYS, 12)], ignore_index=True)
    days = LOW_DAYS + HIGH_DAYS
    pooled = fit_pooled(cb, days, GRID)
    assert pooled.days == days
    pd.testing.assert_frame_equal(pooled.p0, fit_p0(cb, days))
    pd.testing.assert_frame_equal(pooled.cov, fit_coverage(cb, days, GRID))
    assert pooled.p0["p0"].min() > 0.25  # the quiet regime's 0.02 is lost in the pool (0.3 here)


def test_without_regime_awareness_a_moderate_excess_is_missed():
    cb = pd.concat([_days(LOW_DAYS, 0), _days(HIGH_DAYS, 12)], ignore_index=True)
    event_day = _days([SCORED], 0)
    event_day.loc[(event_day["cell"] == CELL) & (event_day["bucket"].dt.hour == 9), "k_strong"] = 10  # share 0.5

    # the system with a regime matched baseline (quiet days only) flags the excess
    cov = fit_coverage(cb[cb["bucket"].dt.strftime("%Y-%m-%d").isin(LOW_DAYS)], LOW_DAYS, GRID)
    p0 = fit_p0(cb, LOW_DAYS)
    scored = apply_coverage(event_day, cov, GRID, LOW_DAYS)
    _, system_events = detect_jamming(scored, LOW_DAYS, GRID, p0=p0)
    assert len(system_events) == 1

    # pooled across both regimes the same excess looks ordinary
    pooled = fit_pooled(cb, LOW_DAYS + HIGH_DAYS, GRID)
    flags, events = detect_no_regime(event_day, pooled, GRID)
    assert not flags["flag"].any() and events.empty


def test_without_coverage_gating_an_unobserved_cell_is_tested():
    base = _days(LOW_DAYS, 0)  # only the ring cells have ever been seen
    stranger = [c for c in h3.grid_disk(CELL, 2) if c not in RING][0]
    day = pd.DataFrame([_row(stranger, SCORED, 9, 20, 15)])
    cov = fit_coverage(base, LOW_DAYS, GRID)
    gated = apply_coverage(day, cov, GRID, LOW_DAYS)
    p0 = fit_p0(base, LOW_DAYS)
    _, system_events = detect_jamming(gated, LOW_DAYS, GRID, p0=p0)
    assert system_events.empty  # never seen on baseline days: status insufficient, not tested
    flags, events = detect_no_coverage(day, LOW_DAYS, p0, GRID)
    assert flags["flag"].tolist() == [True] and len(events) == 1


def test_without_false_discovery_control_a_marginal_excess_is_flagged():
    base = _days(LOW_DAYS, 4, n=20)  # baseline share 0.2 in every ring cell and slot
    cov = fit_coverage(base, LOW_DAYS, GRID)
    p0 = pd.DataFrame({"cell": RING, "stratum": "enroute", "p0": 0.2})
    day = _days([SCORED], 2, n=10)  # 56 quiet tests, share 0.2
    day.loc[(day["cell"] == CELL) & (day["bucket"].dt.hour == 9), "k_strong"] = 6  # one test with share 0.6
    scored = apply_coverage(day, cov, GRID, LOW_DAYS)
    flags_sys, events_sys = detect_jamming(scored, LOW_DAYS, GRID, p0=p0)
    assert events_sys.empty  # p about 0.006 does not survive Benjamini and Yekutieli over 56 tests
    flags, events = detect_no_fdr(scored, LOW_DAYS, p0, GRID)
    assert int(flags["flag"].sum()) == 1 and len(events) == 1
    assert flags.loc[flags["flag"], "p_value"].iloc[0] < bc.B3C_ALPHA
