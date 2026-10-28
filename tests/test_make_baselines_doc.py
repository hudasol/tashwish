"""The baselines document generator, run on SYNTHETIC result files built in the test."""

import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tashwish.baselines.evaluate import EMPTY_JAM, strict_events
from tashwish.detect.jamming import build_events
from tashwish.validate import harness as hz

ROOT = Path(__file__).resolve().parents[1]
JAM = ["system", "B1", "B1b", "B2", "B3a", "B3b", "B3c"]
DAYS = {"d1": "normal", "d2": "normal", "d3": "reduced", "d4": "reduced"}


def _load():
    spec = importlib.util.spec_from_file_location("make_baselines_doc", ROOT / "scripts" / "make_baselines_doc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_split(root: Path, name: str, seed: int):
    rng = np.random.default_rng(seed)
    rows = []
    for day, tr in DAYS.items():
        for i in range(12):
            kind = ["jam_only", "spoof_jump", "null"][i % 3]
            r = {"sid": f"{name}_{day}_{i}", "kind": kind, "tier": ["easy", "medium", "hard", "random"][i % 4] if kind == "jam_only" else "none",
                 "day": day, "run": 0, "n_spoofed": 5 if kind == "spoof_jump" else 0, "displacement_km": np.nan, "scatter_km": np.nan,
                 "traffic": tr, "degraded": "baseline", "data_class": "synthetic"}  # fmt: skip
            for d in JAM:
                r[f"{d}__jam"] = bool(rng.random() < 0.5)
                r[f"{d}__jam_strict"] = bool(rng.random() < 0.4)
            for d in ("system", "B4"):
                r[f"{d}__spoof"] = bool(rng.random() < 0.5)
            rows.append(r)
    scen = pd.DataFrame(rows)
    real = []
    for day, tr in DAYS.items():
        for d in JAM:
            real.append({"day": day, "detector": d, "kind": "jamming_like", "n_tested": 100, "n_flagged": 5 if d == "system" else 20, "n_events": 2,
                         "n_system": 5, "n_both": 4, "n_union": 21 if d != "system" else 5, "data_class": "observed", "traffic": tr, "degraded": "baseline"})  # fmt: skip
        for d in ("system", "B4"):
            real.append({"day": day, "detector": d, "kind": "spoofing_like", "n_tested": 0, "n_flagged": 3, "n_events": 1, "n_system": 3,
                         "n_both": 3, "n_union": 3, "data_class": "observed", "traffic": tr, "degraded": "baseline"})  # fmt: skip
    out = root / name
    out.mkdir(parents=True)
    scen.to_csv(out / "synthetic_scenarios_baselines.csv", index=False)
    pd.DataFrame(real).to_csv(out / "observed_days_baselines.csv", index=False)
    meta = {"split": name, "score_days": list(DAYS), "run_commit": "abc", "baselines_fixed_before_run_commit": "0123456789abcdef",
            "baseline_sources_sha256": "x", "reproduction_of_system": {"scenarios_here": len(scen), "scenarios_committed": len(scen),
            "matched_sid": len(scen), "jam_detected_equal": len(scen), "spoof_detected_equal": len(scen)}}  # fmt: skip
    (out / "run_meta.json").write_text(json.dumps(meta))


@pytest.fixture
def generated(tmp_path, monkeypatch):
    root = tmp_path / "res"
    _fake_split(root, "dev", 1)
    _fake_split(root, "held_out", 2)
    pd.DataFrame({"day": list(DAYS), "traffic": list(DAYS.values())}).to_csv(tmp_path / "regimes.csv", index=False)
    doc = tmp_path / "BASELINES.md"
    doc.write_text(
        "# Baselines\n\nhand written part\n\n<!-- BEGIN GENERATED RESULTS -->\nold\n<!-- END GENERATED RESULTS -->\n"
    )
    mod = _load()
    monkeypatch.setattr(
        "sys.argv", ["x", "--root", str(root), "--doc", str(doc), "--regimes", str(tmp_path / "regimes.csv")]
    )
    mod.main()
    return doc.read_text(), json.loads((root / "summary.json").read_text())


def test_hand_written_part_is_kept_and_old_results_replaced(generated):
    text, _ = generated
    assert "hand written part" in text and "\nold\n" not in text
    assert text.count("<!-- BEGIN GENERATED RESULTS -->") == 1 and text.count("<!-- END GENERATED RESULTS -->") == 1


def test_headline_table_lists_every_detector(generated):
    text, _ = generated
    block = text.split("### Headline comparison")[1].split("### 1.")[0]
    for det in ("system", "B1", "B1b", "B2", "B3a", "B3b", "B3c", "B4"):
        assert f"| {det} |" in block


def test_held_out_numbers_carry_the_post_hoc_label_with_the_commit(generated):
    text, _ = generated
    assert "post hoc, not preregistered, baselines fixed before run (0123456789)" in text
    for line in text.splitlines():
        if line.startswith("###") and "Held out days" in line:
            assert "post hoc, not preregistered, baselines fixed before run" in line


def test_summary_has_both_splits_and_the_expected_tables(generated):
    _, s = generated
    for split in ("dev", "held_out"):
        assert {
            "jam_recall",
            "spoof_recall_n_ge_3",
            "null_flag_rate",
            "real_days_jamming_like",
            "paired_vs_system",
        } <= set(s[split])
        r = s[split]["jam_recall"]["harness"]["all"]["B1"]["easy"]
        assert r["n"] > 0 and 0 <= r["rate"] <= 1


def test_style_rules(generated):
    text, _ = generated
    body = text.split("<!-- BEGIN GENERATED RESULTS -->")[1]
    assert "—" not in body and "–" not in body
    assert not re.search(r"[\U0001F300-\U0001FAFF☀-➿]", body)
    words = re.findall(r"[A-Za-z]+-[A-Za-z]+", body)
    assert set(words) <= {"jamming-like", "spoofing-like", "Jamming-like", "Spoofing-like"}, set(words)


def test_sources_line_cites_repository_files_only(generated):
    text, _ = generated
    line = [x for x in text.splitlines() if x.startswith("Sources:")][-1]
    paths = [p.strip().rstrip(".") for p in line[len("Sources:") :].split(",")]
    assert paths and all(re.match(r"^(docs|results|src|scripts)/[\w./]+$", p) for p in paths)


def test_paired_verdicts():
    mod = _load()
    df = pd.DataFrame({"day": ["a", "a", "b", "b", "c", "c"], "x": [1, 1, 1, 1, 1, 1], "y": [0, 0, 0, 0, 0, 0]})
    p = mod.paired(df, "x", "y")
    assert p["diff"] == 1.0 and p["verdict"] == "above"
    assert mod.paired(df, "y", "x")["verdict"] == "below"
    assert mod.paired(df, "x", "x")["verdict"] == "tied"


def test_strict_events_drop_flags_present_without_injection():
    t0 = pd.Timestamp("2026-03-07 06:00", tz="UTC")
    cells = sorted(__import__("h3").grid_disk(__import__("h3").latlng_to_cell(25.0, 55.0, hz.GRID.h3_res), 1))
    cols = {"stratum": "enroute", "n_aircraft": 10, "k": 8, "ci_lo": 0.5, "ci_hi": 0.9, "p_value": 1e-6}

    def flags(keys):
        return pd.DataFrame([{"cell": c, "bucket": b, "flag": True, **cols} for c, b in keys])

    before = flags([(cells[0], t0)])
    after = flags([(cells[0], t0), (cells[3], t0 + pd.Timedelta(hours=9))])  # one old flag and one new, far in time
    ev = strict_events(after, before)
    assert len(ev) == 1 and ev.iloc[0]["cells"] == cells[3]
    assert strict_events(before, before).empty and strict_events(pd.DataFrame(), before).empty
    assert len(build_events(after, hz.GRID)) == 2 and EMPTY_JAM.empty
