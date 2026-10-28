# Changelog

All notable changes to this project are recorded in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The package version is set in
`src/tashwish/__init__.py`. Entries below were written from the git history. The git tags `v0.0.1` to `v0.3.0` mark early
milestones made on 2026-10-11; the package itself still reported version 0.1.0 until the change listed under Unreleased.

## [Unreleased]

The package version is now 0.9.0, a release candidate for the study dataset. It is not a 1.0 release.

### Added

- The `tashwish` command with the subcommands `ingest`, `incremental`, `build`, `validate`, `api`, `version` and `doctor`.
  The first five hand their arguments to the existing modules unchanged. `doctor` checks the Python version, packages,
  optional extras, `state/`, `processed/` and whether `TASHWISH_STATE_KEY` is set, without printing it.
- `py.typed` marker and package data, so that the package is recognised as typed.
- `.gitattributes` setting LF line endings and marking Parquet, gzip and image files as binary.
- A test that parses `src/` and `scripts/` and fails when text input or output does not name its encoding and newline.
- `requirements-dev.lock`, pinned versions of the dependencies for the `api` and `dev` extras.
- `Makefile` with the targets `install`, `install-locked`, `test`, `lint`, `format`, `build-release`, `serve-web`,
  `serve-api` and `clean`.
- `Dockerfile` and `.dockerignore` for the read only API.
- `.pre-commit-config.yaml` with ruff, ruff format, end of file and trailing whitespace hooks.
- CI on Ubuntu and Windows with Python 3.11, 3.12 and 3.13, including a coverage summary.
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue templates and a pull request template.
- Forward scorer (`scripts/score_forward.py`) and its development day calibration, for the preregistered forward
  evaluation of 2026-03-14 to 2026-04-12. The forward evaluation itself was preregistered before any forward day was
  downloaded.
- Beta binomial sensitivity analysis of jamming-like flags on development days, and the secondary analyses page.
- Held out evaluation, run once against a frozen state, with generated results documents, processed days, release and
  dashboard data.
- Regime aware baselines, background avoiding scenario placement and a regime panel in the dashboard.
- Frozen state, refit, incremental run, release builder and freshness check, with tests.
- Validation harness with synthetic injection, coverage and sensitivity tests, and the read only API.
- Static bilingual dashboard (English and Arabic) with synthetic sample data, accessibility work and exportable images
  that carry the attribution.
- Spoofing-like detector based on ADS-B position jumps with destination clustering, the jamming and spoofing combiner and
  pipeline orchestration.
- Interoperability definitions for Marsad (context file) and Sirb (GNSS degradation parameters), with synthetic and
  draft samples.
- Jamming-like detector with a baseline share per cell, a binomial test, Benjamini and Yekutieli false discovery rate
  control, a Wilson interval gate and event merging.
- Preregistration of the held out split rule and predictions, the study window, and a resumable ingest runner.
- Vendored ODbL 1.0 text, a single source for the attribution string, a licence compliance audit and a web data contract.

### Changed

- The version is read from `tashwish.__version__` by `pyproject.toml` instead of being repeated in both places.
- The synthetic Marsad sample was regenerated for the new version. Only its `tashwish_version` field differs.
- The CI workflow runs on Windows and Python 3.12 in addition to the earlier Ubuntu jobs.
- Persistent low emitters are stored as keyed hashes under `TASHWISH_STATE_KEY`.
- Test fixtures were replaced by anonymised excerpts of the source data.
- Statements in documents were updated after the verification of 2026-10-16, and recalled free tier limits were replaced
  by figures from the official pages.
- Study records (`RESEARCH`, `VALIDATION`, `PREDICTIONS_RESULTS`, `REPORT`, `REVIEW_ROUNDS`, `OVERNIGHT_LOG`,
  `SECONDARY_ANALYSES`, `PROPOSAL`) moved to `docs/research/`, and `NEXT_STEPS.md` became `docs/ROADMAP.md`. The document
  generators write to the new paths. `docs/README.md` indexes the documents.
- The README was rewritten as a project overview. The generated status block is unchanged apart from its links.

### Fixed

- Text files written by the release builder, ingest, state, interop and script modules used the platform default
  encoding and line endings, so output differed on Windows. They now use UTF-8 and LF explicitly.
- `match_scenario` when only one detector fired.
- The coverage test now reports the final status of covered units that failed.
- Incremental run: days inside the study window are refused unless explicitly allowed, gaps before the start day are
  refused, `latest_day` never moves backwards, and permanently missing days fail the run.
- Release builder: web data and release are swapped in atomically, the dataset version includes a content hash, event
  times are rounded to the 3 hour bucket, destination coordinates are withheld below 5 aircraft, and non observed data
  is refused instead of relabelled.
- API: `X-Forwarded-For` is ignored unless `TASHWISH_TRUSTED_PROXY_HOPS` is set, the rate limiter is bounded, and the
  ETag includes a hash of the manifest checksums.
- Spoofing-like detector: time difference floor and exclusion of multilateration positions.
- Forward scorer: it pins the frozen state, runs once, and rejects days that were not observed or were ingested before
  the preregistration.

### Removed

- `src/tashwish.egg-info` is no longer tracked.

## [v0.3.0] - 2026-10-11

### Added

- Loader, feasibility analysis and an empirical coverage model with leave one day out evaluation, with tests.

## [v0.2.0] - 2026-10-11

### Added

- Statistics core and per cell aggregation with Wilson intervals, strata and a sufficiency status.

## [v0.1.0] - 2026-10-11

### Added

- Resumable ranged download, trace parser, schema checked Parquet pipeline and quality report for the ingest.

## [v0.0.1] - 2026-10-11

### Added

- Research notes, data sources, plan, README and licence.

[Unreleased]: https://github.com/hudasol/tashwish/compare/v0.3.0...HEAD
[v0.3.0]: https://github.com/hudasol/tashwish/compare/v0.2.0...v0.3.0
[v0.2.0]: https://github.com/hudasol/tashwish/compare/v0.1.0...v0.2.0
[v0.1.0]: https://github.com/hudasol/tashwish/compare/v0.0.1...v0.1.0
[v0.0.1]: https://github.com/hudasol/tashwish/releases/tag/v0.0.1
