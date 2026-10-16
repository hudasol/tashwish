# Operations: the free tier scheduled incremental run

Written 2026-10-12. Scope: how Tashwish keeps its dataset current using only free GitHub features (Actions on a public
repository, a `data` branch for storage, the default `GITHUB_TOKEN`, no other secrets, no paid service).

Rules used in this file:

- "Measured here" means measured by this project in its own build environment (2 cores). **GitHub runners were NOT tested
  by us.** Nothing below about runner speed, runner disk or download speed on GitHub is measured.
- No documentation page could be retrieved when this file was first written (2026-10-12). On 2026-10-16 the official pages
  listed in section 9 were retrieved; every limit marked "retrieved 2026-10-16" below is the figure stated on that page on that
  date, with its URL in section 9. Providers change these figures; check the page again before depending on one.
- Anything we could not determine is marked UNVERIFIED.

## 1. Pieces

| Piece | Path | Role |
|---|---|---|
| Scheduled workflow | `.github/workflows/incremental.yml` | Daily cron plus manual dispatch; runs everything below |
| CI | `.github/workflows/ci.yml` | Lint and tests on pushes to `main` and on pull requests; never touches data |
| Incremental CLI | `python -m tashwish.operate.incremental` | Finds the next missing archive day, streams and parses it, scores it against the frozen baseline in `state/`, appends to `processed/`, writes `processed/freshness.json` |
| Release CLI | `python -m tashwish.release.build` | Builds dashboard JSON (`web/data`), the versioned dataset, data card and checksums (`release/`) |
| Freshness check | `scripts/check_freshness.py` | Prints ok, amber or red from `freshness.json`; exit code 0, 1, 2 (3 if unreadable); also records a failed run |
| Frozen baseline | `state/` on `main` | Changed only by a manual refit (section 7) |
| Output | `data` branch: `processed/`, `web/data/`, `release/` | Written only by the workflow, never by hand, never `main` |

## 2. How a run works end to end

1. Trigger: cron `23 4 * * *` (daily 04:23 UTC, one day per run) or Actions, "Incremental run", "Run workflow" with `max_days` (1 to 3, capped
   at 3, default 1) and optional `start_day` (YYYY-MM-DD). The `concurrency` group `tashwish-incremental` queues a second run instead
   of overlapping, and never cancels a running one.
2. Checkout `main` (code and `state/`) with `persist-credentials: false`, Python 3.13, `pip install -e ".[dev]"`. Nothing large is cached; `actions/cache` is not
   used for archives.
3. Input validation (integer, date format).
4. Guard tests: `tests/test_source.py`, `test_pipeline.py`, `test_trace.py`, `test_quality_config.py`, `test_split.py`,
   `test_check_freshness.py`, plus any `tests/test_operate*.py` and `tests/test_release*.py`. A failure here stops the run before
   any data is touched.
5. A second working tree `dbranch/` is created from `origin/data` (or an empty orphan `data` branch the first time).
6. For each of up to `max_days` slots, one call of the incremental CLI with `--max-days 1` (the first call also gets
   `--start-day` if given, later slots get `--append-status`), then a 120 s pause (`PAUSE_SECONDS`). Sequential only. The CLI streams each day through ranged
   downloads into `$RUNNER_TEMP/spool`, parses, scores, appends to `dbranch/processed`, and the spool is emptied after each day.
7. `release.build` regenerates `dbranch/web/data` and `dbranch/release` from whatever `processed/` now holds, even if a later day
   failed, so days completed before a failure are published.
8. `scripts/check_freshness.py` logs the resulting level.
9. Only if the build step succeeded: if anything under `processed/`, `web/data/` or `release/` changed, commit as
   `github-actions[bot]` and push to `data`. A normal push, never forced. The `GITHUB_TOKEN` is set on the remote in this
   step only (and in the failure handler's push of `freshness.json`); checkout does not store it, so the install and test
   steps never hold a push credential. The release build writes into temporary directories and swaps them in only when every
   file was written, so a failed build leaves the previous `web/data` and `release` intact and exits non zero.
10. If ingest or build failed the job is failed on purpose, and the failure handler runs (section 6). On a fully good run an
    open "Incremental run failed" issue is commented on and closed.

The workflow's job timeout is 240 minutes and the ingest step's is 200 minutes.

## 3. The CLI contract the workflow relies on

```
python -m tashwish.operate.incremental --state state --processed processed --spool "$RUNNER_TEMP/spool" --max-days 1 [--start-day YYYY-MM-DD] [--append-status] [--allow-study-window]
python -m tashwish.release.build --processed processed --web web/data --release release
```

What the workflow additionally requires from the parent implementation (it calls the first CLI with `--max-days 1` in a loop):

1. `--max-days 1` works, and with no `--start-day` the CLI resumes from the first missing day after the days already in
   `processed/`. `--start-day D` means "begin the search at D".
2. Exit code 0 when it processed the days it found **or there was nothing to do** (the next archive day is not published yet is
   not an error; it must exit 0 and say so). Non zero for download failure, parse failure or a baseline mismatch.
3. Each day is appended atomically (temp file then rename), so a crash never leaves `processed/` half written. A re run of a
   finished day is a no op (this already holds for `tashwish.ingest`).
4. It writes `processed/freshness.json` on success (below). On its own failure it should set `last_run_status=failed` and
   `fallback_active=true` before exiting non zero; if it cannot, the workflow does that anyway through
   `check_freshness.py --mark-failed`.
5. It treats `DayNotAvailable` for a day that is not yet published as "stop, nothing to do". A day that is still unpublished
   more than 2 days after it ended (`GAP_GRACE_DAYS`) is a gap: the run fails (exit 1, `failed`, `fallback_active`) so a
   permanently missing day cannot stall the pipeline behind a green job.
   Refusals exit 2 and change nothing: any day inside the study window (`STUDY_START` to `STUDY_END` in `src/tashwish/split.py`)
   unless `--allow-study-window` is passed, and a `--start-day` that leaves a gap after the last processed day. The workflow never
   passes `--allow-study-window`. `latest_day` never moves backwards (reprocessing an older day keeps the newer value). Each
   processed day's `day.json` records `provenance`: code commit (`GITHUB_SHA`, else the local commit), SHA-256 of
   `state/state.json`, and the SHA-256 of that day's ingest manifest record when available.
   `--append-status` (used for slots after the first in one workflow run) keeps `days_added` and does not let a later `noop`
   overwrite an earlier `ok`.
6. `release.build` is idempotent, reads only `--processed`, and writes `generated_at` (UTC) and `latest_day` into
   `web/data/manifest.json` as in `docs/WEB_DATA_CONTRACT.md`. `dataset_version` is `observed-<latest_day>-<8 hex>`, where the hex
   is a content hash of the published cell buckets and events, so a backfill or correction changes it. Event times are rounded
   to the 3 hour bucket (start floored, end ceiled) and destination coordinates are omitted when fewer than 5 aircraft support them.

`processed/freshness.json` (written by the incremental CLI, read by `check_freshness.py`):

```json
{
  "schema": "tashwish.freshness.v1",
  "generated_at": "2026-10-12T03:41:07Z",
  "latest_day": "2026-10-10",
  "last_run_at": "2026-10-12T03:41:07Z",
  "last_run_status": "ok",
  "fallback_active": false,
  "days_added": ["2026-10-08", "2026-10-09", "2026-10-10"],
  "last_error": null
}
```

`last_run_status` is `ok`, `noop` or `failed`. `generated_at` and `latest_day` only move forward on success. A failed run
changes only `last_run_status`, `fallback_active`, `last_run_at` and `last_error`, so the previous good values (and therefore
the dashboard age) stay honest.

## 4. Free tier arithmetic

Measured here (this project's environment, 2 cores, not GitHub runners):

- Archive size per day: about 2.3 GiB (Jan 2026) to about 4.0 GiB (Oct 2026), prod release (docs/DATA_SOURCES.md section 1).
- Parse: about 6 to 9 minutes per day on 2 cores, plus download time (docs/DATA_SOURCES.md section 7 says about 6 minutes
  including download for the study window; the parent's later figure is 6 to 9 minutes of parsing).
- Download is by 64 MiB byte ranges with resume (`src/tashwish/ingest/source.py`), so a cut connection loses at most one range.

Retrieved 2026-10-16 from the GitHub documentation (URLs in section 9):

- Standard GitHub hosted Linux x64 runner for public repositories: 4 CPU, 16 GB RAM, 14 GB SSD (private repositories: 2 CPU,
  8 GB RAM, 14 GB SSD). The 14 GB is the stated SSD size, not measured free space after the runner image.
- Job execution time on GitHub hosted runners: up to 6 hours per job. Workflow run time: up to 35 days.
- Concurrent jobs on the Free plan: 20 on standard GitHub hosted runners.
- Billing: Actions usage is free for public repositories that use standard GitHub hosted runners (GitHub Free includes 2,000
  minutes a month for private repositories).
- In a public repository, scheduled workflows are disabled automatically when no repository activity has occurred in 60 days.

Not measured, UNVERIFIED: free disk actually left on a runner, and download speed from GitHub Releases to a GitHub runner.

Arithmetic, with the stated assumptions (illustrative, not measured on GitHub):

- Disk: one day's spool is at most about 4 GiB, emptied after each day, plus `processed/` parquet and the dataset. Against
  the stated 14 GB SSD that is a margin of about 3x, if most of that SSD is free (free space after the runner image is UNVERIFIED). Only one day is ever on disk, which is why
  days run one at a time.
- Time per day = download (4 GiB / speed) + parse (9 min worst) . At 10 MiB/s: 6.8 + 9 = about 16 min. At 2 MiB/s: 34 + 9 = about
  43 min. Three days plus two 2 min pauses: about 52 min at 10 MiB/s, about 133 min at 2 MiB/s, both under the 200 minute step
  timeout. Break even speed for three days in 200 minutes: (200 - 4) / 3 = 65 min per day, so about 56 min of download, so
  about 1.2 MiB/s. Below that the step times out and the days finished so far are kept.
- Minutes: a 3 day run is about 1 hour, so a daily run of 1 day (about 20 to 45 minutes at the speeds above) is about 10 to 22 hours a month. Free for public repositories on standard
  runners (retrieved 2026-10-16); on a private repository these minutes would count against the 2,000 minute monthly quota.

### What does not fit, exactly

1. **Keeping pace needs 7 days of processing per week.** The archive adds 7 days a week. The previous design (weekly cron, at
   most 3 days per run) processed at most 3 days a week, so the backlog grew by 4 days a week and `latest_day` lagged: the dashboard
   turned amber (over 48 h) and then red (over 7 days) even when every run succeeded. Recommended: **one run per day at an
   off peak minute, at most 1 day per run** (cron `23 4 * * *`, as configured). That is 7 days a week, uses about 1 hour of runner
   time a day at the measured speeds, and a single failed run costs one day that the next run resumes at, because the CLI resumes at
   the first missing day. Three runs a week of 3 days each would also cover 7 days, but delays freshness by up to 2 days; it is not
   recommended. Whether daily downloads of about 4 GiB are polite use of adsb.lol's GitHub releases is
   UNVERIFIED: the adsb.lol historical data page (retrieved 2026-10-16) states no rate limit or fair use rule for `globe_history`
   downloads. The owner should decide, and ideally ask the maintainers (docs/LICENSING.md section 6 lists the questions).
   Backfill limit: each dispatch processes at most `max_days` days (cap 3) and `start_day` applies to the first slot only, so
   backfill is bounded by one to three days per dispatch and each dispatch is a separate run. Backfilling N days needs about N
   divided by `max_days` dispatches, and a `start_day` that leaves a gap after the last processed day is refused. Days inside the
   study window are not backfilled through this workflow at all (they are refused, see section 3 item 5).
2. **The job time limit bounds catch up.** With the 6 hour job limit (retrieved 2026-10-16), a single run cannot clear a long
   backlog. Even ignoring the polite cap of 3, about 12 days at best is the ceiling for one run. A long backlog after the study window is
   cleared by repeated dispatches, not in one run (section 6).
3. **Public repository is required.** Free Actions usage applies to public repositories on standard runners (retrieved
   2026-10-16). A private repository changes the arithmetic.
4. **Scheduled workflows are paused** in a public repository after 60 days without repository activity (retrieved 2026-10-16).
   Whether data commits to the `data` branch count as activity is UNVERIFIED (the page does not say); re enable the workflow by
   hand in the Actions tab if the scheduled runs stop.
5. **Storage growth.** The `data` branch grows with every commit. GitHub warns on files above 50 MiB, blocks files above
   100 MiB, and recommends repositories ideally below 1 GB and strongly below 5 GB (retrieved 2026-10-16). The size of one
   day's parquet and of the released dataset growth over many days has not been measured. If it grows too large,
   attach the versioned dataset to a GitHub Release instead of committing it (still free) and keep only `web/data` on the branch.
6. **Hosting the dashboard.** The dashboard is static (`web/`). Options and what we know:
   - GitHub Pages (retrieved 2026-10-16): published sites at most 1 GB, source repositories recommended at most 1 GB, a soft
     bandwidth limit of 100 GB a month, a soft limit of 10 builds an hour (not applied to custom Actions workflows), a 10 minute
     deployment timeout, and Pages is not to be used as free hosting for an online business.
   - Vercel Hobby (retrieved 2026-10-16): restricted to non commercial, personal use. Do not use it if the project becomes
     commercial.
   - Render (retrieved 2026-10-16): static sites are free to deploy. A free web service (only needed for the optional
     `src/tashwish/api`) spins down after 15 minutes without inbound traffic and takes about one minute to spin up; each
     workspace gets 750 free instance hours a calendar month. Free services count against the workspace's included outbound
     bandwidth, whose size the page does not state (UNVERIFIED). The static JSON dashboard does not need the API.
   - A static site needs no API process at all, which is the free tier recommendation.
7. **Publication lag of the archive was not characterised.** We do not know how long after a UTC day ends adsb.lol publishes its
   release. Nothing in `src/tashwish/ingest/source.py`, its tests or the docs measures it (UNVERIFIED). Until measured, a run
   that finds the next day missing exits as "nothing to do", and the dashboard shows the true age. The first scheduled runs
   should log the day, the release creation time and the age at discovery; this is an open item.

## 5. Freshness: how it is computed and shown

The dashboard (`web/js/common.js`, `freshness()`) reads `manifest.generated_at` and `manifest.latest_day`:

- `genAge` = hours since `generated_at`.
- `dayAge` = hours since the end of `latest_day` (that day 00:00 UTC plus 24 h).
- `age = max(genAge, dayAge)`; **red** if `age > 7 * 24` h, **amber** if `age > 48` h, otherwise ok.
- The banner line shows when the data was generated, how many hours ago, and the latest day, and the amber or red warning text.

`scripts/check_freshness.py` implements the same rule on `processed/freshness.json` (same fields, same thresholds, strictly
greater than) so the workflow log and the dashboard agree. It also prints `last_run_status` and `fallback_active`. A dashboard
badge cannot show "the last run failed" by itself, because it only reads the manifest; a failed run shows up as the age growing,
as the issue, and in `freshness.json`.

Because `latest_day` is a lagging quantity (a UTC day can only be ingested after it ends and is published), "ok" can never mean
less than about 24 h old. With the daily cadence this is about 24 to 48 h in normal operation; see section 4 item 1.

## 6. When a run fails

What happens automatically:

1. The job fails. Days finished before the failure were still built and pushed.
2. `check_freshness.py --mark-failed` sets `last_run_status=failed`, `fallback_active=true`, `last_run_at`, `last_error` in
   `processed/freshness.json` on the `data` branch and pushes it. `generated_at` and `latest_day` are untouched.
3. The last good dataset and `web/data` keep being served from the `data` branch. The dashboard badge turns amber after 48 h and
   red after 7 days of age.
4. One tracking issue titled exactly "Incremental run failed" is opened, or commented on if already open, with the run link,
   the freshness line and the last 60 log lines. A good run closes it.

Manual recovery, from a clone with the dev environment:

```
# 1. read the failed run's log in the Actions tab; the log tail is also in the issue
# 2. reproduce one day locally into a scratch spool (needs about 4 GiB free; sequential, polite)
git fetch origin data && git worktree add ../tashwish-data origin/data
python -m tashwish.operate.incremental --state state --processed ../tashwish-data/processed --spool /tmp/spool --max-days 1
python -m tashwish.release.build --processed ../tashwish-data/processed --web ../tashwish-data/web/data --release ../tashwish-data/release
python scripts/check_freshness.py ../tashwish-data/processed/freshness.json
# 3. publish only after the check prints ok or a level you accept
cd ../tashwish-data && git checkout -B data origin/data && git add processed web/data release && git commit -m "data: manual recovery" && git push origin data
# 4. or simply re-run in the cloud: Actions > Incremental run > Run workflow (max_days 1)
```

Backfill: dispatch the workflow with `start_day` set to the first missing day (or leave it empty to resume) and `max_days` 3,
repeat until the dashboard reads ok. Days are idempotent, so overlapping a finished day is harmless, and `latest_day` does not
move backwards. The study window (2026-02-07 to 2026-03-13) is not backfilled this way: the CLI refuses those days, because
held out days must be scored once by the validation harness before they are published. Pass `--allow-study-window` locally only
for a deliberate, documented exception.

If the source is unreachable (timeouts, 5xx, 403): do not retry in a tight loop. The CLI retries per range with a backoff
(`src/tashwish/ingest/source.py`); after that the run fails and waits for the next trigger. Check
`https://github.com/adsblol/globe_history_2026/releases` by hand. Do not add mirrors or proxies; if the archive is gone, the
documented fallback is OpenSky (docs/DATA_SOURCES.md section 2), which needs an approved research account and is a separate
piece of work.

If the release naming changes: the URL pattern is the single `_URL` in `src/tashwish/ingest/source.py`
(`v{YYYY.MM.DD}-planes-readsb-{prod|staging}-0.tar.{aa,ab,...}`, repository `globe_history_{year}`). A naming change shows up as
`DayNotAvailable` for days that exist in the browser. Fix `_URL`/`KINDS`, update `tests/test_source.py`, and re run. Compare the
result with an already ingested day before trusting it (row counts per cell).

User agent: `HttpxFetcher` previously sent httpx's default agent. It now sends
`tashwish/0.1 (+https://github.com/hudasol/tashwish; research, sequential ranged downloads)` (`USER_AGENT` in
`src/tashwish/ingest/source.py`), so the maintainers can identify and contact us.

## 7. Baseline refit policy

The baseline in `state/` is frozen: scoring a new day never changes it, which keeps the dataset comparable over time and the
held out evaluation honest. Refit manually, on a branch of `main`, when either:

- every N weeks (suggested N = 12, a project choice, not derived), or
- after a coverage step change: the receiver network visibly changed (a drop or jump in `coverage.json` presence, a new feeder
  region, or many `coverage_lost` cells). Look at the coverage layer on the dashboard first.

Commands (the refit CLI is not part of this contract; the parent should provide one, here called `tashwish.operate.refit`):

```
python -m tashwish.operate.refit --processed ../tashwish-data/processed --state state --window-days 21 --write
git checkout -b refit-YYYY-MM-DD && git add state && git commit -m "state: refit baseline" && open a pull request
```

After merging, bump the dataset version so consumers know scores before and after are not comparable, and note it in the data
card. Do not refit from the scheduled workflow.

## 8. CI and the README badge

`ci.yml` runs ruff (check and format) and pytest with coverage on Python 3.11 and 3.13, with read only permissions, a 20 minute
timeout and cancellation of superseded runs. At the time of writing, `ruff check .` and `ruff format --check .` report errors
in `web/scripts/*.py`, `src/tashwish/api/app.py` and `tests/test_api.py`, so CI would fail until `ruff check . --fix` and
`ruff format .` are run and the remaining findings fixed. This was not touched here to avoid editing files other work is changing.

Badge snippets to paste into the README when the owner wants them (replace nothing; the owner and repo are `hudasol/tashwish`):

```
[![CI](https://github.com/hudasol/tashwish/actions/workflows/ci.yml/badge.svg)](https://github.com/hudasol/tashwish/actions/workflows/ci.yml)
[![Incremental run](https://github.com/hudasol/tashwish/actions/workflows/incremental.yml/badge.svg)](https://github.com/hudasol/tashwish/actions/workflows/incremental.yml)
```

## 9. Sources for the limits (retrieved 2026-10-16)

Each page below was retrieved on 2026-10-16 and the figures in sections 4 and 6 come from it. "Not retrieved" means the page was
not read in that session and anything that depends on it stays UNVERIFIED.

| Claim | Page | Status |
|---|---|---|
| Job and workflow time limits, concurrency | https://docs.github.com/en/actions/reference/limits | retrieved 2026-10-16 |
| Runner CPU, RAM, SSD | https://docs.github.com/en/actions/reference/runners/github-hosted-runners | retrieved 2026-10-16 |
| Free minutes for public repositories | https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions | retrieved 2026-10-16 |
| Disabling of scheduled workflows after inactivity | https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/disabling-and-enabling-a-workflow | retrieved 2026-10-16 |
| Repository and file size limits for the `data` branch | https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github | retrieved 2026-10-16 |
| GitHub Pages limits and acceptable use | https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits | retrieved 2026-10-16 |
| GitHub terms for additional products | https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features | not retrieved, UNVERIFIED |
| Usage limits, billing and administration | https://docs.github.com/en/actions/administering-github-actions/usage-limits-billing-and-administration | not retrieved, UNVERIFIED |
| Vercel Hobby non commercial restriction | https://vercel.com/docs/plans/hobby | retrieved 2026-10-16 |
| Render free web service sleep, spin up and monthly hours | https://render.com/docs/free | retrieved 2026-10-16 |
| adsb.lol fair use or rate guidance for the archive | https://www.adsb.lol/docs/open-data/historical/ | retrieved 2026-10-16; states no rule, so fair use stays UNVERIFIED (ask the maintainers) |
| Archive publication lag after a UTC day ends | not documented anywhere we read | UNVERIFIED; measure it from release creation times |

### Additional UNVERIFIED items on this free tier (kept unverified)

- None of the retrieved limits was tested on a real runner; free disk after the runner image and download speed to a runner are
  not measured.
- Whether a workflow that only pushes to the `data` branch counts as repository activity for the scheduling rule.
- Whether `GITHUB_TOKEN` pushes to `data` are allowed by the repository's default workflow permission setting (it can be set to
  read only at repository level; the owner must check Settings, Actions, General).
- Whether the archive publishes a day soon enough for the 04:23 UTC run to find it (publication lag is not characterised). A day
  not yet published is a noop; a day missing for more than 2 days fails the run.
- No workflow linter (such as actionlint) is run in CI: it needs a download of an external binary and was not checked here.
