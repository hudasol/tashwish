# PROPOSAL, not an achievement

This page proposes future work. It is not a description of something that exists, and it is not a claim of use, review or
support by anyone. **No organisation has reviewed, endorsed, adopted or partnered with this project, and no use by any entity is
claimed.** Tashwish is a research and monitoring tool. It is not for navigation or safety of life, and it does not attribute
interference to any state or actor.

## What exists today

- An open pipeline, in Python with tests, that turns public ADS-B archives (adsb.lol, ODbL 1.0) into per cell, per 3 hour
  aggregates of degraded position reports and a table of jamming like and spoofing like events, with a coverage model that never
  draws missing data as quiet.
- A released study dataset (a release candidate, not yet published with a DOI) for one window, 2026-02-07 to 2026-03-13, 35 days,
  and a static bilingual dashboard showing that fixed snapshot. It is not live data.
- A validation record: controlled injection of SYNTHETIC scenarios into real traffic, preregistered predictions scored once on
  held out days with misses reported as prominently as hits, and a report of where the method fails. Numbers are generated into
  [README.md](../README.md), [REPORT.md](REPORT.md) and [VALIDATION.md](VALIDATION.md).
- A finding about the data: a sharp change from about 2026-03-02 that splits the window into two regimes, with no cause identified.
- Two file formats, not integrations. A context file for Marsad ([MARSAD_INTERFACE.md](MARSAD_INTERFACE.md)) and a degradation
  parameter file for Sirb ([SIRB_INTERFACE.md](SIRB_INTERFACE.md)). Marsad and Sirb are the author's own separate projects. Neither
  reads these files in production, and Tashwish does not modify them.

Its limits are large. There is no ground truth, so accuracy against real interference is unknown. Precision and detection delay are
not measured on real data. Detection of weak, small or short injected events is poor, and results differ by regime. Most real
events found are minimum size spoofing like clusters that may be data errors.

## What is proposed

1. **Continuous operation of the open pipeline** on free infrastructure, one day at a time, so the dataset grows past the study
   window, with each new day labelled by its regime and scored with the frozen method. First step: backfill the roughly 7 months of
   archive days outside the study window and report the results as a second, separate evaluation.
2. **Receiver network cross checks.** Compare the volunteer coverage model with the receivers that feed the archive, and add an
   independent signal such as ship position data (AIS) in the same hours, to learn whether the regime change and the events appear
   in a second sensor type.
3. **Evaluation with an operator's own ground truth.** The only way to measure precision and detection delay is a set of known
   interference intervals kept by an operator or regulator, evaluated on their terms and with their permission. Nothing of this kind
   exists in this project. If it were offered, the preregistration approach used here (predictions and split fixed before scoring)
   should be repeated.
4. **Forward chained validation** and more realistic injection, as listed in [NEXT_STEPS.md](NEXT_STEPS.md).

## Budget: free only

The proposal needs no purchase. It uses free tiers only: public data (adsb.lol archives, ODbL 1.0), free GitHub hosting and scheduled
workflows, a free static site and free web service tier for the dashboard and read only API, free Zenodo for the dataset. The limits
of those free tiers as documented were retrieved from the official pages on 2026-10-16 (`docs/OPERATIONS.md`, section 9);
whether they carry continuous operation in practice is **UNVERIFIED** and is the first thing to check. If a free tier cannot carry the daily volume (about 3 GiB
per day to download and filter), the answer is to slow the backfill or to stop, not to buy capacity. Time is the real cost, and it is
the author's own.

## Risks

- **Misreading.** A map of degraded reports can be read as proof of jamming, or of who is responsible. Mitigation: the safety and
  no attribution statements on every page, data class labels, uncertain labels, and no actor field in any file.
- **Operational misuse.** Someone might use it for navigation or safety decisions. It is not designed or tested for that and says so.
- **False comfort.** An empty cell may mean no receiver, not no interference. Mitigation: the coverage model and the insufficient data
  state, which is never drawn as quiet.
- **Data dependence.** The method depends on volunteer receivers and one archive; a change in either, as the regime change may
  show, can break comparability. Mitigation: regimes, per regime baselines, honest reporting of misses.
- **Licence.** The ODbL reading for derived aggregates is conservative and not legal advice; the maintainers of the source were not
  consulted ([LICENSING.md](LICENSING.md)).
- **Privacy.** Event rows could isolate a few aircraft. Mitigation: times rounded to the bucket, destination coordinates withheld
  below 5 aircraft, no identifiers, and a secret keyed emitter list. Git history still needs a decision (see NEXT_STEPS).
- **Overclaiming.** The results are from one 35 day window in one season. Nothing here transfers automatically elsewhere.

## What would change this proposal

Evidence that the regime change is a receiver network artefact would shift effort from detection to coverage. A refusal of
redistribution from the data source would stop the dataset release. A real ground truth set would turn the work from a method
demonstration into an evaluation.
