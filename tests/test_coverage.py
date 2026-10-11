"""Coverage model tests. All tables here are SYNTHETIC cell-bucket metric tables built by hand."""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tashwish import config as cfg
from tashwish.coverage.model import apply_coverage, fit_coverage, slot_of_day

GRID = cfg.GRID_MAIN
DAYS = [f"2026-03-{d:02d}" for d in range(1, 6)]  # 5 baseline days
HOLE_DAY = "2026-03-06"


def _row(cell, day, hour, n, stratum="enroute"):
    return {
        "cell": cell,
        "bucket": pd.Timestamp(f"{day} {hour:02d}:00", tz="UTC"),
        "stratum": stratum,
        "n_aircraft": n,
        "k_strong": 0,
        "k_gpsjam": 0,
        "n_samples": n * 3,
        "sufficient": n >= 5,
        "share_strong": 0.0 if n else np.nan,
    }


def _table():
    rows = []
    for d in DAYS + [HOLE_DAY]:
        rows.append(_row("A", d, 0, 20))  # A: busy, covered every day ...
        rows.append(_row("B", d, 0, 2))  # B: thin -> never testable
        if d in DAYS[:2]:  # C: testable on 2 of 5 baseline days (0.4 -> marginal)
            rows.append(_row("C", d, 0, 8))
        else:
            rows.append(_row("C", d, 0, 1))
    # ... except A is absent entirely on HOLE_DAY (a coverage hole) -> remove that row
    rows = [r for r in rows if not (r["cell"] == "A" and r["bucket"].strftime("%Y-%m-%d") == HOLE_DAY)]
    return pd.DataFrame(rows)


def _fit(cb):
    return fit_coverage(cb, DAYS, GRID)


def test_slot_of_day():
    b = pd.Series(pd.to_datetime(["2026-03-01 00:00", "2026-03-01 05:00", "2026-03-01 21:00"], utc=True))
    assert slot_of_day(b, GRID).tolist() == [0, 1, 7]


def test_classes():
    cov = _fit(_table()).set_index("cell")
    assert cov.loc["A", "coverage_class"] == "covered"
    assert cov.loc["B", "coverage_class"] == "no_coverage"
    assert cov.loc["C", "coverage_class"] == "marginal"
    assert cov.loc["A", "presence"] == 1.0


def test_thin_cell_never_ok():
    cb = _table()
    out = apply_coverage(cb, _fit(cb), GRID, DAYS)
    assert (out[out["cell"] == "B"]["status"] == "insufficient").all()


def test_hole_materialised_as_coverage_lost_not_quiet():
    cb = _table()
    window = [pd.Timestamp(f"{HOLE_DAY} 00:00", tz="UTC")]
    out = apply_coverage(cb, _fit(cb), GRID, DAYS, window_buckets=window)
    hole = out[(out["cell"] == "A") & (out["bucket"] == window[0])]
    assert len(hole) == 1
    assert hole.iloc[0]["status"] == "coverage_lost"
    assert hole.iloc[0]["n_aircraft"] == 0
    assert np.isnan(hole.iloc[0]["share_strong"])


def test_drop_in_traffic_is_coverage_lost():
    cb = pd.concat([_table(), pd.DataFrame([_row("A", HOLE_DAY, 0, 1)])], ignore_index=True)
    out = apply_coverage(cb, _fit(cb), GRID, DAYS)
    r = out[(out["cell"] == "A") & (out["bucket"].dt.strftime("%Y-%m-%d") == HOLE_DAY)].iloc[0]
    assert r["status"] == "coverage_lost"


def test_leave_one_day_out_does_not_self_vouch():
    # one busy day alone must not make a cell "covered" on that day
    rows = [_row("Z", DAYS[0], 0, 30)] + [_row("Z", d, 0, 0) for d in DAYS[1:]]
    cb = pd.DataFrame(rows)
    out = apply_coverage(cb, _fit(cb), GRID, DAYS)
    day0 = out[out["bucket"].dt.strftime("%Y-%m-%d") == DAYS[0]].iloc[0]
    assert day0["baseline_presence"] == 0.0
    assert day0["status"] == "insufficient"  # enough aircraft, but nothing else ever vouches for the cell


def test_requires_two_baseline_days():
    cb = _table()
    with pytest.raises(ValueError):
        apply_coverage(cb, fit_coverage(cb, DAYS[:1], GRID), GRID, DAYS[:1])


def test_empty_baseline_rejected():
    with pytest.raises(ValueError):
        fit_coverage(_table(), [], GRID)


@settings(max_examples=40, deadline=None)
@given(ns=st.lists(st.integers(0, 40), min_size=6, max_size=6))
def test_ok_implies_enough_and_not_no_coverage(ns):
    rows = [_row("P", d, 3, n) for d, n in zip(DAYS + [HOLE_DAY], ns, strict=True)]
    cb = pd.DataFrame(rows)
    out = apply_coverage(cb, _fit(cb), GRID, DAYS)
    ok = out[out["status"] == "ok"]
    assert (ok["n_aircraft"] >= cfg.MIN_AIRCRAFT_PER_CELL).all()
    assert (ok["coverage_class"] != "no_coverage").all()
