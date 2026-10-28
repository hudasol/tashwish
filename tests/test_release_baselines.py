"""Web data for the baseline comparison, on a tiny SYNTHETIC summary (invented numbers, test only)."""

import json
import re

import pytest

from tashwish.release import build

from .test_release_build import _setup

BANNED = re.compile("[–—−‐‑]|[\U0001f300-\U0001faff]")


def _rate(k, n, lo=None, hi=None):
    return {"k": k, "n": n, "days": 3, "rate": k / n, "lo": lo, "hi": hi}


def _split(scale=1):
    def jam(det_vals):
        return {t: _rate(*v) for t, v in zip(("easy", "medium", "hard", "random"), det_vals, strict=True)}

    return {
        "jam_recall": {
            "harness": {
                "all": {"system": jam([(9, 10, 0.7, 1.0)] * 4), "B1": jam([(5, 10, 0.2, 0.8)] * 4)},
                "normal": {"system": jam([(1, 2, float("nan"), float("nan"))] * 4)},
            },
            "strict": {"all": {"system": jam([(0, 10, 0.0, 0.1)] * 4)}},
        },
        "spoof_recall_n_ge_3": {"all": {"system": _rate(6, 10, 0.4, 0.8), "B4": _rate(9, 10, 0.7, 1.0)}},
        "real_days_jamming_like": {
            "reduced": {
                "system": {
                    "days": 4,
                    "flagged_per_day": 0.5 * scale,
                    "flagged_per_day_lo": 0.0,
                    "flagged_per_day_hi": 1.25,
                },
                "B1": {
                    "days": 4,
                    "flagged_per_day": 7.25 * scale,
                    "flagged_per_day_lo": 3.0,
                    "flagged_per_day_hi": None,
                },
            }
        },
        "real_days_spoofing_like": {
            "all": {"B4": {"days": 5, "flagged_per_day": 2.0, "flagged_per_day_lo": 1.0, "flagged_per_day_hi": 3.0}}
        },
    }


SUMMARY = {"data_class_note": "x", "dev": _split(), "held_out": _split(2)}


def _pick(rows, **kw):
    return [r for r in rows if all(r.get(k) == v for k, v in kw.items())]


def test_rows_carry_only_numbers_from_the_summary():
    rows = build.baseline_rows(SUMMARY)
    (r,) = _pick(rows, metric="jamming_recall", split="dev", regime="pooled", detector="B1", tier="hard")
    assert (r["value"], r["ci_lo"], r["ci_hi"], r["n"], r["data_class"]) == (0.5, 0.2, 0.8, 10, "synthetic")
    (r,) = _pick(rows, metric="spoofing_recall_3plus", split="held_out", detector="B4")
    assert (r["value"], r["n"], r["regime"], r["data_class"]) == (0.9, 10, "pooled", "synthetic")
    (r,) = _pick(rows, metric="flagged_per_day_jamming_like", split="held_out", regime="traffic_reduced", detector="B1")
    assert (r["value"], r["ci_lo"], r["ci_hi"], r["n"], r["data_class"]) == (14.5, 3.0, None, 4, "observed")
    (r,) = _pick(rows, metric="flagged_per_day_spoofing_like", split="dev", detector="B4")
    assert (r["value"], r["n"], r["data_class"]) == (2.0, 5, "observed")


def test_only_the_harness_rule_and_known_sections_are_used_and_gaps_are_skipped():
    rows = build.baseline_rows(SUMMARY)
    assert not _pick(rows, metric="jamming_recall", value=0.0)  # the strict rule is not published
    assert len(_pick(rows, metric="jamming_recall")) == 2 * (
        4 + 4 + 4
    )  # dev and held_out: all system, all B1, normal system
    assert not _pick(rows, regime="traffic_normal", detector="B1")  # absent cells give no row
    assert (
        build.baseline_rows({}) == [] and build.baseline_rows(None) == [] and build.baseline_rows({"dev": None}) == []
    )


def test_unusable_interval_values_become_null_and_the_rows_serialise_without_nan():
    rows = build.baseline_rows(SUMMARY)
    (r,) = _pick(rows, metric="jamming_recall", split="dev", regime="traffic_normal", tier="easy")
    assert r["ci_lo"] is None and r["ci_hi"] is None and r["value"] == 0.5
    json.dumps(rows, allow_nan=False)
    assert build._num(True) is None and build._num("x") is None and build._num(float("inf")) is None


def test_rows_state_their_class_split_regime_and_plain_labels_in_both_languages():
    rows = build.baseline_rows(SUMMARY)
    assert {r["data_class"] for r in rows} == {"synthetic", "observed"} and {r["split"] for r in rows} == {
        "dev",
        "held_out",
    }
    assert {r["regime"] for r in rows} <= {"pooled", "traffic_normal", "traffic_reduced"}
    assert set(build.BASELINE_LABELS) == set(build.BASELINE_JAM_DETECTORS) | set(build.BASELINE_SPOOF_DETECTORS)
    for r in rows:
        assert r["label_en"] == build.BASELINE_LABELS[r["detector"]][0]
        assert re.search("[؀-ۿ]", r["label_ar"]) and r["label_en"] != r["detector"]
        assert (r["metric"] == "jamming_recall") == ("tier" in r)
    for en, ar in build.BASELINE_LABELS.values():
        assert not BANNED.search(en + ar)
        assert not re.search(r"[A-Za-z]-[A-Za-z]", en)  # no hyphenated words in the public labels


def test_build_writes_baselines_json_only_when_the_summary_exists(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    build.main()
    assert not (tmp_path / "web" / "baselines.json").exists()  # absent file: no error, no output
    assert "baselines.json" not in {p.name for p in (tmp_path / "rel").iterdir()}
    (tmp_path / "res" / "baselines").mkdir(parents=True)
    (tmp_path / "res" / "baselines" / "summary.json").write_text(json.dumps(SUMMARY), encoding="utf-8", newline="\n")
    build.main()
    doc = json.loads((tmp_path / "web" / "baselines.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "tashwish.web.baselines.v1" and doc["data_class"] == "observed"
    assert doc["results"] == build.baseline_rows(SUMMARY)
    assert "baselines.json" not in {
        p.name for p in (tmp_path / "rel").iterdir()
    }  # synthetic rows stay out of the release
    (tmp_path / "res" / "baselines" / "summary.json").unlink()
    build.main()
    assert not (tmp_path / "web" / "baselines.json").exists()  # a stale file from an earlier build is removed


def test_a_summary_without_usable_rows_counts_as_absent(tmp_path):
    (tmp_path / "baselines").mkdir()
    (tmp_path / "baselines" / "summary.json").write_text(json.dumps({"dev": {}}), encoding="utf-8", newline="\n")
    assert build.load_baselines(tmp_path) is None
    assert build.load_baselines(tmp_path / "nowhere") is None


@pytest.mark.parametrize("bad", ["x", None, float("nan")])
def test_num_rejects_non_numbers(bad):
    assert build._num(bad) is None


def test_values_are_rounded_to_six_decimals_only():
    assert build._num(1 / 3) == 0.333333 and build._num(0.5) == 0.5 and build._num(7) == 7.0
