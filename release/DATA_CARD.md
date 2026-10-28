# Data card: Tashwish Gulf GNSS interference dataset

**Status: generated for a release candidate, study snapshot of fixed days, not a live feed.** Fields marked `FROM RESULTS` are filled by the
release script from result files, never by hand. Nothing below is a result. A DOI exists only after the maintainer publishes
the release (see `docs/ZENODO.md`).

## Licence and attribution (final wording, applies to every release)

Contains information from adsb.lol, which is made available here under the Open Database License (ODbL). This derived database (Tashwish aggregates) is also made available under the ODbL 1.0.

- Dataset licence: ODbL 1.0, text in `licenses/ODbL-1.0.txt` (shipped with every release, ODbL 4.2.b).
- Source: adsb.lol `globe_history` archives, https://github.com/adsblol/globe_history. Licence URL: https://opendatacommons.org/licenses/odbl/1-0/
- Code that builds the dataset: Apache-2.0.
- The ODbL is applied conservatively: the aggregates are treated as a Derivative Database. Whether that is legally required is
  uncertain; see `docs/LICENSING.md`.
- ODbL 4.6: the full dataset and the build method are offered free of charge as machine readable files.
- Build commit: `5fb5195`. Source: adsb.lol globe_history daily releases (the release kind and tag are in the ingest manifest).
- Study window: 2026-02-07 to 2026-03-13, 35 UTC days.

## Regimes and independence (read before using any rate)

The study window contains a sharp change from about 2026-03-02: the degraded share of en route reports rises from about 1 percent
to more than 10 percent and traffic in the data falls to a fraction of its earlier level. Baselines and coverage are fitted per
regime (`docs/METHODOLOGY.md`, section Regimes). No cause is identified and none is asserted, so do not read the change as
interference beginning or as a fault. Rates pooled across the change describe neither side.

Days are not independent samples. Development and held out days interleave inside a trending series, so held out days are not
later in time than the days used for fitting, and cells and scenarios within a day share traffic. Use intervals that resample
whole days. The held out days were scored once after a freeze (`results/FREEZE.json`).

## What it is

Per H3 cell (resolution 4), per 3 hour UTC bucket, per altitude stratum: number of unique aircraft observed, number with
degraded ADS-B accuracy indicators (NIC, NACp), Wilson intervals, coverage class and status; plus an event table of
jamming-like and spoofing-like anomalies. No raw traces, no aircraft identifiers, no per point positions.

## What it is not

- Not a navigation, flight planning or safety of life product.
- Not evidence of who caused anything. No attribution to any state or actor.
- Not a uniform sensor network: it reflects volunteer receiver coverage, which changes. "Insufficient data" is a state,
  not "no interference".
- Degraded accuracy fields can have non interference causes (older avionics, installation faults).

## Files, schema, coverage, validation numbers, known biases

Generated 2026-10-28T14:26:38Z from processed result files. Latest day: 2026-03-13. Days: 35 (dev 21, held_out 14).

- `cell_buckets.parquet` and `.csv.gz`: h3, bucket_start, slot, stratum, n_aircraft, k_strong, share, ci_lo, ci_hi, status, coverage_class, data_class.
  `share`, `ci_lo`, `ci_hi` are empty unless status is `ok`.
- `events.parquet` and `.csv.gz`: jamming-like, spoofing-like, both, and uncertain events. No identifiers.
- `coverage.parquet`: baseline coverage per (cell, slot, stratum), fitted on development days only.
- Event times are rounded to the 3 hour bucket; events with fewer than 5 aircraft omit destination coordinates.
- `validation.json`, `freshness.json`, `manifest.json`, `checksums.sha256`, `NOTICE`, `ODbL-1.0.txt`.

Cell bucket rows by status: coverage_lost 2968, insufficient 79986, ok 100663.
Events by kind: both 2, jamming_like 6, spoofing_like 19; marked uncertain: 23.

Validation numbers: see `validation.json` and docs/research/VALIDATION.md in the repository (generated from result files).

Known biases: coverage follows volunteer receivers and changes over time; a missing or insufficient cell is not a quiet cell; degraded accuracy indicators have non interference causes; the window is short and not representative of other seasons; dates are not independent samples.
Days scored `dev_leave_one_day_out` were also used to fit the baseline (each day excluded from its own baseline). Days marked `held_out` were scored once with a baseline fitted on development days only.

## Synthetic data

None of the files above contains synthetic data. Synthetic scenario outputs are kept separate and are not part of this release.
