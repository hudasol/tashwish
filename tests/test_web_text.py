"""Checks on the dashboard text and data files that no browser is needed for."""

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
EN = json.loads((WEB / "i18n" / "en.json").read_text(encoding="utf-8"))
AR = json.loads((WEB / "i18n" / "ar.json").read_text(encoding="utf-8"))
BANNED = re.compile("[–—−\U0001f300-\U0001faff☀-➿]")
ALLOWED_HYPHENS = {"jamming-like", "spoofing-like", "ads-b"}  # ADS-B is a standard name


def test_languages_have_the_same_keys():
    assert set(EN) == set(AR)


def test_no_dashes_or_emoji_in_public_text():
    for name, d in (("en", EN), ("ar", AR)):
        bad = [k for k, v in d.items() if BANNED.search(v)]
        assert not bad, (name, bad)


def test_english_text_has_no_hyphenated_words_except_the_allowed_ones():
    licence = re.compile(r"^(?:BSD|Apache|MIT|GPL)-[\w.-]+$")
    for k, v in EN.items():
        for w in re.findall(r"[A-Za-z]+(?:-[A-Za-z0-9.]+)+", v):
            assert w.lower() in ALLOWED_HYPHENS or licence.match(w), (k, w)


def test_static_i18n_keys_used_by_the_scripts_exist():
    used = set()
    for p in (WEB / "js").glob("*.js"):
        used |= set(re.findall(r'\bt\(\s*"([\w.]+)"', p.read_text(encoding="utf-8")))
    for p in WEB.glob("*.html"):
        used |= set(re.findall(r'data-(?:i18n|title-key|i18n-label)="([\w.]+)"', p.read_text(encoding="utf-8")))
    prefixes = (
        "kind.",
        "confidence.",
        "status.",
        "coverage.",
        "class.",
        "fresh.state_",
        "chip.",
        "event.label_",
        "vrow.generic_",
    )
    missing = [k for k in used if k not in EN and not k.endswith(".")]
    assert not [k for k in missing if not k.startswith(prefixes)], missing


def test_every_validation_row_has_scenario_regime_and_metric_text():
    v = json.loads((WEB / "data" / "validation.json").read_text(encoding="utf-8"))
    m = json.loads((WEB / "data" / "methods.json").read_text(encoding="utf-8"))["metrics"]
    assert v["results"]
    for r in v["results"]:
        assert r["data_class"] in ("synthetic", "observed")
        assert "scenario." + r["scenario"] in EN and "scenario." + r["scenario"] in AR, r["scenario"]
        assert "regime." + r["regime"] in EN, r["regime"]
        assert "ci." + r["ci_method"] in EN, r["ci_method"]
        assert "vrow." + re.sub(r"_(normal|reduced)$", "", r["metric"]) in EN, r["metric"]
        assert r["metric"] in m
    assert not any(r["scenario"].startswith("synthetic") and r["data_class"] != "synthetic" for r in v["results"])


def test_arabic_metric_labels_are_arabic():
    m = json.loads((WEB / "data" / "methods.json").read_text(encoding="utf-8"))["metrics"]
    for k in (
        "jamming_recall_easy",
        "jamming_recall_medium",
        "jamming_recall_hard",
        "spoofing_recall_3plus_aircraft",
        "false_coverage_rate",
    ):
        assert re.search("[؀-ۿ]", m[k]["label_ar"]), k


def test_snapshot_manifest_replaces_the_staleness_state():
    man = json.loads((WEB / "data" / "manifest.json").read_text(encoding="utf-8"))
    assert man["mode"] in ("live", "study_snapshot")
    if man["mode"] == "study_snapshot":
        assert man["study_window"]["start"] <= man["study_window"]["end"]
    js = (WEB / "js" / "common.js").read_text(encoding="utf-8")
    assert 'm.mode === "study_snapshot"' in js and "fresh.state_snapshot" in EN
