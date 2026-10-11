"""Jamming detector tests on SYNTHETIC cell-bucket tables (hand-built, labelled synthetic)."""

import h3
import numpy as np
import pandas as pd

from tashwish import config as cfg
from tashwish.coverage.model import apply_coverage, fit_coverage
from tashwish.detect.jamming import build_events, detect_jamming

GRID = cfg.GRID_MAIN
BASE = [f"2026-03-{d:02d}" for d in range(1, 7)]
EVENT_DAY = "2026-03-07"
CENTRE = h3.latlng_to_cell(25.0, 55.0, GRID.h3_res)
RING = sorted(h3.grid_disk(CENTRE, 1))  # 7 adjacent cells


def _synthetic_table(event_cells=(), event_hours=(), k_event=8, n=20, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for day in [*BASE, EVENT_DAY]:
        for cell in RING:
            for hour in range(0, 24, GRID.bucket_hours):
                k = int(rng.binomial(n, 0.03))
                if day == EVENT_DAY and cell in event_cells and hour in event_hours:
                    k = k_event
                rows.append({
                    "cell": cell, "bucket": pd.Timestamp(f"{day} {hour:02d}:00", tz="UTC"), "stratum": "enroute",
                    "n_aircraft": n, "k_strong": k, "k_gpsjam": k, "n_samples": n * 4, "sufficient": True,
                    "share_strong": k / n,
                })  # fmt: skip
    return pd.DataFrame(rows)


def _run(cb):
    cov = fit_coverage(cb, BASE, GRID)
    cb2 = apply_coverage(cb, cov, GRID, BASE)
    return cb2, *detect_jamming(cb2, BASE, GRID)


def test_quiet_data_gives_no_events():
    _, flags, events = _run(_synthetic_table())
    assert events.empty and not flags["flag"].any()


def test_injected_cluster_is_one_event_with_right_extent():
    cells = RING[:3]
    cb, flags, events = _run(_synthetic_table(event_cells=cells, event_hours=(6, 9), k_event=14))
    assert len(events) == 1
    e = events.iloc[0]
    assert set(e["cells"].split(",")) == set(cells)
    assert e["start"] == pd.Timestamp(f"{EVENT_DAY} 06:00", tz="UTC")
    assert e["end"] == pd.Timestamp(f"{EVENT_DAY} 12:00", tz="UTC")
    assert e["confidence"] == "high"
    assert e["kind"] == "jamming_like"


def test_single_cell_single_bucket_is_low_confidence():
    _, _, events = _run(_synthetic_table(event_cells=RING[:1], event_hours=(12,)))
    assert len(events) == 1 and events.iloc[0]["confidence"] == "low"


def test_below_effect_size_gate_not_flagged():
    # 4/20 = 0.2 point estimate: Wilson lower bound is far below the 0.2 gate
    _, flags, events = _run(_synthetic_table(event_cells=RING[:1], event_hours=(12,), k_event=4))
    assert events.empty


def test_insufficient_aircraft_never_flagged():
    cb = _synthetic_table(event_cells=RING[:1], event_hours=(12,), n=4, k_event=4)
    _, flags, events = _run(cb)
    assert events.empty and (flags["n_aircraft"] >= cfg.MIN_AIRCRAFT_PER_CELL).all() if len(flags) else True


def test_distant_flags_are_separate_events():
    far = h3.latlng_to_cell(27.0, 59.0, GRID.h3_res)
    cb = _synthetic_table(event_cells=RING[:1], event_hours=(6,))
    extra = cb[(cb["cell"] == RING[0])].copy()
    extra["cell"] = far
    extra.loc[extra["bucket"] == pd.Timestamp(f"{EVENT_DAY} 06:00", tz="UTC"), "k_strong"] = 8
    cb = pd.concat([cb, extra], ignore_index=True)
    _, _, events = _run(cb)
    assert len(events) == 2


def test_deterministic():
    cb = _synthetic_table(event_cells=RING[:3], event_hours=(6, 9))
    a = _run(cb)[2]
    b = _run(cb.sample(frac=1, random_state=1).reset_index(drop=True))[2]
    pd.testing.assert_frame_equal(a, b)


def test_empty_events_schema():
    assert build_events(pd.DataFrame({"flag": []}), GRID).empty
