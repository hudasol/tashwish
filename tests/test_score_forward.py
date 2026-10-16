"""Forward scorer on SYNTHETIC processed days (invented numbers in a temp dir; nothing here describes the real world)."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("score_forward", ROOT / "scripts" / "score_forward.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _state(root: Path, ref_units: float = 1000.0) -> str:
    root.mkdir(parents=True)
    (root / "state.json").write_text(json.dumps({"ref_units": ref_units}), encoding="utf-8")
    return hashlib.sha256((root / "state.json").read_bytes()).hexdigest()


def _day(processed: Path, day: str, *, units: int, degraded: int, not_enough: int, events: list[str], sha: str,
         mode: str = "frozen_baseline") -> None:  # fmt: skip
    """One synthetic day: covered en route rows of 10 aircraft each plus `not_enough` covered rows with 2 aircraft."""
    d = processed / "days" / day
    d.mkdir(parents=True)
    n_ok = units // 10
    rows = [{"cell": f"c{i}", "stratum": "enroute", "n_aircraft": 10, "k_strong": 1 if i < degraded else 0,
             "coverage_class": "covered"} for i in range(n_ok)]  # fmt: skip
    rows += [{"cell": f"x{i}", "stratum": "enroute", "n_aircraft": 2, "k_strong": 0, "coverage_class": "covered"}
             for i in range(not_enough)]  # fmt: skip
    pd.DataFrame(rows).to_parquet(d / "cb.parquet", index=False)
    pd.DataFrame(
        {"kind": events, "confidence": ["medium"] * len(events), "label_uncertain": [True] * len(events)},
        columns=["kind", "confidence", "label_uncertain"],
    ).to_parquet(d / "events.parquet", index=False)
    meta = {"day": day, "mode": mode, "data_class": "synthetic", "provenance": {"state_sha256": sha}}
    (d / "day.json").write_text(json.dumps(meta), encoding="utf-8")


SPEC = {
    "block": {"first": "2026-03-14", "last": "2026-03-17"},
    "first_week_end": "2026-03-15",
    "min_days": 3,
    "min_subset_days": 2,
    "first_week_min_days": 2,
    "bootstrap": {"reps": 200, "seed": 1},
    "daily_checks": {
        "label_pair": ["reduced", "elevated"],
        "false_coverage_max": {"reduced": 0.5, "normal": 0.1},
        "events_max": 1,
    },  # fmt: skip
    "predictions": [
        {
            "id": "T1",
            "text": "t",
            "metric": "share_days_elevated",
            "subset": "all",
            "op": ">=",
            "threshold": 0.8,
            "p": 0.6,
        },
        {
            "id": "T2",
            "text": "t",
            "metric": "false_coverage_pooled",
            "subset": "reduced",
            "op": "between",
            "threshold": [0.2, 0.5],
            "p": 0.5,
        },  # fmt: skip
        {
            "id": "T3",
            "text": "t",
            "metric": "events_per_day",
            "subset": "normal",
            "op": "<=",
            "threshold": 0.5,
            "p": 0.6,
        },
        {"id": "T4", "text": "t", "metric": "label_switches", "subset": "all", "op": "<=", "threshold": 0, "p": 0.6},
    ],
}


def test_measures_scoring_and_first_failure(tmp_path):
    m = _mod()
    sha = _state(tmp_path / "state")
    p = tmp_path / "processed"
    # ref 1000: units 300 -> reduced; share 30/300 = 0.1 -> elevated. Units 800 -> normal; 0 degraded -> baseline.
    _day(p, "2026-03-14", units=300, degraded=30, not_enough=10, events=["spoofing_like"], sha=sha)
    _day(p, "2026-03-15", units=300, degraded=30, not_enough=30, events=["both", "jamming_like"], sha=sha)
    _day(p, "2026-03-16", units=800, degraded=0, not_enough=0, events=[], sha=sha)
    _day(p, "2026-03-17", units=800, degraded=0, not_enough=0, events=[], sha=sha, mode="dev_leave_one_day_out")
    r = m.score(p, tmp_path / "state", SPEC)
    assert r["n_days_scored"] == 3 and r["rejected_days"][0]["day"] == "2026-03-17" and r["missing_days"] == []
    days = {d["day"]: d for d in r["per_day"]}
    assert (days["2026-03-14"]["traffic"], days["2026-03-14"]["degraded"]) == ("reduced", "elevated")
    assert (days["2026-03-16"]["traffic"], days["2026-03-16"]["degraded"]) == ("normal", "baseline")
    assert days["2026-03-15"]["false_coverage"] == pytest.approx(30 / 60)
    v = {x["id"]: x for x in r["predictions"]}
    assert v["T1"]["verdict"] == "MISS" and v["T1"]["value"] == pytest.approx(2 / 3)
    assert v["T2"]["value"] == pytest.approx(40 / 100) and v["T2"]["verdict"] == "HIT"
    assert v["T3"]["verdict"] == "NOT EVALUABLE"  # one normal day, two needed
    assert v["T4"]["value"] == 1 and v["T4"]["verdict"] == "MISS"
    assert all(x["data_class"] == "OBSERVED" for x in r["predictions"])
    assert r["brier"] == pytest.approx(((0.6 - 0) ** 2 + (0.5 - 1) ** 2 + (0.6 - 0) ** 2) / 3)
    ff = r["first_failures"]
    assert ff["label_pair"]["first_fail"] == "2026-03-16"
    assert ff["events"]["first_fail"] == "2026-03-15"
    assert ff["false_coverage"]["first_fail"] is None
    assert ff["any"]["first_fail"] == "2026-03-15"
    doc = m.render(r, SPEC)
    assert doc.index("| T1 | MISS") < doc.index("| T2 | HIT")  # misses before hits


def test_study_window_is_refused(tmp_path):
    m = _mod()
    _state(tmp_path / "state")
    spec = {**SPEC, "block": {"first": "2026-03-10", "last": "2026-03-20"}}
    with pytest.raises(SystemExit, match="refused"):
        m.score(tmp_path / "processed", tmp_path / "state", spec)


def test_committed_spec_is_complete_and_matches_the_document():
    spec = json.loads((ROOT / "results" / "forward" / "predictions_forward.json").read_text(encoding="utf-8"))
    doc = (ROOT / "docs" / "PREDICTIONS_FORWARD.md").read_text(encoding="utf-8")
    m = _mod()
    assert spec["block"]["first"] == "2026-03-14"
    for p in spec["predictions"]:
        assert p["metric"] in m.METRICS or p["metric"] == "label_switches"
        assert 0 < p["p"] < 1
        assert f"| {p['id']} |" in doc and p["text"] in doc
