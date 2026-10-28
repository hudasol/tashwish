# Data sources, licences and access

Checked 2026-10-11. "Verified" means the page was retrieved. Rule: nothing is built on a source until its licence and
access method are recorded here. Each source's terms and rate limits are respected, and no source is scraped against its terms.

## Decision

| Role | Source | Why |
|---|---|---|
| **Primary** | **adsb.lol `globe_history_YYYY` archives** (GitHub Releases) | Open licence (ODbL 1.0), no account, reachable from the build environment, carries the quality fields in the trace format, full day archives so runs are reproducible |
| **Fallback** | **OpenSky Network historical database** (research access) | Server side spatial filtering and a longer history, but needs an approved research application, is blocked from the build environment, and its terms for releasing derived data are unverified |
| Not used | ADS-B Exchange, Flightradar24, FlightAware, Planespotters, Wingbits | Paid, commercial use restricted, or redistribution prohibited without consent (see below) |
| Out of scope (v1) | AIS | No free historical Gulf archive identified (see [research/RESEARCH.md](research/RESEARCH.md) 1.3) |

## 1. adsb.lol globe_history (primary)

- **Licence:** Open Database Licence 1.0 per the repository README and a `LICENSE-ODbL.txt` file (verified). One
  repository page also lists CC0-1.0 (verified on the 2025 repo page); **the ODbL statement in the README is the one that
  is followed, being the stricter.**
- **Access:** GitHub Releases. Each day is a split tar: `v{YYYY.MM.DD}-planes-readsb-prod-0.tar.aa` and `.ab`
  (verified by ranged requests; there is no `.ac`). If the prod release for a day is much smaller than staging, use the
  larger one (README guidance). Contents: gzip JSON trace files from readsb's `globe_history` directory.
- **Cost / limits:** free. Only GitHub download limits apply. Each day is streamed and filtered to the Gulf box, only the
  needed fields are kept, the raw bytes are discarded, and raw archive files are never redistributed.
- **Size:** about 2.3 GiB (Jan 2026) to about 4.0 GiB (Oct 2026) per day for the prod release; the 2026 repository is
  1816 GiB in total.
- **Time range:** repositories for 2023, 2024, 2025 and 2026 exist. The **2026 repository's release index starts at
  2025-12-14** (verified from RELEASES.md). Earlier coverage in the 2023 to 2025 repositories was not verified.
- **Fields:** the readsb trace format can carry `nic`, `rc`, `nic_baro`, `nac_p`, `nac_v`, `sil`, `sil_type`, `sda`, `gva`
  in an optional per point aircraft object; "not all fields are present" (readsb README-json). **How densely they are
  populated is measured by a probe and reported in [DATA_QUALITY.md](DATA_QUALITY.md).**
- **Coverage caveat:** the data is the union of adsb.lol's feeders and partner feeds. It is **not** a uniform receiver
  network, and the receiver set changes over time. This is the central confounder and is why M3 exists.
- **Attribution:** "Contains information from adsb.lol, which is made available here under the Open Database License (ODbL)." (ODbL 4.3.a wording; single source in `src/tashwish/attribution.py`) The project and the
  repository are cited in the README, the data card and the dashboard footer.
- **Full analysis:** [LICENSING.md](LICENSING.md) (what is verified, what is not, questions for the maintainers).
- **Share alike caveat (a reading of the terms, not legal advice):** the ODbL generally requires derived databases to be shared
  under the ODbL with attribution. The released dataset is an aggregated derivative (cell hour counts and event
  tables), not the raw traces. **It is released under ODbL 1.0 to be safe; code is Apache-2.0.** A university IP office or
  lawyer should confirm before any commercial use. Open item in ROADMAP.

## 2. OpenSky Network historical database (fallback)

- **Access:** SSH Impala shell at `data.opensky-network.org` port 2230 (and a Trino interface via the `pyopensky`
  package); free for approved researchers, government and aviation authorities; private or commercial entities need a
  licence (verified on the data page).
- **Tables listed:** `state_vectors_data4`, `position_data4`, `velocity_data4`, `operational_status_data4`,
  `identification_data4`, `sensor_visibility` and others. Column lists were **not retrieved**; whether `position_data4`
  and `operational_status_data4` carry NIC, NACp, SIL, SDA is **unverified**.
- **REST API:** state vectors have 18 fields with **no** NACp, NIC, SIL or SDA (verified). Authenticated state vectors reach
  back only about an hour. Not usable for history.
- **Terms on redistribution, citation, commercial use:** **unverified** (terms page blocked to the fetcher used).
- **From the build environment:** main site and API unreachable or rate limited; SSH port 2230 is not reachable through the
  HTTP(S)-only proxy. **Any OpenSky run must happen on the owner's own machine.**
- **What the owner must do if this fallback is wanted:** register an OpenSky account; apply for research access with
  an institutional affiliation (if any) and a non commercial research statement; ask OpenSky in writing whether a released
  derived aggregate dataset is allowed and how to cite them; confirm the column names after access is granted.

## 3. Sources evaluated and rejected

| Source | Finding | Verdict |
|---|---|---|
| ADS-B Exchange | Free samples only for the 1st of each month; full history is a paid subscription; commercial use (including non profit) needs written authorisation; bulk redistribution is prohibited without consent | Not usable for a released derived dataset |
| Flightradar24 / FlightAware / Planespotters | Terms not retrieved; site returned 403 to automated fetch; likely paid or restricted | Not used |
| Wingbits | Sales gated; no licence stated | Not used |
| airplanes.live | Licence and access method **unverified**; site returned 403 to the fetcher used | Not used |
| OpenSky pre packaged datasets | Mostly licence not stated; none mention NACp or NIC | Not used |
| Zenodo / Kaggle / Hugging Face | Limited search found no ready made Gulf ADS-B dataset with NACp or NIC (absence of evidence, not proof). A Zenodo "Geospatial Dataset of GNSS Anomalies and Political Violence Events" (CC-BY-4.0, 2025) exists; content not verified | Possible comparison data; not used in v1 |
| aisstream.io / AISHub | WebSocket with API key / terms unverified; looks live only | Out of scope v1 |

## 4. Receiver coverage

No verified public list of receiver locations was found for adsb.lol. Coverage is therefore **inferred empirically** from
the spatial and temporal density of observed positions by altitude band (M3). OpenSky's `sensor_visibility` table may help
in a fallback run (unverified).

## 5. Reference and basemap data (display only)

To be recorded here before the dashboard uses them: airport coordinates (candidate: OurAirports, public domain per its
site; to be verified at M7), country boundaries and basemap tiles (candidate: Natural Earth, public domain; MapLibre with
an open style). **No basemap tile service with restrictive terms will be used.** Verified at M7 and updated here.

## 6. Synthetic data

Any synthetic data (test fixtures, injected scenarios) is labelled synthetic in filenames (`*_synthetic_*`), in schemas
(`data_class = "synthetic"`), in the UI and in the docs, and is never written into the real data tables. See
[METHODOLOGY.md](METHODOLOGY.md) and the data card.

## 7. Study window and split (decided 2026-10-12, reversible until the held out run)

- **Window:** 2026-02-07 to 2026-03-13 inclusive, 35 UTC days, all from the `globe_history_2026` repository (prod or staging,
  the larger release per day). It covers the cited 2026 incident dates 28 Feb, 2 Mar, 7 Mar and 13 Mar ([research/RESEARCH.md](research/RESEARCH.md) section 3).
  Why this size: about 6 minutes of parsing plus download per day on 2 cores gives roughly 4 hours for the whole window in this
  environment, and at least 14 days are needed for baselines. Pre-2025-12 events are out of reach of this archive.
- **Resumable ingest:** `scripts/run_study_ingest.sh` skips complete days (manifest), writes each day atomically, retries a day up
  to 4 times, and can be restarted at any time; a crash loses at most the day in progress. Raw archives are streamed from a spool
  and deleted after each day; `data/raw` and `data/interim` are git ignored, and only derived aggregates are ever released.
- **Split:** `src/tashwish/split.py` and [PREDICTIONS.md](PREDICTIONS.md). 21 DEV days, 14 HELD OUT days, fixed by a hash of the date.
