# Methodology

Tashwish turns public ADS-B reports from commercial aircraft into maps and time series of GNSS jamming-like and
spoofing-like anomalies over the Gulf. It reports evidence of degraded position quality, not proof of interference, and
it never attributes anything to an actor. It is a research and monitoring tool, not a navigation or safety of life
product. Each section below has an explicit anchor (`<a id>`) that the dashboard links to. Terms are explained in [GLOSSARY.md](GLOSSARY.md).

<a id="data-provenance"></a>
## Data provenance

Source: daily `globe_history` releases of adsb.lol (ODbL 1.0), reduced to the Gulf bounding box
(22 to 31 N, 46 to 62 E, the `REGION` constant in `src/tashwish/config.py`, which the ingest filter uses). Raw archives are never committed. The released dataset contains no aircraft identifiers and no
per point positions. Attribution text is defined once in `src/tashwish/attribution.py`.

<a id="grid-and-buckets"></a>
## Grid and buckets

Space is divided with H3 at resolution 4 (cells of about 1,770 square kilometres on average). Time is divided into 3 hour UTC
buckets (eight per day). Cells are further split by altitude stratum: en route (at or above 10,000 ft, the stratum used
on the map), high, mid and low.

<a id="unique-aircraft-count"></a>
## Unique aircraft count

The unit of counting is the aircraft, not the message. Within one cell, bucket and stratum each aircraft (ICAO24 address)
counts once, so a single aircraft transmitting thousands of messages cannot dominate a cell.

<a id="degraded-definition"></a>
## Degraded definition

A position report is degraded when NIC is below 4 or NACp is below 5 (the strong degradation tier). An aircraft is
degraded in a cell bucket when at least half of its quality bearing samples there are degraded and it has at least two
such samples. Ground traffic, vehicles and non transponder emitters are excluded. Aircraft that are degraded nearly all the
time (at least 200 en route samples on at least 3 days with a degraded share of 0.9 or more) are treated as
persistent low emitters (avionics, not interference) and removed. The rule has no spatial condition: it looks at the
aircraft's own samples wherever they were taken. The list is fitted on development days only and is stored keyed with a secret.

<a id="minimum-sample-rule"></a>
## Minimum sample rule

A cell bucket is only tested with at least 5 unique aircraft. Below that the status is `insufficient`. Insufficient is a
state, never a zero and never "quiet".

<a id="wilson-interval"></a>
## Wilson interval

Degraded shares are shown with Wilson score intervals at 95 percent. They are estimates of the observed share among the
aircraft seen, not of the true population of aircraft.

<a id="coverage-model"></a>
## Coverage model

Volunteer receivers change, so absence of data is not absence of interference. For each (cell, slot of day, stratum) the
baseline presence is the share of baseline days on which the cell was testable. Classes: covered (at least 0.5),
marginal (at least 0.1), no coverage (below 0.1). Statuses: `ok` (testable and usable coverage), `insufficient`,
and `coverage_lost`. A cell bucket is `coverage_lost` only when its class is covered, it has fewer than 5 aircraft now, and
it either has no aircraft at all or fewer than 0.3 of its usual (baseline mean) aircraft. A covered cell with fewer than 5
aircraft that is not that low stays `insufficient`. Missing rows in covered cells are materialised as `coverage_lost`.
Baseline days are scored leave one day out so a day cannot vouch for its own coverage. The baseline is fitted per traffic
regime (see [Regimes](#regimes)). Because `coverage_lost` requires too few aircraft now, a test of whether it predicts too
few aircraft in the next bucket is close to circular; `docs/PREDICTIONS_AMENDMENT.md` says so for prediction C4.

<a id="event-definition"></a>
## Event definition

Jamming-like detector. For each tested cell bucket the degraded count is compared with that cell's own baseline share
(empirical Bayes shrinkage, floor 0.02, fitted on development days with the same degraded regime, see [Regimes](#regimes)) with a one sided binomial test. Benjamini and Yekutieli false discovery control
(q = 0.05) is applied per day. A flag also needs at least 3 degraded aircraft and a Wilson lower bound of at least 0.20.
Flags merge into events when cells are H3 neighbours and buckets are adjacent. Events on a day in the elevated degraded regime are measured against the elevated baseline, which mutes them by construction (see [Regimes](#regimes)).

Spoofing-like detector. Uses ADS-B fixes only (MLAT and non transponder emitters are excluded). A jump is an implied speed
of at least 650 kt, a displacement of at least 5 km, at least 2.5 times the aircraft's reported ground speed (floored at
100 kt), within 120 s. Jump destinations are clustered (20 km, 30 min); a cluster needs at least 3 distinct aircraft.
Events carry no aircraft identifiers.

Discrimination. An event is `jamming_like`, `spoofing_like`, or `both` (the spoofing origin lies within 100 km of a
flagged cell within one hour). `label_uncertain` is a first class output, set when the evidence does not support a confident
label (see the next section).

<a id="confidence-grading"></a>
## Confidence grading

Jamming: high needs at least two cells, two buckets and a lower bound of at least 0.40; medium needs two cells or two
buckets; otherwise low. Spoofing: high needs at least 5 aircraft with a destination spread of at most 10 km; medium
otherwise. Uncertain labels: jamming only with low confidence; spoofing only with medium confidence; `both` unless both
components are high.

<a id="fdr-control"></a>
## False discovery control

Benjamini and Yekutieli is used because neighbouring cells are positively dependent. It is conservative.

<a id="regimes"></a>
## Regimes

The study window contains a sharp change. From about 2026-03-02 the tested degraded share of en route reports rises from
about 1 percent to more than 10 percent, also for aircraft seen both before and after, and traffic in the data falls to a
fraction of its earlier level (`results/dev/regime_check.json`, `results/regimes.csv`). One baseline pooled across this change
is wrong on both sides, so every scored day gets two mechanical labels, computed in `src/tashwish/regime.py` from aggregate
counts of that day only, before any detection:

- **Traffic regime.** `reduced` when the total number of en route aircraft counted over the cell buckets of the day is below
  0.5 times the reference level (`TRAFFIC_REDUCED_RATIO`), `normal` otherwise. The reference is the median over development
  days. This label selects the coverage model, that is which cells can be seen at all.
- **Degraded regime.** `elevated` when the tested degraded share (degraded aircraft divided by aircraft among en route cell
  buckets with at least 5 aircraft) is at least 0.05 (`DEGRADED_ELEVATED_SHARE`), `baseline` otherwise. This label selects the
  per cell baseline share used by the jamming like detector.

Baselines for a label are fitted on development days with the same label only, and never on the scored day. At least 3
development days are needed for a regime to be scored (`MIN_REGIME_DAYS`). No cell level or event information enters a label.

What the regimes are not. They describe the data, not the world. A traffic drop can come from airspace closures, fewer
flights, or fewer receivers; a degraded share rise can come from interference or from other causes. No cause is identified
and none is asserted. Two consequences must be kept in mind: the degraded label uses the scored day's own tested share, so
events on an elevated day are measured against a baseline selected using that day's outcome; and in the hash split the
development and held out days interleave inside a series that trends, so held out days are not later in time than the
days used for fitting. Results are therefore reported per regime wherever the regimes differ.

<a id="validation-design"></a>
## Validation design

There are no ground truth labels for GNSS interference in public ADS-B data. Validation therefore uses (1) controlled
injection of synthetic jamming and spoofing into real traffic, always labelled synthetic; (2) a deterministic held out
set of days (a hash of the date, rule `tashwish-heldout-v1`), fixed and listed in `docs/PREDICTIONS.md` before any held out result was
examined, and run once; (3) a coverage model failure test; (4) a sensitivity study; (5) weak labels from publicly documented incident
windows, which are used as weak evidence only. Numbers are in `docs/research/VALIDATION.md`, generated from result files.

## Limits

- The data is aircraft reported quality, so only airspace used by commercial traffic is observable.
- NIC and NACp can degrade for non interference reasons.
- Spoofing-like clusters can have non interference causes (for example MLAT or data errors) that the detector cannot rule out.
- The study window is short (35 days) and one season; results do not transfer automatically elsewhere.
- The data contain a regime change (see [Regimes](#regimes)); statistics pooled across it describe neither side.
- Public aircraft data does not describe drone scale receivers (see `docs/SIRB_INTERFACE.md`).
- Spoofing that leaves the broadcast accuracy fields nominal, and spoofing aimed at a single aircraft, are largely invisible to
  crowd based methods.
- The raw archive is the union of volunteer feeders, not a uniform sensor network. Coverage changes over time, and closed airspace
  and low traffic areas show nothing. The coverage model reduces but cannot remove this.
- Documented incidents are few and mostly described in secondary sources. They are weak labels, never ground truth.
- Numeric thresholds are design choices, not standards, and are tested for sensitivity rather than assumed.
- Maritime (AIS) cross checking is out of scope for this release (see [ROADMAP.md](ROADMAP.md)).
- Most real events found are spoofing-like clusters of the minimum size, 3 aircraft, and most carry an uncertain label. A position
  jump seen by 3 aircraft can be a data error, for example a multilateration artefact, and some events imply speeds of thousands of
  knots that no aircraft flew. Events are candidates for review.
