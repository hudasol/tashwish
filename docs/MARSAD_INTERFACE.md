# Interface for Marsad: regional interference context prior (`tashwish.interference.v1`)

This document is self contained. It specifies a file format and a query contract that Tashwish produces and that Marsad (a
per vehicle position trust layer) could later read. Marsad's code was read but not modified, and
nothing here changes Marsad. The reference code is `src/tashwish/interop/marsad.py` and has no dependency on Marsad.

## 1. What this is, and what it is not

Tashwish measures, from public aircraft ADS-B broadcasts, how many aircraft in a region report degraded position quality. That
is a statement about the regional signal environment at altitude, per H3 cell and time bucket. It is useful to a per
vehicle trust layer only as a **prior**: "in this neighbourhood, at about this time, how common was degraded reporting."

Rules that every producer and consumer must keep:

1. **A prior, never a verdict.** The record says nothing about whether a particular vehicle's position is wrong. It must not
   be used to accuse, flag or exonerate a vehicle on its own.
2. **No attribution.** Nothing in the format names a state, an actor or an intent. `jamming_like` and `spoofing_like` describe
   signal behaviour only.
3. **Evidence, not proof.** Degraded accuracy fields can also come from old avionics or installation faults (see the
   README, honest limitations).
4. **Missing is not clear.** `insufficient`, `coverage_lost`, `no_record`, `stale` and `out_of_region` are all different
   from "no interference". A consumer must never turn any of them into a zero or into `none`.
5. **Altitude.** The data come from aircraft, mostly at cruise altitudes. A ground vehicle or a low drone may experience a very
   different environment. The `alt_band` field states which altitudes a record speaks about.
6. Research and monitoring only. Not a navigation, flight planning or safety of life input.

## 2. Record (one per H3 cell, UTC time bucket and altitude band)

| Field | Type | Meaning |
|---|---|---|
| `h3` | string | H3 cell index. Resolution is `grid.h3_res` of the collection (4 in the default grid, `tashwish.config.GRID_MAIN`). |
| `bucket_start`, `bucket_end` | string (ISO 8601 UTC, ending in `Z`) | Half open interval `[start, end)`. Length is `grid.bucket_hours` (3 in the default grid), aligned to UTC multiples of that length. |
| `alt_band` | string | `enroute` (barometric altitude at or above `ENROUTE_MIN_FT`), `high`, `mid`, `low`. Bands overlap: `enroute` is the union of `mid` and `high`. Cut points are in `tashwish.config`. |
| `p_interference` | number or null | Point estimate of the share of aircraft in the cell bucket that were degraded (the `share_strong` of the metrics table: unique aircraft counted once, degraded means NIC below 4 or NACp below 5 for at least half of the aircraft's samples). **Null unless `status` is `ok`.** It is a share of aircraft, not the probability that any vehicle is affected. |
| `ci_lo`, `ci_hi` | number or null | 95% Wilson score interval for that share. Null unless `status` is `ok`. |
| `kind` | string | `jamming_like`, `spoofing_like`, `both`: an event of that kind overlaps the cell and bucket. `none`: the cell was tested and no event was detected at the detector's thresholds (this is not a statement that interference is absent). `unknown`: the record cannot be classified (not testable, or an altitude band the detectors were not run on). |
| `event_id` | string or null | Id of the overlapping event, as in `events.json` of the web contract. Non null exactly when `kind` is `jamming_like`, `spoofing_like` or `both`. If several events overlap, the smallest id is given and `kind` is merged (`both` if the kinds differ). |
| `n_obs` | integer | Number of distinct eligible aircraft behind the estimate. |
| `coverage_class` | string | `covered`, `marginal`, `no_coverage`: how reliably this cell and time of day is observed by the receiver network, fitted on development days only (`tashwish.coverage.model`). |
| `status` | string | `ok`: enough aircraft to test (`n_obs` at least `MIN_AIRCRAFT_PER_CELL`) in a cell that is not `no_coverage`. `insufficient`: too few aircraft, no statement is made. `coverage_lost`: the cell is normally covered but this bucket has far fewer aircraft than usual or none. |
| `data_quality` | string | Summary of how much weight a consumer may put on the record: `good` (ok, covered, `n_obs` at least `GOOD_MIN_AIRCRAFT`), `limited` (ok otherwise), `poor` (not ok). The thresholds are design choices in `marsad.py`. |
| `data_class` | string | `observed` or `synthetic`. Synthetic data are invented for tests and demonstrations and must never be used as a prior. |
| `attribution` | string | Exactly `tashwish.attribution.DATASET_ATTRIBUTION` (ODbL notice for adsb.lol and for the derived aggregates). |
| `dataset_version` | string | Version label of the dataset the record belongs to. |
| `generated_at` | string (ISO 8601 UTC) | When the file was produced. |

Invariants (enforced by `validate_feature_collection`):

* `status = ok` implies numeric `p_interference`, `ci_lo`, `ci_hi` with `0 <= ci_lo <= p_interference <= ci_hi <= 1`.
* `status != ok` implies all three are null, `kind` is not `none`, and `data_quality` is `poor`.
* `kind = none` only occurs for `alt_band = enroute`, the band the detectors are run on.
* `(h3, bucket_start, alt_band)` is unique. Cells with no row at all are simply absent: absence means "not observed", never "clear".
* No `NaN` or infinity anywhere. Unknown properties are rejected (additions need a new minor version, section 6).

## 3. Layouts

### 3.1 GeoJSON FeatureCollection

One Feature per record. Geometry is the H3 cell polygon (RFC 7946, counterclockwise exterior ring, `[longitude, latitude]`).
The Feature `id` is `h3|bucket_start|alt_band`. `properties` holds exactly the fields of the first group of the table above
(`h3` to `data_class`). The three fields that are constant for the whole file (`attribution`, `dataset_version`,
`generated_at`) are top level members of the collection and apply to every Feature; the query response (section 4) repeats them.

Top level members:

```
type, schema ("tashwish.interference.v1"), data_class, notice, dataset_version, generated_at, code_commit,
tashwish_version, attribution, grid {h3_res, bucket_hours}, max_age_hours, features
```

`notice` is mandatory. For synthetic files it begins with `SYNTHETIC DATA` and the file name must contain `SYNTHETIC`.
A synthetic sample is committed at `interop/samples/marsad_context_SYNTHETIC_sample.geojson`; it is generated by
`scripts/make_marsad_synthetic_sample.py` from seeded invented cells (`tashwish.interop.synthetic`). Real sample files are
produced later from real results.

### 3.2 Parquet

The same records as a flat table, no geometry (a consumer can derive it from `h3`). Column order and types are
`marsad.PARQUET_SCHEMA`: `h3`, `bucket_start`, `bucket_end` (timestamp, ms, UTC), `alt_band`, `p_interference`, `ci_lo`, `ci_hi`
(nullable float64), `kind`, `event_id` (nullable string), `n_obs` (int32), `coverage_class`, `status`, `data_quality`,
`data_class`, `attribution`, `dataset_version`, `generated_at`. File level key value metadata: `tashwish.schema`,
`tashwish.grid` (JSON), `tashwish.max_age_hours`, `tashwish.notice`, `tashwish.code_commit`, `tashwish.generated_at`.

### 3.3 Producing and checking

```
from tashwish.interop.marsad import to_geojson, to_parquet, validate_feature_collection
fc = to_geojson(cb, events, dataset_version=..., data_class="observed", path="context.geojson")
assert validate_feature_collection(fc) == []
to_parquet(cb, events, "context.parquet", dataset_version=..., data_class="observed")
```

`cb` is the cell bucket metrics table from `tashwish.metrics.aggregate.cell_bucket_metrics` after
`tashwish.coverage.model.apply_coverage` (columns `cell, bucket, stratum, n_aircraft, share_strong, ci_lo_strong,
ci_hi_strong, status, coverage_class`). `events` is the table from `tashwish.detect.discriminate.combine`
(`event_id, kind, start, end, lat, lon, cells`). An event is attached to every cell it lists and every bucket it overlaps;
a spoofing-like event with no listed cells is attached to the cell containing its origin point.

## 4. Query contract

```
GET /v1/context?lat=<deg>&lon=<deg>&t=<ISO 8601 UTC, ends in Z>&alt_ft=<barometric feet, optional>&mode=<retrospective|nowcast, optional>
```

`lat`, `lon`, `t` are required. `alt_ft` selects the band: at or above the high cut, try `high` then `enroute`; at or above the
en route cut, `mid` then `enroute`; below it, `low` only; omitted means `enroute`. A malformed request is HTTP 400
(`ValueError` in the reference code). Every other outcome is HTTP 200 with a `status`, so that a consumer cannot mistake an
error page for data.

Modes:

* `retrospective` (default): the record whose bucket contains `t`. For replay and analysis.
* `nowcast`: the latest completed bucket with `bucket_end <= t`. If `t - bucket_end` exceeds `max_age_hours` the answer is `stale`.

Response (JSON):

```
{ "schema": "tashwish.interference.v1",
  "status": "ok | insufficient | coverage_lost | no_record | stale | out_of_region",
  "usable_as_prior": true only when status is "ok",
  "reason": "plain words",
  "query": { lat, lon, t, alt_ft, mode },
  "record": { the record fields of section 2 } or null,
  "age_hours": number or null, "max_age_hours": number,
  "dataset_version", "generated_at", "data_class", "attribution", "notice" }
```

`record` is present for `ok`, `insufficient`, `coverage_lost` and `stale` (so the caller can log what was seen) and null
otherwise. The reference implementation is `marsad.ContextIndex(feature_collection).query(...)`; a web service is a thin
wrapper around it.

### 4.1 How a consumer must treat each status

| `status` | Meaning | What a consumer does |
|---|---|---|
| `ok` | Tested, estimate with interval | May use `p_interference` with `ci_lo`, `ci_hi` as a prior, subject to `data_quality` and `data_class` |
| `insufficient` | Too few aircraft | No information. Use the consumer's own default prior. Never treat as clear |
| `coverage_lost` | Receivers that normally see this cell did not | No information, and a mild reason for caution. Never treat as clear |
| `no_record` | The collection has no row for this cell, time or band | Same as insufficient |
| `stale` | Latest record is older than `max_age_hours` (nowcast) | Same as insufficient |
| `out_of_region` | Position outside the study box | Same as insufficient |
| `data_class = synthetic` | Invented data | Refuse to use as a prior |

A consumer must never substitute a number, and above all never zero, for a missing or non `ok` answer. In particular the
absence of interference evidence is not evidence of absence.

### 4.2 Staleness

Tashwish is a batch pipeline over daily archives, so a bucket is only available some time after it ends. Each collection
carries `max_age_hours` (default `marsad.STALENESS_MAX_AGE_HOURS`, a design choice, not a standard). Consumers read the
value from the collection and do not hard code it. Age is `t - bucket_end` in `nowcast` mode. In `retrospective` mode there is
no age limit, because the record is about `t` itself; the consumer should still check `generated_at` against the version it has validated.

## 5. Worked example (all numbers below are from the SYNTHETIC sample, not observed)

The sample file contains records such as the following (invented data, `data_class` synthetic).

A tested cell with a synthetic jamming-like event: `h3 8443127ffffffff`, bucket `2026-01-01T09:00:00Z` to `12:00:00Z`,
`alt_band enroute`, `p_interference 0.566667`, `ci_lo 0.391973`, `ci_hi 0.726225`, `kind jamming_like`,
`event_id SYN-J-0001`, `n_obs 30`, `coverage_class covered`, `status ok`, `data_quality good`.

A tested cell with no detected event: `h3 8443a1bffffffff`, bucket `06:00` to `09:00`, `p_interference 0.028571`, `ci_lo 0.005061`,
`ci_hi 0.145331`, `kind none`, `n_obs 35`, `status ok`. Note that the interval does not shrink to zero: "none" here means
"no event detected", and the upper bound is still above the point estimate.

A cell that could not be tested: `h3 8443ac9ffffffff`, same bucket, `p_interference null`, `ci_lo null`, `ci_hi null`,
`kind unknown`, `n_obs 1`, `coverage_class marginal`, `status insufficient`, `data_quality poor`.

### 5.1 How Marsad could use it (description only; nothing is implemented in Marsad)

Marsad scores a vehicle track with its own evidence (for example kinematic consistency, accuracy fields, cross checks). A
regional prior can only move the starting point of that scoring, in four steps:

1. For the vehicle's position and time, call the query. If `usable_as_prior` is false, or `data_class` is synthetic, skip the
   prior and use Marsad's own default starting point. This is the main path for missing data and is deliberately a no op.
2. If `ok`, convert the Tashwish share into a bounded adjustment of Marsad's prior odds that "the environment around this
   vehicle is degraded". Use the interval, not only the point estimate: the adjustment is computed from `ci_lo` and `ci_hi`, so a
   wide interval (small `n_obs`) produces a small and uncertain adjustment, and `data_quality` of `limited` shrinks it further.
   The share is a share of aircraft at altitude, so for vehicles far from that altitude the adjustment should be damped by a
   Marsad side factor that Marsad must calibrate on its own data. Tashwish does not supply that factor.
3. Combine with the vehicle evidence in the usual Bayesian way: posterior odds = adjusted prior odds times the likelihood ratio from
   the vehicle's own evidence. The regional prior never acts as evidence about the vehicle; it only changes how much vehicle
   evidence is needed.
4. Report the prior and its source (`dataset_version`, `event_id` if any) beside the vehicle score, so that a reader can see that
   a score was influenced by regional context and by how much. When the prior was skipped, say so.

On the synthetic example: the jamming-like cell would justify a prior that the neighbourhood is degraded, with a wide interval
(0.391973 to 0.726225); the quiet cell would justify little change, with an upper bound that is still not zero; and the
`insufficient` cell would justify no change at all, and must not be treated as being quiet.

A prior may make Marsad more cautious in a degraded neighbourhood. It must not lower Marsad's caution because a cell looks
quiet or because data are missing.

## 6. Versioning and backward compatibility

* The schema id is `tashwish.interference.v<major>`. This document defines major 1.
* Within a major version a producer may add new optional top level members and new optional properties only if consumers can
  ignore them. The validator in this repository is strict (it rejects unknown properties) so that additions are made
  deliberately; consumers should be tolerant of unknown members and strict about the ones they use.
* Adding a value to `kind`, `status`, `coverage_class`, `alt_band` or `data_quality`, removing or renaming any field, changing the
  meaning of `p_interference` or of the intervals, or changing grid semantics requires a new major version. A consumer that meets an
  unknown value of one of these enumerations must treat the record as `insufficient`.
* Changing the grid (resolution or bucket length) is not a breaking change in the format, because the grid is stated in the
  collection, but a consumer must read `grid` and must not assume it.
* Old major versions are produced in parallel for a deprecation period announced in the dataset notes.
* `dataset_version` changes whenever the numbers could change (new days, new thresholds, new coverage fit). Consumers should store it
  with any score that used the prior.

## 7. Provenance and licensing

Every file carries the exact attribution string from `src/tashwish/attribution.py` (`DATASET_ATTRIBUTION`); the licence analysis is in
`docs/LICENSING.md`, section 4. The data are aggregates by cell and time bucket; no aircraft identifier or per point position is included.
