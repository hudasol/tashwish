# Interface for Sirb: empirical GNSS degradation parameter file (`tashwish.sirb_gnss_params.v1`)

This document is self contained. It specifies a JSON file that Tashwish produces and that Sirb (a drone show planner and
verifier) could read as an **illustrative stress prior**. Sirb's code and repository were not read or touched to write it, and
nothing here changes Sirb. The reference code is `src/tashwish/interop/sirb.py`.

## 1. Read this first: what the numbers are, and what they are not

The parameters come from **public aircraft ADS-B broadcasts, mostly at cruise-type altitudes, over the Gulf**. They describe
how aircraft avionics report their own position quality and how often those reports pause, in ordinary conditions and during
en-route interference. They do **not** describe a drone-scale receiver, low-altitude urban multipath, or a small antenna. A
drone near the ground sees a different signal environment, a different receiver and a different failure behaviour.

Use them only to shape scenarios, for example "what if reported quality drops for a few minutes and updates thin out", and to
make stress tests honest about uncertainty. Do not use them as a measured model of a drone's GNSS behaviour, as certification
input, for navigation or safety of life, or to say anything about who caused a degradation. The file says so itself in its
`caveats` block (section 5), and Sirb should surface that block wherever it shows the parameters.

## 2. How the file is built

`python -m tashwish.interop.sirb --days 2026-02-08 2026-02-09 --out params.json [--interim data/interim] [--n-boot 1000] [--seed N]`

* **Dev days only.** The days are checked against `tashwish.split`. A held-out day is refused (exit code 2, nothing written)
  unless `--allow-held-out` is passed, in which case `provenance.dev_only` is false and a warning is the first caveat.
  A wrong `split` label in the day metadata is also refused. The held-out set stays untouched for evaluation.
* **Samples.** Airborne position samples broadcast by the aircraft's own transponder (`src_type = adsb_icao`; ground
  vehicles, multilateration positions and samples on the ground are excluded) inside the study box, with barometric altitude.
  Repeated (aircraft, timestamp) rows are removed. Memory is bounded because the CLI loads one day at a time.
* **Quality samples.** Samples that carry their own NIC. Values carried forward from an earlier message (`q_carried`) are used only
  to classify update intervals, never to count quality values, episodes or transitions, so one report is not counted many times.
* **Strongly degraded.** NIC below `NIC_STRONG_BELOW` or NACp below `NACP_STRONG_BELOW` (`tashwish.config`), the same definition
  as the regional detectors.
* **Degraded episode.** A maximal run of one aircraft's consecutive quality samples that are all strongly degraded, with
  neighbours at most `EPISODE_GAP_S` apart, and at least `MIN_EPISODE_SAMPLES` samples (so that it has a duration). Its duration is
  last minus first sample time. Shorter strongly degraded runs ("isolated") belong to neither class and are counted in `n`.
* **Classes.** `baseline`: samples (or intervals starting at samples) that are not strongly degraded. `degraded_episode`:
  samples inside an episode.
* **Strata.** `enroute`, `high`, `mid`, `low` by barometric altitude (cut points in `tashwish.config`); `enroute` is the union
  of `mid` and `high`, so strata overlap by construction. Region: `gulf_box` (the study box of `tashwish.config.REGION`).
* **Uncertainty.** `boot_lo`, `boot_hi` are percentile bootstrap intervals (95%) that resample **aircraft-days** with
  replacement, with a fixed seed so the same input gives the same file. Wilson intervals are also given for shares; they treat
  samples as independent and are therefore too narrow. Poisson exact intervals for the episode rate assume independent episodes
  and are also too narrow. Prefer the bootstrap intervals.
* **Minimum sizes.** A block with too few aircraft-days (`MIN_CLUSTERS`), quality samples (`MIN_N_CATEGORICAL`) or episodes
  (`MIN_EPISODES`, for the duration only) carries `"status": "insufficient"` and no numbers. It is never filled with zeros.

## 3. Parameters

Per `regions.gulf_box.strata.<stratum>`:

| Block | Content |
|---|---|
| `n` | Counts behind the stratum: position samples, quality samples, isolated degraded samples, intervals used, intervals over the horizon, samples flagged by the source as having no position for 20 s before them (a cross check on the dropout measure), single sample runs, unique aircraft, aircraft-days. |
| `baseline.quality_categories`, `degraded_episode.quality_categories` | (a) Categorical distribution of NIC (`nic`) and NACp (`nacp`), keys "0" to "11": `k`, `n`, `share`, `wilson_lo`, `wilson_hi`, `boot_lo`, `boot_hi`. Shares for NACp are among samples that report NACp; `n_nacp_missing` counts the others. Within `degraded_episode` the values are, by definition, limited to the degraded range for at least one of the two fields. |
| `degraded_episode.episodes.duration_s` | (b) Episode duration quantiles (`q05`, `q25`, `q50`, `q75`, `q95`), each with `value`, `boot_lo`, `boot_hi`, in seconds. |
| `degraded_episode.episodes.rate_per_aircraft_hour` | (c) Episodes started per aircraft hour of observed quality-sample time in the stratum (neighbouring samples within the gap), with bootstrap and Poisson exact intervals. `exposure_aircraft_hours` and `n_episodes` are alongside. |
| `<class>.update_interval_and_dropout.update_interval_s` | (d) Quantiles (`q50`, `q90`, `q95`, `q99`) of the seconds between consecutive position samples of one aircraft-day, with bootstrap intervals. Quantiles come from 0.1 s bins below 30 s. Intervals longer than `DT_HORIZON_S` (leg changes, coverage loss) and samples flagged as a new leg are excluded and counted. An interval belongs to the class of the sample it starts at. |
| `<class>.update_interval_and_dropout.dropout` | (d) `share_gt_20s` and `share_gt_60s`: share of intervals longer than 20 s and 60 s, with Wilson and bootstrap intervals. |
| `transitions` | (e) `p_next_degraded_given_current_degraded` and `p_next_degraded_given_current_nominal`: probability that the next quality sample (same aircraft, within the gap) is strongly degraded, with Wilson and bootstrap intervals. Pairs never cross aircraft. |

The `definitions` block of the file restates every threshold and unit used, with the values taken from the code that produced it.

### 3.1 How Sirb could use it

Draw a scenario, not a prediction. For example: pick a stratum closest to the scenario's altitude band as a *loose analogue* only,
sample an episode start from the rate (a Poisson process with the rate and its interval), a duration from the duration quantiles,
sample NIC and NACp values from the degraded-episode categories while an episode is active, and thin the update stream with the
dropout shares. Carry the interval limits through (run the scenario at the low and high ends) so that the report shows how much
the answer depends on the uncertainty. Label every output "illustrative stress prior from aircraft ADS-B, not a drone model".
A block that is `insufficient` cannot be used.

## 4. Provenance block

`provenance` holds: `source`, `dataset_version` (the CLI sets `draft-` plus a digest of the input files' sha256 values unless one is
given), `days` (each with `day`, `split` of `dev` or `held_out`, and the manifest's `rows`, `aircraft`, `out_sha256`, `ingested_utc`,
`ingest_code_version`), `dev_only`, `split_rule`, `code_commit` (short git commit, `+dirty` if uncommitted changes existed),
`tashwish_version`, `attribution` (exactly `tashwish.attribution.DATASET_ATTRIBUTION`), `generated_at`, `seed`, `n_boot`,
`bootstrap_unit`, `confidence_level`. Top level: `schema`, `data_class` (`observed` or `synthetic`), `notice`, `definitions`,
`caveats`, `regions`.

## 5. The `caveats` block

`caveats.summary` states the limits of section 1 in plain words. `caveats.points` lists the specific limits: source and coverage; NIC and
NACp are accuracy classes an aircraft transmits about itself, not measured errors; degradation can come from avionics, not only
interference; update intervals and dropouts mix aircraft behaviour, receiver coverage gaps and archive thinning, and their upper
tail reflects the archive's own sampling near the source's 20 second gap mark; samples are not independent, so use bootstrap
intervals; the file is built from the listed development days only; insufficient means not enough data, not zero; and no attribution.
`caveats.not_for` lists uses that are out of scope. The text is the module constant `sirb.CAVEATS`, and tests assert its key phrases.

## 6. Versioning

The schema id is `tashwish.sirb_gnss_params.v<major>`. Within major 1, new optional members may be added and consumers must ignore
members they do not know. Renaming or removing a member, changing the unit or meaning of a parameter, or changing the definition of a
degraded episode requires a new major version. `provenance.code_commit` and `dataset_version` identify the exact computation.

## 7. Files

* `src/tashwish/interop/sirb.py`: `build_params(points, days_meta, ...)`, the CLI, and the helper functions.
* `interop/samples/sirb_gnss_params_dev21.json`: the file built from all 21 development days (the earlier draft used 7 and was removed).
  The days used are recorded in its `provenance.days`. It is built from development days only (held-out days are excluded by default) and the file
  should be rebuilt if more days are ingested. It is real (observed) data and carries the same caveats.
* `tests/test_interop_sirb.py`: tests on SYNTHETIC point tables with known answers (episode count, duration, rate, transitions,
  dropout shares, category counts), exclusion rules, insufficient blocks, the held-out refusal, the CLI, and seed determinism.
