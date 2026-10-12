# Methodology

Tashwish turns public ADS-B reports from commercial aircraft into maps and time series of GNSS jamming-like and
spoofing-like anomalies over the Gulf. It reports evidence of degraded position quality, not proof of interference, and
it never attributes anything to an actor. It is a research and monitoring tool, not a navigation or safety of life
product. Each section below is an anchor that the dashboard links to.

## data-provenance

Source: daily `globe_history` releases of adsb.lol (ODbL 1.0), reduced to the Gulf bounding box
(22 to 31 N, 46 to 60 E). Raw archives are never committed. The released dataset contains no aircraft identifiers and no
per point positions. Attribution text is defined once in `src/tashwish/attribution.py`.

## grid-and-buckets

Space is divided with H3 at resolution 4 (cells of about 1,770 square kilometres on average). Time is divided into 3 hour UTC
buckets (eight per day). Cells are further split by altitude stratum: en route (at or above 10,000 ft, the stratum used
on the map), high, mid and low.

## unique-aircraft-count

The unit of counting is the aircraft, not the message. Within one cell, bucket and stratum each aircraft (ICAO24 address)
counts once, so a single aircraft transmitting thousands of messages cannot dominate a cell.

## degraded-definition

A position report is degraded when NIC is below 4 or NACp is below 5 (the strong degradation tier). An aircraft is
degraded in a cell-bucket when at least half of its quality bearing samples there are degraded and it has at least two
such samples. Ground traffic, vehicles and non transponder emitters are excluded. Aircraft that are degraded nearly all the
time everywhere (at least 200 samples on at least 3 days with a degraded share of 0.9 or more) are treated as
persistent low emitters (avionics, not interference) and removed; the list is fitted on development days only.

## minimum-sample-rule

A cell-bucket is only tested with at least 5 unique aircraft. Below that the status is `insufficient`. Insufficient is a
state, never a zero and never "quiet".

## wilson-interval

Degraded shares are shown with Wilson score intervals at 95 percent. They are estimates of the observed share among the
aircraft seen, not of the true population of aircraft.

## coverage-model

Volunteer receivers change, so absence of data is not absence of interference. For each (cell, slot of day, stratum) the
baseline presence is the share of baseline days on which the cell was testable. Classes: covered (at least 0.5),
marginal (at least 0.1), no coverage (below 0.1). Statuses: `ok` (testable and usable coverage), `insufficient`,
and `coverage_lost` (a covered cell that is now empty or below 0.3 of its usual traffic). Missing rows in covered cells are
materialised as `coverage_lost`. Baseline days are scored leave one day out so a day cannot vouch for its own coverage.

## event-definition

Jamming-like detector. For each tested cell-bucket the degraded count is compared with that cell's own baseline share
(empirical Bayes shrinkage, floor 0.02) with a one sided binomial test. Benjamini and Yekutieli false discovery control
(q = 0.05) is applied per day. A flag also needs at least 3 degraded aircraft and a Wilson lower bound of at least 0.20.
Flags merge into events when cells are H3 neighbours and buckets are adjacent.

Spoofing-like detector. Uses ADS-B fixes only (MLAT and non transponder emitters are excluded). A jump is an implied speed
of at least 650 kt, a displacement of at least 5 km, at least 2.5 times the aircraft's reported ground speed (floored at
100 kt), within 120 s. Jump destinations are clustered (20 km, 30 min); a cluster needs at least 3 distinct aircraft.
Events carry no aircraft identifiers.

Discrimination. An event is `jamming_like`, `spoofing_like`, or `both` (the spoofing origin lies within 100 km of a
flagged cell within one hour). `label_uncertain` is a first class output, set when the evidence does not support a confident
label (see the next section).

## confidence-grading

Jamming: high needs at least two cells, two buckets and a lower bound of at least 0.40; medium needs two cells or two
buckets; otherwise low. Spoofing: high needs at least 5 aircraft with a destination spread of at most 10 km; medium
otherwise. Uncertain labels: jamming only with low confidence; spoofing only with medium confidence; `both` unless both
components are high.

## fdr-control

Benjamini and Yekutieli is used because neighbouring cells are positively dependent. It is conservative.

## validation-design

There are no ground truth labels for GNSS interference in public ADS-B data. Validation therefore uses (1) controlled
injection of synthetic jamming and spoofing into real traffic, always labelled synthetic; (2) a deterministic held out
set of days (a hash of the date), fixed and listed in `docs/PREDICTIONS.md` before any held out result was examined, and
run once; (3) a coverage model failure test; (4) a sensitivity study; (5) weak labels from publicly documented incident
windows, which are used as weak evidence only. Numbers are in `docs/VALIDATION.md`, generated from result files.

## Limits

- The data is aircraft reported quality, so only airspace used by commercial traffic is observable.
- NIC and NACp can degrade for non interference reasons.
- Spoofing-like clusters can have non interference causes (for example MLAT or data errors) that the detector cannot rule out.
- The study window is short and one season; results do not transfer automatically elsewhere.
- Public aircraft data does not describe drone scale receivers (see `docs/SIRB_INTERFACE.md`).
