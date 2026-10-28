## Summary

What changed, and why.

## How it was checked

- [ ] `python -m pytest` passes
- [ ] `python -m ruff check .` and `python -m ruff format --check .` pass
- [ ] New or changed behaviour has tests

## Notes for the reviewer

- [ ] Detector behaviour, thresholds or published numbers are unchanged, or the affected result files are regenerated in this pull request
- [ ] No generated data (`processed/`, `state/`, `results/`, `release/`, `web/data/`) was edited by hand
- [ ] No secrets, aircraft identifiers or personal data are added
- [ ] Text files are written as UTF-8 with LF line endings
- [ ] Documentation and `CHANGELOG.md` are updated where needed
