# Tashwish research notes (Phase 0)

Status: written 2026-10-11. Every factual claim below was taken from a page retrieved during research; the numbered
links are in the source list at the end. Anything not verified is marked **unverified**. Design choices that are ours,
not literature backed, are marked **[DESIGN]**. Direct quotation is avoided on purpose.

Tashwish is a research and monitoring tool. It is **not** a navigation or safety of life system, and it never
attributes interference to an actor.

---

## 1. Prior art

### 1.1 Summary table

| Work | Medium | Method (as retrieved) | Open? | Main limits stated or evident |
|---|---|---|---|---|
| GPSJam [1] | Public map | Share of aircraft with low NACp per hex, deduplicated per aircraft, rolling 24 h UTC, since 2022-02-14. Percent bad = 100 x (bad - 1) / (good + bad). Colours: green < 2 %, yellow 2 to 10 %, red > 10 %. | Code, licence and data download **unverified** | Cannot say which navigation system was used; red/yellow does not prove jamming; daily aggregation lets short events colour a day; blank means no aircraft or no feeding receivers; the "-1" biases toward showing nothing in sparse hexes |
| Flightradar24 GPS jamming map [10] | Public map | Uses NIC; no numeric thresholds published; 6 h and 24 h views | No download or licence found | Only shown where enough flights and enough of its own receivers exist |
| Stanford GPS Lab RFI portal [5, 35] | Public map + JSON downloads | ADS-B based; Inside GNSS reports NIC < 7 flagged as RFI and a velocity test for spoofing [35]; localisation method published in NAVIGATION 2025 [6] | Data under CC BY-NC 4.0 [5] | Non commercial licence; spoofing results described as forthcoming [35]; no Gulf specific analysis found on pages retrieved |
| SkAI / ZHAW tracker, CyCon 2025 [27] | Live map + paper | OpenSky 2024 data. Jamming = hourly ratio of low NIC (< 4) to high NIC (> 6) flights. Spoofing = position jumps, unrealistic speeds, incoherent altitudes seen by several aircraft | Code/data release **unverified** | No detection without traffic and receivers; single aircraft targeted spoofing not detected |
| Schafer et al., ION GNSS+ 2023 [22] | Paper | NIC < 6 with a 25 % problem time threshold, agglomerative clustering (50 km / 30 min), jammer localisation from radio horizon crossings; one year of European data | No release stated | No ground truth; validated against infrastructure, imagery and media |
| Liu et al., NAVIGATION 72(3) 2025 [6] | Paper | NIC as proxy for jammer power; propagation and antenna model; non linear least squares localisation; tested on Denver 2022 | - | Assumes a single static omnidirectional jammer |
| Darabseh et al., OpenSky workshop 2019 [21] | Paper | Baseline NACp distribution plus missing position distributions across receivers | - | Early scheme, 2019 |
| Pleninger et al., Aeronautical Journal 2025 [26] | Paper (paywalled) | NACp implied error compared with GPS almanac HDOP; tested on deliberate jamming experiments | - | Thresholds unverified (paywall) |
| Aireon white papers [24, 7] | Vendor paper | Space based ADS-B; H3 res 3 hex tiles, hourly anomaly fractions; independent position check against multilateration; spoofing signatures include duplicate ICAO24 and track discontinuities | Proprietary data | Indirect indicator; a 2024 algorithm update inflated counts [24] |
| Spire [36] | Vendor blog | Hex maps from NIC/NACp percentile cohorts | Data sold | Hex size and thresholds unspecified |
| Windward, C4ADS, UT Austin, SeaSpoofFinder, others (maritime) | Mixed | See 1.3 | Mostly proprietary or commentary; SeaSpoofFinder open | Different sensor (AIS); see 1.3 |

### 1.2 What the notices and official papers say (relevant to the Gulf)

- **EASA SIB 2022-02R4** (3 July 2026) names the Middle East among affected areas but, in the pages retrieved, does not
  name the Gulf states or Iran individually; it treats ADS-B only as something GNSS interference can corrupt [3, 4].
- **EASA CZIB 2026-03** covers FIRs for Bahrain, Iran, Iraq, Israel, Jordan, Kuwait, Lebanon, Oman, Qatar, UAE and Saudi
  Arabia [8]. The revisions retrieved (R11, R13, R14) do not mention GNSS, so we treat it as an airspace risk marker, not
  a GNSS label [7 to 9].
- **CAAS SIB 2026-01** (13 March 2026) explicitly mentions GNSS interference, jamming and spoofing for Iran and the
  wider Middle East / Persian Gulf [2].
- **UAE papers to ICAO MID:** a Learjet 45 reported jamming before the Emirates FIR on 3 Oct 2023 [13]; CNS SG/14-WP/5 (Oct
  2025) describes cross checking ADS-B, radar and multilateration for surveillance data integrity, notes more
  interference and suspected spoofing, and asks the region to share anonymised interference data and keep a regional
  repository [UAE-WP5 = 6B].
- **Saudi Arabia, CNS SG/15-WP/08** (7 May 2026) proposes a national automated GNSS RFI monitoring system and a
  centralised regional database or dashboard [19]. **Oman CNS SG/14-WP/9** (1 Oct 2025) addresses a regional approach to
  GNSS RFI management [20]. Neither contains quantitative data. Together with the UAE paper these show that regional
  bodies have asked for shared monitoring data; we did not find an open, method documented tool for the Gulf.
- **IATA GPS Signal Interference Summary Report**, RASG-MID/12, May 2025, study period Jan 2023 to Sep 2024, names Iraq and
  Saudi Arabia (Baghdad and Jeddah FIRs) among the top areas in the Gulf region; the jamming/spoofing split method is not
  explained [18].
- **OPSGROUP** recorded about 20 near identical spoofing reports, mostly in the Baghdad FIR, by 28 Sep 2023, with one crew
  diverted to Doha [17]; later updates describe "Baghdad", "Cairo" and "Beirut" type signatures [11].

### 1.3 Maritime (AIS) work

- C4ADS, "Above Us Only Stars" (March 2019): suspected AIS spoofing in Russia, Crimea and Syria [28].
- Windward publishes proprietary counts for the Gulf (e.g. a mid June 2025 average of 970 ships per day [33]); method
  not published, data not released. Several 2026 figures reach us only through secondary articles [25, 31] and are **not
  independently verified**.
- UT Austin Radionavigation Lab: expert commentary, no data or method released [30].
- SeaSpoofFinder (arXiv 2602.16257, CC BY 4.0) is open and uses aisstream.io from Dec 2025; it reports Baltic, Black Sea,
  Murmansk, Haifa and Moscow, **not** the Persian Gulf or Hormuz [32].
- AIS depends on the same GNSS being attacked, attribution is not definitive, and coverage is uneven [16, 31, 32].
- No free historical Gulf AIS archive was identified (aisstream.io appears live only; **unverified**). AIS cross checking
  is therefore **out of scope for v1** and listed in ROADMAP.

### 1.4 Gap analysis: candidate differentiators checked against what we retrieved

| Candidate | Finding | Evidence |
|---|---|---|
| Reproducible open pipeline with tests | **Not found** in any retrieved work | SeaSpoofFinder publishes a tool and results for AIS, no tests mentioned [32]; Stanford publishes data and scripts, not a described test suite [5]; GPSJam code **unverified** [1] |
| Confidence intervals and minimum sample rules per cell | **Partly**: ad hoc sparsity correction (GPSJam "-1") and a 25 % problem time rule [1, 22]; no per cell interval on the share found | [1, 22, 6] |
| Explicit receiver coverage modelling ("no data" is not "no interference") | **Not found as a model**; every source warns about it in prose | [1, 10, 27, 35] |
| Jamming vs spoofing discrimination | **Done by others, not Gulf specific** | [27, 35] |
| Altitude stratification | **Not found as a published per band method** | [1, 27] |
| Gulf specific airport proximity analysis | **Not found** | Gulf sources are shipping oriented or news [25, 30, 31, 33] |
| Released versioned open dataset | **Partly**: Stanford JSON under CC BY-NC [5]; no versioned, citable Gulf ADS-B release found | [5, 32] |
| Documented methodology | **Done in parts** by the papers; vendor sources are thin | [6, 22, 26, 27] |

**Positioning (what Tashwish claims, and no more):**
1. An open, tested, resumable pipeline from a fully open raw archive to a released dataset.
2. Per cell, per hour uncertainty: Wilson intervals, minimum sample rules, empirical Bayes shrinkage, and false discovery
   control; "insufficient data" is a first class state.
3. An explicit empirical receiver coverage model that gates every claim.
4. Altitude stratified Gulf analysis (an airport aware layer was considered and not built).
5. Validation as a product feature: controlled injection (recall on injected scenarios; precision and detection delay are not
   measured on real data), plus replay of cited incident windows as weak labels, with failures reported.

**Caution:** Stanford's portal is the closest prior art and may already have Gulf views. We cite it, benchmark against it
where licence allows (non commercial use for comparison only), and do not claim novelty for jamming mapping itself.
We drop the claim of a unique jamming vs spoofing split; that exists [27, 35].

---

## 2. Methodology

### 2.1 ADS-B quality indicators (tables from [1B], TU Delft "1090 MHz Riddle")

- NIC (containment radius Rc, 95 %): 11 < 7.5 m; 10 < 25 m; 9 < 75 m; 8 < 0.1 NM (185 m); 7 < 0.2 NM (370 m);
  6 < 0.5 NM (926 m) (or < 0.6 NM with supplement); 5 < 1 NM; 4 < 2 NM; 3 < 4 NM; 2 < 8 NM; 1 < 20 NM; 0 unknown or > 20 NM.
- NACp (EPU, 95 %): 11 < 3 m; 10 < 10 m; 9 < 30 m; 8 < 0.05 NM (93 m); 7 < 0.1 NM (185 m); 6 < 0.3 NM; 5 < 0.5 NM;
  4 < 1 NM; 3 < 2 NM; 2 < 4 NM; 1 < 10 NM; 0 unknown or > 10 NM.
- NACv: 1 < 10 m/s; 2 < 3 m/s; 3 < 1 m/s; 4 < 0.3 m/s. SIL: 1 < 1e 3; 2 < 1e 5; 3 < 1e 7 (per hour or per sample by SILs).
- Legacy NUCp (ADS-B version 0) maps from the type code and corresponds to the NIC scale.
- **SDA and GVA numeric tables: unverified.** We store the fields but do not threshold on them in v1.

### 2.2 Thresholds used in practice

- GPSJam: share of low accuracy aircraft; hex colour bands above [1]. A secondary article states the metric is NACp with a cut at 8 [5B]; the FAQ itself states no cutoff [1] - **treat NACp < 8 as secondary**.
- OpenSky/SkAI: hourly ratio of NIC < 4 to NIC > 6 [27]. Schafer: NIC < 6 [22]. Aireon: normal NIC 8 or 9, drops to 4 to 6 correlate with interference [7].
- FAA/ICAO APAC paper: NIC > 6 availability criterion; NIC = 0 is the most likely reported value once NIC falls below 6;
  NACp violations are an order of magnitude rarer than NIC violations [8B].

### 2.3 Confounders (sourced)

Receiver horizon and coverage (typically a few hundred km per sensor [27]); closed airspace shows no data [5B, 27];
daily aggregation hides short events [1]; aircraft at altitude see more sources [1]; crowd sourced feeds can aggregate and
hide detail [35]; installation and receiver faults and fleet version mix [8B]; duplicate ICAO24 and "no position" events
have non GNSS causes [7]. **Inferred, not sourced:** MLAT derived positions mixed into feeds, low/surface behaviour,
per ICAO24 baselines, receiver timing errors.

### 2.4 Spoofing signatures (sourced)

Position jumps, implausible implied speed, incoherent altitude, common false locations across several aircraft, EPU
jumps and UTC clock jumps (OPSGROUP) [11, 27, 35]. Integrity fields can stay nominal under spoofing, so behavioural
signatures matter [7]. Single aircraft targeted spoofing is not detectable by crowd methods [27].

### 2.5 Statistics

- Wilson score interval (Wilson 1927) for binomial shares [13B]; standard reference recommending it: Brown, Cai and
  DasGupta 2001 (link only, text **not retrieved**) [14B].
- Empirical Bayes shrinkage (beta binomial) [15B] - derivation details **unverified**, treated as **[DESIGN]**.
- Benjamini Hochberg (1995) and Benjamini Yekutieli (2001) for false discovery control; adjacent hexes are spatially
  correlated, so we use BY where dependence matters [16B].
- CUSUM (Page 1954) for onset and delay [17B]. H3 resolution table [18B].

### 2.6 Detection design (full spec in docs/METHODOLOGY.md, added at M2/M4)

- Count unique ICAO24 per H3 cell per time bucket; use each aircraft's worst quality value in the bucket. [DESIGN, extends [1]]
- "Degraded" tiers: **strong** = NIC < 4 or NACp < 5 (NIC < 4 from [27], NACp < 5 is **[DESIGN]**); **GPSJam compatible**
  = NACp < 8 (secondary).
- Wilson lower bound against a per cell, per hour of day baseline; minimum n and minimum bad aircraft counts;
  false discovery control across cells. All numeric defaults are **[DESIGN]** and are tested for sensitivity (M5).
- Exclude ground and very low aircraft from the main layer; report a separate near airport layer. [DESIGN]
- Spoofing-like: implied speed versus reported velocity, track discontinuity, clustered offsets across at least three
  distinct aircraft; duplicate ICAO24 and "no position" as supporting evidence only. [DESIGN with literature support for
  the signatures, not the numbers]

---

## 3. Weak labels for validation (never ground truth)

Only items we actually retrieved; dates as stated by the source.

| Date / window | Region | What the source says | Source | Use |
|---|---|---|---|---|
| 29 Aug 2023 onward; 26 Sep 2023 first report; 28 Sep 2023 FAA memo | Baghdad, northern Tehran, Baku FIRs | Spoofing of en route aircraft; Dubai and Doha routes mentioned | [11, 17] | **Not usable with the data we have**: our open archive starts Dec 2025 |
| 13 Jun 2025 / mid June 2025 | Gulf, Hormuz | Mostly maritime reporting | [20B, 33] | Same: before archive start |
| 28 Feb 2026 onward | Persian Gulf | Windward: more than 1,100 vessels in 24 h (secondary article) | [25] | Context only (maritime, secondary) |
| 2 Mar 2026 | Eastern Arabian Peninsula | SkAI: at least 169 aircraft hit by spoofing (secondary article) | [25] | **Primary replay window**, weak label, number unverified |
| 7 Mar 2026 | Saudi, Kuwait, UAE, Qatar, Oman, Iran | Windward: 1,650+ ships, 30+ clusters (secondary article) | [25] | Context only (maritime) |
| 4 Jul 2026 to 4 Oct 2026 validity | Northern Iraq | NOTAM ORBB A0279/26 about GPS jamming or spoofing | [22B] | NOTAM validity is not an incident window; context |
| 13 Mar 2026 | Iran and Gulf | CAAS SIB 2026-01 text on GNSS interference | [2] | Textual label |

**Consequence for validation:** the open archive covers 2025-12-14 to present, so documented incident replay is limited to
the 2026 events above. We state this limitation in the report. Pre-2025-12 labels would need another source
(OpenSky research access, see DATA_SOURCES.md).

---

## 4. Alignment with UAE priorities (factual, not a claim of endorsement)

Labels: DIRECT = directly about GNSS interference; ADJACENT = thematically related only.

- DIRECT: UAE working papers to ICAO MID describe growing interference and ask for regional data sharing and a regional
  repository [6B, 13]. Saudi Arabia asks for an automated monitoring system and regional dashboard [19].
- DIRECT (product level): commercial anti jam receivers and GPS free navigation products are on the regional market
  [12B, 13B2, 11B]. These are receiver side capabilities; Tashwish is regional context.
- ADJACENT: Abu Dhabi Government Digital Strategy 2025 to 2027 (AI first government, sovereign cloud) [14B2].
- Not found / unverified: a standalone GCAA, Dubai Airports or Abu Dhabi Airports notice on GNSS in 2026; any UAE national sovereign PNT policy text.
- Secondary source figures about UAE water vessel incidents (RICS citing Lloyd's List; AFP via Dawn) are **not
  independently verified** [8B2, 9B].

Practical relevance: aviation safety awareness and open, auditable monitoring. No organisation has reviewed or endorsed
this project.

---

## 5. Relationship to Marsad (read only review, commit e4efbe3)

Marsad is a position trust layer: per vehicle trust state, per track trust, and an internal time decayed hex map fed by its
own events. Its map has no public external ingest; it is internal; cells are axial hexes, not H3. Tashwish must **not**
duplicate per vehicle trust, a decayed fleet map from vehicle events, attribution, or RF analysis. Tashwish is the
regional, multi hour, multi aircraft context feed. Interface proposal and contract: see docs/MARSAD_INTERFACE.md (M6).
Marsad is not modified.

---

## Sources

Numbers match the research reports; suffix letters (B, B2) separate lists from different reports.

**Prior art report**
1. https://gpsjam.org/faq/
2. https://www.caas.gov.sg/docs/default-source/docs---srg/caas_sib_2026-01_middle_east_conflict_13-mar-2026.pdf
3. https://www.easa.europa.eu/en/node/143832
4. https://ad.easa.europa.eu/blob/EASA_SIB_2022-02R4.pdf/SIB_2022-02R4_1
5. https://rfi.stanford.edu/resources
6. https://navi.ion.org/content/72/3/navi.716
7. https://www.easa.europa.eu/en/print/pdf/node/143294/276607
8. https://www.easa.europa.eu/en/print/pdf/node/143294/277504
9. https://www.easa.europa.eu/en/domains/air-operations/czibs/2026-03
10. https://www.flightradar24.com/blog/gps-jamming-map/
11. https://ops.group/blog/gps-spoofing-update-08nov2023/
12. https://safeairspace.net/?p=169
13. https://www.icao.int/MID/Documents/2023/PBN%20SG8-PBN%20Airspace%20Design%20Workshop/WP%2011%20-%20GNSS%20Anomalies%20UAE%20GCAA.pdf
16. https://windward.ai/blog/what-is-gps-jamming-and-why-are-we-seeing-so-much-of-it/
17. https://ops.group/blog/faa-warning-navigation-failures/
18. https://www2023.icao.int/MID/MIDANPIRG/Documents/MID22%20and%20RASGMID12/PPT%2022-%20IATA%20-%20GPS%20Signal%20Interference%20-%20%20Summary%20Report%20(1).pdf
19. https://www.icao.int/sites/default/files/MID/MeetingDocs/2026/FM%20WG5%20%26%20CNS%20SG15/4-%20CNS%20SG15%20-%20Documentation/WP08.pdf
20. https://www.icao.int/sites/default/files/MID/MeetingDocs/2025/Fourteenth%20Meeting%20of%20the%20of%20the%20MIDANPIRG%20Communication%2C%20Navigation%20and%20Surveillance%20Sub-Group%20%28CNS%20SG/2-%20Documentation/WP09.pdf
21. https://easychair.org/publications/paper/Mp3x
22. https://disco.cs.rptu.de/downloads/publicationfiles/jammer_on_the_horizon.pdf
24. https://aireon.com/wp-content/uploads/2025/05/Aireon-White-Paper-GPS-Anomaly-Trends.pdf
25. https://newspaceeconomy.ca/2026/03/20/gps-jamming-and-the-war-over-navigation-what-gpsjam-org-reveals-about-the-middle-east-conflict/
26. https://www.cambridge.org/core/journals/aeronautical-journal/article/gnss-interference-detection-methodology-utilising-adsb-nacp-indicator-and-gps-almanac-data/72FEBF7BFE1541D7BF146B14BFAA4AB8
27. https://www.lenders.ch/publications/conferences/cycon25_2.pdf
28. https://c4ads.org/?p=3108
30. https://radionavlab.ae.utexas.edu/?p=5268
31. https://insidegnss.com/gnss-interference-complicates-navigation-as-hormuz-shipping-disruption-deepens/
32. https://arxiv.org/html/2602.16257v1
33. https://www.porttechnology.org/news/global-trade/gps-jamming-disrupts-hundreds-of-vessels-in-strait-of-hormuz/
35. https://insidegnss.com/q-what-has-been-learned-recently-about-gnss-rf-jamming-and-spoofing-events-what-tools-are-available-online-to-track-and-investigate-these-events/
36. https://spire.com/blog/space-reconnaissance/gnss-interference-report-russia/

**Methodology report (suffix B)**
- 1B https://books.open.tudelft.nl/home/catalog/download/11/14/69?inline=1
- 5B (same article as 25 above)
- 6B/UAE-WP5 https://www.icao.int/sites/default/files/MID/MeetingDocs/2025/Fourteenth%20Meeting%20of%20the%20of%20the%20MIDANPIRG%20Communication%2C%20Navigation%20and%20Surveillance%20Sub-Group%20%28CNS%20SG/2-%20Documentation/WP05.pdf
- 8B https://www.icao.int/sites/default/files/APAC/Meetings/2021/2021%20SURICG%206/4-Information%20Papers/IP14_USA-AI.7-ADS-B-Equipage-and-Quality-Performance-Rev.pdf
- 13B https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval
- 14B https://projecteuclid.org/journals/statistical-science/volume-16/issue-2/Interval-Estimation-for-a-Binomial-Proportion/10.1214/ss/1009213286.full (link only, not retrieved)
- 15B https://en.wikipedia.org/wiki/Empirical_Bayes_method
- 16B https://en.wikipedia.org/wiki/False_discovery_rate
- 17B https://en.wikipedia.org/wiki/CUSUM
- 18B https://h3geo.org/docs/core-library/restable/
- 20B https://mykn.kuehne-nagel.com/news/article/incidents-of-gps-jamming-reported-in-haifa-an-16-Jun-2025
- 22B https://safeairspace.net/iraq

**Alignment report (suffix B2)**
- 8B2 https://www.rics.org/news-insights/gnss-spoofing-and-mitigation-in-the-arabian-gulf
- 9B https://www.dawn.com/news/1981534
- 11B https://www.zawya.com/en/press-release/companies-news/uae-launches-next-gen-gps-less-navigation-and-secure-flight-control-to-strengthen-aviation-security-w1s9niu5
- 12B https://www.aviation-defence-universe.com/edge-launches-first-uae-made-anti-jam-gps-system-for-resilient-navigation
- 13B2 https://www.janes.com/defence-intelligence-insights/defence-news/air/idex-2025-edge-group-to-supply-gps-protect-to-uae-mod
- 14B2 https://www.cio.com/article/3812023/abu-dhabi-set-to-become-the-worlds-first-fully-ai-powered-government-by-2027.html
- Marsad files (commit e4efbe3): https://github.com/hudasol/marsad/blob/e4efbe33c3b48bba8162cc99d20ec0af614f8ff9/README.md , .../plan.md , .../docs/API.md , .../src/marsad/tracks/interference.py
