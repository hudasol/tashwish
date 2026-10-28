"""B1 and B1b on small SYNTHETIC cell bucket tables with known answers."""

import h3
import pandas as pd

from tashwish import config as cfg
from tashwish.baselines import constants as bc
from tashwish.baselines.jamming import detect_fixed_fraction, flag_fixed_fraction

GRID = cfg.GRID_MAIN
CELL = h3.latlng_to_cell(25.0, 55.0, GRID.h3_res)
NB = sorted(h3.grid_disk(CELL, 1))[1]
T = pd.Timestamp("2026-03-07 06:00", tz="UTC")


def _cb(rows):
    return pd.DataFrame([
        {"cell": c, "bucket": b, "stratum": s, "n_aircraft": n, "k_strong": k, "k_gpsjam": k, "n_samples": 4 * n,
         "sufficient": n >= 5, "status": "ok" if n >= 5 else "insufficient"}
        for c, b, s, n, k in rows
    ])  # fmt: skip


def test_constants_match_the_specification():
    assert bc.B1_MIN_SHARE == 0.10 and bc.B1_MIN_AIRCRAFT == 5 and bc.B1B_SPARSITY_OFFSET == 1
    assert bc.B1_MIN_AIRCRAFT == cfg.MIN_AIRCRAFT_PER_CELL


def test_b1_flags_exactly_at_the_fraction_and_needs_five_aircraft():
    cb = _cb(
        [
            (CELL, T, "enroute", 10, 1),  # share 0.10: flagged
            (CELL, T + pd.Timedelta(hours=3), "enroute", 10, 0),  # none degraded
            (CELL, T + pd.Timedelta(hours=6), "enroute", 20, 1),  # 0.05: below
            (NB, T, "enroute", 4, 4),  # all degraded but only 4 aircraft: not tested
            (NB, T + pd.Timedelta(hours=3), "high", 10, 10),  # other stratum: ignored
        ]
    )
    f = flag_fixed_fraction(cb)
    assert len(f) == 3  # the 4 aircraft row and the other stratum are not tested
    assert f.set_index("bucket")["flag"].to_dict() == {
        T: True,
        T + pd.Timedelta(hours=3): False,
        T + pd.Timedelta(hours=6): False,
    }


def test_b1b_subtracts_one_degraded_aircraft():
    t2 = T + pd.Timedelta(hours=3)
    cb = _cb([(CELL, T, "enroute", 10, 1), (NB, T, "enroute", 10, 2), (CELL, t2, "enroute", 5, 2)])
    plain = flag_fixed_fraction(cb).set_index(["cell", "bucket"])["flag"]
    corrected = flag_fixed_fraction(cb, sparsity_correction=True).set_index(["cell", "bucket"])["flag"]
    assert plain.all()  # 0.10, 0.20 and 0.40
    assert not corrected[(CELL, T)]  # (1 minus 1) / 10 = 0
    assert corrected[(NB, T)]  # (2 minus 1) / 10 = 0.10
    assert corrected[(CELL, t2)]  # (2 minus 1) / 5 = 0.20


def test_b1_events_merge_adjacent_cells_in_one_bucket():
    cb = _cb([(CELL, T, "enroute", 10, 5), (NB, T, "enroute", 10, 5)])
    flags, events = detect_fixed_fraction(cb, GRID)
    assert flags["flag"].all() and len(events) == 1 and events.iloc[0]["n_cells"] == 2


def test_b1_on_empty_input_returns_empty():
    flags, events = detect_fixed_fraction(_cb([(CELL, T, "enroute", 4, 4)]), GRID)  # nothing reaches 5 aircraft
    assert flags.empty and events.empty
