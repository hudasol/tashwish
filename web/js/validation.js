import { hasKey, boot, state, t, el, num, mlink, fmtInt, fmtDec, methodLabel } from "./common.js";

const REPO_RESULTS_URL = "https://github.com/hudasol/tashwish/blob/main/docs/research/PREDICTIONS_RESULTS.md";
const REPO_BASELINES_URL = "https://github.com/hudasol/tashwish/blob/main/docs/BASELINES.md";

function fmtVal(metric, x) {
  if (x === null || x === undefined) return t("common.na");
  return metric.endsWith("_hours") ? fmtDec(x, 1) : (x * 100).toFixed(1) + "%";
}

// Rows follow the row contract (metric, scenario, data_class, regime, value, ci_lo, ci_hi, n, ci_method, note).
// Older files carry only metric, scenario, value, ci_lo, ci_hi, n: defaults are filled here, never invented upstream.
export function normaliseRow(r, fileSynthetic) {
  const scenario = r.scenario || "";
  let dc = r.data_class || (scenario.startsWith("synthetic") ? "synthetic" : "observed");
  if (fileSynthetic) dc = "synthetic"; // a synthetic sample file has no observed rows
  if (dc !== "synthetic" && dc !== "observed") dc = "observed";
  return { ...r, scenario, data_class: dc, regime: r.regime || "pooled", ci_method: r.ci_method || "wilson", note: r.note || "" };
}

const lookup = (prefix, id, fallback) => (hasKey(prefix + id) ? t(prefix + id) : fallback);
const humanise = (s) => String(s).replace(/_/g, " ");

function chip(dc) {
  return el("span", { class: "chip " + (dc === "synthetic" ? "syn" : "obs"), text: t("chip." + dc) });
}

function rowTable(rows, caption) {
  const tbl = el("table", { class: "data" },
    el("caption", { class: "sr-only", text: caption }),
    el("thead", {}, el("tr", {},
      el("th", { scope: "col", text: t("validation.col_metric") }), el("th", { scope: "col", text: t("validation.col_tested") }),
      el("th", { scope: "col", class: "n", text: t("validation.col_value") }), el("th", { scope: "col", class: "n", text: t("validation.col_ci") }),
      el("th", { scope: "col", class: "n", text: t("validation.col_n") }), el("th", { scope: "col", text: t("validation.col_meaning") }))),
    el("tbody"));
  rows.forEach((r) => {
    const tr = el("tr");
    const label = state.data.methods && state.data.methods.metrics && state.data.methods.metrics[r.metric] ? methodLabel(r.metric) : humanise(r.metric);
    tr.append(el("th", { scope: "row" }, label + " ", mlink(r.metric), el("span", { class: "cell-sub" }, chip(r.data_class))));
    tr.append(el("td", {}, lookup("scenario.", r.scenario, humanise(r.scenario)),
      el("span", { class: "cell-sub", text: lookup("regime.", r.regime, humanise(r.regime)) })));
    tr.append(el("td", { class: "n" }, num(fmtVal(r.metric, r.value), r.metric)));
    tr.append(el("td", { class: "n" }, "[", num(fmtVal(r.metric, r.ci_lo), r.metric), ", ", num(fmtVal(r.metric, r.ci_hi), r.metric), "]",
      el("span", { class: "cell-sub", text: lookup("ci.", r.ci_method, humanise(r.ci_method)) })));
    tr.append(el("td", { class: "n" }, num(fmtInt(r.n), r.metric)));
    tr.append(el("td", {}, lookup("vrow.", r.metric.replace(/_(normal|reduced)$/, ""), t("vrow.generic_" + r.data_class)),
      r.note ? el("span", { class: "cell-sub", text: r.note }) : null));
    tbl.tBodies[0].append(tr);
  });
  return el("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": caption }, tbl);
}

/* ---------- comparison with simple detectors (web/data/baselines.json, optional) ---------- */
const BL_TIERS = ["easy", "medium", "hard", "random"];
const BL_TIER_KEYS = { easy: "baselines.col_easy", medium: "baselines.col_medium", hard: "baselines.col_hard", random: "baselines.col_random" };
const BL_SPLITS = [["dev", "baselines.split_dev_h", "baselines.split_dev_p"], ["held_out", "baselines.split_held_h", "baselines.split_held_p"]];
const BL_REGIME_COLS = [["pooled", "baselines.col_pooled"], ["traffic_normal", "baselines.col_normal"], ["traffic_reduced", "baselines.col_reduced"]];
let blRegime = "pooled"; // regime shown in the recall tables; kept when the language is switched

// Rows of the file that the page can place: a known class and split, a number, a detector label. Anything else is dropped.
export function baselineRows(file) {
  const rows = (file && Array.isArray(file.results) && file.results) || [];
  return rows.filter((r) => r && (r.data_class === "synthetic" || r.data_class === "observed") && (r.split === "dev" || r.split === "held_out")
    && typeof r.value === "number" && r.detector && r.label_en);
}

const blLabel = (r) => (state.lang === "ar" && r.label_ar ? r.label_ar : r.label_en);
const blFmt = (x, kind) => (kind === "pct" ? (x * 100).toFixed(1) + "%" : x.toFixed(1));
const blNum = (text) => el("span", { class: "bl-num", text });

function blCell(r, kind, nKey, applicable) {
  if (!r) return el("td", { class: "n" }, el("span", { class: "cell-sub", text: t(applicable ? "common.na" : "baselines.not_applicable") }));
  const interval = typeof r.ci_lo === "number" && typeof r.ci_hi === "number"
    ? el("span", { class: "cell-sub" }, blNum("[" + blFmt(r.ci_lo, kind) + ", " + blFmt(r.ci_hi, kind) + "]")) : null;
  return el("td", { class: "n" }, blNum(blFmt(r.value, kind)), interval,
    el("span", { class: "cell-sub", text: t(nKey, { n: fmtInt(r.n) }) }));
}

function blTable(caption, firstHead, cols, detectors, cellFor) {
  const tbl = el("table", { class: "data bl-table" },
    el("caption", { class: "sr-only", text: caption }),
    el("thead", {}, el("tr", {}, el("th", { scope: "col", text: firstHead }),
      ...cols.map((c) => el("th", { scope: "col", class: "n", text: c })))),
    el("tbody"));
  detectors.forEach((d) => {
    const tr = el("tr", { class: d.detector === "system" ? "sys" : null });
    tr.append(el("th", { scope: "row", text: blLabel(d) }));
    cellFor(d).forEach((c) => tr.append(c));
    tbl.tBodies[0].append(tr);
  });
  return el("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": caption }, tbl);
}

// Detectors of a set of rows in the order the file lists them (the file puts the system first).
function blDetectors(rows) {
  const seen = new Map();
  rows.forEach((r) => { if (!seen.has(r.detector)) seen.set(r.detector, r); });
  return [...seen.values()];
}

function blSyntheticTable(rows, splitName) {
  const jam = rows.filter((r) => r.metric === "jamming_recall"), spoof = rows.filter((r) => r.metric === "spoofing_recall_3plus");
  const dets = blDetectors(rows);
  const jamSet = new Set(jam.map((r) => r.detector)), spoofSet = new Set(spoof.map((r) => r.detector));
  const find = (list, d, tier) => list.find((r) => r.detector === d.detector && r.regime === blRegime && (tier ? r.tier === tier : true));
  const cols = [...BL_TIERS.map((k) => t(BL_TIER_KEYS[k])), t("baselines.col_spoof")];
  return blTable(t("baselines.syn_cap", { split: splitName }), t("baselines.col_detector"), cols, dets, (d) => [
    ...BL_TIERS.map((k) => blCell(find(jam, d, k), "pct", "baselines.n_scen", jamSet.has(d.detector))),
    blCell(find(spoof, d), "pct", "baselines.n_scen", spoofSet.has(d.detector)),
  ]);
}

function blObservedTable(rows, capKey, splitName) {
  const cols = BL_REGIME_COLS.map(([, k]) => t(k));
  return blTable(t(capKey, { split: splitName }), t("baselines.col_detector"), cols, blDetectors(rows), (d) =>
    BL_REGIME_COLS.map(([reg]) => blCell(rows.find((r) => r.detector === d.detector && r.regime === reg), "dec", "baselines.n_days", true)));
}

function renderBaselines(body) {
  const all = baselineRows(state.data.baselines);
  if (!all.length) return; // no file, or nothing the page can place: the section stays hidden
  const sec = el("section", { class: "bl", "aria-labelledby": "bl-h" });
  sec.append(el("h2", { class: "group-h", id: "bl-h", text: t("baselines.h") }), el("p", { class: "help", text: t("baselines.lede") }));
  const synRegimes = BL_REGIME_COLS.map(([r]) => r).filter((r) => all.some((x) => x.data_class === "synthetic" && x.regime === r));
  if (!synRegimes.includes(blRegime)) blRegime = synRegimes[0] || "pooled";
  const synBoxes = [];
  if (synRegimes.length > 1) {
    const sel = el("select", { id: "bl-regime", onchange: (e) => {
      blRegime = e.target.value;
      synBoxes.forEach(({ box, rows, name }) => { box.textContent = ""; box.append(blSyntheticTable(rows, name)); });
    } }, ...BL_REGIME_COLS.filter(([r]) => synRegimes.includes(r)).map(([r, k]) => el("option", { value: r, selected: r === blRegime, text: t(k) })));
    sec.append(el("p", { class: "bl-ctl" }, el("label", { for: "bl-regime", text: t("baselines.regime_label") + " " }), sel));
  }
  BL_SPLITS.forEach(([split, h, p]) => {
    const rows = all.filter((r) => r.split === split);
    if (!rows.length) return;
    const name = t(h);
    sec.append(el("h3", { text: name }), el("p", { class: "help", text: t(p) }));
    const synRows = rows.filter((r) => r.data_class === "synthetic");
    if (synRows.length) {
      const box = el("div", { class: "bl-box" });
      box.append(blSyntheticTable(synRows, name));
      synBoxes.push({ box, rows: synRows, name });
      sec.append(el("h4", {}, chip("synthetic"), " " + t("baselines.syn_h")), el("p", { class: "help", text: t("baselines.syn_p") }), box);
    }
    const jamObs = rows.filter((r) => r.data_class === "observed" && r.metric === "flagged_per_day_jamming_like");
    const spoofObs = rows.filter((r) => r.data_class === "observed" && r.metric === "flagged_per_day_spoofing_like");
    if (jamObs.length) {
      sec.append(el("h4", {}, chip("observed"), " " + t("baselines.obs_h")), el("p", { class: "help strong", text: t("baselines.obs_p") }),
        blObservedTable(jamObs, "baselines.obs_cap", name));
    }
    if (spoofObs.length) sec.append(el("h4", { text: t("baselines.obs_spoof_h") }), blObservedTable(spoofObs, "baselines.obs_spoof_cap", name));
  });
  sec.append(el("p", { class: "help" }, el("a", { href: REPO_BASELINES_URL, rel: "noopener", text: t("baselines.docs_link") }), "."));
  body.append(sec);
}

function render() {
  const body = document.getElementById("validation-body");
  body.textContent = "";
  const v = state.data.validation;
  const raw = (v && Array.isArray(v.results) && v.results) || [];
  if (!v || raw.length === 0) {
    body.append(el("div", { class: "empty card", role: "status" }, el("h2", { text: t("validation.empty_h") }), el("p", { text: t("validation.empty") })));
    return;
  }
  const rows = raw.map((r) => normaliseRow(r, state.data.synthetic));
  if (state.data.synthetic) body.append(el("p", { class: "help strong", text: t("validation.synthetic_note") }));
  [["synthetic", "validation.group_syn_h", "validation.group_syn_p"], ["observed", "validation.group_obs_h", "validation.group_obs_p"]].forEach(([dc, h, p]) => {
    const g = rows.filter((r) => r.data_class === dc);
    if (!g.length) return;
    body.append(el("h2", { class: "group-h", text: t(h) }), el("p", { class: "help", text: t(p) }), rowTable(g, t(h)));
  });
  renderBaselines(body);
  body.append(el("p", { class: "help" }, t("validation.misses") + " ", el("a", { href: REPO_RESULTS_URL, rel: "noopener", text: t("validation.misses_link") }), "."));
  body.append(el("p", { class: "help", text: t("validation.limits") }));
}

boot("validation.html", async () => { render(); });
