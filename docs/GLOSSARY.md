# Glossary

Plain definitions of the terms used in this repository.

## Signals and data

**GNSS.** Global navigation satellite systems, the family that GPS belongs to. Aircraft use GNSS to know where they are.

**Jamming.** Radio noise that drowns out satellite signals so a receiver cannot compute a position or computes it badly.
Tashwish reports *jamming-like* behaviour: many aircraft in one place reporting worse position quality. It does not prove jamming.

**Spoofing.** Fake satellite signals that make a receiver compute a wrong position. Tashwish reports *spoofing-like*
behaviour: several aircraft reporting positions that jump to a common false location at impossible speeds. It does not prove
spoofing, and a data error can look the same.

**تشويش (tashwish).** Arabic for interference or jamming.

**ADS-B.** Automatic Dependent Surveillance Broadcast. Aircraft broadcast their own position and some quality fields about once
a second. Volunteer receivers collect these broadcasts, and adsb.lol publishes daily archives that this project uses.

**NIC.** Navigation Integrity Category, an ADS-B field in which the aircraft states how large an area its position could be
wrong within. A low value means the aircraft is less sure of its position. In this project NIC below 4 counts as degraded.

**NACp.** Navigation Accuracy Category for Position, an ADS-B field stating the aircraft's own estimate of its position error.
A low value means a larger error. In this project NACp below 5 counts as degraded.

**H3.** A system of hexagonal map cells with numbered sizes (resolutions). This project uses resolution 4, with cells of about
1,770 square kilometres.

**Slot.** One of the eight 3 hour parts of a UTC day (00 to 03, 03 to 06, and so on). Baselines are kept per slot so that the
quiet night hours are compared with other night hours.

**Stratum.** An altitude band: en route (at or above 10,000 ft, the main layer), high (25,000 ft and above), mid and low.

**Cell bucket.** One H3 cell during one 3 hour UTC bucket (and one stratum). All counts are per cell bucket.

**Uncertain label.** A flag (`label_uncertain`) on an event whose evidence does not support a confident choice between
jamming like, spoofing like, or both. It is a first class output, not a failure.

## Statistics

**Wilson interval.** A formula interval for a share (such as degraded aircraft out of all aircraft) that behaves well for small
counts. It treats every unit as independent, so it is not used as an uncertainty statement for pooled units.

**False discovery control.** A rule for flagging many cells at once without flagging too many by chance. This project uses the
Benjamini and Yekutieli procedure at q 0.05, which allows for neighbouring cells being related.

**Day bootstrap.** An interval made by resampling whole days with replacement. It is used because cells, scenarios and events
within a day share traffic and are not independent. An interval of 1.000 to 1.000 means every resampled set of days was perfect;
it is not a statement of certainty.

**Brier score.** The mean squared gap between a stated probability and what happened (1 if it happened, 0 if not). 0 is perfect;
0.25 is the score of always saying 0.5. It is used here to score the confidences written next to the predictions.

## Validation

**Synthetic injection.** Adding invented, clearly labelled degradation or displaced positions to real traffic, so that the right
answer is known. Results from it are marked SYNTHETIC. They show whether the detector finds what was injected, not how accurate it
is on real interference.

**Recall.** The share of injected scenarios that the detector found (at least one event overlaps the scenario in space and time).

**Precision.** The share of flags that are real. It is not measured on real data, because no ground truth exists there.

**Coverage lost (`coverage_lost`).** A status for a cell bucket that is normally covered by receivers but has no aircraft now or
fewer than 0.3 of its usual aircraft, and fewer than 5 aircraft. It is drawn as a hole, never as quiet.

**Tested degraded share.** Of the aircraft in cell buckets that have at least 5 aircraft (so can be tested), the share that
report degraded accuracy. It is computed per day for the regime labels.

**False coverage.** A cell that the coverage model calls covered but that had too few aircraft on the scored day.

**Regime.** A mechanical label of a day, traffic normal or reduced, degraded baseline or elevated (see [METHODOLOGY.md](METHODOLOGY.md), section
Regimes). It describes the data, not a cause.

**Held out day, development day.** A development day was used to design the system and fit baselines. A held out day was fixed
beforehand, scored once after a freeze, and never used for fitting. Held out here does not mean later in time.

**HIT, MISS.** A preregistered prediction whose pass criterion, written before the held out run, was met (HIT) or not (MISS). Misses
are reported with the same prominence as hits.

## Licence

**ODbL.** The Open Database License 1.0. adsb.lol publishes its data under it, and the released Tashwish aggregates are offered
under it too. Attribution is required: "Contains information from adsb.lol, which is made available here under the Open Database
License (ODbL)." The code is Apache-2.0.
