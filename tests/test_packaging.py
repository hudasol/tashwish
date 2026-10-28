"""Packaging metadata: typed marker, package data and the console script."""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import tashwish

ROOT = Path(__file__).resolve().parents[1]
META = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_py_typed_marker_exists_and_is_listed_as_package_data():
    assert (Path(tashwish.__file__).parent / "py.typed").is_file()
    assert "py.typed" in META["tool"]["setuptools"]["package-data"]["tashwish"]


def test_console_script_points_at_a_callable():
    target = META["project"]["scripts"]["tashwish"]
    module, _, func = target.partition(":")
    assert callable(getattr(importlib.import_module(module), func))
