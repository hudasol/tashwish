# Dashboard and API data contract (`tashwish.web.v1`)

Produced by `python -m tashwish.release.web` (not yet written; the dashboard is built against this contract and a labelled
synthetic sample). All files are static JSON under `web/data/`. Every file carries `schema`, `data_class`
(`observed` or `synthetic`), `generated_at` (UTC ISO), `code_commit`, and `attribution` (the exact string from
`src/tashwish/attribution.py`). A page showing `data_class = synthetic` MUST show a persistent, unmissable SYNTHETIC banner and
must never be shown beside observed data in the same view.

| File | Content |
|---|---|
| `manifest.json` | `schema`, `data_class`, `generated_at`, `code_commit`, `dataset_version`, `attribution`, `grid` (`h3_res`, `bucket_hours`), `bbox`, `days`: list of `{day, split: "dev"\|"held_out", rows, aircraft, ingested_at}`, `latest_day`, `freshness_hours_hint`, `mode` (`live` or `study_snapshot`), and for a snapshot `study_window` `{start, end}` |
| `days/YYYY-MM-DD.json` | `cells`: array of `[h3, slot, n_aircraft, k_strong, ci_lo, ci_hi, status, coverage_class]` for stratum `enroute`; `status` in `ok, insufficient, coverage_lost`; `coverage_class` in `covered, marginal, no_coverage`; slot = 0..7 (3 h UTC buckets). Missing cell = no row. Insufficient and coverage_lost MUST NOT be drawn as "quiet". |
| `events.json` | array of events: `event_id, kind (jamming_like/spoofing_like/both/uncertain), label_uncertain (bool), confidence (low/medium/high), start, end, n_cells, cells (list of h3), lat, lon, n_aircraft, k_degraded, peak_share, peak_ci_lo, min_p, evidence (free numeric fields, no aircraft identifiers), methods (list of anchors into docs/METHODOLOGY.md)` |
| `daily.json` | `days`: `{day, split, n, k, share, ci_lo, ci_hi}` region wide en route degraded share per day; read by the dashboard panel on the change in the data from early March |
| `coverage.json` | per `[h3, slot]`: `presence`, `class` (fitted on dev days) |
| `validation.json` | `results`: rows `{metric, scenario, data_class (synthetic\|observed), regime (pooled\|traffic_normal\|traffic_reduced), value, ci_lo, ci_hi, n, ci_method (wilson\|day_bootstrap), note}`, generated from `results/` (never typed by hand). The file level `data_class` stays `observed` because the loader requires one class per file; each row states its own class and the page shows a SYNTHETIC or OBSERVED chip per row in two tables. Older rows without the per row fields are accepted: class is inferred from the scenario id (`synthetic...`), regime defaults to `pooled`, `ci_method` to `wilson`. |
| `methods.json` | map from metric/field name to `{label_en, label_ar, method_anchor}` so every displayed number links to its method |

Notes: no aircraft identifiers or per point positions appear in any web file. Numbers shown in the UI come only from these files.

Build mode: `python -m tashwish.release.build --mode live|study_snapshot` (default from environment `TASHWISH_MODE`, else `live`).
`live` is what the scheduled incremental workflow uses (it passes no mode); the dashboard then warns when data is stale.
`study_snapshot` marks a fixed study dataset: the dashboard shows "STUDY SNAPSHOT, start to end, not live" instead of the
staleness warning. The mode is written to both `web/data/manifest.json` and `release/manifest.json`.

## `baselines.json` (`tashwish.web.baselines.v1`, optional)

Written by the same build only when `results/baselines/summary.json` exists; otherwise the file is absent (a file left by an
earlier build is removed) and the validation page hides the section "Comparison with simple detectors". Absence is never an
error. It carries the common fields (`data_class` is `observed` at file level, as for `validation.json`) and `results`: rows
`{metric, tier (jamming recall only), data_class (synthetic|observed), split (dev|held_out), regime (pooled|traffic_normal|traffic_reduced), detector, label_en, label_ar, value, ci_lo, ci_hi, n}`.
Every number is copied from the summary by a pure function (`baseline_rows` in `release/build.py`); gaps stay null.

| `metric` | `data_class` | `value`, `n` |
|---|---|---|
| `jamming_recall` (with `tier` easy, medium, hard, random) | synthetic | recall on injected scenarios, harness rule; `n` scenarios; 95% day bootstrap interval |
| `spoofing_recall_3plus` | synthetic | recall on injected spoofing of 3 or more aircraft; `n` scenarios |
| `flagged_per_day_jamming_like` | observed | mean flagged cell buckets per real day; `n` days |
| `flagged_per_day_spoofing_like` | observed | mean flagged origin units per real day; `n` days |

Real day rows are a burden count, not an error rate: there is no ground truth. `split` `held_out` is labelled post hoc, not
preregistered. Rows with `data_class` synthetic stay out of the observed release, so this file is written to `web/data/` only.
