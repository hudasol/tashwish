"""Command line entry point: `tashwish <command>`.

Most commands pass their arguments unchanged to an existing module, so `tashwish build --help` shows the options of
`python -m tashwish.release.build`. The module itself is not modified; this file only chooses which one to run.

  ingest       download and ingest archive days            (tashwish.ingest)
  incremental  process the next archive day into processed/ (tashwish.operate.incremental)
  build        build the release and dashboard data         (tashwish.release.build)
  validate     run the validation harness                   (tashwish.validate.run)
  api          serve the read only API                      (tashwish.api)
  version      print the package version
  doctor       check the environment
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import sys
from collections.abc import Callable
from pathlib import Path

from . import __version__

MIN_PYTHON = (3, 11)
STATE_KEY_ENV = "TASHWISH_STATE_KEY"
STATE_KEY_MIN_LENGTH = 16

# command -> (module, one line description). Each module has a `main` function.
DELEGATED = {
    "ingest": ("tashwish.ingest.__main__", "download and ingest archive days to Parquet"),
    "incremental": ("tashwish.operate.incremental", "process the next archive day into processed/"),
    "build": ("tashwish.release.build", "build the dataset release and the dashboard data"),
    "validate": ("tashwish.validate.run", "run the validation harness"),
    "api": ("tashwish.api.__main__", "serve the read only API (needs the api extra)"),
}

CORE_PACKAGES = ["duckdb", "h3", "httpx", "numpy", "pandas", "pyarrow", "scipy", "tabulate"]
EXTRAS = {"api": ["fastapi", "uvicorn"], "dev": ["pytest", "pytest_cov", "hypothesis", "ruff"]}


def _run_module_main(main: Callable[..., int | None], prog: str, args: list[str]) -> int:
    """Call a module's `main` the way `python -m` would, returning an exit status.

    Some modules read sys.argv themselves and some take an argv list; setting sys.argv covers both."""
    saved = sys.argv
    sys.argv = [prog, *args]
    try:
        try:
            rc = main(args) if _takes_argv(main) else main()
        except SystemExit as e:
            return _exit_code(e.code)
        return 0 if rc is None else int(rc)
    finally:
        sys.argv = saved


def _takes_argv(main: Callable[..., object]) -> bool:
    import inspect

    return len(inspect.signature(main).parameters) > 0


def _exit_code(code: object) -> int:
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return 1


def _delegate(command: str, args: list[str]) -> int:
    module_name, _ = DELEGATED[command]
    module = importlib.import_module(module_name)
    return _run_module_main(module.main, f"tashwish {command}", args)


def _has_package(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def doctor(root: Path | None = None, out=None) -> int:
    """Print the state of the environment. Exit 1 when something required is missing, otherwise 0.

    Required: Python version and the core packages. Optional extras, the state/ and processed/ directories and the
    state key are reported as notes, since a reader of the published data needs none of them."""
    out = out or sys.stdout
    root = root or Path.cwd()
    failed = False

    def line(status: str, text: str) -> None:
        print(f"{status:<8}{text}", file=out)

    print(f"tashwish {__version__}", file=out)
    py = sys.version_info
    if (py.major, py.minor) >= MIN_PYTHON:
        line("ok", f"Python {py.major}.{py.minor}.{py.micro}")
    else:
        failed = True
        line(
            "missing", f"Python {py.major}.{py.minor}.{py.micro}, {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is required"
        )

    missing = [p for p in CORE_PACKAGES if not _has_package(p)]
    if missing:
        failed = True
        line("missing", "required packages: " + ", ".join(missing))
    else:
        line("ok", "required packages are installed")

    for extra, packages in EXTRAS.items():
        absent = [p for p in packages if not _has_package(p)]
        if absent:
            line("note", f"extra '{extra}' is not complete, missing: {', '.join(absent)}")
        else:
            line("ok", f"extra '{extra}' is installed")

    for name, purpose in (("state", "frozen baseline for scoring new days"), ("processed", "scored days")):
        if (root / name).is_dir():
            line("ok", f"{name}/ found ({purpose})")
        else:
            line("note", f"{name}/ not found in {root} ({purpose})")

    key = os.environ.get(STATE_KEY_ENV, "")
    if not key:
        line("note", f"{STATE_KEY_ENV} is not set; the incremental command and state refits need it")
    elif len(key) < STATE_KEY_MIN_LENGTH:
        line("note", f"{STATE_KEY_ENV} is set but shorter than {STATE_KEY_MIN_LENGTH} characters, which is too short")
    else:
        line("ok", f"{STATE_KEY_ENV} is set")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tashwish",
        description="Gulf GNSS interference observatory from public ADS-B data. Research and monitoring tool, "
        "not for navigation.",
        epilog="Run 'tashwish <command> --help' for the options of a command.",
    )
    ap.add_argument("--version", action="version", version=f"tashwish {__version__}")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    for name, (_, text) in DELEGATED.items():
        sub.add_parser(name, help=text, add_help=False)
    sub.add_parser("version", help="print the package version")
    d = sub.add_parser("doctor", help="check Python, packages, state/, processed/ and the state key")
    d.add_argument("--root", type=Path, default=None, help="directory that holds state/ and processed/ (default: .)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in DELEGATED:
        return _delegate(args[0], args[1:])
    ap = build_parser()
    try:
        ns = ap.parse_args(args)
    except SystemExit as e:
        return _exit_code(e.code)
    if ns.command == "version":
        print(__version__)
        return 0
    if ns.command == "doctor":
        return doctor(ns.root)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
