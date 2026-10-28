# Architecture

Principle: **precompute everything, serve static files.** Static outputs are cheap, fast, auditable and hard to break.
The API is a thin read only layer over the same released files. Method details are in [METHODOLOGY.md](METHODOLOGY.md).

## Data flow

```
adsb.lol globe_history (GitHub Releases, ODbL)
        |  ranged, resumable HTTPS download (64 MiB chunks, retries)
        v
tashwish.ingest  -- stream tar -> parse gzip JSON traces -> filter to Gulf box
        |           validate schema, write data/interim/points/YYYY-MM-DD.parquet  (raw bytes discarded)
        |           write data/interim/manifest.jsonl  (day, source tag, sizes, rows, sha256, code version)
        |           write data quality report per day
        v
tashwish.metrics -- per (H3 cell, hour, altitude stratum): unique aircraft, degraded counts, Wilson CI, shrinkage
        v
tashwish.coverage -- empirical receiver coverage per (cell, hour of day, altitude band) -> sufficiency flag
        v
tashwish.detect   -- jamming-like events (baseline + Wilson bound + FDR + hysteresis)
        |            spoofing-like events (kinematics + clustering)
        v
data/processed/*.parquet   cell_hour metrics, coverage, events, event_evidence
        |
        +--> tashwish.validate  (synthetic injection, weak label replay, robustness)  -> docs/research/VALIDATION.md + results/
        +--> tashwish.release   (versioned dataset + data card + checksums)
        +--> tashwish.api       (FastAPI, read only, DuckDB over Parquet)
        +--> web/               (static dashboard built from processed outputs)
```

## Stack and why

| Choice | Why | Alternatives considered |
|---|---|---|
| Python 3.13 | Matches the owner's environment; scientific stack | - |
| DuckDB + Parquet | Columnar, single file, SQL for aggregation, zero server; Parquet is the released format too | SQLite (poor for analytics), Postgres (needs a server) |
| H3 (Uber) | Equal ish area hexes, hierarchical, standard; resolution table sourced in [research/RESEARCH.md](research/RESEARCH.md) | Lat/lon grid (distorts cell area), S2 |
| NumPy / SciPy / pandas | Wilson intervals, FDR, clustering; no heavy ML needed because methods are interpretable by design | scikit-learn only where a clustering primitive is needed |
| FastAPI | Typed, OpenAPI docs for free, tiny | Flask |
| MapLibre GL + deck.gl front end | Open source maps, performant hex layers, RTL capable UI | Leaflet (slow for many polygons), Mapbox (token and terms) |
| pytest + hypothesis + ruff | Property tests for statistics, fast lint | - |
| GitHub Actions | CI badge, runs tests and lint on a clean checkout | - |

The product contains no generated narrative text.

## Package layout

```
src/tashwish/
  config.py        region box, H3 resolutions, thresholds
  schema.py        Arrow schema of the point table, data_class (observed | synthetic) rules
  split.py         deterministic development and held out day split
  regime.py        day level traffic and degraded regime labels
  pipeline.py      stage orchestration from points to detections
  attribution.py   attribution wording, the single source for every public surface
  cli.py           the tashwish command
  ingest/          source adapter, ranged download, trace parsing, quality report
  metrics/         degradation tiers, per cell aggregation, statistics (Wilson, shrinkage, FDR), grid feasibility
  coverage/        empirical receiver coverage model
  detect/          jamming-like and spoofing-like detectors, event discrimination
  validate/        injection scenarios (synthetic), harness, coverage test, sensitivity study
  operate/         incremental run, scoring against the frozen state, refit
  release/         dataset and dashboard data build, data card, checksums
  api/             read only FastAPI service
  interop/         Marsad and Sirb file formats, synthetic samples
tests/             unit, property and integration tests; small fixtures in tests/fixtures (labelled synthetic where invented)
web/               static dashboard
docs/              user and developer documents (index in docs/README.md); docs/research holds the study records
scripts/           document generators, regime and freshness checks, forward scoring
```

## Key design decisions (reversible, recorded)

1. **Unique aircraft counting.** Prevents long lived or chatty aircraft dominating a cell bucket
   (see [METHODOLOGY.md](METHODOLOGY.md), section Unique aircraft count).
2. **"Insufficient data" is a state, not a colour.** Any cell bucket failing the coverage or minimum sample test is
   rendered distinctly and excluded from "quiet" statistics (see [METHODOLOGY.md](METHODOLOGY.md), section Minimum sample rule).
3. **Observed and synthetic never share a table.** Different directories, different schemas (`data_class` column checked
   at write time), different UI layers.
4. **Everything is a pure function of the manifest.** Re running a stage on the same inputs and code version yields the
   same bytes (Parquet written with fixed settings, sorted rows). Tests assert this.
5. **Raw archives are never stored or redistributed.** The pipeline streams, filters and discards them. Only derived aggregates are released.
6. **Hosting:** static dashboard on Vercel (or Render static site); read only API on Render. Both deploy from the repository.

## Failure modes handled

- Download interrupted by the egress proxy (connections are cut after roughly 100 seconds): ranged chunks with retries; a
  day is only marked complete when the whole tar parsed and row counts reconcile.
- Archive day missing or truncated upstream: manifest records it as a gap; gaps are shown, never interpolated.
- Receiver set changes: coverage model is time varying; step changes in coverage are flagged in the data quality report.
- Field sparsity: measured per day and published; thresholds only use fields above a documented presence rate.

## Open items to be settled with data (see [DATA_QUALITY.md](DATA_QUALITY.md))

- Presence rates of NIC, NACp, SIL, SDA, ADS-B version proxies in the archive.
- Whether position source (ADS-B vs MLAT vs Mode S) is separable per point, so MLAT derived positions can be excluded.
