# Next steps

An honest list of what is unfinished, ordered roughly by how much it matters. Items marked UNVERIFIED could not be checked from the
build environment and must be checked by the maintainer before anyone relies on them. Research and monitoring tool. Not for
navigation or safety of life.

## Data and operation

1. **Backfill the rest of the archive.** The released study dataset covers 2026-02-07 to 2026-03-13 (35 days). The open archive
   runs from 2025-12-14, which leaves roughly 7 months of days to ingest. The incremental workflow does one day per run on a daily
   schedule, so the backfill is slow by design; it should run one day per run and be watched. Days outside the study window are
   new data for a second, separate evaluation. Days inside the study window must stay refused (see `docs/OPERATIONS.md`).
2. **Validate the GitHub free tier limits (UNVERIFIED).** Runner CPU, memory and disk, job time limits, the effect of
   inactivity on scheduled workflows, repository size limits, and adsb.lol fair use were measured only locally (about 3 GiB per day
   to download and filter). Nothing has been run on the hosted free tier. Treat every number in `docs/OPERATIONS.md` marked
   UNVERIFIED as a question to answer.
3. **Set the `TASHWISH_STATE_KEY` secret.** The persistent emitter list is keyed with a secret. The secret must be created by
   the maintainer as a repository secret before any scheduled run; it must never be committed. Scheduled runs fail without it.
4. **Render free tier behaviour (UNVERIFIED).** Cold start time, sleep after inactivity, memory limit of the API and the hosting of
   the static dashboard were not tested on the real service. The live dashboard is a fixed study snapshot, not live data.

## Science

5. **AIS cross check.** Compare the Gulf aircraft view with ship position data (AIS) in the same hours and cells. AIS data are
   public only in part and often licensed; check terms first. This could give an independent signal for some events, and is the
   most useful next validation. Out of scope for the current release.
6. **Forward chained validation.** Fit on days up to a date and score only later days, for example fit up to 2026-03-02 and score
   2026-03-08 to 2026-03-13. The current held out days interleave with development days, so they are not a test of the future. This
   needs data not used so far or a clearly labelled secondary analysis, because the held out run is single use.
7. **Beta binomial sensitivity.** The binomial test treats the baseline share as known and ignores day to day overdispersion. A
   beta binomial variant would show how many flags survive.
8. **More realistic injection.** Partial degradation of an aircraft's samples, drifting spoof tracks, and one scenario per run to
   test whether shared false discovery families inflate recall.
9. **Explain the regime change.** Check whether the traffic drop and the rise in degraded reports coincide with changes in the
   receiver network, airline schedules or airspace use. Do not assert a cause without independent evidence.
10. **Evaluation with ground truth.** Public ADS-B has none. An operator's own interference logs, evaluated under that operator's
    terms, would allow precision and detection delay to be measured. None exists in this repository (see `docs/PROPOSAL.md`).
11. **Understand the spoofing recall trend** with displacement (higher at 10 km than at 250 km) and the high share of minimum size
    clusters among real events.

## Repository decisions for the maintainer

12. **History rewrite decision.** Git history still contains an earlier affiliation sentence and raw adsb.lol test fixtures with
    aircraft identifiers (the working tree has anonymised versions). Before any public push, decide whether to rewrite history
    (for example with `git filter-repo`) or to start a fresh repository from the current tree. Rewriting changes every commit hash, so
    the frozen commit recorded in `results/FREEZE.json` would no longer exist; keep a note of the old hashes if the freeze
    ordering must stay checkable.
13. **Maintainer issue not sent.** Questions for the adsb.lol maintainers about redistribution of derived aggregates and the
    release kinds are drafted in `docs/LICENSING.md` but no issue has been sent. Send it, or decide to proceed on the conservative
    ODbL reading.
14. **Compare the ODbL text** in `licenses/` with the copy at opendatacommons.org and record the result.
15. **Arabic review.** The Arabic dashboard text and the Arabic safety banner were written without a native review. A fluent reader
    should check meaning, tone and the technical terms.
16. **Zenodo release.** Follow `docs/ZENODO.md`: account, upload, metadata, DOI. A DOI exists only after publishing; none is claimed.
17. **Commit state.** The working tree holds uncommitted documentation, generator and release changes. Review and commit them.

## Not planned

Live operation as a service anyone should rely on, jammer localisation, attribution of any event to an actor, and any use for
navigation or safety of life.
