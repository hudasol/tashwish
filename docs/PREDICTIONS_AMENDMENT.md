# Amendment to the preregistered predictions

`docs/PREDICTIONS.md` is unchanged. This file is committed BEFORE the held out run. It records what changed after the
predictions were written and how each prediction will be evaluated. The git history of both files is part of the evidence.

## 1. What was learned on development days after the predictions were written

- From 2026-03-02 the share of degraded en route reports rises from about 1 percent to above 10 percent, and traffic falls to
  roughly a third of its earlier level (`results/dev/regime_check.json`; `docs/VALIDATION.md`). For the same
  aircraft the degraded sample share rose, so this is not only a different mix of aircraft. The cause is not known and no cause
  is asserted.
- A single baseline pooled across this change cannot be right on both sides: for the 1,237 aircraft seen in both periods the
  share of degraded samples was 0.011 early and 0.352 late (`same_aircraft_sample_share_early` and
  `same_aircraft_sample_share_late` in `results/dev/regime_check.json`). An earlier version of this file quoted per cell baseline
  medians (0.02, 0.41 and 0.03) from a review; no committed result file reproduces them, so they are removed. The statement in
  the original code comments that contamination only makes the detector more conservative was false across a regime change and
  has been corrected.

## 2. Changes to the system made before the freeze (development days only)

1. Regime aware baselines (`src/tashwish/regime.py`). Two mechanical labels are computed from aggregate counts of the scored day:
   traffic `normal` or `reduced` (fewer than half the reference en route aircraft per cell bucket; the reference is the median
   of development days), and degraded `baseline` or `elevated` (region wide tested degraded share below or at least 0.05). The
   coverage model is fitted on development days with the same traffic label, and the per cell baseline share on development days
   with the same degraded label, always excluding the scored day. No held out day is ever used for fitting.
2. Validation scenarios are no longer placed within one ring and one bucket of a real flag found on the uninjected day, so a
   merge with a real event cannot be credited as a detection.
3. Spoofing scenarios now vary the scatter of displaced aircraft (1.5, 6 and 15 km), where before it was always 1.5 km.
4. Run once guard hardened: the held out run requires a clean tree at the frozen commit, writes a `RUNNING` marker at start,
   refuses a second start, takes no `--max-days` and no other output folder; replacing a freeze needs a recorded reason.
5. The persistent emitter list in the frozen state is keyed with a secret (HMAC), not hashed with a public salt.

## 3. How the original predictions will be evaluated (mapping, not edits)

- C1 to C3: reported pooled, as worded, and also per traffic regime, with the day bootstrap interval as the headline interval.
  A pooled unit level Wilson interval is not used as an uncertainty statement because units are not independent.
- C4: unchanged, with the caveat that a covered unit is `coverage_lost` only when too few aircraft appear now, which makes the
  test close to tautological.
- J1 to J3: as worded; J3 is reported on all scenarios (as worded) and on testable scenarios (median target traffic of at least
  5 aircraft) because many hard scenarios cannot be tested by construction. The pass or fail verdict uses the wording of
  PREDICTIONS.md (all scenarios).
- J4: first bucket detection rate; delay is measured from the first affected bucket on a bucket grid, so it is clipped at zero.
- J5: reported as the real event rate of medium or high confidence events per held out day (these are not necessarily false).
- J6: as worded when every cell has at least 10 scenarios; otherwise reported as not evaluable, with pooled marginals shown.
- S2, S3 and the committed label accuracy of S4 are pipeline separation checks: the injections change only one input of one
  detector each, so these results are close to true by construction and are not evidence of discrimination in real data.
- R2 to R4: reported pooled and by degraded regime. Report days are context only.
- Bootstrap intervals resample whole days within regime where a regime has at least 3 days.

## 4. Additional predictions, written before the held out run

Confidence is my probability that the prediction passes. The held out regime and event results have not been looked at.

| ID | Prediction | Pass criterion | Confidence |
|---|---|---|---|
| A1 | The regime labels follow the calendar seen in development | held out days 2026-02-07 to 2026-02-26 are all labelled traffic normal and degraded baseline; 2026-03-03, 03-08, 03-10 and 03-13 are all labelled traffic reduced and degraded elevated. 02-28 and 03-01 are not predicted. | 0.70 |
| A2 | Within regime, covered cells rarely lack data | false coverage rate (class covered, fewer than 5 aircraft) at most 0.10 in each traffic regime on held out days, by the day bootstrap point estimate | 0.60 |
| A3 | Few events on degraded baseline days | medium or high confidence events per held out day with degraded label baseline: at most 0.5 on average | 0.50 |
| A4 | Scenario recall is not lowered by the new placement rule | easy tier jamming recall on held out days at least 0.90 | 0.75 |

## 5. Disclosures about what was seen

- The ingest log and manifest showed row and aircraft counts for held out days 2026-02-07, 02-10, 02-11, 02-12, 02-15 and 02-18
  (normal volume, about 1.65 to 1.8 million rows and 2,040 to 2,170 aircraft). Download sizes were shown for the other held out
  days. D1 and D2 are therefore not blind for those days.
- No degraded share, event or coverage result for any held out day has been computed or read.
- A1 and A2 were written after the download sizes of held out days 2026-03-03 to 2026-03-13 were visible, so they are informed
  guesses, not blind predictions.
- Independent reviews of methods and statistics, honesty, and code (rounds 1 to 3, by separate agents with no access to held out
  results) ran before the freeze. Rounds 4 and 5 (results and claims, readability) ran after the held out run. Findings and what
  was done are in `docs/REVIEW_ROUNDS.md`.

## 6. Corrections made after the held out run

This file was edited after the held out run for wording only, and the edits are visible in git history: the baseline numbers in
section 1 were replaced by numbers that a committed file reproduces, the disclosure about reviews and about A1 and A2 in section
5 was made more precise, hyphenated compounds were written as separate words, and this section was added. No prediction, pass
criterion or confidence was changed.
