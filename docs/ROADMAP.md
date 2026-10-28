# Next steps

An honest list of what is unfinished, ordered roughly by how much it matters. Items marked UNVERIFIED could not be checked from the
build environment and must be checked by the maintainer before anyone relies on them. Research and monitoring tool. Not for
navigation or safety of life.

## Data and operation

1. **Backfill the rest of the archive.** The released study dataset covers 2026-02-07 to 2026-03-13 (35 days). The open archive
   runs from 2025-12-14, which leaves roughly 7 months of days to ingest. The incremental workflow does one day per run on a daily
   schedule, so the backfill is slow by design; it should run one day per run and be watched. Days outside the study window are
   new data for a second, separate evaluation. Days inside the study window must stay refused (see `docs/OPERATIONS.md`).
2. **Test the GitHub free tier in practice.** The documented limits (runner size, job time limit, free minutes, scheduled
   workflow disabling, size limits) were retrieved from the official pages on 2026-10-16 and are cited in `docs/OPERATIONS.md`.
   Still UNVERIFIED: free disk on a real runner, download speed to a runner, adsb.lol fair use (its page states no rule), and the
   archive's publication lag. Nothing has been run on the hosted free tier.
3. **Set the `TASHWISH_STATE_KEY` secret.** The persistent emitter list is keyed with a secret. The secret must be created by
   the maintainer as a repository secret before any scheduled run; it must never be committed. Scheduled runs fail without it.
4. **Render free tier behaviour in practice.** The documented spin down (15 minutes), spin up (about one minute) and monthly
   instance hours were retrieved on 2026-10-16 (`docs/OPERATIONS.md`, section 4). The memory limit of the API and real cold start
   times were not tested on the real service. The live dashboard is a fixed study snapshot, not live data.

## Science

5. **AIS cross check.** Compare the Gulf aircraft view with ship position data (AIS) in the same hours and cells. AIS data are
   public only in part and often licensed; check terms first. This could give an independent signal for some events, and is the
   most useful next validation. Out of scope for the current release.
6. **Run the forward evaluation.** Preregistered in `docs/PREDICTIONS_FORWARD.md` (2026-03-14 to 2026-04-12) with its scorer
   `scripts/score_forward.py`, both committed before any day after the study window was downloaded. It needs item 3 (the
   `TASHWISH_STATE_KEY` secret) and then one incremental run per day and one scorer run.
7. **Act on the beta binomial sensitivity.** Done on development days (`docs/research/SECONDARY_ANALYSES.md`, section 1): the flags on
   elevated days do not survive the measured overdispersion. Decide, in a new preregistered version, whether the detector should
   account for overdispersion; the frozen detector stays as it is.
8. **More realistic injection.** Partial degradation of an aircraft's samples, drifting spoof tracks, and one scenario per run to
   test whether shared false discovery families inflate recall.
9. **Explain the regime change.** Public sources on airspace closures and on maritime GNSS interference from 28 February 2026 are
   recorded in `docs/research/SECONDARY_ANALYSES.md`, section 3, as consistent timing only. Still open: receiver network changes in the same
   days, and aviation specific reports. Do not assert a cause without independent evidence.
10. **Evaluation with ground truth.** Public ADS-B has none. An operator's own interference logs, evaluated under that operator's
    terms, would allow precision and detection delay to be measured. None exists in this repository (see `docs/research/PROPOSAL.md`).
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
14. **Decide on the ODbL text** in `licenses/`. Compared with the official text on 2026-10-16 (`licenses/README.md`): one cross
    reference differs (Section 4.74 a. in the adsb.lol copy, 4.7 a. officially). Decide whether to ship the official text.
15. **Arabic review.** The Arabic dashboard text and the Arabic safety banner were written without a native review. A fluent reader
    should check meaning, tone and the technical terms.
16. **Zenodo release.** Follow `docs/ZENODO.md`: account, upload, metadata, DOI. A DOI exists only after publishing; none is claimed.
17. **Merge order.** Pull request 2 and the stacked pull requests of 2026-10-16 (forward preregistration, secondary analyses,
    verification) are open; merge them in order (`docs/research/OVERNIGHT_LOG.md`).

## Not planned

Live operation as a service anyone should rely on, jammer localisation, attribution of any event to an actor, and any use for
navigation or safety of life.
