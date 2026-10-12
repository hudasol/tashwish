import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "check_freshness", Path(__file__).resolve().parents[1] / "scripts" / "check_freshness.py"
)
cf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cf)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def doc(gen_hours_ago: float, latest_day: str) -> dict:
    gen = (NOW - timedelta(hours=gen_hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"generated_at": gen, "latest_day": latest_day, "last_run_status": "ok", "fallback_active": False}


def test_ok():
    assert cf.evaluate(doc(5, "2026-10-11"), NOW)["level"] == "ok"  # day ended 12 h ago


def test_amber_by_day_age():
    # latest day ended 2026-10-10T00:00Z, 60 h before NOW; generated recently
    r = cf.evaluate(doc(1, "2026-10-09"), NOW)
    assert r["level"] == "amber" and r["latest_day_age_hours"] == 60.0


def test_amber_by_generated_age():
    assert cf.evaluate(doc(49, "2026-10-11"), NOW)["level"] == "amber"


def test_boundaries_are_strictly_greater():
    assert cf.evaluate(doc(48, "2026-10-11"), NOW)["level"] == "ok"
    assert cf.evaluate(doc(7 * 24, "2026-10-11"), NOW)["level"] == "amber"
    assert cf.evaluate(doc(7 * 24 + 0.1, "2026-10-11"), NOW)["level"] == "red"


def test_red_by_day_age():
    assert cf.evaluate(doc(1, "2026-10-01"), NOW)["level"] == "red"


def test_main_exit_codes(tmp_path, capsys):
    p = tmp_path / "freshness.json"
    fresh = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    p.write_text(json.dumps({"generated_at": fresh, "latest_day": yesterday}))
    assert cf.main([str(p)]) == 0
    p.write_text(json.dumps({"generated_at": "2020-01-01T00:00:00Z", "latest_day": "2020-01-01"}))
    assert cf.main([str(p)]) == 2
    assert "red" in capsys.readouterr().out


def test_missing_and_malformed_are_unknown(tmp_path):
    assert cf.main([str(tmp_path / "nope.json")]) == 3
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert cf.main([str(bad)]) == 3
    bad.write_text(json.dumps({"latest_day": "2026-10-01"}))
    assert cf.main([str(bad)]) == 3


def test_mark_failed_keeps_last_good(tmp_path):
    p = tmp_path / "sub" / "freshness.json"
    p.parent.mkdir()
    p.write_text(json.dumps(doc(3, "2026-10-11")))
    assert cf.main([str(p), "--mark-failed", "download failed"]) == 0
    out = json.loads(p.read_text())
    assert out["last_run_status"] == "failed" and out["fallback_active"] is True
    assert out["latest_day"] == "2026-10-11" and out["generated_at"] == doc(3, "2026-10-11")["generated_at"]
    assert out["last_error"] == "download failed"


def test_mark_failed_creates_file(tmp_path):
    p = tmp_path / "freshness.json"
    cf.mark_failed(p, "x", NOW)
    assert json.loads(p.read_text())["fallback_active"] is True
    assert cf.main([str(p)]) == 3  # no generated_at: cannot be evaluated, never looks healthy


@pytest.mark.parametrize("ts", ["2026-10-12T00:00:00Z", "2026-10-12T00:00:00+00:00"])
def test_timestamp_forms(ts):
    assert cf.evaluate({"generated_at": ts, "latest_day": "2026-10-11"}, NOW)["level"] == "ok"
