# Release API (`tashwish.api.v1`)

A read only JSON service over one released dataset directory. It adds no data of its own: every number is a row of the
release Parquet files, and every response says which `dataset_version` it came from. Code is Apache-2.0, the data is ODbL 1.0.
Attribution: `src/tashwish/attribution.py` (`DATASET_ATTRIBUTION`), sent on every response.

Install and run (the API is an optional extra, the base install does not need FastAPI):

```bash
pip install '.[api]'
python -m tashwish.api --release-dir release/ --port 8000
# or, as on Render:
TASHWISH_RELEASE_DIR=release uvicorn tashwish.api.app:create_app_from_env --factory --port 8000
```

Interactive documentation is at `/docs` and the OpenAPI document at `/openapi.json`. Deployment: [render.yaml](../render.yaml).

## Release directory it serves

```
release/manifest.json        schema tashwish.release.v1 (dataset_version, generated_at, code_commit, data_class,
                             attribution, grid, bbox, days, latest_day, files{name: {path, sha256, bytes}})
release/cell_buckets.parquet h3, bucket_start, slot, stratum, n_aircraft, k_strong, share, ci_lo, ci_hi, status, coverage_class, data_class
release/events.parquet       event_id, kind, label_uncertain, confidence, start, end, lat, lon, n_cells, cells, ... , day, data_class
release/coverage.parquet     h3, slot, stratum, presence, mean_n, coverage_class
release/validation.json  freshness.json  DATA_CARD.md  NOTICE  checksums.sha256  ODbL-1.0.txt
```

At start the service checks: manifest schema and keys, `attribution` equals the code constant, every listed file exists with the
listed size, the three Parquet files have the required columns, and the `data_class` of the rows equals the manifest
`data_class` (a release that mixes synthetic and observed rows is refused). Set `TASHWISH_VERIFY_HASHES=1` to also verify every
SHA-256 at start (reads every file, so it slows the cold start). If `manifest.json` changes on disk, the next request
reloads the release; a failed reload keeps serving the last good one.

## Endpoints

All are `GET` and return JSON, except downloads. List endpoints return an envelope
`{schema, dataset_version, data_class, attribution, [synthetic_notice], count, limit, next_cursor, data}`.

| Endpoint | Purpose |
|---|---|
| `/health` | Liveness: `{status, dataset_version, latest_day, age_hours, data_class}`. `status` is `ok`, or `stale` when `age_hours` exceeds 48. Always HTTP 200. Reads only cached small JSON. |
| `/v1/manifest` | The release manifest. |
| `/v1/days` | Days with `split` (`dev`, `held_out`), row and aircraft counts, grid, `latest_day`. |
| `/v1/cells?day=&slot=&stratum=&status=&limit=&cursor=` | Cell/bucket rows, ordered by `bucket_start, h3, stratum`. `limit` 1 to 5000 (default 1000). |
| `/v1/events?from=&to=&kind=&min_confidence=&uncertain=&limit=&cursor=` | Events overlapping the window, ordered by `start, event_id`. `limit` 1 to 1000 (default 200). |
| `/v1/events/{event_id}` | One event. |
| `/v1/coverage?slot=&stratum=&limit=&cursor=` | Receiver coverage model. `limit` 1 to 5000 (default 1000). |
| `/v1/validation` | `validation.json` as released (404 if the release has none). |
| `/v1/freshness` | `freshness.json` plus `age_hours`. Never cached. |
| `/v1/context?lat=&lon=&t=&alt_ft=&mode=` | Interference context prior, schema `tashwish.interference.v1` (below). |
| `/v1/download/{name}` | Streams a file listed in `manifest.files`. SHA-256 in `X-Content-SHA256`. Anything not listed is 404. |

Parameter rules: `day` is a real calendar date `YYYY-MM-DD` and must be in the release (else 404 `day_not_in_release`); `slot` is
`0..(24/bucket_hours - 1)`; `stratum` is `enroute|high|mid|low`; `status` is `ok|insufficient|coverage_lost`; `kind` is
`jamming_like|spoofing_like|both|uncertain`; `min_confidence` is `low|medium|high` and means "at least"; `uncertain` is
a boolean on `label_uncertain`. `from` and `to` are `YYYY-MM-DD` (the whole UTC day) or `YYYY-MM-DDTHH:MM[:SS]Z`. Unknown and repeated
query parameters are rejected.

### Never a zero

`insufficient` and `coverage_lost` rows in `/v1/cells` have `share`, `ci_lo`, `ci_hi` and `k_strong` equal to `null`, even if a
file contained numbers there. `/v1/context` has the explicit statuses `ok`, `insufficient`, `coverage_lost`, `no_record`,
`stale` and `out_of_region`; only `ok` has `usable_as_prior: true`, and a synthetic release never does. Treat every other status as
"no information", not as "clear" ([MARSAD_INTERFACE.md](MARSAD_INTERFACE.md) section 4.1). An event of kind `uncertain`
overlapping an `ok` cell gives `kind: "unknown"` in the context record, never `none`.

`/v1/context` follows `tashwish.interop.marsad.ContextIndex` and a test compares the two on hundreds of probes. Differences,
all on purpose: malformed input is HTTP 422 (the interface document says 400); a synthetic release returns
`usable_as_prior: false`; the staleness limit is `marsad.STALENESS_MAX_AGE_HOURS`.

## Examples

```bash
B=http://localhost:8000
curl -s $B/health
curl -s "$B/v1/days"
curl -s "$B/v1/cells?day=2026-01-10&stratum=enroute&status=ok&limit=100"
curl -s "$B/v1/events?from=2026-01-10&to=2026-01-11&min_confidence=medium"
curl -s "$B/v1/events/synth-ev-001"
curl -s "$B/v1/context?lat=25.2&lon=55.3&t=2026-01-10T07:00:00Z&alt_ft=35000&mode=retrospective"
curl -sOJ "$B/v1/download/cell_buckets.parquet"
curl -si -H 'If-None-Match: W/"..."' "$B/v1/days"          # 304 when unchanged
```

Paging: repeat the request with `cursor=<next_cursor>` until `next_cursor` is `null`:

```bash
url="$B/v1/cells?day=2026-01-10&limit=5000"; cur=""
while :; do
  r=$(curl -s "$url${cur:+&cursor=$cur}"); echo "$r" | jq -c '.data[]' >> cells.jsonl
  cur=$(echo "$r" | jq -r '.next_cursor // empty'); [ -z "$cur" ] && break
done
```

A cursor is opaque, bound to the endpoint, the filters and the `dataset_version`. Reusing it with other filters is 422; reusing it after the
release changed is 409 `stale_cursor`.

## Headers on every response

| Header | Value |
|---|---|
| `X-Attribution` | exactly `DATASET_ATTRIBUTION` (ODbL notice for adsb.lol and the derived database) |
| `X-Data-Class` | `observed` or `synthetic` |
| `X-Dataset-Version` | the loaded `dataset_version` |
| `X-Synthetic: true` | only for synthetic releases, together with a top level `synthetic_notice` in the body. Show it. |
| `ETag`, `Cache-Control` | see Caching |

## Error model

Every error is `{"error": {"code", "message", "details"?}}` (plus `synthetic_notice` for synthetic releases) with the headers above.

| HTTP | `code` | When |
|---|---|---|
| 404 | `not_found`, `day_not_in_release`, `event_not_found`, `file_not_listed`, `validation_unavailable` | resource not in this release |
| 405 | `method_not_allowed` | any method other than GET. The API has no write operation. |
| 409 | `dataset_version_mismatch`, `stale_cursor` | pinned version or cursor from another release |
| 414 | `query_too_long` | query string over 2048 characters |
| 422 | `invalid_request`, `unknown_parameter`, `repeated_parameter`, `invalid_cursor`, `invalid_day`, `invalid_slot`, `invalid_timestamp`, `invalid_range`, `invalid_t` | bad input; `details` lists `{field, message}` and never echoes the value |
| 429 | `rate_limited` | over the per client limit; honour `Retry-After` |
| 500 | `internal_error` | no internals are returned |

## Caching

* Every cacheable response has a weak `ETag` derived from `dataset_version` and the request. Send `If-None-Match` to get a bodyless `304`.
* The `ETag` hashes the dataset version, the SHA-256 of `checksums.sha256` from the manifest (which covers every release file), the path and the query. A rebuild with changed content therefore changes every ETag even if the day label is unchanged.
* Default `Cache-Control: public, max-age=300, must-revalidate`.
* Add `dataset_version=<current value>` to any `/v1` request to pin it: the answer cannot change for that version, so it is sent as
  `public, max-age=31536000, immutable`, and a version that is not the loaded one is `409`.
* `/health` and `/v1/freshness` are `no-cache`. Errors are `no-store`.

## Limits and safety

* No unbounded response: lists are paged (cells and coverage at most 5000 rows, events at most 1000), downloads are streamed.
* Per client sliding window rate limit, default 300 per minute (`TASHWISH_RATE_LIMIT_PER_MIN`, 0 disables), keyed on the peer address.
  `X-Forwarded-For` is client controlled and is ignored unless `TASHWISH_TRUSTED_PROXY_HOPS` is set to the number of trusted
  proxies in front of the app; the entry that many hops from the right is then used. The key store is bounded (least recently
  seen keys are evicted one at a time). `/health` is exempt. The window lives in process memory.
* DuckDB runs with one thread and a 256 MB memory limit by default (`TASHWISH_DUCKDB_THREADS`, `TASHWISH_DUCKDB_MEMORY`).
  All request values are bound parameters; query text is fixed. Only whitelisted columns are selected, none identifies an aircraft.
* CORS: any origin, `GET` only, no credentials. Preflight for any other method is refused.
* Keyset paging scans from the filter, not from an offset, but a very wide unfiltered scan over a large file still costs a full
  read. Write `cell_buckets.parquet` sorted by `bucket_start, h3, stratum` for the best behaviour.

## What the free tier does not guarantee

* **Availability.** A Render free web service sleeps after about 15 minutes idle. The next request waits for a cold start
  (about a minute here: container start, Python imports, opening the release). Retry with backoff; do not use it as a live dependency.
* **Capacity.** Shared CPU, 512 MB RAM, one worker. Heavy concurrent paging will be slow or rate limited. Download the Parquet
  files for bulk work.
* **Persistence.** The disk is ephemeral. The release is read from the deployed repository, so a new release means a new deploy. The
  rate limiter and caches reset on every restart.
* **Freshness.** `age_hours` and `/v1/freshness` tell you how old the data is. A stale dataset still answers (`status: stale` in `/health`);
  it is the caller's job to check it. There is no SLA, no support, and no guarantee the service stays up.
* **Fitness for use.** What the indicators mean and what they do not mean is stated in [METHODOLOGY.md](METHODOLOGY.md) and the data
  card. The service is not a source for operational decisions.

## Tests

`tests/test_api.py` builds a tiny **synthetic** release (`tests/synth_release.py`, labelled synthetic in the manifest, data card and every row) and checks
pagination, validation, headers, the synthetic banner, context statuses and parity with `ContextIndex`, 405 on write methods,
injection attempts, caching, CORS, downloads and startup refusal of inconsistent releases.
