import { hasKey, boot, state, t, el, num, mlink, fmtInt, fmtDec, methodLabel } from "./common.js";

const REPO_RESULTS_URL = "https://github.com/hudasol/tashwish/blob/main/docs/PREDICTIONS_RESULTS.md";

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
  body.append(el("p", { class: "help" }, t("validation.misses") + " ", el("a", { href: REPO_RESULTS_URL, rel: "noopener", text: t("validation.misses_link") }), "."));
  body.append(el("p", { class: "help", text: t("validation.limits") }));
}

boot("validation.html", async () => { render(); });
