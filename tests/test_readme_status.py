"""The README status block must equal the block generated from the result files (numbers are never typed by hand)."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _gen():
    spec = importlib.util.spec_from_file_location("make_readme_status", ROOT / "scripts" / "make_readme_status.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_readme_status_block_equals_generated_block():
    m = _gen()
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    found = re.search(re.escape(m.BEGIN) + r".*?" + re.escape(m.END), text, re.S)
    assert found, "README.md has no STATUS markers"
    assert found.group(0) == m.build_block()


def test_status_block_has_no_dashes_or_hyphenated_words():
    block = _gen().build_block()
    assert not re.search("[" + chr(0x2013) + chr(0x2014) + chr(0x2212) + "]", block)
    body = re.sub(r"`[^`]*`|\]\([^)]*\)", "", block)
    assert not [w for w in re.findall(r"[A-Za-z]+-[A-Za-z]+", body) if w != "ADS-B"]


def test_status_block_labels_synthetic_and_observed():
    block = _gen().build_block()
    assert "SYNTHETIC" in block and "OBSERVED" in block
    assert "tashwish-heldout-v1" in block


def test_report_equals_generated_report():
    spec = importlib.util.spec_from_file_location("make_report", ROOT / "scripts" / "make_report.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert (ROOT / "docs" / "research" / "REPORT.md").read_text(encoding="utf-8") == m.build()
