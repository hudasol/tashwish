# Baselines

Tashwish reports detection rates, but a rate without a comparator has no reference point. This document specifies five
simple comparison detectors (B1, B1b, B2, B3 with three ablations, B4), fixes every constant before any run, and then
reports how they compare with the system on the same footing. Everything about injected scenarios is SYNTHETIC. Everything
about real days is OBSERVED and has no ground truth. Tashwish is a research tool. It is not for navigation or safety of
life, and it never attributes interference to an actor.

## Specification

Status: written and committed before any baseline was run on any day. The commit that contains this section is the
specification commit. Constants below are a priori choices. None was fitted, and none will be changed after a development
result is seen. If a bug is found, it is fixed in a new commit and the fix is reported.

### Common footing

1. All jamming-like baselines consume the same cell bucket metrics as the system (`metrics_for_day`: the same grid, H3
   resolution 4 and 3 hour UTC buckets, the same en route stratum, the same aircraft level degraded definition, the same
   removal of persistent low emitters). Differences in results therefore come from the detection logic, not from
   preprocessing.
2. Every baseline emits flags with the same columns as `flag_buckets` and turns them into events with the unchanged
   `build_events` function (merge by H3 adjacency and adjacent buckets). Spoofing-like baseline events use the columns that
   `combine` and `match_scenario` read. Scenarios are scored by the unchanged `match_scenario` and `drop_background`.
3. Scenarios, seeds, days, runs per day and the scenario mix are those of `results/dev` and `results/held_out` (4 runs per
   day, mix 6 jamming only, 4 spoofing jump, 3 spoofing and jamming, 3 null). Scenario generation is not changed. The
   system is run again inside the same loop and its outcomes are compared with the committed result files as a reproduction
   check.
4. Fitting data. Anything fitted comes from development days only and never includes the scored day. A held out day is only
   scored. No constant below was tuned on any day.

### B1 fixed fraction

For each en route cell bucket with at least 5 aircraft, flag when the share of degraded aircraft is at least 0.10. The share
is `k_strong / n_aircraft`, where an aircraft is degraded when at least half of its quality bearing samples have NIC below 4
or NACp below 5 (the project's strong tier). No baseline is fitted and no uncertainty is computed.

Justification, limited to what the repository text supports. `docs/RESEARCH.md` section 1.1 records that the public GPSJam
map colours a hex red above 10 percent bad aircraft, so 0.10 is the public map's red boundary. The same text does not state
any minimum aircraft count for the map, so the minimum of 5 is an a priori constant (it equals the system's own minimum, so
both detectors test the same units). B1 is not claimed to reproduce GPSJam or any other service: GPSJam uses its own degraded
definition, hex size and a rolling 24 hour window, which are not reproduced here.

### B1b fixed fraction with the sparsity correction (additional)

Added so that B1 is not a strawman. `docs/RESEARCH.md` section 1.1 records that GPSJam computes percent bad as 100 times
(bad minus 1) divided by (good plus bad). B1b flags an en route cell bucket with at least 5 aircraft when
`(k_strong minus 1) / n_aircraft` is at least 0.10. Everything else is as B1. It is an extra comparator beyond the five
requested, specified before any run, and it is not claimed to reproduce GPSJam.

### B2 climatology z score

For each (cell, 3 hour slot of day) in the en route stratum, take the degraded share `k_strong / n_aircraft` on every
development day other than the scored day on which the cell bucket had at least 5 aircraft. Compute the mean and the sample
standard deviation (denominator n minus 1). Flag an en route cell bucket with at least 5 aircraft when its share is strictly
greater than mean plus 3 standard deviations. A cell and slot with fewer than 3 usable development days is not flaggable. No
regime labels, no coverage model, no multiple test control, and no floor on the standard deviation: where the baseline share
never varied the threshold equals the mean, so any excess flags. That is the literal rule and it is kept.

### B3 binomial test without the project's safeguards

Three ablations of the real jamming-like detector, using the real code (`flag_buckets` and `build_events`) wherever it can
be switched by an existing argument, and recomputing the final flag from the real p values otherwise. All other gates are
the system's (at least 3 degraded aircraft, Wilson lower bound at least 0.20, shrinkage and floor 0.02 of the baseline
share).

B3a, no regime aware baselines. The baseline share (p0) and the coverage model are both fitted on all development days other
than the scored day, pooled across regimes, instead of on development days with the same regime label.

B3b, no coverage gating. Every en route cell bucket with at least 5 aircraft is tested (status from `metrics_for_day`,
before the coverage model), so cells that are normally unobserved are no longer excluded. Regime aware p0 as in the system.

B3c, no false discovery control. The Benjamini and Yekutieli step is replaced by a per test threshold: a test is significant
when its one sided binomial p value is below 0.01. Everything else as in the system.

### B4 naive speed threshold for spoofing

Consecutive airborne ADS-B fixes of the same aircraft (same input filter as the system) form a jump when the time gap is
between 0 and 120 seconds and the implied ground speed, computed with a gap floor of 1 second, is above 800 knots. The 800
knot value is an a priori constant, above any commercial jet ground speed including a strong tailwind. There is no
minimum distance, no comparison with the reported speed, no clustering and no minimum number of aircraft: every jump is an
event with one aircraft, and its start and end are the two fix times. The system by contrast requires 650 knots, 5 km, 2.5
times the reported speed, and a cluster of at least 3 aircraft.

### Evaluation design

1. Metrics. Jamming recall by tier (easy, medium, hard, random) on jamming only scenarios; spoofing recall on spoofing
   jump scenarios with 3 or more displaced aircraft; flag rate on null scenarios (jamming flag rate for jamming-like
   detectors, spoofing flag rate for B4 and the system).
2. Two matching rules. The harness rule is the unchanged one: events with the same identifier as an event found on the
   uninjected day are removed, and the rest are matched. It can credit a noisy detector for merging an injection into a
   existing real flag. The strict rule builds events from newly flagged cell buckets only (cell buckets flagged on the
   uninjected day are removed before events are built), so only flags caused by the injection can count. Both are reported,
   and where they differ the strict one is the safer reading.
3. Regimes. Each day carries the traffic label (`normal` or `reduced`) from `results/regimes.csv`. Results are pooled and
   by traffic regime. The reduced traffic days are also the days with an elevated degraded share, except 2026-02-28.
4. Uncertainty. Resampling whole days with replacement, 2000 repetitions, seed 5, 95 percent percentile intervals (the
   same estimator as `cluster_bootstrap_rate` used by the system's own result files, vectorised over repetitions). Regimes with fewer than 2 days get no interval.
5. Real days (OBSERVED, no truth). For each detector on each day: number of flagged cell buckets, flagged share of tested
   cell buckets, and overlap with the system. The overlap is the Jaccard index of the set of flagged (cell, bucket) pairs
   with the set flagged by the system (for B4, jump origin cells and buckets against the origins of jumps inside system
   spoofing-like events). Flags that are present are not claimed to be false, since there is no truth.
6. Held out days. The held out days were scored once for the system under a frozen state. The baselines are scored on them
   after the fact. Every held out baseline number is labelled "post hoc, not preregistered, baselines fixed before run"
   followed by the commit hash recorded in the result files, and the run refuses to start if the baseline sources differ
   from that commit. No baseline is tuned on a held out day.

### Expectations written before the run

These are expectations, not preregistered predictions, and they are listed so they can be seen to be right or wrong.

1. B1 and B1b will have high recall on easy scenarios and a large number of flagged units on real days, mostly single
   aircraft excesses in small cells, with B1 worse than B1b.
2. B2 will do poorly across the regime change because its baseline is pooled, and on reduced days will flag little or much
   depending on the pooled standard deviation, not on the day.
3. B3a will flag far more cell buckets on elevated days or far fewer, because p0 comes from the wrong regime.
4. B3b and B3c will have recall at least that of the system, and more flags on real days.
5. B4 will have recall close to the system's for 3 or more displaced aircraft and a much larger number of events on real
   days.
6. Where a baseline matches the system on recall, the system's advantage lies in the flag burden on real days, not in
   recall.

Sources: docs/RESEARCH.md, docs/METHODOLOGY.md, docs/PREDICTIONS_AMENDMENT.md, docs/VALIDATION.md, src/tashwish/detect/jamming.py, src/tashwish/detect/spoofing.py, src/tashwish/validate/harness.py, src/tashwish/validate/run.py, src/tashwish/validate/inject.py, src/tashwish/regime.py.

<!-- BEGIN GENERATED RESULTS -->
Results have not been generated yet.
<!-- END GENERATED RESULTS -->
