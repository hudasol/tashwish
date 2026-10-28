# Contributing

Thank you for your interest in Tashwish. This file describes how to set up a development environment, how to check a
change before sending it, and what the project asks of contributions.

Tashwish reports observations of jamming-like and spoofing-like anomalies in public ADS-B data. It does not attribute
interference to any actor, and it is not a navigation or safety of life tool. Changes should keep it that way.

## Getting started

You need Python 3.11 or newer and git.

```
git clone https://github.com/hudasol/tashwish.git
cd tashwish
python -m venv .venv
```

Activate the environment (`source .venv/bin/activate` on Linux and macOS, `.venv\Scripts\Activate.ps1` in PowerShell),
then install the package with the API and development extras:

```
python -m pip install -e ".[api,dev]"
```

Check the installation with:

```
tashwish doctor
```

## Pinned development environment

`requirements-dev.lock` lists the exact versions of every direct and transitive dependency of the package and its `api`
and `dev` extras, as resolved on Linux with Python 3.13. It needs Python 3.12 or newer, because the pinned numpy and
scipy releases do not support 3.11. To install with those versions:

```
python -m pip install -c requirements-dev.lock -e ".[api,dev]"
```

Continuous integration does not use the lock. It installs the version ranges from `pyproject.toml`, so that the supported
Python versions and the lower bounds are tested as well.

To regenerate the lock, create a clean virtual environment, install `.[api,dev]` without constraints, and record the
installed distributions that belong to the dependency closure of the package. Do not use a plain `pip freeze` of an
environment that holds other tools, because unrelated packages would be pinned too. Review the diff and run the full test
suite before committing a new lock.

## Checking a change

```
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

`make test`, `make lint` and `make format` run the same commands on Linux and macOS. On Windows, run the `python -m`
commands directly. The other make targets are `install`, `install-locked`, `build-release`, `serve-web`, `serve-api` and
`clean`; each one is a single `python -m` command that you can copy from the `Makefile`.

To run the hooks automatically before each commit, install `pre-commit` and enable it once with
`pre-commit install`. The hooks are ruff, ruff format, a final newline check and a trailing whitespace check.

## The command line

The `tashwish` command is a thin front end for the existing modules:

| Command | Runs |
|---|---|
| `tashwish ingest` | `python -m tashwish.ingest` |
| `tashwish incremental` | `python -m tashwish.operate.incremental` |
| `tashwish build` | `python -m tashwish.release.build` |
| `tashwish validate` | `python -m tashwish.validate.run` |
| `tashwish api` | `python -m tashwish.api` |
| `tashwish version` | prints the package version |
| `tashwish doctor` | checks Python, packages, `state/`, `processed/` and whether `TASHWISH_STATE_KEY` is set |

Arguments after the command name are passed on unchanged, so `tashwish build --help` shows the options of the release
builder. The release builder and the validation runner locate the repository from the position of their source files, so
run them from a source checkout with an editable install, not from a copy installed into site packages.

## Text files and line endings

Text files are written as UTF-8 with LF line endings on every platform, so that generated files and checksums are
identical on Linux and Windows. In practice:

- Pass `encoding="utf-8"` to `open`, `Path.read_text` and `Path.write_text`.
- Pass `newline="\n"` when writing text, and `lineterminator="\n"` to `DataFrame.to_csv`.
- Do not rely on the default encoding of the platform.

`tests/test_text_io.py` parses `src/`, `scripts/` and `tests/` and fails when a call lacks these arguments. `.gitattributes` sets
`eol=lf` and marks Parquet, gzip and image files as binary.

## Data, state and secrets

- `processed/`, `state/`, `results/`, `release/` and `web/data/` hold generated or frozen content. Do not edit them by hand.
  Regenerate them with the commands described in `docs/OPERATIONS.md`, and explain why in the pull request.
- The input data contain no aircraft identifiers, and no change may add them to any file in the repository.
- `TASHWISH_STATE_KEY` is a secret. Never write it into a file, a log, an issue or a pull request. The incremental workflow
  reads it from a repository secret.
- A change to detector behaviour, thresholds or the validation protocol changes published numbers. Say so in the pull
  request, and regenerate the affected result files in the same pull request.

## Commits and pull requests

- Make small commits with one logical change each. The message should say what changed and why.
- Open a pull request against `main` and fill in the template. Describe how you checked the change.
- Keep pull requests focused. Unrelated clean up belongs in a separate pull request.
- Add or update tests for behaviour you change. Tests must not need network access.
- Public text is written in plain, formal English. Report what the data shows and state what was not verified.

## Reporting problems

Use the issue templates for bugs, data quality reports and feature requests. Report security problems as described in
`SECURITY.md`, not in a public issue.

## Licence

By contributing you agree that your contribution is released under the Apache License 2.0 that covers the code
(see `LICENSE`). Derived data files are under the ODbL 1.0 (see `NOTICE`).
