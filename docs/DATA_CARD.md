# Data card: Tashwish Gulf GNSS interference dataset

**Status: DRAFT template. No dataset has been released.** Fields marked `FROM RESULTS` are filled by the release script
from result files, never by hand. Nothing below is a result.

## Licence and attribution (final wording, applies to every release)

Contains information from adsb.lol, which is made available here under the Open Database License (ODbL). This derived database (Tashwish aggregates) is also made available under the ODbL 1.0.

- Dataset licence: ODbL 1.0, text in `licenses/ODbL-1.0.txt` (shipped with every release, ODbL 4.2.b).
- Source: adsb.lol `globe_history` archives, https://github.com/adsblol/globe_history. Licence URL: https://opendatacommons.org/licenses/odbl/1-0/
- Code that builds the dataset: Apache-2.0.
- The ODbL is applied conservatively: we treat the aggregates as a Derivative Database. Whether that is legally required is
  uncertain; see `docs/LICENSING.md`.
- ODbL 4.6: the full dataset and the build method are offered free of charge as machine readable files.
- Source release tags and build commit: `FROM RESULTS`.

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

`FROM RESULTS` (generated at release time from `data/processed` and `docs/VALIDATION.md`).

## Synthetic data

Any synthetic scenario output is separate (`*_synthetic_*`, `data_class = synthetic`) and is not part of the observed dataset.
