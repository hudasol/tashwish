"""Forward scorer on SYNTHETIC processed days (invented numbers in a temp dir; nothing here describes the real world).

The synthetic days carry `data_class: observed` only so that the scorer's observed code path can be exercised, in the same way
as `tests/synth_release.py`; such a folder never leaves a test temp dir. One test checks that a day labelled synthetic is
rejected.
"""

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
LATE = "2026-10-20T00:00:00Z"  # after the registration time used below


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
         mode: str = "frozen_baseline", data_class: str = "observed", ingested_at: str = LATE,
         small_n: int = 2) -> None:  # fmt: skip
    """One synthetic day: covered en route rows of 10 aircraft each plus `not_enough` covered rows with `small_n` aircraft."""
    d = processed / "days" / day
    d.mkdir(parents=True)
    n_ok = units // 10
    rows = [{"cell": f"c{i}", "stratum": "enroute", "n_aircraft": 10, "k_strong": 1 if i < degraded else 0,
             "coverage_class": "covered"} for i in range(n_ok)]  # fmt: skip
    rows += [{"cell": f"x{i}", "stratum": "enroute", "n_aircraft": small_n, "k_strong": 0, "coverage_class": "covered"}
             for i in range(not_enough)]  # fmt: skip
    pd.DataFrame(rows).to_parquet(d / "cb.parquet", index=False)
    pd.DataFrame(
        {"kind": events, "confidence": ["medium"] * len(events), "label_uncertain": [True] * len(events)},
        columns=["kind", "confidence", "label_uncertain"],
    ).to_parquet(d / "events.parquet", index=False)
    meta = {"day": day, "mode": mode, "data_class": data_class, "ingested_at": ingested_at,
            "provenance": {"state_sha256": sha}}  # fmt: skip
    (d / "day.json").write_text(json.dumps(meta), encoding="utf-8")


def _spec(sha: str, **over) -> dict:
    spec = {
        "registered_at": "2026-10-16T01:07:28Z",
        "state_sha256": sha,
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
            },  # fmt: skip
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
            },  # fmt: skip
            {
                "id": "T4",
                "text": "t",
                "metric": "label_switches",
                "subset": "all",
                "op": "<=",
                "threshold": 0,
                "p": 0.6,
            },
            {
                "id": "T5",
                "text": "t",
                "metric": "share_days_elevated",
                "subset": "first_week",
                "op": ">=",
                "threshold": 1.0,
                "p": 0.7,
            },  # fmt: skip
            {
                "id": "T6",
                "text": "t",
                "metric": "spoofing_like_uncertain_share",
                "subset": "all",
                "op": ">=",
                "threshold": 0.5,
                "p": 0.7,
                "min_spoofing_like_events": 5,
            },  # fmt: skip
        ],
    }
    return {**spec, **over}


def test_measures_scoring_and_first_failure(tmp_path):
    m = _mod()
    sha = _state(tmp_path / "state")
    p = tmp_path / "processed"
    # ref 1000: units 300 -> reduced; share 30/300 = 0.1 -> elevated. Units 800 -> normal; 0 degraded -> baseline.
    _day(p, "2026-03-14", units=300, degraded=30, not_enough=10, events=["spoofing_like"], sha=sha)
    _day(p, "2026-03-15", units=300, degraded=30, not_enough=30, events=["both", "jamming_like"], sha=sha)
    _day(p, "2026-03-16", units=800, degraded=0, not_enough=0, events=[], sha=sha)
    _day(p, "2026-03-17", units=800, degraded=0, not_enough=0, events=[], sha=sha, mode="dev_leave_one_day_out")
    r = m.score(p, tmp_path / "state", _spec(sha))
    assert r["n_days_scored"] == 3 and r["missing_days"] == []
    assert r["rejected_days"] == [{"day": "2026-03-17", "reasons": ["mode is not frozen_baseline"]}]
    days = {d["day"]: d for d in r["per_day"]}
    assert (days["2026-03-14"]["traffic"], days["2026-03-14"]["degraded"]) == ("reduced", "elevated")
    assert (days["2026-03-16"]["traffic"], days["2026-03-16"]["degraded"]) == ("normal", "baseline")
    assert days["2026-03-15"]["false_coverage"] == pytest.approx(30 / 60)
    v = {x["id"]: x for x in r["predictions"]}
    assert v["T1"]["verdict"] == "MISS" and v["T1"]["value"] == pytest.approx(2 / 3)
    assert v["T2"]["value"] == pytest.approx(40 / 100) and v["T2"]["verdict"] == "HIT"
    assert v["T2"]["ci_lo"] <= v["T2"]["value"] <= v["T2"]["ci_hi"]
    assert v["T3"]["verdict"] == "NOT EVALUABLE"  # one normal day, two needed
    assert v["T4"]["value"] == 1 and v["T4"]["verdict"] == "MISS"
    assert v["T5"]["n_days"] == 2 and v["T5"]["verdict"] == "HIT"  # first week: 03-14 and 03-15 only, both elevated
    assert v["T6"]["verdict"] == "NOT EVALUABLE" and "2 spoofing-like events" in v["T6"]["reason"]
    assert all(x["data_class"] == "OBSERVED" for x in r["predictions"])
    assert r["brier"] == pytest.approx(((0.6 - 0) ** 2 + (0.5 - 1) ** 2 + (0.6 - 0) ** 2 + (0.7 - 1) ** 2) / 4)
    ff = r["first_failures"]
    assert ff["label_pair"]["first_fail"] == "2026-03-16"
    assert ff["events"]["first_fail"] == "2026-03-15"
    assert ff["false_coverage"]["first_fail"] is None
    assert ff["any"]["first_fail"] == "2026-03-15"
    doc = m.render(r, _spec(sha))
    assert doc.index("| T1 | MISS") < doc.index("| T2 | HIT")  # misses before hits


def test_minimum_sample_boundary_and_rejections(tmp_path):
    m = _mod()
    sha = _state(tmp_path / "state")
    p = tmp_path / "processed"
    # covered rows with exactly 5 aircraft are enough; rows with 4 are not
    _day(p, "2026-03-14", units=300, degraded=30, not_enough=10, events=[], sha=sha, small_n=4)
    _day(p, "2026-03-15", units=300, degraded=30, not_enough=10, events=[], sha=sha, small_n=5)
    _day(p, "2026-03-16", units=300, degraded=30, not_enough=0, events=[], sha=sha, data_class="synthetic")
    _day(p, "2026-03-17", units=300, degraded=30, not_enough=0, events=[], sha=sha, ingested_at="2026-10-15T00:00:00Z")
    r = m.score(p, tmp_path / "state", _spec(sha))
    days = {d["day"]: d for d in r["per_day"]}
    assert days["2026-03-14"]["n_covered_not_enough"] == 10 and days["2026-03-15"]["n_covered_not_enough"] == 0
    rej = {x["day"]: x["reasons"] for x in r["rejected_days"]}
    assert rej == {"2026-03-16": ["data_class is not observed"], "2026-03-17": ["ingested before the preregistration"]}


def test_refusals(tmp_path):
    m = _mod()
    sha = _state(tmp_path / "state")
    p = tmp_path / "processed"
    with pytest.raises(SystemExit, match="study window"):
        m.score(p, tmp_path / "state", _spec(sha, block={"first": "2026-03-10", "last": "2026-03-20"}))
    with pytest.raises(SystemExit, match="not the frozen state"):
        m.score(p, tmp_path / "state", _spec("0" * 64))
    _day(p, "2026-03-14", units=300, degraded=30, not_enough=0, events=[], sha=sha)
    with pytest.raises(SystemExit, match="not processed"):  # run once: only when the block is complete
        m.score(p, tmp_path / "state", _spec(sha))
    r = m.score(p, tmp_path / "state", _spec(sha), incomplete_reason="archive gap")
    assert r["incomplete_reason"] == "archive gap" and r["missing_days"] == ["2026-03-15", "2026-03-16", "2026-03-17"]


def _numbers(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"(?<![\w.-])\d+(?:\.\d+)?(?![\w-])", text)]


def test_committed_spec_matches_the_document_and_the_frozen_state():
    spec = json.loads((ROOT / "results" / "forward" / "predictions_forward.json").read_text(encoding="utf-8"))
    doc = (ROOT / "docs" / "PREDICTIONS_FORWARD.md").read_text(encoding="utf-8")
    m = _mod()
    assert spec["state_sha256"] == hashlib.sha256((ROOT / "state" / "state.json").read_bytes()).hexdigest()
    assert spec["block"] == {"first": "2026-03-14", "last": "2026-04-12"}
    subsets = {"all": "all", "first_week": "2026-03-14 to 2026-03-20", "elevated": "degraded elevated days",
               "reduced": "traffic reduced days", "normal": "traffic normal days", "baseline": "degraded baseline days"}  # fmt: skip
    ops = {">=": ("at least", "equal to"), "<=": ("at most",), "between": ("from",)}
    rows = {r.split("|")[1].strip(): [c.strip() for c in r.split("|")[1:-1]] for r in doc.splitlines()
            if re.match(r"^\| F\d+ \|", r)}  # fmt: skip
    assert set(rows) == {p["id"] for p in spec["predictions"]}
    for p in spec["predictions"]:
        assert p["metric"] in m.METRICS or p["metric"] == "label_switches"
        pid, text, _measure, days, crit, prob = rows[p["id"]]
        assert text == p["text"] and days == subsets[p["subset"]] and float(prob) == p["p"]
        assert crit.startswith(ops[p["op"]])
        th = p["threshold"] if isinstance(p["threshold"], list) else [p["threshold"]]
        assert _numbers(crit)[: len(th)] == [float(x) for x in th], (pid, crit)
    sec5 = doc[doc.index("## 5.") : doc.index("## 6.")]
    dc = spec["daily_checks"]
    for v in (dc["false_coverage_max"]["reduced"], dc["false_coverage_max"]["normal"], dc["events_max"]):
        assert float(v) in _numbers(sec5)
    sec2 = doc[doc.index("## 2.") : doc.index("## 3.")]
    for v in (spec["min_days"], spec["min_subset_days"], spec["first_week_min_days"], spec["bootstrap"]["reps"]):
        assert float(v) in _numbers(sec2)
