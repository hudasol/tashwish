# Tashwish (تشويش): Gulf GNSS Interference Observatory

> **Research and monitoring tool. Not a navigation, flight planning or safety of life system.**
> Do not use it to make operational decisions about aircraft, vessels or vehicles. Use official NOTAMs, airspace
> notices and your regulator.
>
> **No attribution.** Tashwish reports what the data shows (where, when, which signal behaviour, how confident). It does
> **not** say who is responsible, and nothing in it should be read as attributing interference to any state or actor.

An open, reproducible pipeline and dashboard that turns public aircraft broadcast (ADS-B) data into maps and time series
of GNSS **jamming-like** and **spoofing-like** anomalies across the Gulf, with stated uncertainty, a validation plan using
synthetic injection and documented incident windows as weak labels, and a planned versioned dataset.

**Status:** research prototype under active construction. No dataset has been released and no validation result is
claimed in this README. Milestones and what "done" means for each are in [plan.md](plan.md). This README describes only
what exists in the repository today.

| Milestone | State |
|---|---|
| M0 research, plan, repository | done |
| M1 ingestion (resumable, schema checked) | code and tests present |
| M2 core metrics | code and tests present |
| M3 coverage model | code and tests present |
| M4 detection (jamming-like, spoofing-like) | code and tests present |
| M5 validation (synthetic injection, coverage and sensitivity tests, weak label replay) | harness and development day results present; report generated into `docs/VALIDATION.md` (not yet generated, see below) |
| M6 read only API and dataset builder | code and tests present; no dataset released |
| M7 bilingual static dashboard | present, shown with synthetic sample data only |
| M8 deployment | not done; workflows and notes in [docs/OPERATIONS.md](docs/OPERATIONS.md) |

Documents: methods in [docs/METHODOLOGY.md](docs/METHODOLOGY.md); pre registered predictions and held out rule in
[docs/PREDICTIONS.md](docs/PREDICTIONS.md); validation results will be written by a generator into
`docs/VALIDATION.md` (generated later, so the file may not exist yet; see `scripts/make_results_docs.py`). Results are
not restated here: see docs/VALIDATION.md.

## The problem

GNSS interference over the Gulf is acknowledged by regulators and operators, and regional bodies have asked for shared
monitoring and a regional repository of interference data (see [docs/RESEARCH.md](docs/RESEARCH.md)). Public maps exist,
but they are mostly closed method, daily aggregated, and show "nothing" where there are simply no receivers. Tashwish
is an open alternative where **every number can be traced to a computation and every claim carries its uncertainty**.

## What is different (and what is not)

We checked prior art before claiming anything ([docs/RESEARCH.md](docs/RESEARCH.md), section 1.4). Jamming maps from
ADS-B quality indicators already exist (GPSJam, Flightradar24, Stanford's RFI portal, academic work), so **mapping
interference from ADS-B is not our novelty.** What Tashwish adds:

1. **Open, tested, resumable pipeline** from a fully open raw archive to a released dataset.
2. **Per cell, per hour uncertainty:** Wilson intervals, minimum sample rules, shrinkage and false discovery control.
3. **Explicit receiver coverage model:** "no data" and "insufficient data" are never drawn as "no interference".
4. **Altitude stratified and airport aware** Gulf analysis.
5. **Validation as a feature:** controlled injection of clearly labelled synthetic interference into real traffic
   (precision, recall, detection delay), replay of cited incident windows as weak labels, and robustness tests, with
   failures reported.

## Method in brief

Aircraft broadcast how well their GNSS receiver thinks it knows its position (NIC, NACp and related fields). When many
aircraft in a cell suddenly report degraded accuracy, that is *jamming-like*. When aircraft report positions that jump,
imply impossible speeds, or cluster at common false locations, that is *spoofing-like*. We count **unique aircraft** per
H3 cell per hour, compute confidence intervals on the degraded share, require minimum sample sizes, correct for many
cells at once, and mark cells the receiver network cannot see as *insufficient data*. Full specification:
[docs/METHODOLOGY.md](docs/METHODOLOGY.md). Literature and prior art: [docs/RESEARCH.md](docs/RESEARCH.md).

## Honest limitations (known now)

- ADS-B accuracy fields can degrade for reasons unrelated to interference (older avionics, installation faults, ADS-B
  version mix). Degradation is evidence, not proof.
- Spoofing that leaves the broadcast accuracy fields nominal, and spoofing aimed at a single aircraft, are largely
  invisible to crowd based methods.
- The raw archive is the union of volunteer feeders, not a uniform sensor network. Coverage changes over time. Closed
  airspace and low traffic areas show nothing. The coverage model reduces but cannot remove this.
- Documented incidents we can use are few and mostly described in secondary sources. They are used as **weak labels**,
  never ground truth. Our open archive starts on 2025-12-14, which limits replay to 2026 events.
- Numeric thresholds are design choices, not standards, and are tested for sensitivity rather than assumed.
- Maritime (AIS) cross checking is out of scope for v1.

## Data and licensing

- Primary source: [adsb.lol](https://www.adsb.lol/) `globe_history` archives, ODbL 1.0. *Contains information from adsb.lol, which is made available here under the Open Database License (ODbL).* Licence analysis: [docs/LICENSING.md](docs/LICENSING.md). Details and every other source we checked: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
- Code: Apache-2.0 (see `LICENSE`). Released dataset: ODbL 1.0 (derived aggregates), with a data card.
- Synthetic data is always labelled synthetic (filenames, schema, UI, docs) and never appears in real-data views.

## Quickstart

Install with `pip install -e ".[dev]"` (Python 3.11 or later) and run `pytest` and `ruff check .`. Operational
commands (incremental run, release build, API, dashboard) are listed in [docs/OPERATIONS.md](docs/OPERATIONS.md),
[docs/API.md](docs/API.md) and [docs/DASHBOARD.md](docs/DASHBOARD.md).

## Relationship to Marsad

[Marsad](https://github.com/hudasol/marsad) is a per vehicle and per track position-trust layer. Tashwish is separate and
complementary: a regional interference context feed that could later inform Marsad as a prior. Tashwish does not
duplicate vehicle trust, and Marsad is not modified by this project. The proposed interface is specified in [docs/MARSAD_INTERFACE.md](docs/MARSAD_INTERFACE.md).

## Relationship to Sirb

Sirb (a drone show planner and verifier) could read an empirical GNSS degradation parameter file built from public aircraft ADS-B data, as an illustrative stress prior only, not a drone receiver model: [docs/SIRB_INTERFACE.md](docs/SIRB_INTERFACE.md). Sirb is not modified by this project.

## Author

Huda Mueen.
