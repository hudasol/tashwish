# Tashwish plan

Tashwish (تشويش), the Gulf GNSS Interference Observatory: an open, reproducible pipeline and dashboard that turns public
aircraft-broadcast data into maps and time series of GNSS jamming-like and spoofing-like anomalies across the Gulf, with
honest uncertainty, validation against documented incidents, and a released dataset.

**Non-negotiables** (copied from the brief; they gate every milestone)
1. No fabricated data, citations, results or incident claims. Everything shown is traceable to a source or a reproducible computation.
2. Synthetic data is labelled synthetic in filenames, schemas, UI and docs, and never mixed into real-data views.
3. Respect every source's terms and rate limits. Licence and access recorded in docs/DATA_SOURCES.md before use.
4. Never attribute interference to an actor or state.
5. Research and monitoring tool, not a navigation or safety-of-life system.
6. No generic chatbot or document layer. The value is signal processing, uncertainty handling and validation.
7. Accounts and keys are created by the owner; work continues on open data meanwhile.
8. A blocked, paid or unusable source is documented, not silently replaced.

## Scope for v1 (decided, reversible)

- **Region:** Gulf box lat 22 to 31 N, lon 46 to 62 E (UAE, Qatar, Bahrain, Kuwait, Oman north, Saudi east, Iranian coast,
  Hormuz, Gulf of Oman).
- **Source:** adsb.lol globe_history, 2025-12-14 onward (the 2026 repository). OpenSky is a documented fallback, not built.
- **Spatial index:** H3 resolution 5 (about 253 km2) primary, resolution 6 for the airport-proximity layer.
- **Time bucket:** 1 hour (UTC).
- **Study window for the released dataset v1:** a bounded set of days chosen to include documented incident dates and
  quiet controls (decided at M1 after storage and bandwidth are measured). Not "all of history".
- **Out of scope v1:** AIS cross-check, jammer localisation, a live feed, accounts.

## Milestones

Each milestone ends with tests passing in CI, a small-commits history and a git tag. "Done" is checked literally.

### M0: Research and repo (tag v0.0.1)
- docs/RESEARCH.md, DATA_SOURCES.md, ARCHITECTURE.md, plan.md, README.md pushed; About text and topics set.
- Done when: all five files exist, every citation in RESEARCH.md is from a retrieved page, README has the safety and
  no-attribution statements.

### M1: Ingestion (v0.1.0)
- Resumable, idempotent per-day ingestion: stream the two tar parts, filter to the Gulf box, write Parquet per day with a
  fixed schema, delete raw bytes. A manifest records day, source tag, byte sizes, row counts, hash of output, code version.
- Schema validation (pandera or explicit checks) and a data-quality report per day: field presence rates (NIC, NACp, SIL,
  SDA), position-source mix, duplicate and out-of-range rows, temporal gaps.
- Done when: re-running a day is a no-op, an interrupted run resumes, tests cover parsing of every trace-point shape
  we have seen, and a real day has produced a quality report committed to docs/DATA_QUALITY.md.

### M2: Core metrics (v0.2.0)
- Per H3 cell, hour and altitude stratum: unique aircraft, degraded aircraft (strong and GPSJam-compatible tiers), share,
  Wilson interval, minimum-sample status, traffic-density normalisation, empirical-Bayes shrunk share.
- Done when: unit tests against hand-computed Wilson values and property tests (monotonicity, bounds, dedup invariance);
  the metric table for a real day is reproducible bit-for-bit from the Parquet.

### M3: Coverage model (v0.3.0)
- Empirical receiver-coverage estimate per cell, hour-of-day and altitude band from the density of observed aircraft
  and positions over a rolling baseline; cells below a documented threshold are "insufficient data" and can never be
  coloured as quiet.
- Done when: tests show a synthetic coverage hole produces "insufficient data" rather than "no interference", and the
  coverage layer for a real day is inspected and its failure modes written down.

### M4: Detection (v0.4.0)
- Jamming-like: Wilson lower bound against a per-cell, per-hour baseline, minimum n and bad counts, false-discovery
  control, onset/end by hysteresis or CUSUM; event table with start, end, geometry, type, confidence, evidence fields.
- Spoofing-like: implied speed versus reported velocity, track discontinuity, clustered offsets over at least three
  distinct aircraft; duplicates and "no position" as supporting evidence only.
- Done when: interpretable event tables for real days, with every event traceable to the aircraft counts and messages
  behind it; unit tests for each detector on constructed cases.

### M5: Validation (v0.5.0) (the most important milestone)
- Replay of documented windows from retrieved, citable reports as **weak labels**, never ground truth.
- Controlled injection of **synthetic** degradation into real traffic: precision, recall and detection delay by scenario
  difficulty (intensity, area, duration, traffic density, coverage).
- Robustness: sensitivity to density, coverage, thresholds, and day-to-day stability. Failures reported honestly.
- Done when: docs/VALIDATION.md reports numbers produced by committed scripts, including the scenarios where the method fails.

### M6: API and dataset (v0.6.0)
- Read-only FastAPI API with OpenAPI docs; versioned open dataset (Parquet and CSV) with a data card (sources, licence,
  method, biases, labelling); docs/MARSAD_INTERFACE.md contract.
- Done when: dataset v1.0 is built by one command from the manifests, checksummed, and the API serves it with tests.

### M7: Dashboard (v0.7.0)
- MapLibre/deck.gl map with time slider, event list, per-event evidence panel, uncertainty and coverage layers,
  methodology page, data download, and the safety and no-attribution statement; Arabic and English with RTL; every
  number links to its method or source; accessible and fast (static precomputed outputs).
- Done when: keyboard-operable, contrast-checked, works at phone width, no number without a method link.

### M8: Deploy (v0.8.0)
- Live URL, health check, CI badge, reproducible build instructions.
- Done when: a clean clone builds with documented commands and the live site matches the released dataset version.

## Phase 3: critique rounds (v0.9.0 and v1.0.0)
Five rounds recorded in docs/REVIEW_ROUNDS.md: ADEO, EDGE, TII, ATRC, senior engineer. Each: critique, checklist,
fixed, deliberately not fixed and why.

## Phase 4: research output
docs/REPORT.md (6 to 10 pages equivalent), one-page summary, 60 to 90 second demo script, docs/NEXT_STEPS.md.

## Definition of done (project)
Live dashboard and API; CI passing; meaningful tests; reproducible from a clean clone; honest validation including failures;
released dataset with data card; README, plan.md, ARCHITECTURE.md, DATA_SOURCES.md, RESEARCH.md, REVIEW_ROUNDS.md,
REPORT.md present and consistent with the code; NEXT_STEPS.md sized for short sessions.

## Risks and how they are handled
| Risk | Handling |
|---|---|
| NIC/NACp sparsely populated in the archive | Measured by the M1 probe first; the design adapts (documented in DATA_QUALITY.md) |
| Receiver set changes over time create fake trends | Coverage model gates claims; per-cell baselines; report day-to-day stability |
| Archive volume (about 4 GiB per day) | Streaming filter, bounded study window, raw bytes never stored |
| Weak labels are weak | Reported as weak labels with explicit limits; injection supplies the quantitative evidence |
| Build environment cannot reach some sources | Documented; owner-run steps listed in DATA_SOURCES.md |
| GitHub write access missing | Work proceeds in a local git history; push when access exists |
