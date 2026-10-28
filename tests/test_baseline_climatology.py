"""B2 climatology z score on small SYNTHETIC cell bucket tables with known answers."""

import h3
import pandas as pd

from tashwish import config as cfg
from tashwish.baselines import constants as bc
from tashwish.baselines.jamming import detect_climatology, fit_climatology, flag_climatology

GRID = cfg.GRID_MAIN
CELL = h3.latlng_to_cell(25.0, 55.0, GRID.h3_res)
OTHER = sorted(h3.grid_disk(CELL, 1))[1]
DEV = [f"2026-02-{d:02d}" for d in range(10, 16)]  # six development days
SCORED = "2026-03-07"


def _row(cell, day, hour, n, k):
    return {"cell": cell, "bucket": pd.Timestamp(f"{day} {hour:02d}:00", tz="UTC"), "stratum": "enroute", "n_aircraft": n,
            "k_strong": k, "k_gpsjam": k, "n_samples": 4 * n, "sufficient": n >= 5, "status": "ok" if n >= 5 else "insufficient"}  # fmt: skip


def _dev_table():
    rows = []
    for i, day in enumerate(DEV):
        rows.append(_row(CELL, day, 6, 10, i % 2))  # shares 0.0 and 0.1 alternating: mean 0.05
        rows.append(_row(OTHER, day, 6, 10, 0))  # never degraded: standard deviation zero
        if i < 2:
            rows.append(_row(CELL, day, 9, 10, 0))  # only two usable days in this slot: not flaggable
        rows.append(_row(CELL, day, 12, 4, 4))  # fewer than 5 aircraft: never contributes
    return pd.DataFrame(rows)


def test_constants_match_the_specification():
    assert (bc.B2_Z, bc.B2_MIN_AIRCRAFT, bc.B2_MIN_DAYS) == (3.0, 5, 3)


def test_fit_uses_only_requested_days_and_enough_aircraft():
    cb = _dev_table()
    clim = fit_climatology(cb, DEV, GRID).set_index(["cell", "slot"])
    assert set(clim.index) == {(CELL, 2), (OTHER, 2)}  # slot 2 is hours 6 to 9; the thin slots are dropped
    r = clim.loc[(CELL, 2)]
    assert abs(r["mean"] - 0.05) < 1e-12 and abs(r["sd"] - 0.05477225575051661) < 1e-9 and r["n_days"] == 6
    assert len(fit_climatology(cb, DEV[:2], GRID)) == 0  # two days are below the minimum of three
    assert len(fit_climatology(cb, ["2026-03-01"], GRID)) == 0  # days outside the table


def test_threshold_is_mean_plus_three_sd_strictly():
    clim = fit_climatology(_dev_table(), DEV, GRID)  # threshold for CELL slot 2: 0.05 + 3 * 0.054772 = 0.21432
    day = pd.DataFrame(
        [
            _row(CELL, SCORED, 6, 10, 2),  # share 0.20: below the threshold
            _row(CELL, SCORED, 9, 10, 9),  # slot 3 has no climatology: cannot be flagged
            _row(CELL, SCORED, 12, 4, 4),  # fewer than 5 aircraft
            _row(CELL, SCORED, 15, 10, 9),  # no climatology
        ]
    )
    assert not flag_climatology(day, clim, GRID)["flag"].any()
    hi = pd.DataFrame([_row(CELL, SCORED, 6, 10, 3)])  # share 0.30: above
    assert flag_climatology(hi, clim, GRID)["flag"].tolist() == [True]


def test_zero_variance_cell_flags_on_any_excess():
    clim = fit_climatology(_dev_table(), DEV, GRID)
    one = pd.DataFrame([_row(OTHER, SCORED, 6, 10, 1), _row(OTHER, SCORED, 18, 10, 1)])
    f = flag_climatology(one, clim, GRID)
    assert f["flag"].tolist() == [
        True,
        False,
    ]  # slot 6 (hour 18) has no climatology; the first row exceeds a zero threshold


def test_events_are_built_from_flags():
    clim = fit_climatology(_dev_table(), DEV, GRID)
    day = pd.DataFrame([_row(CELL, SCORED, 6, 10, 5), _row(OTHER, SCORED, 6, 10, 5)])
    flags, events = detect_climatology(day, clim, GRID)
    assert flags["flag"].all() and len(events) == 1 and events.iloc[0]["n_cells"] == 2
