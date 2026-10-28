# Publishing the dataset on Zenodo (steps for the maintainer)

The Zenodo account and the publish step belong to the maintainer. Everything else is prepared in `release/`
(built by `python -m tashwish.release.build`) with `checksums.sha256`, `NOTICE`, `ODbL-1.0.txt` and a generated
`DATA_CARD.md`. The steps below follow the Zenodo web interface as documented at the time of writing; items marked UNVERIFIED could not be checked
from the build environment, so each should be compared with what the interface shows.

1. Create an account at https://zenodo.org (free). Signing in with the GitHub account `hudasol` is the simplest route.
2. Choose **New upload**. Upload every file in `release/`: `cell_buckets.parquet`, `cell_buckets.csv.gz`, `events.parquet`,
   `events.csv.gz`, `daily_region.csv`, `coverage.parquet`, `validation.json`, `freshness.json`, `manifest.json`, `DATA_CARD.md`, `NOTICE`,
   `ODbL-1.0.txt`, `checksums.sha256`. Do not upload anything from `data/` (raw and interim data are not part of the release).
3. Metadata:
   - Resource type: **Dataset**.
   - Title: `Tashwish: Gulf GNSS interference observatory, derived aggregates from public ADS-B data (<first day> to <last day>)`.
   - Authors: the maintainer's name. An affiliation is added only if one should be shown.
   - Description: paste the first two paragraphs of `release/DATA_CARD.md` and the line "Research and monitoring tool.
     Not for navigation or safety of life. No attribution of interference to any actor."
   - Licence: choose the Open Data Commons Open Database License (ODbL) v1.0 entry from the list (UNVERIFIED: the identifier is
     `odc-odbl`). The dataset is a derived database of adsb.lol data, so ODbL applies to it.
   - Related identifiers: add `https://github.com/hudasol/tashwish` as "is supplement to", and
     `https://github.com/adsblol/globe_history` as "is derived from".
   - Keywords: GNSS, jamming, spoofing, ADS-B, Gulf, aviation, open data.
   - Version: the `dataset_version` value in `release/manifest.json`.
4. Check the attribution: the description or the notes must contain the exact line from `NOTICE`:
   `Contains information from adsb.lol, which is made available here under the Open Database License (ODbL).`
   with the hyperlinks to https://github.com/adsblol/globe_history and https://opendatacommons.org/licenses/odbl/1-0/.
5. Choose **Save draft**, read the preview, then **Publish**. Publishing cannot be undone (a record can be updated with a new
   version but not deleted once it has a DOI). Zenodo then shows a DOI. Copy it.
6. Put the DOI in `CITATION.cff` (`doi:` field) and the README badge line, and commit. Do not put a DOI anywhere before it exists.
7. Optional: in Zenodo **Account, GitHub**, switch on the `hudasol/tashwish` repository. After that, every GitHub Release
   that is created is archived as a code snapshot with its own DOI. This archives source code only, not the dataset files; the dataset is
   the manual upload in step 2.
8. Create the GitHub Release for the same software version by following `docs/RELEASES.md` (the Releases page, **Draft a new
   release**, choose **Create new tag on publish**).
