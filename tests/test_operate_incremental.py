import json
from datetime import UTC, datetime, timedelta

import pandas as pd

from tashwish.operate import incremental
from tashwish.operate.processed import list_days, write_day
from tashwish.operate.state import FrozenState


def _state(tmp_path, end):
    st = FrozenState(["2026-02-08", "2026-02-09"], pd.DataFrame({"icao24": []}), pd.DataFrame(), pd.DataFrame(),
                     {"baseline_end": end})  # fmt: skip
    st.save(tmp_path / "state")


def test_nothing_due_is_noop(tmp_path):
    yday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    _state(tmp_path, yday)
    rc = incremental.main(
        ["--state", str(tmp_path / "state"), "--processed", str(tmp_path / "p"), "--spool", str(tmp_path / "s")]
    )
    assert rc == 0
    f = json.loads((tmp_path / "p" / "freshness.json").read_text())
    assert f["last_run_status"] == "noop" and f["fallback_active"] is False


def test_failure_keeps_last_good_and_flags_fallback(tmp_path, monkeypatch):
    _state(tmp_path, "2026-04-01")
    p = tmp_path / "p"
    p.mkdir()
    (p / "freshness.json").write_text(json.dumps({"generated_at": "2026-04-02T00:00:00Z", "latest_day": "2026-04-01"}))

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(incremental, "ingest_day", boom)
    rc = incremental.main(
        [
            "--state",
            str(tmp_path / "state"),
            "--processed",
            str(p),
            "--spool",
            str(tmp_path / "s"),
            "--start-day",
            "2026-04-02",
        ]
    )
    assert rc == 1
    f = json.loads((p / "freshness.json").read_text())
    assert f["last_run_status"] == "failed" and f["fallback_active"] is True
    assert f["latest_day"] == "2026-04-01" and f["generated_at"] == "2026-04-02T00:00:00Z"


def test_resume_at_first_missing_day(tmp_path):
    _state(tmp_path, "2026-04-01")
    cb = pd.DataFrame([{"cell": "c", "bucket": pd.Timestamp("2026-04-02", tz="UTC"), "stratum": "enroute", "n_aircraft": 1, "k_strong": 0,
                        "share_strong": 0.0, "ci_lo_strong": 0.0, "ci_hi_strong": 1.0, "status": "insufficient", "coverage_class": "marginal", "slot": 0}])  # fmt: skip
    write_day(
        tmp_path / "p",
        "2026-04-02",
        cb,
        pd.DataFrame(),
        split="incremental",
        mode="m",
        rows=1,
        aircraft=1,
        ingested_at=None,
    )
    st = FrozenState.load(tmp_path / "state")
    assert list_days(tmp_path / "p") == ["2026-04-02"]
    assert incremental.next_days(tmp_path / "p", st, 2, None)[0] == "2026-04-03"


def _cb(day):
    return pd.DataFrame([{"cell": "c", "bucket": pd.Timestamp(day, tz="UTC"), "stratum": "enroute", "n_aircraft": 1, "k_strong": 0,
                          "share_strong": 0.0, "ci_lo_strong": 0.0, "ci_hi_strong": 1.0, "status": "insufficient", "coverage_class": "marginal", "slot": 0}])  # fmt: skip


def _fake_pipeline(monkeypatch):
    monkeypatch.setattr(incremental, "ingest_day", lambda day, cfg: None)
    monkeypatch.setattr(
        incremental, "score_day_frozen",
        lambda work, day, st: {"cb": _cb(day), "events": pd.DataFrame(), "rows": 1, "aircraft": 1},
    )  # fmt: skip


def _run(tmp_path, *extra):
    return incremental.main(
        ["--state", str(tmp_path / "state"), "--processed", str(tmp_path / "p"), "--spool", str(tmp_path / "s"), *extra]
    )


def test_study_window_days_are_refused_by_default(tmp_path, monkeypatch):
    _fake_pipeline(monkeypatch)
    _state(tmp_path, "2026-03-10")  # the next days (11 to 13 March) lie in the study window
    assert _run(tmp_path) == 2
    assert not (tmp_path / "p" / "freshness.json").exists()  # a refusal changes nothing
    assert list_days(tmp_path / "p") == []
    _state(tmp_path, "2026-02-06")
    assert _run(tmp_path, "--start-day", "2026-02-07") == 2
    st = FrozenState.load(tmp_path / "state")
    assert incremental.next_days(tmp_path / "p", st, 1, "2026-02-07", allow_study_window=True) == ["2026-02-07"]
    assert _run(tmp_path, "--start-day", "2026-02-07", "--allow-study-window") == 0
    assert list_days(tmp_path / "p") == ["2026-02-07"]


def test_gap_before_start_day_is_refused(tmp_path, monkeypatch):
    _fake_pipeline(monkeypatch)
    _state(tmp_path, "2026-04-01")
    assert _run(tmp_path, "--start-day", "2026-04-05") == 2
    assert list_days(tmp_path / "p") == []


def test_latest_day_never_moves_backwards_and_days_added_is_a_list(tmp_path, monkeypatch):
    _fake_pipeline(monkeypatch)
    _state(tmp_path, "2026-04-01")
    p = tmp_path / "p"
    p.mkdir()
    (p / "freshness.json").write_text(json.dumps({"generated_at": "2026-04-06T00:00:00Z", "latest_day": "2026-04-05"}))
    for d in ("2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05"):
        write_day(p, d, _cb(d), pd.DataFrame(), split="incremental", mode="m", rows=1, aircraft=1, ingested_at=None)
    assert _run(tmp_path, "--start-day", "2026-04-03") == 0  # reprocess an earlier day
    f = json.loads((p / "freshness.json").read_text())
    assert f["latest_day"] == "2026-04-05"
    assert f["days_added"] == ["2026-04-03"] and f["last_run_status"] == "ok"


def test_noop_slot_does_not_overwrite_earlier_ok_with_append_status(tmp_path, monkeypatch):
    _fake_pipeline(monkeypatch)
    _state(tmp_path, "2026-04-01")
    assert _run(tmp_path) == 0
    monkeypatch.setattr(incremental, "next_days", lambda *a, **k: [])
    assert _run(tmp_path, "--append-status") == 0
    f = json.loads((tmp_path / "p" / "freshness.json").read_text())
    assert f["last_run_status"] == "ok" and f["days_added"] == ["2026-04-02"] and f["latest_day"] == "2026-04-02"
    assert _run(tmp_path) == 0  # without the flag a new run starts clean
    f = json.loads((tmp_path / "p" / "freshness.json").read_text())
    assert f["last_run_status"] == "noop" and f["days_added"] == []


def test_permanently_missing_day_is_a_failure_not_a_green_noop(tmp_path, monkeypatch):
    _state(tmp_path, "2026-04-01")

    def missing(day, cfg):
        raise incremental.DayNotAvailable("no release")

    monkeypatch.setattr(incremental, "ingest_day", missing)
    assert _run(tmp_path) == 1
    f = json.loads((tmp_path / "p" / "freshness.json").read_text())
    assert f["last_run_status"] == "failed" and f["fallback_active"] is True and "gap" in f["last_error"]


def test_day_json_records_provenance(tmp_path, monkeypatch):
    _fake_pipeline(monkeypatch)
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    _state(tmp_path, "2026-04-01")
    assert _run(tmp_path) == 0
    meta = json.loads((tmp_path / "p" / "days" / "2026-04-02" / "day.json").read_text())
    prov = meta["provenance"]
    assert prov["code_commit"] == "abc123"
    assert prov["state_sha256"] == incremental.sha256_file(tmp_path / "state" / "state.json")
    assert "ingest_manifest_sha256" in prov and meta["data_class"] == "observed"
