# Dashboard and API data contract (`tashwish.web.v1`)

Produced by `python -m tashwish.release.web` (not yet written; the dashboard is built against this contract and a labelled
synthetic sample). All files are static JSON under `web/data/`. Every file carries `schema`, `data_class`
(`observed` or `synthetic`), `generated_at` (UTC ISO), `code_commit`, and `attribution` (the exact string from
`src/tashwish/attribution.py`). A page showing `data_class = synthetic` MUST show a persistent, unmissable SYNTHETIC banner and
must never be shown beside observed data in the same view.

| File | Content |
|---|---|
| `manifest.json` | `schema`, `data_class`, `generated_at`, `code_commit`, `dataset_version`, `attribution`, `grid` (`h3_res`, `bucket_hours`), `bbox`, `days`: list of `{day, split: "dev"\|"held_out", rows, aircraft, ingested_at}`, `latest_day`, `freshness_hours_hint` |
| `days/YYYY-MM-DD.json` | `cells`: array of `[h3, slot, n_aircraft, k_strong, ci_lo, ci_hi, status, coverage_class]` for stratum `enroute`; `status` in `ok, insufficient, coverage_lost`; `coverage_class` in `covered, marginal, no_coverage`; slot = 0..7 (3 h UTC buckets). Missing cell = no row. Insufficient and coverage_lost MUST NOT be drawn as "quiet". |
| `events.json` | array of events: `event_id, kind (jamming_like/spoofing_like/both/uncertain), label_uncertain (bool), confidence (low/medium/high), start, end, n_cells, cells (list of h3), lat, lon, n_aircraft, k_degraded, peak_share, peak_ci_lo, min_p, evidence (free numeric fields, no aircraft identifiers), methods (list of anchors into docs/METHODOLOGY.md)` |
| `coverage.json` | per `[h3, slot]`: `presence`, `class` (fitted on dev days) |
| `validation.json` | headline validation numbers with confidence intervals, generated from `results/` (never typed by hand) |
| `methods.json` | map from metric/field name to `{label_en, label_ar, method_anchor}` so every displayed number links to its method |

Notes: no aircraft identifiers or per point positions appear in any web file. Numbers shown in the UI come only from these files.
