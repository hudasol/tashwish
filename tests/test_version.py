"""The package version has one source, `tashwish.__version__`, which pyproject.toml reads."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import tashwish

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_a_release_number():
    assert re.fullmatch(r"\d+\.\d+\.\d+", tashwish.__version__)


def test_pyproject_reads_the_version_from_the_package():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" in meta["project"]["dynamic"]
    assert "version" not in meta["project"]
    assert meta["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "tashwish.__version__"}
