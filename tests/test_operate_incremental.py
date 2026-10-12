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
    _state(tmp_path, "2026-02-09")
    p = tmp_path / "p"
    p.mkdir()
    (p / "freshness.json").write_text(json.dumps({"generated_at": "2026-02-10T00:00:00Z", "latest_day": "2026-02-09"}))

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
            "2026-02-10",
        ]
    )
    assert rc == 1
    f = json.loads((p / "freshness.json").read_text())
    assert f["last_run_status"] == "failed" and f["fallback_active"] is True
    assert f["latest_day"] == "2026-02-09" and f["generated_at"] == "2026-02-10T00:00:00Z"


def test_resume_at_first_missing_day(tmp_path):
    _state(tmp_path, "2026-02-09")
    cb = pd.DataFrame([{"cell": "c", "bucket": pd.Timestamp("2026-02-10", tz="UTC"), "stratum": "enroute", "n_aircraft": 1, "k_strong": 0,
                        "share_strong": 0.0, "ci_lo_strong": 0.0, "ci_hi_strong": 1.0, "status": "insufficient", "coverage_class": "marginal", "slot": 0}])  # fmt: skip
    write_day(
        tmp_path / "p",
        "2026-02-10",
        cb,
        pd.DataFrame(),
        split="incremental",
        mode="m",
        rows=1,
        aircraft=1,
        ingested_at=None,
    )
    st = FrozenState.load(tmp_path / "state")
    assert list_days(tmp_path / "p") == ["2026-02-10"]
    assert incremental.next_days(tmp_path / "p", st, 2, None)[0] == "2026-02-11"
