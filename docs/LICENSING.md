# Licensing analysis: adsb.lol globe_history, the derived Tashwish dataset, and the dashboard

Prepared 2026-10-12, revised the same day after retrieving primary texts (see 8.1). This is a working analysis by the project, not legal advice. Nothing here has been reviewed by a
lawyer or by adsb.lol. Rules used in this file:

- Text in quotation marks was retrieved from the page named in section 8 during this session. Where a fetch tool
  returned a summary rather than the page, the quote is marked "(tool excerpt)" and the section number comes from that
  excerpt. The ODbL full text was not retrieved as one continuous document, so every ODbL quote is a short excerpt.
- Anything not retrieved is marked UNVERIFIED.
- Pages that errored are listed in section 6 under "owner must fetch". No workaround was attempted.

## 1. Summary table

| Artifact | Licence we apply | Attribution text | Share-alike applies? | Confidence |
|---|---|---|---|---|
| Source: adsb.lol globe_history archives | ODbL 1.0 (README, `LICENSE-ODbL.txt`, docs page "License: ODbL 1.0"). CC0 also asserted elsewhere, see 2.1 | Not mandated by adsb.lol in any retrieved page; ODbL 4.3 and 4.2 supply the duty once we publish | n/a | Medium |
| Released derived dataset (per H3 cell, per 3 hour bucket counts, plus event table) | ODbL 1.0, release as a Derivative Database to be safe | Include notice in 4.1 below, ship a copy of the ODbL, keep upstream notices (ODbL 4.2.a to 4.2.c) | Probably yes. Conservative position: yes, because Substantial extraction into a new database is a Derivative Database (ODbL 4.4.b). Arguable that tiny aggregates are not, see 2.3 | Medium on "treat as ODbL", low on "must" |
| Public web dashboard (maps and charts) | Not a database release. A Produced Work. Dashboard code stays Apache-2.0 | Notice next to the work (ODbL 4.3), wording in 3.3 | No for the dashboard itself (ODbL 4.5.b). But ODbL 4.6 applies if the dashboard is a Produced Work from a Derivative Database: offer the dataset | Medium |
| Tashwish code | Apache-2.0 (`LICENSE`) | Standard Apache-2.0 notices | No. ODbL scope excludes computer programs (2.0, tool excerpt) | Medium |
| Python dependencies | Individual licences, see section 5 | None needed unless we bundle or redistribute them | No | High for the metadata read, medium for transitive bundled parts |

## 2. Derived dataset analysis

### 2.1 What the source says about its own licence, and the inconsistency

Retrieved statements:

1. `adsblol/globe_history_2026` README: "This database is made available under the Open Database License:" followed by the
   ODbL URL (tool excerpt, confirmed again on the 2025 repository README and the README blob page).
2. Repository root files (2026 and 2025): `LICENSE-ODbL.txt` and `LICENSE-cc0.txt`. GitHub's sidebar states "ODbL-1.0,
   CC0-1.0 licenses found". The first file starts with "## ODC Open Database License (ODbL)". The second starts with
   "Creative Commons Legal Code" and "CC0 1.0 Universal". The repository description says "Openly licensed."
3. adsb.lol docs page `docs/open-data/historical/`: "License: ODbL 1.0". It names `readsb-prod-0`, `readsb-prod-1` and
   `readsb-staging-0` and links the GitHub repository. It gives no attribution instruction (tool excerpt).
4. adsb.lol partners page (`docs/acknowledgements/partners/`): "By sharing data with ADSB.lol, you agree to license your
   data as CC0 ." and "In exchange, you get access to the aggregated data of all the other aggregators, including
   ADSB.lol, licensed to you as CC0 ." No attribution requirement is stated there.
5. adsb.lol privacy and licence page: "you agree, to the extent possible under law, to waive all copyright and related or
   neighboring rights to the data you are sharing" and "under the CC0 license." (two fragments of one sentence, tool
   excerpt). It does not mention ODbL or attribution.
6. The README says the archive "includes data from ADSB.lol feeders and friends, FlyItalyADSB and TheAirTraffic.com".
   It has no attribution requirement. Its Acknowledgements thank contributors.

Inconsistency: statements 1 to 3 say ODbL, statements 4 and 5 say CC0, and the repositories ship both licence files.

Our reading (UNVERIFIED, not stated by adsb.lol in any retrieved page): CC0 governs what individual feeders and partner
aggregators contribute to adsb.lol (statements 4 and 5), while the compiled archive is published as a database under the
ODbL (statements 1 to 3). Under that reading both are true at once: the ODbL covers the collection, and CC0 means no
contributor can add terms to individual records (compare ODbL 2.4, tool excerpt: "this License does not cover any rights
(other than Database Rights or in contract) in individual Contents").

Which we follow: the ODbL, because the README and the data docs page name it for the archive itself, and it is the stricter
of the two. If the ODbL turned out not to apply, releasing under ODbL anyway loses nothing for readers. If CC0 were the only
licence, our attribution would still be good practice. Cost of being wrong in this direction is small.

### 2.1a Resolved from primary text (revision)

The adsb.lol repository ships its own copy of the ODbL (`LICENSE-ODbL.txt`, 25,241 bytes, sha256 `d93f9962...b88611`),
retrieved in full by direct download. It is now vendored at `licenses/ODbL-1.0.txt`. On 2026-10-16 it was compared line by line
with the official plain text on opendatacommons.org (`licenses/README.md`): apart from trailing spaces, one cross reference
differs (Section 4.74 a. in this copy, 4.7 a. officially). Verbatim clauses from it:

- 1.0 "Publicly" - "means to Persons other than You or under Your control by either more than 50% ownership or by the power to direct their activities (such as contracting with an independent consultant)."
- 1.0 "Substantial" - "Means substantial in terms of quantity or quality or a combination of both. The repeated and systematic Extraction or Re-utilisation of insubstantial parts of the Contents may amount to the Extraction or Re-utilisation of a Substantial part of the Contents."
- 1.0 "Convey" ends: "Conveying does not include interaction with a user through a computer network, or creating and Using a Produced Work, where no transfer of a copy of the Database or a Derivative Database occurs." Consequence: serving the dashboard over the web is not Conveying; handing out dataset files is.
- 4.3 in full: "Creating and Using a Produced Work does not require the notice in Section 4.2. However, if you Publicly Use a Produced Work, You must include a notice associated with the Produced Work reasonably calculated to make any Person that uses, views, accesses, interacts with, or is otherwise exposed to the Produced Work aware that Content was obtained from the Database, Derivative Database, or the Database as part of a Collective Database, and that it is available under this License."
- 4.3.a: "Contains information from DATABASE NAME, which is made available here under the Open Database License (ODbL)." followed by "DATABASE NAME should be replaced with the name of the Database and a hyperlink to the URI of the Database. "Open Database License" should contain a hyperlink to the URI of the text of this License. If hyperlinks are not possible, You should include the plain text of the required URI's with the above notice."
- 4.4.a: Derivative Databases Publicly Used "must be only under the terms of: i. This License; ii. A later version of this License similar in spirit to this License; or iii. A compatible license." 4.4.b: "Extraction or Re-utilisation of the whole or a Substantial part of the Contents into a new database is a Derivative Database and must comply with Section 4.4."
- 4.2.d: "If it is not possible to put the required notices in a particular file due to its structure, then You must include the notices in a location (such as a relevant directory) where users would be likely to look for it."

Consequences now settled by text (not by legal opinion): the dashboard notice must hyperlink "adsb.lol" to the database URI and
"Open Database License" to the licence text, or print the URLs; it must be visible to anyone who views or interacts with
the work, which includes exported images. The repository README states: "This database is made available under the Open
Database License: http://opendatacommons.org/licenses/odbl/1.0/." It also says the archive "includes data from ADSB.lol
feeders and friends, FlyItalyADSB and TheAirTraffic.com" and "is a collection of all the data known to ADSB.lol". It gives no
attribution instruction and does not mention CC0. The partner terms are still unverified (item 7 in section 6).

### 2.2 ODbL definitions that matter (section numbers from the ODbL page)

- 1.0 Database: "A collection of material (the Contents) arranged in a systematic or methodical way".
- 1.0 Contents: "The contents of this Database, which includes the information, independent works, or other material".
- 1.0 Produced Work: "a work (such as an image, audiovisual material, text, or sounds) resulting from using the whole or a
  Substantial part of the Contents (via a search or other query) from this Database" (assembled from two excerpts).
- 1.0 Derivative Database: "Means a database based upon the Database, and includes any translation, adaptation,
  arrangement, modification".
- 1.0 Collective Database: "Means this Database in unmodified form as part of a collection of independent databases in
  themselves".
- 1.0 Substantial: "Means substantial in terms of quantity or quality or a combination of both." The excerpt we retrieved
  also described repeated, systematic extraction of insubstantial parts as potentially amounting to a Substantial
  extraction (paraphrase from the tool, wording not captured verbatim; verify in the full text, UNVERIFIED as a quote).
- 1.0 Extraction: "the permanent or temporary transfer of all or a Substantial part of the Contents to another medium".
- 1.0 Re-utilisation: "any form of making available to the public all or a Substantial part of the Contents by the
  distribution of copies".
- 1.0 Publicly: "means to Persons other than You or under Your control by either more than 50% ownership" (truncated; the
  rest of the definition, about power to direct activities, is UNVERIFIED as a quote).
- 1.0 Convey: "Using the Database, a Derivative Database, or the Database as part of a Collective Database" (truncated).
- 1.0 Use: "As a verb, means doing any act that is restricted by copyright or Database Rights".
- 4.2 Notices: "If You Publicly Convey this Database, any Derivative Database, or the Database as part of a Collective
  Database", then (a) "Do so only under the terms of this License or another license permitted under Section 4.4;" (b)
  "Include a copy of this License (or, as applicable, a license permitted under Section 4.4)"; (c) "Keep intact any
  copyright or Database Right notices and notices that refer to this License."; (d) a fallback where "it is not possible to put
  the required notices in a particular file due to its structure".
- 4.3 "Notice for using output (Contents).": "Creating and Using a Produced Work does not require the notice in Section 4.2."
  and "However, if you Publicly Use a Produced Work, You must include a notice associated with the Produced Work". Example
  notice, 4.3.a: "Contains information from DATABASE NAME, which is made available here under the Open Database License
  (ODbL)."
- 4.4 "Share alike.": (a) "Any Derivative Database that You Publicly Use must be only under the terms of:" this licence, a
  later version, or a compatible licence (the three items are from the tool summary, not quoted); (b) "Extraction or
  Re-utilisation of the whole or a Substantial part of the Contents into a new database" is a Derivative Database; (c) "A
  Derivative Database is Publicly Used and so must comply with Section 4.4."; (d) "You must not add Contents to Derivative
  Databases under Section 4.4 a that are incompatible with the rights granted".
- 4.5 "Limits of Share Alike.": (a) "You are not required to license Collective Databases under this License"; (b) creating a
  Produced Work does "not create a Derivative Database for purposes of Section 4.4"; (c) "Use of a Derivative Database
  internally within an organisation is not to the public".
- 4.6 "Access to Derivative Databases.": "If You Publicly Use a Derivative Database or a Produced Work from a Derivative
  Database, You must also offer" "to recipients of the Derivative Database or Produced Work a copy in a machine readable form
  of:" (a) "The entire Derivative Database" or (b) "A file containing all of the alterations made to the Database" (or the
  method used to make them). Cost: "available at no more than a reasonable production cost for physical distributions" and
  "free of charge if distributed over the internet".
- 4.7 "Technological measures and additional terms": "This License does not allow You to impose (except subject to Section
  4.7 b.) any terms or any technological measures" (rest truncated).
- 4.8 "Licensing of others.": recipients get a licence on the same terms (tool summary, not quoted).
- 2.4: "this License does not cover any rights (other than Database Rights or in contract) in individual Contents".

### 2.3 Is our dataset a Derivative Database?

Facts: input is the Gulf subset of daily archives. Output is a table of counts per H3 cell per 3 hour bucket of aircraft
with degraded accuracy fields, plus an event table. No raw traces, no per point positions, no identifiers retained.

Arguments that it is a Derivative Database ("treat as share-alike"):

- It is "a database based upon the Database" (1.0) and "arrangement, modification" is in the definition.
- ODbL 4.4.b treats Extraction or Re-utilisation of a Substantial part of the Contents into a new database as creating a
  Derivative Database. We read every record in the box across every day processed, which is systematic and may be
  Substantial in quantity even if the output is small.
- Neither the ODbL excerpts we retrieved nor any adsb.lol page says aggregation or statistics are exempt.

Arguments that it is not (weaker, UNVERIFIED as to any authority):

- The output contains no Contents (no records), only derived statistics, so there is arguably no Extraction or
  Re-utilisation of the Contents into the new database.
- Database right is a sui generis right in some jurisdictions only (EU style). Whether it applies to adsb.lol or to us in the
  UAE was not researched, UNVERIFIED. The ODbL is also a contract (the ODbL preamble says so, tool excerpt), which may bind
  regardless.

Decision: release under ODbL 1.0. Reason: lowest risk, costs nothing, matches the existing DATA_SOURCES.md decision, and
the ODbL is generous (commercial use allowed per 3.1, tool excerpt).

What follows if we treat it as a Derivative Database and publish it ("Publicly Use"):

1. Licence it under ODbL 1.0 (4.4.a), include a copy or URI of the licence and keep upstream notices (4.2.b, 4.2.c).
2. Provide a machine readable copy, free of charge over the internet, of the entire dataset or the alterations plus the method
   (4.6). Hosting the files and the code that builds them satisfies both options in spirit; confirm with a lawyer.
3. Do not add contents under terms incompatible with ODbL (4.4.d). Do not mix in rows from sources whose terms bar
   redistribution. DATA_SOURCES.md lists the rejected sources.
4. No technical or contractual restriction that undercuts the licence (4.7.a). Do not put the dataset behind terms that forbid
   redistribution or commercial use.
5. Our own added work (event definitions, the confidence scores) is inside the Derivative Database and so ships under the
   same ODbL. The code that produces it remains Apache-2.0.

What does not need share-alike: internal use not made public (4.5.c); the dashboard image or chart as such (4.5.b).

Cautions: (i) never redistribute raw archive files or raw trace excerpts except under the same ODbL terms with notices;
(ii) do not release a sample of raw rows "for illustration" without treating it as a Database extract; (iii) the dataset should
state the build date and the source release tags so readers can reproduce it.

## 3. Dashboard (Produced Work) analysis

### 3.1 Classification

A map tile image, chart, or rendered table "resulting from using ... Contents (via a search or other query)" fits the Produced
Work definition (1.0) when produced from the archive or from our derived dataset. If the dashboard also lets visitors download
the underlying numbers, that download is a database extract and falls under 2.3, not 3.

### 3.2 Obligations

- Notice (ODbL 4.3): when publicly using a Produced Work, include a notice associated with the work. The full clause is
  quoted in 2.1a: the notice must be "reasonably calculated" to make anyone viewing or interacting with the work aware that
  Content came from the Database and is available under the ODbL. The example notice (4.3.a) is the model and is
  stated to "satisfy notice under Section 4.3".
- No share-alike on the Produced Work: 4.5.b.
- 4.6 still applies because the dashboard is "a Produced Work from a Derivative Database" if the dataset is a Derivative
  Database. Therefore link to the dataset download on the dashboard.
- OSM caveat: if the base map uses OpenStreetMap tiles or data, that is a separate attribution duty (3.4 below). It is
  independent of adsb.lol.

### 3.3 Exact notice wording (dashboard footer, also shown in each exported image or chart)

Primary notice, based on the ODbL 4.3.a example with the database name substituted:

> Contains information from adsb.lol, which is made available here under the Open Database License (ODbL).

Placed visibly in the page footer and, for exported PNG or SVG charts, inside the image footer, so it travels with the work.
Add a link on "adsb.lol" to https://github.com/adsblol/globe_history and on "ODbL" to
https://opendatacommons.org/licenses/odbl/1-0/ (the README itself uses `opendatacommons.org/licenses/odbl/1.0/`; the
`1-0` form is the one retrieved for this analysis).

Second line for the derived dataset:

> Tashwish aggregates are a derived database, also made available under the ODbL 1.0. Download: [dataset link].

The README, DATA_SOURCES.md, NOTICE and the draft data card now carry exactly the primary notice, and the string lives in
`src/tashwish/attribution.py` with a test (`tests/test_attribution.py`) that fails if any of them drifts. The dashboard (M7)
must import it. The README link `opendatacommons.org/licenses/odbl/1.0/` is adsb.lol's own form; we use `.../1-0/`, which was
retrieved for this analysis. Whether both resolve to the same page was not checked.

### 3.4 OSMF guidance (interpretive reference only, OSM specific)

The OpenStreetMap Foundation pages are OSMF's view for OpenStreetMap data. They do not bind adsb.lol and are not adsb.lol's
interpretation. Used here only as a reference for how a body that wrote the ODbL licensing practice reads the same terms.

- "Licence/Community Guidelines" (OSMF wiki): "Produced Work" is a term used by ODbL to broadly separate something created
  from a database but not a database itself, with a data visualisation among the examples (tool excerpt). On Substantial,
  the page says "This is OpenStreetMap's view of what is substantial in our own context." and gives no numeric threshold.
  On Collective versus Derivative, a Collective Database consists of "independent" databases (tool excerpt).
- "Licence/Attribution Guidelines" (OSMF wiki): "Attribution must be placed in the vicinity of the produced work";
  "Attribution must be legible and understandable."; "Note that attribution is only necessary when a Produced Work is used
  Publicly"; and for OSM specifically "Attribution must be to "OpenStreetMap"." plus "Attribution must also make it clear
  that the data is available under the Open Database License."

Takeaways we borrow as good practice, not as obligations to adsb.lol: put credit next to the work, make it legible, name the
source and the licence.

## 4. Recommended attribution strings

| Where | String |
|---|---|
| Dashboard footer, chart image footer | `Contains information from adsb.lol, which is made available here under the Open Database License (ODbL).` |
| Dataset README, data card, metadata `attribution` field | primary string, then `This derived database (Tashwish aggregates) is also made available under the ODbL 1.0.` (`attribution.DATASET_ATTRIBUTION`), with the source and licence URLs beside it |
| Dataset file header or sidecar (`NOTICE`) | The string above plus: `Source release tags: [list]. Built [date] with Tashwish [git commit].` Ship `LICENSE-ODbL.txt` beside the data (4.2.b) |
| Code repository README | `Code: Apache-2.0. Data: ODbL 1.0. Contains information from adsb.lol.` |
| Paper or report | `Data: adsb.lol globe_history archives (ODbL 1.0), accessed [date].` plus the dataset DOI or URL |
| If OpenStreetMap basemap used | `Map data from OpenStreetMap` with the ODbL statement, per the OSMF attribution page above; also the tile provider's own credit (UNVERIFIED, not researched) |

No em dashes or emojis in any string.

## 5. Dependency licences

Read with `importlib.metadata` inside `/home/claude/tashwish/.venv` (Python 3.13) on 2026-10-12. "Field" shows which metadata
carried the answer. All requested packages were installed. We distribute none of them, so no licence notice duty arises unless
a release bundles them (for example a container image or wheel bundle, in which case ship their licence files).

| Package | Installed | Licence | Source field | Role |
|---|---|---|---|---|
| duckdb | 1.5.6 | MIT | Classifier only (License field empty) | runtime |
| h3 | 4.5.0 | Apache-2.0 | License text and classifier | runtime |
| httpx | 0.28.1 | BSD-3-Clause | License field | runtime |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | License-Expression | runtime |
| pandas | 3.0.6 | BSD-3-Clause | License text and classifier | runtime |
| pyarrow | 26.0.0 | Apache-2.0 | License-Expression | runtime |
| scipy | 1.18.1 | BSD (text begins "Copyright (c) 2001-2002 Enthought, Inc. 2003, SciPy Developers."; bundled third party parts carry their own licences, not enumerated here, UNVERIFIED) | Classifier and License text | runtime |
| tabulate | 0.10.0 | MIT | License-Expression | runtime |
| fastapi | 0.143.0 | MIT | License-Expression | optional `api` |
| uvicorn | 0.54.0 | BSD-3-Clause | License-Expression | optional `api` (extra, not on the requested list) |
| pytest | 9.1.1 | MIT | License-Expression | dev |
| pytest-cov | 7.1.0 | MIT | License-Expression | dev (extra, not on the requested list) |
| hypothesis | 6.168.5 | MPL-2.0 | License-Expression | dev |
| ruff | 0.17.0 | MIT | License-Expression | dev |

Notes: MPL-2.0 (hypothesis) is file level copyleft and only matters if we modify and redistribute hypothesis files; we use it
as a dev tool only. Dependencies are separate from the ODbL data licence, which excludes computer programs (2.0, tool
excerpt). Transitive dependencies were not enumerated.

## 6. Still uncertain

1. Whether aggregated counts are a "Derivative Database" or only a statistical output. We treat them as one, conservatively.
2. What "Substantial" means for adsb.lol's archive. No adsb.lol guidance retrieved. The OSMF guideline gives no numeric
   threshold and is OSM specific.
3. Whether the CC0 statements (partners page, privacy page) mean the archive itself is CC0 in whole or in part, or only that
   contributors waive rights in what they send. adsb.lol does not reconcile this on any page we retrieved.
4. Whether adsb.lol wants any particular attribution form. No page we retrieved gives one.
5. Whether database right or copyright subsists in adsb.lol's compilation in the jurisdictions that matter (UAE, UK, EU). Not
   researched, UNVERIFIED.
6. RESOLVED in revision: the full wording of 4.3, "Publicly", "Convey", "Substantial" and 4.4.a was retrieved (2.1a).
   The line by line comparison of the vendored licence copy with the official text was done on 2026-10-16
   (`licenses/README.md`).
7. Licence terms of FlyItalyADSB and TheAirTraffic.com data beyond what adsb.lol's partners page says.
8. The OSMF subpages specific to Produced Work and Substantial (for example the Produced Work and Substantial guideline
   subpages) were not fetched, only the Community Guidelines landing page and the Attribution Guidelines page.
9. Whether publishing a dashboard in the UAE under a studio or university name changes any contractual position. Not
   researched. The licensor is the individual author unless the owner decides otherwise.

Owner must fetch (pages that errored in this session, no workaround attempted):

- https://www.adsb.lol/docs/open-data/overview/ (error)
- https://www.adsb.lol/docs/overview/introduction/ (error)
- https://www.adsb.lol/docs/ (error)
- Optional: read the ODbL once end to end (a full copy is now in `licenses/ODbL-1.0.txt`)
- (done in revision) `LICENSE-ODbL.txt` retrieved in full; `LICENSE-cc0.txt` retrieved, standard CC0 1.0 text not compared
- The adsb.lol GitHub organisation pages for any contributing or data policy file (not attempted)

## 7. Draft issue for adsb.lol maintainers

Title: Licence and attribution clarification for derived aggregates from globe_history

Body:

> Hello, and thank you for publishing the archives. We are building an open, non commercial monitor of GNSS interference
> in the Gulf from the globe_history releases. Before we publish we would like to confirm our understanding. We are not asking
> for legal advice, only for how you read your own terms.
>
> 1. The README and docs say ODbL 1.0, and the repositories also ship `LICENSE-cc0.txt` and the partners and privacy pages
>    mention CC0. Is the archive as published licensed under the ODbL only, with CC0 applying to what feeders and partners
>    contribute?
> 2. We publish per H3 cell, per 3 hour counts of aircraft with degraded accuracy fields, plus an event table, with no raw
>    traces. Do you consider that a Derivative Database that must be shared under the ODbL, or an output outside it?
> 3. Is there a size or fraction of the archive that you regard as Substantial?
> 4. Is this attribution acceptable: "Contains information from adsb.lol, which is made available here under the Open
>    Database License (ODbL)." Do you want a specific link, logo or wording?
> 5. For a public dashboard of charts and maps, is that notice in the footer sufficient?
> 6. Are partner datasets (FlyItalyADSB, TheAirTraffic.com) included in the archive under the same terms?
> 7. Is there any restriction on citing individual aircraft identifiers in published event tables? (We plan not to publish
>    them.)
> 8. Which releases (`prod` versus `staging`) do you want cited for reproducibility?
>
> We will credit the project in the repository, data card and dashboard. Thank you.

## 8. Sources actually retrieved (2026-10-12)

### 8.1 Added in revision

| Source | URL | Result |
|---|---|---|
| `LICENSE-ODbL.txt`, full | https://raw.githubusercontent.com/adsblol/globe_history_2026/main/LICENSE-ODbL.txt | Downloaded in full, vendored |
| `README.md`, 2026 repo | https://raw.githubusercontent.com/adsblol/globe_history_2026/main/README.md | Downloaded; licence sentence, partners, no attribution rule |
| ODbL 4.3, 4.4, 4.2.d, definitions | https://opendatacommons.org/licenses/odbl/1-0/ | Verbatim excerpts via fetch tool |
| `docs/open-data/overview/` | https://www.adsb.lol/docs/open-data/overview/ | Errored again, not worked around |

### 8.2 First pass

| Source | URL | Result |
|---|---|---|
| ODbL 1.0 full text | https://opendatacommons.org/licenses/odbl/1-0/ | Retrieved as excerpts through a summarising fetch tool, several passes; section numbers from those excerpts |
| adsblol globe_history_2026 README and repository page | https://github.com/adsblol/globe_history_2026 and `/blob/main/README.md` | Retrieved |
| globe_history_2025 repository page | https://github.com/adsblol/globe_history_2025 | Retrieved |
| `LICENSE-cc0.txt` (first lines) | https://raw.githubusercontent.com/adsblol/globe_history_2026/main/LICENSE-cc0.txt | Retrieved, CC0 1.0 Universal |
| `LICENSE-ODbL.txt` (first lines) | https://raw.githubusercontent.com/adsblol/globe_history_2026/main/LICENSE-ODbL.txt | Retrieved, ODbL |
| adsb.lol home | https://www.adsb.lol/ | Retrieved (no licence text; links to privacy and licence page) |
| adsb.lol privacy and licence | https://www.adsb.lol/privacy-license/ | Retrieved (CC0 waiver sentence) |
| adsb.lol partners | https://www.adsb.lol/docs/acknowledgements/partners/ | Retrieved (CC0 sharing terms) |
| adsb.lol historical data docs | https://www.adsb.lol/docs/open-data/historical/ | Retrieved ("License: ODbL 1.0") |
| OSMF Licence/Community Guidelines | https://osmfoundation.org/wiki/Licence/Community_Guidelines | Retrieved (OSM specific) |
| OSMF Licence/Attribution Guidelines | https://osmfoundation.org/wiki/Licence/Attribution_Guidelines | Retrieved (OSM specific) |
| Python package metadata | `/home/claude/tashwish/.venv`, `importlib.metadata` | Read locally |
| Repository docs | `/home/claude/tashwish/docs/DATA_SOURCES.md`, `README.md` | Read locally for existing decisions |

A web search for the adsb.lol licence returned only generic results (globe_history 2024 and 2025 repositories, OSM wiki
licence pages); none were used beyond the pages above.
