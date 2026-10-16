# Overnight log, 2026-10-16

A record of one unattended working session: what was done, what was found and what failed, in the order the work was done.
Research and monitoring tool. Not for navigation or safety of life. Nothing here attributes interference to any state or actor.

Rules followed throughout: the study window held out days stay closed (the held out validation was not run again), no frozen
threshold or detector behaviour was changed, no raw ADS-B archive was written to git, and every result number cited here is in a
committed result file named next to it.

## A. Orientation

Done.

- Branch base: `phase5/review-fixes` (pull request 2, still open at the start of the session). The work of this session is on
  feature branches stacked on it.
- Tests: on this Windows machine, `python -m pytest -p no:warnings` gives 291 passed and 6 failed. All 6 failures are in
  `tests/test_release_build.py` and have one cause: `src/tashwish/release/build.py` reads a JSON file with `read_text()` and no
  encoding, so Python uses the Windows default code page and fails on a UTF-8 byte. With Python's UTF-8 mode
  (`PYTHONUTF8=1`) all 297 tests pass. CI runs on Linux, where UTF-8 is the default. The builder was not changed here (rule:
  only the changes the task needs); every later test run in this log uses `PYTHONUTF8=1`. `ruff check .` passes.
- Archive access: the adsb.lol `globe_history_2026` release asset for 2026-03-13 answered a HEAD request with status 200. A day
  inside the study window, already processed, was used on purpose, so that nothing about any day after 2026-03-13 was seen before
  the forward preregistration (item B) was committed.
- `TASHWISH_STATE_KEY` is not set in this environment (checked for the process, the user and the machine scope; the value was
  never printed). The frozen scoring path (`score_day_frozen` in `src/tashwish/operate/state.py`) keys aircraft addresses with
  this secret to match the persistent emitter list, and raises without it.

Consequences:

- Item C (backfill) is skipped, as instructed.
- Item D (forward chained validation) is blocked. Scoring new days against the frozen state needs the key. Rebuilding the
  persistent emitter list another way would be a workaround of the secret, so it was not done. What was done instead is to make
  D ready to run: the forward preregistration (item B) and the forward scorer are committed before any new day was downloaded,
  so the maintainer can run C and D as soon as the key is set (see item D below).

## B. Forward preregistration

Done, before any new data was looked at.

- `docs/PREDICTIONS_FORWARD.md` and its machine readable copy `results/forward/predictions_forward.json` (commit `7deb3f8`)
  preregister twelve predictions for the 30 days 2026-03-14 to 2026-04-12: regime persistence (F1 to F6), false coverage by
  traffic regime (F7, F8) and events per day (F9 to F12), each with a numeric pass criterion and a stated probability, plus three
  daily checks that locate where the forward run fails first.
- `scripts/score_forward.py` (commit `8ddabc6`) is the scorer, written before the data. It refuses study window days, rejects
  days not scored with the committed frozen state, and writes HIT or MISS with intervals, the Brier score and the first failing day.
  Its `calibrate` command wrote `results/forward/dev_calibration.json` from the 21 development days only. As a check of the
  scorer, its recomputed regime labels, en route units and tested degraded shares equal `results/regimes.csv` on all 21
  development days, and its per day false coverage equals the per day values in `results/dev/observed_coverage_summary.json`.
- Tests: 300 passed (`PYTHONUTF8=1`), including 3 new tests in `tests/test_score_forward.py` on synthetic days. `ruff check`
  and `ruff format --check` pass.
- Limitation: the predictions were written after the held out summaries of the study window were published in this repository,
  so they are informed by all 35 study days, not only by the development days. They are blind to every day after 2026-03-13.
