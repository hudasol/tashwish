# Dashboard (static site in `web/`)

Plain HTML, CSS and ES modules. No build step, no API keys, no paid services, no third party map tile servers. It
consumes the contract in [WEB_DATA_CONTRACT.md](WEB_DATA_CONTRACT.md) (`tashwish.web.v1`).

## Serve locally and verify

```bash
# 1. basemap (build time only; needs network, public domain Natural Earth data)
bash web/scripts/fetch_basemap.sh          # writes web/data/ne_countries.json; on failure prints why and exits 1
# 2. labelled synthetic sample (seeded; uses src/tashwish/attribution.py)
.venv/bin/python web/scripts/make_sample.py
.venv/bin/python web/scripts/make_sample.py --check   # attribution text, schema and data_class in every web/data JSON
# 3. serve
cd web && python -m http.server 8000     # open http://localhost:8000/
```

The site loads `web/data/manifest.json` if present (the release step writes observed data there). Otherwise it falls
back to `web/data/sample_synthetic/` and shows the persistent red SYNTHETIC SAMPLE banner (also whenever any loaded
file says `data_class = synthetic`). If the files disagree on `data_class` the page refuses to render.
Verify by opening the page in both languages, stepping the slider with the arrow keys, opening the table view, and
exporting an image. If the basemap fetch failed, the map shows a plain background with a graticule and says so.

## Files

`index.html` (map, slider, events, evidence, table view, downloads), `methods.html` (renders `methods.json`),
`validation.html` (renders `validation.json`, "no results yet" state), `css/style.css`, `js/*.js`, `i18n/en.json`,
`i18n/ar.json`, `map/style.json`, `scripts/fetch_basemap.sh`, `scripts/clip_basemap.py`, `scripts/make_sample.py`,
`data/ne_countries.json`, `data/sample_synthetic/`.

## Third party libraries (pinned, loaded from jsDelivr with SRI; local fallback path `web/vendor/<name>-<version>/` if they are vendored)

| Library | Version | Licence | Use |
|---|---|---|---|
| maplibre-gl | 4.7.1 | BSD-3-Clause | map canvas, local style only |
| deck.gl (umbrella bundle, contains @deck.gl/geo-layers `H3HexagonLayer`) | 9.0.38 | MIT | H3 cell, text and event layers |
| h3-js | 4.1.0 | Apache-2.0 | required global of `H3HexagonLayer`; also used for cell centres |
| Natural Earth `ne_50m_admin_0_countries` | master at fetch time (hash and time recorded in `data/ne_countries.json` `_provenance`) | public domain | country outlines, fetched at build time |

The deck.gl umbrella bundle does not include h3-js; `H3HexagonLayer` fails without the `h3` global, so h3-js is loaded first.
Attribution control text on the map: "Natural Earth (public domain)".

## Contract shapes the contract text leaves open (to be reconciled with the release builder, `tashwish.release.build`)

- `manifest.bbox`: object `{south, west, north, east}` (an array `[west, south, east, north]` is also accepted). The released
  manifest carries the study box (22 to 31 N, 46 to 62 E) so the map opens on the data.
- `events.json`: object with an `events` array (a bare array is also accepted).
- `coverage.json`: `cells`: array of `{h3, slot, presence, class}`.
- `validation.json`: `results`: array of `{metric, scenario, value, ci_lo, ci_hi, n}`; an empty array shows "no results yet".
- `methods.json`: `metrics`: map from field name to `{label_en, label_ar, method_anchor}`.
- Day rows: `ci_lo` and `ci_hi` may be `null` when status is not `ok`.
- Method keys the UI looks up: every field name above plus `degraded_share`, `evidence.<name>` for each key in an event's
  `evidence`, `generated_at`, `latest_day`, `freshness_hours_hint`, `slot`, `bucket_hours`, `h3_res`. A number whose key is
  missing links to `methods.html#unmapped` and logs a console warning.
- The method anchors (`wilson-interval`, `event-definition`, ...) name sections of `docs/METHODOLOGY.md`.
- The `attribution` field carries `DATASET_ATTRIBUTION` (primary notice plus derived database sentence) from `attribution.py`.

## Behaviour notes

- Colour for share is used only for status `ok` with coverage not `no_coverage`. `insufficient`, `coverage_lost` and
  `no_coverage` use separate greys with a glyph (`/`, `X`, `|`) and legend entries; missing rows stay blank. CSS style
  hatching via deck's `FillStyleExtension` was tried and rendered solid black in the test browser, so it was replaced by grey plus glyph.
- Freshness uses the worse of the age of `generated_at` and the end of `latest_day`: amber over 48 h, red over 7 days, with a
  text state word as well as colour.
- Every displayed number is a `span.num[data-method="methods.html#anchor"]`; clicking opens the method section in a new tab, and
  column headers and evidence labels carry real links for keyboard users.
- Numbers use Latin digits in both languages. The time slider stays left to right in RTL, as time axes usually do.
- Export image: PNG drawn on a canvas with the SYNTHETIC banner and watermark when applicable, a legend strip, and a footer with
  the exact attribution text, both source URLs, the basemap credit and the safety line.
- Language is stored in `localStorage` (try/catch); dark mode follows `prefers-color-scheme`; animation honours `prefers-reduced-motion`.

## Arabic strings to review

All Arabic in `i18n/ar.json` was written without a native reviewer. Least certain:
`app.title` and `app.lede` (GNSS rendered as "أنظمة الملاحة بالأقمار الصناعية"), `kind.spoofing_like` ("يشبه الخداع"; some
regulators prefer "الانتحال" or "التضليل" for spoofing), `kind.jamming_like`, `banner.safety` (the no attribution clause),
`banner.synthetic` ("عينة اصطناعية"), all `legend.*`, `status.coverage_lost`, `time.live`, `split.held_out`, `scenario.*`,
`methods.*`, and the Arabic labels in `data/sample_synthetic/methods.json`. The ODbL notice is shown in English by design
(exact legal wording).

## Not verified

The vendored fallback (`web/vendor/`) was not needed and is untested, because the CDN was reachable from the test browser.
The amber freshness state was not screenshotted (red was tested with a faked clock). No real screen reader was used.
