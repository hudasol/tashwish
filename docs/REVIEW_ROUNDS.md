# Review rounds

Five rounds of independent review were run on this repository by separate reviewer agents, each reading from one angle. Each
reviewer was told to find faults, not to confirm. Counts below are counts of numbered findings in the reviewer's written report.
The reports themselves are working notes outside the repository; this file records their scope, counts, categories, what was
fixed and what was not.

Timing matters for the held out result. Rounds 1 to 3 ran on 2026-10-12 before the freeze, with no access to held out results, and
their findings changed the system before it was frozen. Rounds 4 and 5 ran after the held out run, so they could change
documents, labels, reporting and the dashboard, but not the frozen detectors or the held out result. The scoring code did not
change after the freeze (see `results/FREEZE_LOG.jsonl`).

No organisation reviewed this project. "Independent" means a separate agent without the author's context, not an external expert.

## Round 1: methods and statistics (before the freeze)

**Scope.** Statistical design, baselines, coverage model, injection, matching, predictions, bootstrap. `results/dev` only.

**Found (17 findings plus one wording note).** 3 blockers, 7 major, 7 minor.
- Statistics and design (blockers): one baseline pooled across the 2026-03-02 regime change; coverage predictions C1 and C3
  decided by regime mix; S2, S3 and label accuracy true by construction.
- Validation realism (major): injection easier than reality; background merge credited as detection; shared false discovery
  families across scenarios; J3 and J4 near mechanical; J5 and R2 to R4 measure the regime; day bootstrap unstable; held out data
  partly exposed through the ingest log.
- Minor: a NaN trap when reading `null`, S4 definition, J1 and J2 wording, C4 near tautology, bounding box, persistent emitter
  wording, no beta binomial check.

**Fixed.** Regime aware baselines and coverage fitted on development days only (`src/tashwish/regime.py`, amendment section 2);
scenario placement away from real flags; varied spoof scatter; C1 to C3, R2 to R4 reported per regime with a day bootstrap
within regime; J3 also on testable scenarios; J4 relabelled as first bucket detection; J5 reported as a real event rate; S2, S3
and committed label accuracy labelled as pipeline separation checks; exposure of held out ingest counts disclosed and D1, D2 marked
not blind (`docs/PREDICTIONS_AMENDMENT.md`); `keep_default_na` handled in the results generator. After the held out run: the
METHODOLOGY bounding box (now 46 to 62 E), the `coverage_lost` condition and the persistent emitter wording.

**Not fixed, and why.**
- Jamming injection still degrades all samples of the chosen aircraft, and spoofing injection is still cleaner than reality;
  partial degradation and drifting spoof tracks were not added before the freeze and cannot be added to the frozen run.
- Shared false discovery families across scenarios (M4) were not measured; a one scenario per run comparison was not done.
- The spoof injection does not rebuild the jamming input, so S2 and S3 remain close to true by construction.
- The beta binomial sensitivity check for day level overdispersion (m7) is not done (listed in `docs/NEXT_STEPS.md`).
- Data quality documents generated from every manifest day, including held out days, were not checked again for a development day
  filter. Treat that as open.

## Round 2: honesty, licensing and privacy (before the freeze)

**Scope.** README, docs, web, API, interop, release builder, state, git history. Held out results not read.

**Found (17 findings).** 2 blockers, 5 major, 10 minor.
- Privacy (blockers and major): raw adsb.lol traces with aircraft identifiers in test fixtures that were already pushed; a
  reversible hashed persistent emitter list on main; event rows as quasi identifiers (second precision times, destination
  clusters of 3 aircraft).
- Claims (major): named organisations that read as review or targeting; a university affiliation against the owner's wish; a
  README that overstated status; an overreaching regional need claim.
- Labels and licensing (minor): synthetic samples carrying real attribution; footer attribution that could vanish; download
  headers; hard coded data class; Marsad wording; Arabic safety wording; CITATION licence note; missing referenced files;
  hyphen style.

**Fixed.** Fixtures anonymised (fake addresses, no callsigns); persistent emitter list keyed with a secret (HMAC) instead of a
public salt; event times rounded to the 3 hour bucket and destination coordinates withheld below 5 aircraft; named
organisations and the need claim removed from plan.md and RESEARCH.md (and two remaining names removed in the post run pass);
affiliation removed from the working tree; synthetic samples relabelled; attribution refusal in the dashboard; data class asserted
by the release builder; CITATION and Zenodo notes; Arabic banner wording.

**Not fixed, and why.**
- The raw fixture files and the affiliation sentence remain in git history. History was not rewritten. This is an owner
  decision and is listed in `docs/NEXT_STEPS.md`. Until then the repository must not be pushed to a public remote.
- The ODbL text in `licenses/` has not been compared with the copy on opendatacommons.org (listed in NEXT_STEPS).
- Whether every download response carries the attribution header was not checked again here.

## Round 3: code and operations (before the freeze)

**Scope.** Incremental run, frozen state, release builder, workflows, API, held out guard, free tier feasibility.

**Found (17 findings plus a feasibility section and test gaps).** 3 blockers, 9 major, 5 minor.
- Held out integrity (blockers): backfill could score held out days; the run once guard could be beaten; nothing could run as
  deployed (no committed state).
- Operations (major): freshness contract; one day per dispatch; wide workflow permissions; non atomic releases; version ignoring
  content; spoofable rate limiter; reversible hashes; growing data branch; no provenance in day files.
- Free tier: the daily volume of about 3 GiB and a weekly schedule do not keep pace; runner limits were not verified.

**Fixed.** Study window guard in the incremental run; run once guard hardened (`RUNNING` marker, no `--max-days`, no other output
folder, a recorded reason to replace a freeze); atomic swap of web data and release; dataset version with a content hash; proxy
trust off unless configured, bounded rate limiter; freshness list, monotone latest day, failure on a permanently missing day;
provenance in day files; state committed; token only in push steps with credentials not persisted; null handling in the
freshness check.

**Not fixed, and why.**
- The incremental workflow still holds write permission for the whole job (the push steps are narrowed, the job is not split).
- The growing `data` branch (release files committed again every run) is not addressed.
- Free tier limits of GitHub Actions and Render remain UNVERIFIED; nothing here was run on those services.
- Some test gaps (refit, equivalence of the frozen and harness paths on a held out day) were only partly closed.
- Render serves `release/` from the deployed branch; a continuous `data` branch deployment was not tested.

## Round 4: results and claims (after the held out run)

**Scope.** Result files against every claim in README, docs and release; arithmetic; held out discipline; banned characters.

**Found (26 findings).** 4 blockers, 12 major, 10 minor.
- Passed without action: the order of events in git and in `FREEZE_LOG.jsonl`, one freeze only, the arithmetic of 28 predictions
  and the tables, banned characters, no attribution, no endorsement, the safety statement.
- Blockers: pooled false coverage and pooled recall hiding the regime change; HIT and MISS shown without a data class; the
  university name and a GitHub URL in history.
- Major: stale README status; capabilities not in the code (airport aware, precision, detection delay); grid and bounding box
  disagreements; the regime change absent from documents and dashboard; mislabelled data class on the validation page; regime
  label caveats missing; two meanings of easy and hard; no precision style number; thin discussion of misses; documents cited as
  evidence that did not exist; third party map claims stronger than the evidence; minimum size spoofing clusters without a
  caveat next to them.
- Minor: hyphens, a post freeze source hash mismatch, an uncommitted tree, stale plan.md, raw floats, unexplained displacement
  trend, results exactly at threshold, private names in RESEARCH.md, a pre freeze sentence that overstated blindness.

**Fixed.** Regime split rows replace pooled rows in the headline, VALIDATION, the README block and the report; data class column
and statement added to PREDICTIONS_RESULTS; README rewritten (no airport claim, recall on injected scenarios only, 3 hour
buckets, third party maps cited from RESEARCH.md 1.1, minimum size caveat); METHODOLOGY gained a Regimes section and the
corrected bounding box; DATA_CARD aligned with the release candidate; plan.md corrected; REVIEW_ROUNDS, REPORT and NEXT_STEPS written;
the baseline numbers that no file reproduced were replaced by values from `results/dev/regime_check.json`;
names removed from RESEARCH.md; a FREEZE_LOG entry records that the builder, generators and web changed after the freeze and the
scoring code did not; the amendment wording was made precise and its edit is disclosed in its section 6. The dashboard items
(data class chips, missing scenario keys, translated labels, a regime panel) were handled in a separate change to `web/` and the
generators.

**Not fixed, and why.**
- Git history still contains the university name and raw fixtures (B4). Rewriting history is an owner decision (NEXT_STEPS).
- The forward chained check (fit up to 2026-03-02, score 2026-03-08 to 2026-03-13) is not done; the held out run is single use.
- Hyphenated words remain in frozen or generated files not owned by the documentation pass (`docs/PREDICTIONS.md`, generated
  tables) and in quoted licence text in `docs/LICENSING.md`, where altering a quotation would be wrong.
- The review noted an uncommitted working tree; the tree is still uncommitted by instruction.
- The unmatched event share in scenario runs (70 of 449) is reported and discussed but not explained.

## Round 5: readability for a non expert (after the held out run)

**Scope.** A technically literate reader who has never seen GNSS or ADS-B reads the README, VALIDATION, PREDICTIONS_RESULTS,
METHODOLOGY, the three dashboard pages and the release package.

**Found (17 findings).** 0 blockers, 9 major, 8 minor.
- Major: README without results, window or summary; README saying the dashboard is synthetic only while it shows real data (and
  a stale warning banner on a fixed snapshot); README promises the project does not keep; the regime change explained nowhere;
  two meanings of easy and hard; undefined jargon; broken Markdown tables from unescaped pipes; a validation page that is hard
  to read; real events that look more certain than they are.
- Minor: no reading order; anchor ids as headings; raw numbers in generated text; term drift (held out, the identifier held_out, and a hyphenated form);
  the Arabic word without a gloss; ids as event labels; displacement trend unexplained; small safety banner on some pages.

**Fixed.** README opens with the safety, no attribution and no endorsement statements, a Start here list, a generated status
block and a plain reading of it; GLOSSARY.md added and linked; METHODOLOGY headings plain with explicit anchors; Arabic gloss;
rounded numbers; the minimum size and data error caveat in README; the generated tables in VALIDATION and PREDICTIONS_RESULTS
use "given" instead of a pipe; the study snapshot mode and regime panel on the dashboard were handled in `web/`.

**Not fixed, and why.**
- `docs/PREDICTIONS.md` is frozen evidence and still contains unescaped pipes in the C4 row; it was not edited.
- Readable event labels instead of ids, and repeating the safety banner in each page lede, were not checked again in this pass.
- The terms "held out" and "development" are used in public text; code keeps `held_out` and `dev` as identifiers.

## Reading the counts

Findings overlap across rounds (the regime change appears in rounds 1, 4 and 5), and counts depend on how a reviewer groups items.
They are a measure of effort and of what was left open, not a quality score. The open items worth the most attention are the git
history rewrite decision, the unverified free tier limits, and the fact that nothing here validates the detector against real
interference.
