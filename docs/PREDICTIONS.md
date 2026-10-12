# Pre-registered predictions

Written and committed BEFORE any held-out day was analysed. A prediction file that is edited after results exist is
worthless, so: the git history of this file is part of the evidence. After the single held-out run, results are appended in
`docs/PREDICTIONS_RESULTS.md` (generated from result files), never by editing this file.

## 0. Protocol

- **Study window:** 2026-02-07 to 2026-03-13 inclusive, 35 UTC days, adsb.lol globe_history (see DATA_SOURCES.md section 7).
- **Split rule (fixed in `src/tashwish/split.py`, rule id `tashwish-heldout-v1`):** a day is held out when
  `sha256("tashwish-heldout-v1|YYYY-MM-DD") mod 3 == 0`, except days inspected before the rule existed, which are DEV by declaration.
- **Resulting split:** 21 DEV days, 14 HELD-OUT days:
  `2026-02-07, 02-10, 02-11, 02-12, 02-15, 02-18, 02-24, 02-26, 02-28, 03-01, 03-03, 03-08, 03-10, 03-13`.
- **Disclosures about prior exposure** (so the reader can judge): (a) `2026-03-02` was explored during M1 to M3 and is DEV by
  declaration. (b) The ingest log printed row and aircraft counts for `2026-02-14` (DEV) and `2026-02-15` (HELD-OUT): about
  1.75 to 1.79 million rows and about 2,130 aircraft per day. Nothing else about `02-15` was examined. (c) The window start
  and the modulus were changed once, from (14 Feb, mod 4, 3 held-out days) to (7 Feb, mod 3, 14 held-out days), purely to get
  enough held-out days for confidence intervals, before any held-out result existed.
- **No tuning on held-out days:** thresholds, baselines (`p0`), coverage fits, detector rules and scenario designs use DEV days
  only. Baselines and coverage for evaluating a held-out day are fitted on all 21 DEV days.
- **Run once:** the held-out run is executed once at a frozen code commit and frozen `config.py`; the commit hash is recorded in
  the results. If a bug is found afterwards, the fix is reported as a second, labelled run, and the first stays in the report.
- **Incident reports are weak labels, not ground truth.** No prediction below treats a report as proof of interference, and no
  result attributes interference to any actor.
- **Synthetic scenarios** (injection) are labelled synthetic everywhere and never appear in real views.

## 1. Predictions

Confidence is my subjective probability that the prediction passes. "Pass" criteria are exact so hits and misses are mechanical.

### Data and ingest

| ID | Prediction | Pass criterion | Confidence |
|---|---|---|---|
| D1 | Every held-out day exists in the archive and ingests | 14 of 14 days complete in the manifest | 0.90 |
| D2 | Daily volume is similar to the two days whose counts I saw | every held-out day has 1.2 to 2.6 million rows and 1,600 to 2,800 unique aircraft | 0.80 |

### Coverage model (fitted on DEV days, tested on held-out days)

Unit: a (cell, 3 h slot, stratum=enroute) triple on a held-out day. "Enough" = at least `MIN_AIRCRAFT_PER_CELL` aircraft observed.

| ID | Prediction | Pass criterion | Confidence |
|---|---|---|---|
| C1 | Cells classed `covered` are mostly enough on a new day | P(enough given covered) >= 0.70 | 0.65 |
| C2 | Cells classed `no_coverage` are rarely enough on a new day | P(enough given no_coverage) <= 0.15 | 0.70 |
| C3 | The model does wrongly claim coverage sometimes, mostly at low traffic hours | 0.10 <= P(not enough given covered) <= 0.35, and the failure rate in slots 0 and 1 (00 to 05 UTC) exceeds the rate in slots 3 to 5 (09 to 17 UTC) | 0.55 |
| C4 | `coverage_lost` flags carry information | among covered triples, P(enough on the NEXT bucket | coverage_lost now) < P(enough on the next bucket | ok now) | 0.60 |

### Jamming-like detector on SYNTHETIC injection into held-out real traffic

Injection raises the degraded share in chosen real cell-buckets (labelled synthetic, `data_class = synthetic`). Difficulty axes:
intensity (target degraded share 0.3 / 0.5 / 0.8), area (1 / 3 / 7 cells), duration (1 / 2 / 3 buckets), traffic (aircraft per cell-bucket).
Event level recall: an injected scenario is detected if at least one event overlaps it in space and time.

| ID | Prediction | Pass criterion | Confidence |
|---|---|---|---|
| J1 | Easy scenarios are found | intensity 0.8, 3+ cells, 2+ buckets, >=10 aircraft per cell: event recall >= 0.95 | 0.80 |
| J2 | Medium scenarios mostly found | intensity 0.5, 3 cells, 2 buckets, >=10 aircraft: event recall between 0.70 and 0.95 | 0.55 |
| J3 | Hard scenarios mostly missed | intensity 0.3 OR <8 aircraft per cell, 1 cell, 1 bucket: event recall <= 0.50 | 0.75 |
| J4 | Detection delay is short when detected | median delay <= 0 buckets (first affected bucket) for easy, <= 1 bucket for medium | 0.70 |
| J5 | False events on un-injected held-out days are rare | <= 0.5 events of confidence medium or high per held-out day on average | 0.55 |
| J6 | Recall rises with intensity, area, aircraft count and duration | the rate is non-decreasing along each axis with other axes at medium (allowing ties) | 0.85 |

### Spoofing-like detector and jamming versus spoofing discrimination (SYNTHETIC)

Scenario kinds: `jam_only` (accuracy degraded, positions honest), `spoof_jump` (positions displaced to a common false location for
>=3 aircraft, accuracy fields nominal), `spoof_and_jam` (both), `null` (nothing injected). Labels allowed from the system: `jamming_like`,
`spoofing_like`, `both`, `uncertain`, `none`.

| ID | Prediction | Pass criterion | Confidence |
|---|---|---|---|
| S1 | `spoof_jump` with >=3 aircraft is detected as spoofing-like | recall >= 0.80 | 0.65 |
| S2 | `spoof_jump` is NOT flagged by the jamming detector (accuracy nominal) | jamming flag rate on `spoof_jump` <= 0.10 | 0.85 |
| S3 | `jam_only` is not called spoofing-like | spoofing-like flag rate on `jam_only` <= 0.10 | 0.80 |
| S4 | The system says `uncertain` for a meaningful minority and is right more often when it commits | uncertain share between 0.05 and 0.30 of detected events; accuracy among committed labels >= 0.85 | 0.50 |
| S5 | `spoof_jump` with only 1 or 2 aircraft is mostly missed (by design) | recall <= 0.30 | 0.80 |

### Real held-out days with weak labels (reports are context, not truth)

Held-out days with a cited report: `2026-02-28` (maritime report, secondary), `2026-03-13` (CAAS SIB text). Non incident held-out days are
the other 12. Dev incident days (`03-02`, `03-07`) are not tests.

| ID | Prediction | Pass criterion | Confidence |
|---|---|---|---|
| R1 | Some interference-like activity on report days | each of 02-28 and 03-13 has at least one event (jamming-like medium+ or spoofing-like) inside the box | 0.55 |
| R2 | Report days are busier than non report days | mean events per day on {02-28, 03-13} > mean events per day on the other 12 held-out days | 0.55 |
| R3 | A background rate exists | at least 4 of the 12 non report held-out days have at least one event of any kind | 0.65 |
| R4 | The Gulf north (lat > 26) carries most events | share of event centroid lat > 26 is >= 0.5 | 0.60 |

### Sensitivity (on DEV days only, no held-out data)

| ID | Prediction | Pass criterion | Confidence |
|---|---|---|---|
| X1 | Event counts are most sensitive to the effect-size gate and min aircraft, least to the FDR q | rank of absolute change in event count for +/-25% on each parameter: gate and min aircraft both above q | 0.65 |
| X2 | Event locations are stable under +/-25% threshold changes | >= 70% of baseline events keep a Jaccard overlap of cells >= 0.5 with some event | 0.60 |
| X3 | Day to day variation is large relative to threshold effects | std of daily event count over DEV days / mean > 0.5 | 0.60 |

## 2. How results will be reported

`docs/PREDICTIONS_RESULTS.md` will list every ID, the observed value with a Wilson or bootstrap interval, HIT or MISS, and
the frozen commit. Misses are not explained away in that table; discussion goes in `docs/VALIDATION.md`.
