"""The `tashwish` command: help text, exit codes, delegation and the environment check."""

from __future__ import annotations

import sys
from collections import namedtuple

import pytest

from tashwish import __version__, cli

COMMANDS = ["ingest", "incremental", "build", "validate", "api", "version", "doctor"]


def test_top_level_help_lists_every_command(capsys):
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    for name in COMMANDS:
        assert name in out
    assert "not for navigation" in out


def test_no_command_prints_help_and_fails(capsys):
    assert cli.main([]) == 2
    assert "usage: tashwish" in capsys.readouterr().out


def test_unknown_command_is_a_usage_error(capsys):
    assert cli.main(["nonsense"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_version_command_and_flag(capsys):
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == __version__
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"tashwish {__version__}"


@pytest.mark.parametrize("command", ["ingest", "incremental", "build", "validate", "api"])
def test_delegated_commands_show_the_module_help(command, capsys):
    assert cli.main([command, "--help"]) == 0
    out = capsys.readouterr().out
    assert "usage:" in out and "--" in out


def test_delegated_command_passes_arguments_and_exit_status(monkeypatch):
    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        seen["sys_argv"] = list(sys.argv)
        return 7

    monkeypatch.setattr("tashwish.operate.incremental.main", fake_main)
    assert cli.main(["incremental", "--spool", "x", "--max-days", "2"]) == 7
    assert seen["argv"] == ["--spool", "x", "--max-days", "2"]
    assert seen["sys_argv"][0] == "tashwish incremental"


def test_module_that_reads_sys_argv_gets_its_arguments(monkeypatch):
    seen = {}

    def fake_main():
        seen["argv"] = sys.argv[1:]

    monkeypatch.setattr("tashwish.release.build.main", fake_main)
    before = list(sys.argv)
    assert cli.main(["build", "--mode", "study_snapshot"]) == 0
    assert seen["argv"] == ["--mode", "study_snapshot"]
    assert sys.argv == before


def test_system_exit_from_a_module_becomes_the_return_value(monkeypatch):
    def failing():
        raise SystemExit(1)

    monkeypatch.setattr("tashwish.release.build.main", failing)
    assert cli.main(["build"]) == 1


def test_bad_option_for_a_delegated_command_exits_2(capsys):
    assert cli.main(["build", "--no-such-option"]) == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_incremental_requires_a_spool_directory(capsys):
    assert cli.main(["incremental"]) == 2
    assert "--spool" in capsys.readouterr().err


# doctor


def _doctor(tmp_path, capsys, **kw):
    rc = cli.main(["doctor", "--root", str(tmp_path)])
    return rc, capsys.readouterr().out


def test_doctor_without_the_state_key(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(cli.STATE_KEY_ENV, raising=False)
    rc, out = _doctor(tmp_path, capsys)
    assert rc == 0
    assert f"{cli.STATE_KEY_ENV} is not set" in out
    assert "state/ not found" in out and "processed/ not found" in out


def test_doctor_with_the_state_key_never_prints_it(tmp_path, capsys, monkeypatch):
    secret = "k" * 12 + "UNIQUE-VALUE-0123"
    monkeypatch.setenv(cli.STATE_KEY_ENV, secret)
    (tmp_path / "state").mkdir()
    (tmp_path / "processed").mkdir()
    rc, out = _doctor(tmp_path, capsys)
    assert rc == 0
    assert f"{cli.STATE_KEY_ENV} is set" in out
    assert "state/ found" in out and "processed/ found" in out
    assert secret not in out and "UNIQUE-VALUE" not in out


def test_doctor_flags_a_short_key_without_printing_it(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(cli.STATE_KEY_ENV, "abc123xyz")
    rc, out = _doctor(tmp_path, capsys)
    assert rc == 0
    assert "shorter than" in out and "abc123xyz" not in out


def test_doctor_fails_on_an_old_python(tmp_path, capsys, monkeypatch):
    info = namedtuple("info", "major minor micro releaselevel serial")
    monkeypatch.setattr(sys, "version_info", info(3, 10, 0, "final", 0))
    rc, out = _doctor(tmp_path, capsys)
    assert rc == 1
    assert "3.11 or newer" in out


def test_doctor_fails_when_a_required_package_is_missing(tmp_path, capsys, monkeypatch):
    real = cli._has_package
    monkeypatch.setattr(cli, "_has_package", lambda name: False if name == "duckdb" else real(name))
    rc, out = _doctor(tmp_path, capsys)
    assert rc == 1
    assert "required packages: duckdb" in out


def test_doctor_reports_an_incomplete_extra_as_a_note(tmp_path, capsys, monkeypatch):
    real = cli._has_package
    monkeypatch.setattr(cli, "_has_package", lambda name: False if name == "fastapi" else real(name))
    rc, out = _doctor(tmp_path, capsys)
    assert rc == 0
    assert "extra 'api' is not complete, missing: fastapi" in out
