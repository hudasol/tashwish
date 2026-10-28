# Data card: Tashwish Gulf GNSS interference dataset

**Status: release candidate, study snapshot of fixed days, not a live feed.** Fields marked `FROM RESULTS` are filled by the
release script from result files, never by hand. Nothing below is a result. A DOI exists only after the maintainer publishes
the release (see `docs/ZENODO.md`).

## Licence and attribution (final wording, applies to every release)

Contains information from adsb.lol, which is made available here under the Open Database License (ODbL). This derived database (Tashwish aggregates) is also made available under the ODbL 1.0.

- Dataset licence: ODbL 1.0, text in `licenses/ODbL-1.0.txt` (shipped with every release, ODbL 4.2.b).
- Source: adsb.lol `globe_history` archives, https://github.com/adsblol/globe_history. Licence URL: https://opendatacommons.org/licenses/odbl/1-0/
- Code that builds the dataset: Apache-2.0.
- The ODbL is applied conservatively: we treat the aggregates as a Derivative Database. Whether that is legally required is
  uncertain; see `docs/LICENSING.md`.
- ODbL 4.6: the full dataset and the build method are offered free of charge as machine readable files.
- Source release tags and build commit: `FROM RESULTS`.
- Study window: `FROM RESULTS`.

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

`FROM RESULTS` (generated at release time from `data/processed` and `docs/research/VALIDATION.md`).

## Synthetic data

Any synthetic scenario output is separate (`*_synthetic_*`, `data_class = synthetic`) and is not part of the observed dataset.
