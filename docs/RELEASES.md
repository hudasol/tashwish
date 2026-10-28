# Releases

This document describes how a release of the software and of the dataset is prepared. Tags and GitHub Releases are created by the
maintainer on the GitHub Releases page; no automated job creates them. The Zenodo steps are in [ZENODO.md](ZENODO.md).

## Three version numbers

- **Software version.** Set once in `src/tashwish/__init__.py` (`__version__`); `pyproject.toml` reads it from there. The current value
  is 0.9.0, a release candidate for the study dataset, not a 1.0 release.
- **Dataset version.** Written by `python -m tashwish.release.build` as `dataset_version` in `release/manifest.json`. It has the form
  `observed-<latest day>-<8 characters of a content hash>`, so it changes when the released rows change, not when the code changes.
- **Citation metadata.** `CITATION.cff` carries the software version in `version`. It carries no release date until a release
  has been published, because a date for an unpublished release would be untrue. Its `doi` field is added only after Zenodo issues one.

`CHANGELOG.md` records each software version. The section `Unreleased` becomes a dated section with the version number when the
tag is created.

## Checklist

1. Start from the branch to be released, with a clean working tree and `main` merged into it.
2. Run `pytest -p no:warnings`, `ruff check .` and `ruff format --check .`; all must pass.
3. Confirm that `__version__` in `src/tashwish/__init__.py` is the intended version and that `CITATION.cff` carries the same `version`.
4. Rebuild the generated documents with the scripts named in [README.md](README.md) and check that no result file changed unexpectedly.
5. Rebuild `release/` with `python -m tashwish.release.build`, check `checksums.sha256` and read `release/manifest.json`
   (`dataset_version`, `code_commit`, days covered).
6. In `CHANGELOG.md`, rename `Unreleased` to the version and the date of the release, and start a new empty `Unreleased` section.
7. In `CITATION.cff`, set `date-released` to the date of the release. Commit and push.
8. On the GitHub Releases page choose **Draft a new release**, choose **Create new tag on publish**, name the tag `v<version>`
   (for example `v0.9.0`), select the commit from step 7, copy the changelog section into the notes, and publish.
9. Upload the dataset to Zenodo following [ZENODO.md](ZENODO.md), using the `dataset_version` from step 5, then add the DOI to
   `CITATION.cff` and the README in a later commit.

## Tags

The tags `v0.0.1` to `v0.3.0` mark early milestones made on 2026-10-11. They are not moved or deleted. A tag is never reused for another commit.
