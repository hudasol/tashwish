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
## Results

Generated by `scripts/make_baselines_doc.py` from the files in `results/baselines/`. Rates are shown with 95 percent intervals from resampling whole days (2000 repetitions, seed 5). Tables of injected scenarios are SYNTHETIC. Tables of real days are OBSERVED and have no ground truth. Tashwish never attributes interference to an actor.

### Run provenance and reproduction of the system

The system is run again inside the same loop as the baselines. The two right hand count columns show how many of its scenario outcomes equal the committed result files of the original runs.

| Split | Days | Scenarios here | Matched to committed file | System jam outcome equal | System spoof outcome equal | Commit |
|---|---|---|---|---|---|---|
| dev | 21 | 1257 | 1257 | 1257 of 1257 | 1257 of 1257 | 400ed6d545 |

### 1. Jamming recall by tier: Development days (the system was developed on these days; the baselines were not tuned on any day)

Harness rule (unchanged `drop_background` and `match_scenario`). SYNTHETIC.

Traffic regime: all (21 days)

| Detector | easy (n=127) | medium (n=124) | hard (n=125) | random (n=128) |
|---|---|---|---|---|
| system | 0.92 [0.87, 0.97] | 0.82 [0.72, 0.92] | 0.14 [0.07, 0.21] | 0.48 [0.35, 0.59] |
| B1 | 0.80 [0.66, 0.91] | 0.80 [0.67, 0.91] | 0.45 [0.35, 0.55] | 0.70 [0.57, 0.82] |
| B1b | 0.84 [0.73, 0.93] | 0.82 [0.71, 0.92] | 0.46 [0.36, 0.55] | 0.76 [0.65, 0.85] |
| B2 | 0.90 [0.83, 0.96] | 0.89 [0.82, 0.95] | 0.44 [0.37, 0.52] | 0.72 [0.63, 0.80] |
| B3a | 0.94 [0.88, 0.99] | 0.88 [0.79, 0.96] | 0.19 [0.12, 0.28] | 0.58 [0.49, 0.66] |
| B3b | 0.92 [0.87, 0.97] | 0.82 [0.72, 0.92] | 0.14 [0.08, 0.21] | 0.48 [0.35, 0.59] |
| B3c | 0.93 [0.88, 0.97] | 0.90 [0.84, 0.96] | 0.17 [0.10, 0.25] | 0.52 [0.41, 0.63] |

Traffic regime: normal (13 days)

| Detector | easy (n=77) | medium (n=77) | hard (n=79) | random (n=79) |
|---|---|---|---|---|
| system | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.19 [0.10, 0.30] | 0.65 [0.53, 0.74] |
| B1 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.57 [0.47, 0.68] | 0.89 [0.81, 0.95] |
| B1b | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.56 [0.44, 0.68] | 0.89 [0.81, 0.95] |
| B2 | 1.00 [1.00, 1.00] | 0.99 [0.96, 1.00] | 0.51 [0.40, 0.61] | 0.81 [0.71, 0.89] |
| B3a | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.15 [0.07, 0.25] | 0.65 [0.53, 0.74] |
| B3b | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.20 [0.12, 0.31] | 0.65 [0.53, 0.74] |
| B3c | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.20 [0.11, 0.31] | 0.65 [0.53, 0.74] |

Traffic regime: reduced (8 days)

| Detector | easy (n=50) | medium (n=47) | hard (n=46) | random (n=49) |
|---|---|---|---|---|
| system | 0.80 [0.73, 0.88] | 0.53 [0.39, 0.64] | 0.04 [0.00, 0.09] | 0.20 [0.10, 0.32] |
| B1 | 0.48 [0.31, 0.67] | 0.47 [0.33, 0.64] | 0.24 [0.13, 0.41] | 0.41 [0.25, 0.62] |
| B1b | 0.60 [0.44, 0.75] | 0.53 [0.37, 0.68] | 0.28 [0.19, 0.37] | 0.55 [0.38, 0.74] |
| B2 | 0.74 [0.65, 0.81] | 0.72 [0.62, 0.80] | 0.33 [0.26, 0.39] | 0.57 [0.44, 0.65] |
| B3a | 0.86 [0.73, 0.96] | 0.68 [0.53, 0.83] | 0.26 [0.13, 0.42] | 0.47 [0.33, 0.60] |
| B3b | 0.80 [0.73, 0.88] | 0.53 [0.39, 0.64] | 0.04 [0.00, 0.09] | 0.20 [0.10, 0.32] |
| B3c | 0.82 [0.76, 0.88] | 0.74 [0.67, 0.84] | 0.11 [0.02, 0.21] | 0.33 [0.20, 0.47] |

Strict rule (only flags caused by the injection can count). SYNTHETIC.

Traffic regime: all (21 days)

| Detector | easy (n=127) | medium (n=124) | hard (n=125) | random (n=128) |
|---|---|---|---|---|
| system | 0.92 [0.87, 0.97] | 0.82 [0.72, 0.92] | 0.14 [0.07, 0.21] | 0.48 [0.35, 0.59] |
| B1 | 0.86 [0.76, 0.94] | 0.83 [0.72, 0.93] | 0.42 [0.33, 0.52] | 0.77 [0.65, 0.86] |
| B1b | 0.90 [0.82, 0.96] | 0.87 [0.78, 0.95] | 0.47 [0.38, 0.56] | 0.80 [0.70, 0.88] |
| B2 | 0.94 [0.89, 0.98] | 0.93 [0.86, 0.98] | 0.42 [0.33, 0.51] | 0.74 [0.65, 0.82] |
| B3a | 0.94 [0.88, 0.99] | 0.90 [0.83, 0.97] | 0.20 [0.12, 0.28] | 0.60 [0.51, 0.68] |
| B3b | 0.92 [0.87, 0.97] | 0.82 [0.72, 0.92] | 0.15 [0.09, 0.22] | 0.48 [0.35, 0.59] |
| B3c | 0.94 [0.89, 0.98] | 0.91 [0.85, 0.96] | 0.17 [0.10, 0.25] | 0.52 [0.41, 0.63] |

Traffic regime: normal (13 days)

| Detector | easy (n=77) | medium (n=77) | hard (n=79) | random (n=79) |
|---|---|---|---|---|
| system | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.19 [0.10, 0.30] | 0.65 [0.53, 0.74] |
| B1 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.54 [0.44, 0.66] | 0.89 [0.81, 0.95] |
| B1b | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.56 [0.44, 0.68] | 0.89 [0.81, 0.95] |
| B2 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.51 [0.38, 0.63] | 0.82 [0.72, 0.91] |
| B3a | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.15 [0.07, 0.25] | 0.65 [0.53, 0.74] |
| B3b | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.20 [0.12, 0.31] | 0.65 [0.53, 0.74] |
| B3c | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.20 [0.11, 0.31] | 0.65 [0.53, 0.74] |

Traffic regime: reduced (8 days)

| Detector | easy (n=50) | medium (n=47) | hard (n=46) | random (n=49) |
|---|---|---|---|---|
| system | 0.80 [0.73, 0.88] | 0.53 [0.39, 0.64] | 0.04 [0.00, 0.09] | 0.20 [0.10, 0.32] |
| B1 | 0.64 [0.50, 0.77] | 0.55 [0.44, 0.70] | 0.22 [0.14, 0.29] | 0.57 [0.38, 0.75] |
| B1b | 0.74 [0.61, 0.86] | 0.66 [0.50, 0.80] | 0.33 [0.24, 0.42] | 0.65 [0.48, 0.80] |
| B2 | 0.84 [0.76, 0.92] | 0.81 [0.65, 0.94] | 0.26 [0.19, 0.34] | 0.61 [0.45, 0.74] |
| B3a | 0.86 [0.73, 0.96] | 0.74 [0.60, 0.87] | 0.28 [0.16, 0.40] | 0.53 [0.38, 0.67] |
| B3b | 0.80 [0.73, 0.88] | 0.53 [0.39, 0.64] | 0.07 [0.00, 0.14] | 0.20 [0.10, 0.32] |
| B3c | 0.84 [0.78, 0.91] | 0.77 [0.70, 0.84] | 0.11 [0.02, 0.21] | 0.33 [0.20, 0.47] |

### 2. Spoofing recall, 3 or more displaced aircraft: Development days (the system was developed on these days; the baselines were not tuned on any day)

SYNTHETIC.

| Traffic regime | Scenarios | system | B4 |
|---|---|---|---|
| all | 188 | 0.63 [0.57, 0.69] | 0.99 [0.97, 1.00] |
| normal | 127 | 0.60 [0.52, 0.68] | 0.98 [0.96, 1.00] |
| reduced | 61 | 0.70 [0.66, 0.75] | 1.00 [1.00, 1.00] |

### 3. Flag rate on null scenarios: Development days (the system was developed on these days; the baselines were not tuned on any day)

SYNTHETIC. Fraction of null scenarios overlapped by an event after background removal. See the limits on why this is close to zero by construction.

| Traffic regime | Null scenarios | system harness jam | B1 harness jam | B1b harness jam | B2 harness jam | B3a harness jam | B3b harness jam | B3c harness jam | system strict jam | B1 strict jam | B1b strict jam | B2 strict jam | B3a strict jam | B3b strict jam | B3c strict jam | system harness spoof | B4 harness spoof |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 222 | 0.000 | 0.063 | 0.009 | 0.023 | 0.009 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.005 | 0.000 | 0.000 | 0.009 | 0.077 |
| normal | 156 | 0.000 | 0.051 | 0.000 | 0.013 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.006 | 0.096 |
| reduced | 66 | 0.000 | 0.091 | 0.030 | 0.045 | 0.030 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.015 | 0.000 | 0.000 | 0.015 | 0.030 |

### 4. Real days, jamming-like flags: Development days (the system was developed on these days; the baselines were not tuned on any day)

OBSERVED, no truth. Flagged cell buckets are not claimed to be false alarms or true events.

| Traffic regime | Detector | Days | Tested per day | Flagged per day [day bootstrap] | Flagged share of tested | Events per day | Jaccard with system | Share of system flags also flagged | Flagged but not by system per day |
|---|---|---|---|---|---|---|---|---|---|
| all | system | 21 | 1239 | 0.2 [0.0, 0.4] | 0.000 | 0.2 | 1.000 | 1.00 | 0.0 |
| all | B1 | 21 | 1271 | 108.6 [81.9, 138.1] | 0.085 | 19.6 | 0.002 | 1.00 | 108.4 |
| all | B1b | 21 | 1271 | 51.0 [29.1, 75.1] | 0.040 | 7.7 | 0.004 | 1.00 | 50.9 |
| all | B2 | 21 | 1271 | 62.1 [51.3, 75.2] | 0.049 | 22.6 | 0.002 | 0.75 | 62.0 |
| all | B3a | 21 | 1250 | 17.4 [7.7, 28.1] | 0.014 | 4.7 | 0.008 | 0.75 | 17.3 |
| all | B3b | 21 | 1271 | 0.2 [0.0, 0.6] | 0.000 | 0.2 | 0.500 | 0.75 | 0.1 |
| all | B3c | 21 | 1239 | 2.3 [0.9, 4.0] | 0.002 | 1.7 | 0.083 | 1.00 | 2.1 |
| normal | system | 13 | 1845 | 0.1 [0.0, 0.2] | 0.000 | 0.1 | 1.000 | 1.00 | 0.0 |
| normal | B1 | 13 | 1872 | 65.0 [51.6, 85.8] | 0.035 | 23.7 | 0.001 | 1.00 | 64.9 |
| normal | B1b | 13 | 1872 | 9.3 [4.8, 14.8] | 0.005 | 3.9 | 0.008 | 1.00 | 9.2 |
| normal | B2 | 13 | 1872 | 53.9 [41.2, 71.2] | 0.029 | 24.5 | 0.001 | 1.00 | 53.8 |
| normal | B3a | 13 | 1846 | 0.1 [0.0, 0.2] | 0.000 | 0.1 | 1.000 | 1.00 | 0.0 |
| normal | B3b | 13 | 1872 | 0.1 [0.0, 0.2] | 0.000 | 0.1 | 1.000 | 1.00 | 0.0 |
| normal | B3c | 13 | 1845 | 0.1 [0.0, 0.2] | 0.000 | 0.1 | 1.000 | 1.00 | 0.0 |
| reduced | system | 8 | 253 | 0.4 [0.0, 0.9] | 0.001 | 0.4 | 1.000 | 1.00 | 0.0 |
| reduced | B1 | 8 | 295 | 179.4 [150.9, 208.4] | 0.609 | 13.0 | 0.002 | 1.00 | 179.0 |
| reduced | B1b | 8 | 295 | 118.9 [102.7, 136.5] | 0.403 | 13.9 | 0.003 | 1.00 | 118.5 |
| reduced | B2 | 8 | 295 | 75.5 [61.9, 89.0] | 0.256 | 19.6 | 0.003 | 0.67 | 75.2 |
| reduced | B3a | 8 | 282 | 45.6 [30.2, 60.3] | 0.162 | 12.1 | 0.005 | 0.67 | 45.4 |
| reduced | B3b | 8 | 295 | 0.5 [0.0, 1.2] | 0.002 | 0.5 | 0.400 | 0.67 | 0.2 |
| reduced | B3c | 8 | 253 | 5.9 [3.1, 8.9] | 0.023 | 4.2 | 0.064 | 1.00 | 5.5 |

### 5. Real days, spoofing-like jumps: Development days (the system was developed on these days; the baselines were not tuned on any day)

OBSERVED, no truth.

| Traffic regime | Detector | Days | Flagged origin units per day [day bootstrap] | Events per day | Jaccard with system | Share of system units also flagged |
|---|---|---|---|---|---|---|
| all | system | 21 | 2.8 [1.1, 4.6] | 0.7 | 1.000 | 1.00 |
| all | B4 | 21 | 59.4 [45.8, 73.6] | 121.4 | 0.046 | 0.98 |
| normal | system | 13 | 0.8 [0.0, 1.8] | 0.3 | 1.000 | 1.00 |
| normal | B4 | 13 | 35.5 [26.3, 46.3] | 45.2 | 0.024 | 1.00 |
| reduced | system | 8 | 5.9 [2.6, 9.1] | 1.2 | 1.000 | 1.00 |
| reduced | B4 | 8 | 98.2 [93.1, 103.5] | 245.1 | 0.058 | 0.98 |

### 6. Baseline minus system on identical scenarios: Development days (the system was developed on these days; the baselines were not tuned on any day)

Differences in recall on the same scenarios. The verdict is above when the whole day bootstrap interval of the difference is positive, below when it is negative, and tied otherwise. A baseline that is above or tied with the system is reported as such.

| Metric | Traffic regime | Detector | Scenarios | Rule | Baseline minus system [day bootstrap] | Verdict |
|---|---|---|---|---|---|---|
| jamming recall, easy | all | B1 | 127 | harness | -0.13 [-0.24, -0.03] | below |
| jamming recall, easy | all | B1b | 127 | harness | -0.08 [-0.16, -0.01] | below |
| jamming recall, easy | all | B2 | 127 | harness | -0.02 [-0.05, +0.00] | tied |
| jamming recall, easy | all | B3a | 127 | harness | +0.02 [-0.02, +0.07] | tied |
| jamming recall, easy | all | B3b | 127 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | all | B3c | 127 | harness | +0.01 [+0.00, +0.03] | tied |
| jamming recall, medium | all | B1 | 124 | harness | -0.02 [-0.10, +0.06] | tied |
| jamming recall, medium | all | B1b | 124 | harness | +0.00 [-0.07, +0.07] | tied |
| jamming recall, medium | all | B2 | 124 | harness | +0.06 [+0.01, +0.12] | above |
| jamming recall, medium | all | B3a | 124 | harness | +0.06 [+0.00, +0.14] | tied |
| jamming recall, medium | all | B3b | 124 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | all | B3c | 124 | harness | +0.08 [+0.02, +0.15] | above |
| jamming recall, hard | all | B1 | 125 | harness | +0.31 [+0.22, +0.41] | above |
| jamming recall, hard | all | B1b | 125 | harness | +0.32 [+0.24, +0.40] | above |
| jamming recall, hard | all | B2 | 125 | harness | +0.30 [+0.22, +0.38] | above |
| jamming recall, hard | all | B3a | 125 | harness | +0.06 [-0.02, +0.15] | tied |
| jamming recall, hard | all | B3b | 125 | harness | +0.01 [+0.00, +0.03] | tied |
| jamming recall, hard | all | B3c | 125 | harness | +0.03 [+0.00, +0.07] | tied |
| jamming recall, random | all | B1 | 128 | harness | +0.23 [+0.12, +0.35] | above |
| jamming recall, random | all | B1b | 128 | harness | +0.28 [+0.18, +0.39] | above |
| jamming recall, random | all | B2 | 128 | harness | +0.24 [+0.16, +0.33] | above |
| jamming recall, random | all | B3a | 128 | harness | +0.10 [+0.04, +0.17] | above |
| jamming recall, random | all | B3b | 128 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, random | all | B3c | 128 | harness | +0.05 [+0.00, +0.09] | tied |
| jamming recall, all tiers | all | B1 | 504 | harness | +0.10 [+0.02, +0.17] | above |
| jamming recall, all tiers | all | B1b | 504 | harness | +0.13 [+0.07, +0.19] | above |
| jamming recall, all tiers | all | B2 | 504 | harness | +0.15 [+0.12, +0.18] | above |
| jamming recall, all tiers | all | B3a | 504 | harness | +0.06 [+0.01, +0.12] | above |
| jamming recall, all tiers | all | B3b | 504 | harness | +0.00 [+0.00, +0.01] | tied |
| jamming recall, all tiers | all | B3c | 504 | harness | +0.04 [+0.02, +0.07] | above |
| jamming recall, easy | all | B1 | 127 | strict | -0.06 [-0.14, -0.01] | below |
| jamming recall, easy | all | B1b | 127 | strict | -0.02 [-0.09, +0.02] | tied |
| jamming recall, easy | all | B2 | 127 | strict | +0.02 [-0.02, +0.05] | tied |
| jamming recall, easy | all | B3a | 127 | strict | +0.02 [-0.02, +0.07] | tied |
| jamming recall, easy | all | B3b | 127 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | all | B3c | 127 | strict | +0.02 [+0.00, +0.04] | tied |
| jamming recall, medium | all | B1 | 124 | strict | +0.01 [-0.06, +0.08] | tied |
| jamming recall, medium | all | B1b | 124 | strict | +0.05 [-0.01, +0.12] | tied |
| jamming recall, medium | all | B2 | 124 | strict | +0.10 [+0.04, +0.18] | above |
| jamming recall, medium | all | B3a | 124 | strict | +0.08 [+0.02, +0.16] | above |
| jamming recall, medium | all | B3b | 124 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | all | B3c | 124 | strict | +0.09 [+0.03, +0.16] | above |
| jamming recall, hard | all | B1 | 125 | strict | +0.29 [+0.21, +0.37] | above |
| jamming recall, hard | all | B1b | 125 | strict | +0.34 [+0.26, +0.42] | above |
| jamming recall, hard | all | B2 | 125 | strict | +0.28 [+0.19, +0.38] | above |
| jamming recall, hard | all | B3a | 125 | strict | +0.06 [-0.01, +0.14] | tied |
| jamming recall, hard | all | B3b | 125 | strict | +0.02 [+0.00, +0.04] | tied |
| jamming recall, hard | all | B3c | 125 | strict | +0.03 [+0.00, +0.07] | tied |
| jamming recall, random | all | B1 | 128 | strict | +0.29 [+0.19, +0.40] | above |
| jamming recall, random | all | B1b | 128 | strict | +0.32 [+0.22, +0.43] | above |
| jamming recall, random | all | B2 | 128 | strict | +0.27 [+0.17, +0.36] | above |
| jamming recall, random | all | B3a | 128 | strict | +0.12 [+0.05, +0.22] | above |
| jamming recall, random | all | B3b | 128 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, random | all | B3c | 128 | strict | +0.05 [+0.00, +0.09] | tied |
| jamming recall, all tiers | all | B1 | 504 | strict | +0.13 [+0.08, +0.18] | above |
| jamming recall, all tiers | all | B1b | 504 | strict | +0.17 [+0.12, +0.23] | above |
| jamming recall, all tiers | all | B2 | 504 | strict | +0.17 [+0.13, +0.22] | above |
| jamming recall, all tiers | all | B3a | 504 | strict | +0.07 [+0.02, +0.13] | above |
| jamming recall, all tiers | all | B3b | 504 | strict | +0.00 [+0.00, +0.01] | tied |
| jamming recall, all tiers | all | B3c | 504 | strict | +0.05 [+0.02, +0.07] | above |
| spoofing recall, 3 or more displaced | all | B4 | 188 | harness | +0.36 [+0.29, +0.42] | above |
| jamming recall, easy | normal | B1 | 77 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | normal | B1b | 77 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | normal | B2 | 77 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | normal | B3a | 77 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | normal | B3b | 77 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | normal | B3c | 77 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | normal | B1 | 77 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | normal | B1b | 77 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | normal | B2 | 77 | harness | -0.01 [-0.04, +0.00] | tied |
| jamming recall, medium | normal | B3a | 77 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | normal | B3b | 77 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | normal | B3c | 77 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, hard | normal | B1 | 79 | harness | +0.38 [+0.28, +0.47] | above |
| jamming recall, hard | normal | B1b | 79 | harness | +0.37 [+0.26, +0.47] | above |
| jamming recall, hard | normal | B2 | 79 | harness | +0.32 [+0.20, +0.42] | above |
| jamming recall, hard | normal | B3a | 79 | harness | -0.04 [-0.10, +0.00] | tied |
| jamming recall, hard | normal | B3b | 79 | harness | +0.01 [+0.00, +0.04] | tied |
| jamming recall, hard | normal | B3c | 79 | harness | +0.01 [+0.00, +0.04] | tied |
| jamming recall, random | normal | B1 | 79 | harness | +0.24 [+0.16, +0.32] | above |
| jamming recall, random | normal | B1b | 79 | harness | +0.24 [+0.16, +0.32] | above |
| jamming recall, random | normal | B2 | 79 | harness | +0.16 [+0.10, +0.23] | above |
| jamming recall, random | normal | B3a | 79 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, random | normal | B3b | 79 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, random | normal | B3c | 79 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, all tiers | normal | B1 | 312 | harness | +0.16 [+0.13, +0.18] | above |
| jamming recall, all tiers | normal | B1b | 312 | harness | +0.15 [+0.12, +0.19] | above |
| jamming recall, all tiers | normal | B2 | 312 | harness | +0.12 [+0.09, +0.15] | above |
| jamming recall, all tiers | normal | B3a | 312 | harness | -0.01 [-0.03, +0.00] | tied |
| jamming recall, all tiers | normal | B3b | 312 | harness | +0.00 [+0.00, +0.01] | tied |
| jamming recall, all tiers | normal | B3c | 312 | harness | +0.00 [+0.00, +0.01] | tied |
| jamming recall, easy | normal | B1 | 77 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | normal | B1b | 77 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | normal | B2 | 77 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | normal | B3a | 77 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | normal | B3b | 77 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | normal | B3c | 77 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | normal | B1 | 77 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | normal | B1b | 77 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | normal | B2 | 77 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | normal | B3a | 77 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | normal | B3b | 77 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | normal | B3c | 77 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, hard | normal | B1 | 79 | strict | +0.35 [+0.25, +0.45] | above |
| jamming recall, hard | normal | B1b | 79 | strict | +0.37 [+0.26, +0.47] | above |
| jamming recall, hard | normal | B2 | 79 | strict | +0.32 [+0.18, +0.45] | above |
| jamming recall, hard | normal | B3a | 79 | strict | -0.04 [-0.10, +0.00] | tied |
| jamming recall, hard | normal | B3b | 79 | strict | +0.01 [+0.00, +0.04] | tied |
| jamming recall, hard | normal | B3c | 79 | strict | +0.01 [+0.00, +0.04] | tied |
| jamming recall, random | normal | B1 | 79 | strict | +0.24 [+0.16, +0.32] | above |
| jamming recall, random | normal | B1b | 79 | strict | +0.24 [+0.16, +0.32] | above |
| jamming recall, random | normal | B2 | 79 | strict | +0.18 [+0.11, +0.25] | above |
| jamming recall, random | normal | B3a | 79 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, random | normal | B3b | 79 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, random | normal | B3c | 79 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, all tiers | normal | B1 | 312 | strict | +0.15 [+0.12, +0.18] | above |
| jamming recall, all tiers | normal | B1b | 312 | strict | +0.15 [+0.12, +0.19] | above |
| jamming recall, all tiers | normal | B2 | 312 | strict | +0.12 [+0.09, +0.16] | above |
| jamming recall, all tiers | normal | B3a | 312 | strict | -0.01 [-0.03, +0.00] | tied |
| jamming recall, all tiers | normal | B3b | 312 | strict | +0.00 [+0.00, +0.01] | tied |
| jamming recall, all tiers | normal | B3c | 312 | strict | +0.00 [+0.00, +0.01] | tied |
| spoofing recall, 3 or more displaced | normal | B4 | 127 | harness | +0.39 [+0.30, +0.47] | above |
| jamming recall, easy | reduced | B1 | 50 | harness | -0.32 [-0.53, -0.10] | below |
| jamming recall, easy | reduced | B1b | 50 | harness | -0.20 [-0.39, -0.04] | below |
| jamming recall, easy | reduced | B2 | 50 | harness | -0.06 [-0.12, -0.02] | below |
| jamming recall, easy | reduced | B3a | 50 | harness | +0.06 [-0.05, +0.16] | tied |
| jamming recall, easy | reduced | B3b | 50 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | reduced | B3c | 50 | harness | +0.02 [+0.00, +0.07] | tied |
| jamming recall, medium | reduced | B1 | 47 | harness | -0.06 [-0.23, +0.19] | tied |
| jamming recall, medium | reduced | B1b | 47 | harness | +0.00 [-0.16, +0.20] | tied |
| jamming recall, medium | reduced | B2 | 47 | harness | +0.19 [+0.10, +0.29] | above |
| jamming recall, medium | reduced | B3a | 47 | harness | +0.15 [+0.00, +0.36] | tied |
| jamming recall, medium | reduced | B3b | 47 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | reduced | B3c | 47 | harness | +0.21 [+0.10, +0.36] | above |
| jamming recall, hard | reduced | B1 | 46 | harness | +0.20 [+0.08, +0.38] | above |
| jamming recall, hard | reduced | B1b | 46 | harness | +0.24 [+0.16, +0.32] | above |
| jamming recall, hard | reduced | B2 | 46 | harness | +0.28 [+0.22, +0.35] | above |
| jamming recall, hard | reduced | B3a | 46 | harness | +0.22 [+0.07, +0.40] | above |
| jamming recall, hard | reduced | B3b | 46 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, hard | reduced | B3c | 46 | harness | +0.07 [+0.00, +0.16] | tied |
| jamming recall, random | reduced | B1 | 49 | harness | +0.20 [-0.02, +0.49] | tied |
| jamming recall, random | reduced | B1b | 49 | harness | +0.35 [+0.14, +0.59] | above |
| jamming recall, random | reduced | B2 | 49 | harness | +0.37 [+0.24, +0.50] | above |
| jamming recall, random | reduced | B3a | 49 | harness | +0.27 [+0.16, +0.36] | above |
| jamming recall, random | reduced | B3b | 49 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, random | reduced | B3c | 49 | harness | +0.12 [+0.02, +0.22] | above |
| jamming recall, all tiers | reduced | B1 | 192 | harness | +0.00 [-0.12, +0.21] | tied |
| jamming recall, all tiers | reduced | B1b | 192 | harness | +0.09 [-0.02, +0.25] | tied |
| jamming recall, all tiers | reduced | B2 | 192 | harness | +0.19 [+0.14, +0.25] | above |
| jamming recall, all tiers | reduced | B3a | 192 | harness | +0.17 [+0.07, +0.27] | above |
| jamming recall, all tiers | reduced | B3b | 192 | harness | +0.00 [+0.00, +0.00] | tied |
| jamming recall, all tiers | reduced | B3c | 192 | harness | +0.10 [+0.06, +0.15] | above |
| jamming recall, easy | reduced | B1 | 50 | strict | -0.16 [-0.33, -0.04] | below |
| jamming recall, easy | reduced | B1b | 50 | strict | -0.06 [-0.21, +0.06] | tied |
| jamming recall, easy | reduced | B2 | 50 | strict | +0.04 [-0.04, +0.11] | tied |
| jamming recall, easy | reduced | B3a | 50 | strict | +0.06 [-0.05, +0.16] | tied |
| jamming recall, easy | reduced | B3b | 50 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, easy | reduced | B3c | 50 | strict | +0.04 [+0.00, +0.10] | tied |
| jamming recall, medium | reduced | B1 | 47 | strict | +0.02 [-0.14, +0.23] | tied |
| jamming recall, medium | reduced | B1b | 47 | strict | +0.13 [-0.02, +0.30] | tied |
| jamming recall, medium | reduced | B2 | 47 | strict | +0.28 [+0.17, +0.39] | above |
| jamming recall, medium | reduced | B3a | 47 | strict | +0.21 [+0.09, +0.40] | above |
| jamming recall, medium | reduced | B3b | 47 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, medium | reduced | B3c | 47 | strict | +0.23 [+0.13, +0.37] | above |
| jamming recall, hard | reduced | B1 | 46 | strict | +0.17 [+0.11, +0.25] | above |
| jamming recall, hard | reduced | B1b | 46 | strict | +0.28 [+0.20, +0.39] | above |
| jamming recall, hard | reduced | B2 | 46 | strict | +0.22 [+0.13, +0.30] | above |
| jamming recall, hard | reduced | B3a | 46 | strict | +0.24 [+0.12, +0.36] | above |
| jamming recall, hard | reduced | B3b | 46 | strict | +0.02 [+0.00, +0.06] | tied |
| jamming recall, hard | reduced | B3c | 46 | strict | +0.07 [+0.00, +0.16] | tied |
| jamming recall, random | reduced | B1 | 49 | strict | +0.37 [+0.16, +0.60] | above |
| jamming recall, random | reduced | B1b | 49 | strict | +0.45 [+0.27, +0.65] | above |
| jamming recall, random | reduced | B2 | 49 | strict | +0.41 [+0.24, +0.58] | above |
| jamming recall, random | reduced | B3a | 49 | strict | +0.33 [+0.20, +0.45] | above |
| jamming recall, random | reduced | B3b | 49 | strict | +0.00 [+0.00, +0.00] | tied |
| jamming recall, random | reduced | B3c | 49 | strict | +0.12 [+0.02, +0.22] | above |
| jamming recall, all tiers | reduced | B1 | 192 | strict | +0.10 [-0.02, +0.24] | tied |
| jamming recall, all tiers | reduced | B1b | 192 | strict | +0.20 [+0.08, +0.33] | above |
| jamming recall, all tiers | reduced | B2 | 192 | strict | +0.23 [+0.17, +0.32] | above |
| jamming recall, all tiers | reduced | B3a | 192 | strict | +0.21 [+0.11, +0.30] | above |
| jamming recall, all tiers | reduced | B3b | 192 | strict | +0.01 [+0.00, +0.02] | tied |
| jamming recall, all tiers | reduced | B3c | 192 | strict | +0.11 [+0.07, +0.16] | above |
| spoofing recall, 3 or more displaced | reduced | B4 | 61 | harness | +0.30 [+0.25, +0.34] | above |

### 7. Summary of where baselines are above, tied with or below the system: Development days (the system was developed on these days; the baselines were not tuned on any day)

B1, jamming recall by tier, harness rule: above the system in 3 of 8 tier and regime cells (hard on normal days (+0.38); random on normal days (+0.24); hard on reduced days (+0.20)), tied in 4, below in 1 (easy on reduced days (-0.32)).

B1, jamming recall by tier, strict rule: above the system in 4 of 8 tier and regime cells (hard on normal days (+0.35); random on normal days (+0.24); hard on reduced days (+0.17); random on reduced days (+0.37)), tied in 3, below in 1 (easy on reduced days (-0.16)).

B1b, jamming recall by tier, harness rule: above the system in 4 of 8 tier and regime cells (hard on normal days (+0.37); random on normal days (+0.24); hard on reduced days (+0.24); random on reduced days (+0.35)), tied in 3, below in 1 (easy on reduced days (-0.20)).

B1b, jamming recall by tier, strict rule: above the system in 4 of 8 tier and regime cells (hard on normal days (+0.37); random on normal days (+0.24); hard on reduced days (+0.28); random on reduced days (+0.45)), tied in 4, below in 0.

B2, jamming recall by tier, harness rule: above the system in 5 of 8 tier and regime cells (hard on normal days (+0.32); random on normal days (+0.16); medium on reduced days (+0.19); hard on reduced days (+0.28); random on reduced days (+0.37)), tied in 2, below in 1 (easy on reduced days (-0.06)).

B2, jamming recall by tier, strict rule: above the system in 5 of 8 tier and regime cells (hard on normal days (+0.32); random on normal days (+0.18); medium on reduced days (+0.28); hard on reduced days (+0.22); random on reduced days (+0.41)), tied in 3, below in 0.

B3a, jamming recall by tier, harness rule: above the system in 2 of 8 tier and regime cells (hard on reduced days (+0.22); random on reduced days (+0.27)), tied in 6, below in 0.

B3a, jamming recall by tier, strict rule: above the system in 3 of 8 tier and regime cells (medium on reduced days (+0.21); hard on reduced days (+0.24); random on reduced days (+0.33)), tied in 5, below in 0.

B3b, jamming recall by tier, harness rule: above the system in 0 of 8 tier and regime cells, tied in 8, below in 0.

B3b, jamming recall by tier, strict rule: above the system in 0 of 8 tier and regime cells, tied in 8, below in 0.

B3c, jamming recall by tier, harness rule: above the system in 2 of 8 tier and regime cells (medium on reduced days (+0.21); random on reduced days (+0.12)), tied in 6, below in 0.

B3c, jamming recall by tier, strict rule: above the system in 2 of 8 tier and regime cells (medium on reduced days (+0.23); random on reduced days (+0.12)), tied in 6, below in 0.

B4, spoofing recall, harness rule: above the system in 2 of 2 tier and regime cells (spoofing on normal days (+0.39); spoofing on reduced days (+0.30)), tied in 0, below in 0.

OBSERVED, normal days: B1 flagged 65.0 cell buckets per day against 0.1 for the system; the share of the system's own flags that it also flagged was 1.00.

OBSERVED, normal days: B1b flagged 9.3 cell buckets per day against 0.1 for the system; the share of the system's own flags that it also flagged was 1.00.

OBSERVED, normal days: B2 flagged 53.9 cell buckets per day against 0.1 for the system; the share of the system's own flags that it also flagged was 1.00.

OBSERVED, normal days: B3a flagged 0.1 cell buckets per day against 0.1 for the system; the share of the system's own flags that it also flagged was 1.00.

OBSERVED, normal days: B3b flagged 0.1 cell buckets per day against 0.1 for the system; the share of the system's own flags that it also flagged was 1.00.

OBSERVED, normal days: B3c flagged 0.1 cell buckets per day against 0.1 for the system; the share of the system's own flags that it also flagged was 1.00.

OBSERVED, reduced days: B1 flagged 179.4 cell buckets per day against 0.4 for the system; the share of the system's own flags that it also flagged was 1.00.

OBSERVED, reduced days: B1b flagged 118.9 cell buckets per day against 0.4 for the system; the share of the system's own flags that it also flagged was 1.00.

OBSERVED, reduced days: B2 flagged 75.5 cell buckets per day against 0.4 for the system; the share of the system's own flags that it also flagged was 0.67.

OBSERVED, reduced days: B3a flagged 45.6 cell buckets per day against 0.4 for the system; the share of the system's own flags that it also flagged was 0.67.

OBSERVED, reduced days: B3b flagged 0.5 cell buckets per day against 0.4 for the system; the share of the system's own flags that it also flagged was 0.67.

OBSERVED, reduced days: B3c flagged 5.9 cell buckets per day against 0.4 for the system; the share of the system's own flags that it also flagged was 1.00.

OBSERVED, normal days: B4 gave 45.2 events per day against 0.3 for the system.

OBSERVED, reduced days: B4 gave 245.1 events per day against 1.2 for the system.

### Limits

1. Scenarios were generated for the system. They are placed away from real flags of the system, not of the baselines. A
   baseline with many real flags can therefore have injected scenarios land in or beside its own background flags. The harness
   rule drops events whose identifier also appears on the uninjected day. It can credit a baseline when an injection merges
   into a background flag and the merged event gets a new identifier, and it can hide an injection that adds flags to a
   background event without changing its identifier. The strict rule removes both effects by counting only cell buckets that
   were not flagged on the uninjected day. A detector that flags a large share of all units on a day cannot be given a
   meaningful recall by either rule.
2. Recall and the number of flags on real days must be read together. A baseline with a lower gate than the system, for
   example fewer degraded aircraft required, finds smaller injections, and the same lower gate flags more units on real days.
   Real day flags are not labelled false because there is no truth, so the real day tables describe burden, not error rate.
3. The flag rate on null scenarios is nearly empty by construction. Null scenarios inject nothing, and flags present without
   injection are removed before scoring, so a flag can appear on a null footprint only through event merging with a
   neighbouring injected scenario. It is reported because it was asked for, and it is not a measure of the false alarm rate.
4. The system was developed on the development days. The baselines were specified before any run and not tuned, so the
   development comparison favours the system slightly. The held out days were scored once for the system under a frozen
   state, and the baselines were scored on them afterwards without tuning.
5. Injection is a controlled test of sensitivity, not of real world accuracy. Synthetic recall says nothing about how often
   real interference would be detected, and OBSERVED flags are evidence of degraded position quality, not of interference or
   of anyone's actions.
6. Day level intervals resample whole days within the listed regime. With few days in a regime the intervals are wide, and
   regimes with fewer than 2 days have no interval.
7. B3a pools the coverage model as well as the baseline share, because both are regime specific in the system.
8. Tashwish is a research tool. It is not for navigation or for any safety of life use.

Sources: docs/RESEARCH.md, docs/METHODOLOGY.md, docs/PREDICTIONS_AMENDMENT.md, docs/VALIDATION.md, results/dev/synthetic_scenarios.csv, results/held_out/synthetic_scenarios.csv, results/regimes.csv, results/baselines/summary.json.
<!-- END GENERATED RESULTS -->
