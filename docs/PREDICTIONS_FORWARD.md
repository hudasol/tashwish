# Forward evaluation: preregistered predictions

Research and monitoring tool. Not for navigation or safety of life. Nothing here attributes interference to any state or actor.

This file is committed BEFORE any day after 2026-03-13 was downloaded, parsed or scored. Its git history, and the commit time of
this file compared with the `ingested_at` time in each forward day's `day.json`, are the evidence for that order. The machine
readable copy that the scorer reads is `results/forward/predictions_forward.json`; a test checks that the two agree. Editing
either file after the first forward day is processed invalidates the evaluation, and git history would show it.

## 1. Why a forward evaluation

The held out days of the study window interleave with the development days inside a series that changes over time
(`docs/VALIDATION.md`, section 1, caveat 2). They were never used for fitting, but they are not later in time than the fitting
days. This evaluation scores days that come strictly after every day used to build the frozen state, so it tests whether what was
learned in February and March still describes the data afterwards.

## 2. Design

- **Block.** The 30 UTC days 2026-03-14 to 2026-04-12. These are exactly the first 30 days the incremental pipeline processes
  when it starts from an empty processed folder, because it resumes after `baseline_end` (2026-03-13) in `state/state.json`.
- **System.** Unchanged. Each day is scored by `python -m tashwish.operate.incremental` with the frozen state in `state/`
  (fitted on development days only). No refit, no threshold change, no change to the detectors. The scorer accepts only days
  whose `day.json` says `mode` `frozen_baseline` and whose recorded `state_sha256` equals the SHA-256 of the committed
  `state/state.json`; other days are listed as rejected, not scored.
- **Scorer.** `scripts/score_forward.py score`, committed with this file and tested on synthetic days only. It reads processed
  outputs and the frozen state, recomputes the two regime labels with the frozen rules of `src/tashwish/regime.py`, and writes
  `results/forward/forward_scored.json` and `docs/FORWARD_RESULTS.md`. It refuses any day inside the study window, so it cannot
  score a held out day.
- **Data class.** Every measure is OBSERVED: real days, nothing injected.
- **Missing days.** A day that is not published, fails to process or is rejected is listed, never imputed. The incremental run
  processes days in order, so the scored days are a contiguous run from 2026-03-14.
- **Evaluability.** A prediction over all days needs at least 20 scored days. A prediction over one regime needs at least 3
  scored days in that regime. F2 needs at least 5 scored days in 2026-03-14 to 2026-03-20. F12 also needs at least 5
  spoofing-like events. Otherwise the verdict is NOT EVALUABLE, which is neither a hit nor a miss.
- **Verdict.** HIT or MISS is decided on the point value. Intervals are reported next to it: a day bootstrap (2000 resamples of
  whole days within the subset, seed 20260314) for rates and means, and a Wilson interval on day counts for shares of days, which
  is descriptive only because consecutive days are not independent. F6 is a count and has no interval.
- **Brier score.** The mean of (stated probability minus outcome) squared over evaluable predictions, outcome 1 for HIT and 0 for
  MISS. A constant forecast of 0.5 scores 0.25. The predictions are correlated (F1, F3, F4 and F10 move together), so the Brier
  score is not an average over independent events.
- **Run once.** The scorer is run on the first complete processing of the block and its output is committed whatever it says.
  Misses are reported before hits.

## 3. What the predictions were anchored on

Only development days and results already published in this repository: the per day measures of the 21 development days
(`results/forward/dev_calibration.json`, produced by `scripts/score_forward.py calibrate`, held out days not read), and the
held out summaries already in `docs/VALIDATION.md` and `results/regimes.csv`. No source about events after 2026-03-13 (news,
notices, other maps) was consulted before this file was committed; the regime change investigation of this session (item E3 of
`docs/OVERNIGHT_LOG.md`) was done afterwards.

What the anchors say, in words: on development days the reduced traffic regime and the elevated degraded regime occurred on the
same days, the tested degraded share rose through early March, false coverage was low on normal traffic days and several times
higher on reduced traffic days with a rising tendency, and events were rare, with jamming-like events muted on elevated days by
construction (`docs/METHODOLOGY.md`, Regimes).

## 4. Predictions

Probability is my stated probability that the prediction is a HIT. The threshold columns are design choices written before the
data, not estimates.

| ID | Prediction | Measure | Days | Pass criterion | Probability |
|---|---|---|---|---|---|
| F1 | The elevated degraded regime persists | share of scored days labelled degraded elevated | all | at least 0.80 | 0.55 |
| F2 | No return to the baseline regime in the first week | share of scored days labelled degraded elevated | 2026-03-14 to 2026-03-20 | equal to 1 (every day) | 0.75 |
| F3 | The reduced traffic regime persists | share of scored days labelled traffic reduced | all | at least 0.80 | 0.55 |
| F4 | The two regime labels stay coupled | share of scored days on which traffic is reduced exactly when degraded is elevated | all | at least 0.90 | 0.65 |
| F5 | The tested degraded share stays in the March range | median tested degraded share | degraded elevated days | from 0.10 to 0.45 | 0.60 |
| F6 | The degraded label rarely switches | number of changes of the degraded label between consecutive scored days | all | at most 2 | 0.60 |
| F7 | False coverage on reduced traffic days stays high but bounded | pooled false coverage rate (covered en route units with fewer than 5 aircraft) | traffic reduced days | from 0.20 to 0.55 | 0.55 |
| F8 | False coverage on normal traffic days stays low | pooled false coverage rate | traffic normal days | at most 0.10 | 0.70 |
| F9 | Few events per day | mean events per scored day, all kinds and confidences | all | at most 2.0 | 0.60 |
| F10 | Few jamming-like events on elevated days | mean events of kind jamming_like or both per day | degraded elevated days | at most 0.5 | 0.65 |
| F11 | Few events on baseline days | mean events per day | degraded baseline days | at most 0.5 | 0.60 |
| F12 | Most spoofing-like events carry an uncertain label | share of events of kind spoofing_like or both with an uncertain label | all | at least 0.50 | 0.75 |

How the regime predictions read together: F1 and F3 say the March regime persists; F2 says it does not end at once; F4 and F6 say
the change is a step, not a flicker. If the data return to the February regime, F1, F2 and F3 miss and F8 and F11 become
evaluable. If the data vary, F6 misses.

## 5. Where it fails first

Besides the block level verdicts, the scorer reports, in date order, the first scored day on which each daily check fails:

| Daily check | Passes on a day when |
|---|---|
| label_pair | the day is labelled traffic reduced and degraded elevated |
| false_coverage | the day's false coverage rate is at most 0.55 on a reduced traffic day, or at most 0.10 on a normal traffic day |
| events | the day has at most 4 events (the largest daily count on development days) |

## 6. How to run it (needs the maintainer)

The incremental run needs the `TASHWISH_STATE_KEY` secret, which is not available to the session that wrote this file.

```
# set TASHWISH_STATE_KEY in the environment first (never commit or print it)
python -m tashwish.operate.incremental --state state --processed <processed folder> --spool <scratch folder> --max-days 1
# repeat until 2026-04-12 is processed, or dispatch the scheduled workflow, which writes to the data branch
python scripts/score_forward.py score --processed <processed folder>
```

Commit `results/forward/forward_scored.json` and `docs/FORWARD_RESULTS.md` as produced, together with the per day rows,
aircraft and run time recorded by the run.
