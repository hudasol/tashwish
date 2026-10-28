# Documentation

The documents in this directory describe how Tashwish works and how to use and operate it. The records of the study itself are in
[research/](research/). Terms are defined in [GLOSSARY.md](GLOSSARY.md).

## Using the data and the software

- [METHODOLOGY.md](METHODOLOGY.md): how every number is computed, including the regimes, and the limits of the method.
- [DATA_CARD.md](DATA_CARD.md): what the released dataset contains, what it does not, and how to read its rates.
- [DATA_SOURCES.md](DATA_SOURCES.md): the sources checked, the one used, and their licences and access methods.
- [DATA_QUALITY.md](DATA_QUALITY.md): generated report on field presence and quality of the ingested data.
- [LICENSING.md](LICENSING.md): analysis of the ODbL as it applies to the source, the released dataset and the dashboard.
- [API.md](API.md): the read only release API, its endpoints, errors, caching and limits.
- [DASHBOARD.md](DASHBOARD.md): the static dashboard, how to serve it, and its behaviour.
- [WEB_DATA_CONTRACT.md](WEB_DATA_CONTRACT.md): the JSON files the dashboard reads.
- [GLOSSARY.md](GLOSSARY.md): plain definitions of the terms used in the repository.

## Developing and operating

- [ARCHITECTURE.md](ARCHITECTURE.md): data flow, stack, package layout and design decisions.
- [OPERATIONS.md](OPERATIONS.md): the scheduled incremental run on free tiers, failure handling and the baseline refit policy.
- [ZENODO.md](ZENODO.md): steps for publishing a dataset release on Zenodo.
- [ROADMAP.md](ROADMAP.md): open work and unverified items.

## Interfaces to other projects

- [MARSAD_INTERFACE.md](MARSAD_INTERFACE.md): the context file and query contract for Marsad.
- [SIRB_INTERFACE.md](SIRB_INTERFACE.md): the degradation parameter file for Sirb.

## Preregistration

These files are frozen. Results are never written into them.

- [PREDICTIONS.md](PREDICTIONS.md): predictions and pass criteria written before the held out run.
- [PREDICTIONS_AMENDMENT.md](PREDICTIONS_AMENDMENT.md): amendment made before the held out run, with the reasons.
- [PREDICTIONS_FORWARD.md](PREDICTIONS_FORWARD.md): preregistered forward evaluation on days after the study window.

## Baselines

- [BASELINES.md](BASELINES.md): comparison of the detectors with simple baselines.

## Study records

- [research/VALIDATION.md](research/VALIDATION.md): generated validation report with the held out and development results.
- [research/PREDICTIONS_RESULTS.md](research/PREDICTIONS_RESULTS.md): every preregistered prediction with its outcome.
- [research/REPORT.md](research/REPORT.md): technical report generated from the result files.
- [research/SECONDARY_ANALYSES.md](research/SECONDARY_ANALYSES.md): analyses outside the preregistration.
- [research/RESEARCH.md](research/RESEARCH.md): prior art, signal background and sources.
- [research/REVIEW_ROUNDS.md](research/REVIEW_ROUNDS.md): review rounds, what was fixed and what was not.
- [research/OVERNIGHT_LOG.md](research/OVERNIGHT_LOG.md): log of the working session of 2026-10-16.
- [research/PROPOSAL.md](research/PROPOSAL.md): proposed future work.

The frozen preregistration records (`PREDICTIONS.md`, `PREDICTIONS_AMENDMENT.md` and `PREDICTIONS_FORWARD.md`) keep their original relative paths and are not edited,
so they name study records at the locations they had when they were written.

Generated files carry a header naming the script that writes them. Regenerate them with `scripts/make_results_docs.py`,
`scripts/make_report.py`, `scripts/make_secondary_doc.py` and `scripts/make_data_quality_doc.py`; the README status block comes from
`scripts/make_readme_status.py`.
