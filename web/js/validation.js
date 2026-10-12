import { hasKey, boot, state, t, el, num, mlink, fmtInt, fmtDec, methodLabel } from "./common.js";

function fmtVal(metric, x) {
  if (x === null || x === undefined) return t("common.na");
  return metric.endsWith("_hours") ? fmtDec(x, 1) : (x * 100).toFixed(1) + "%";
}

function render() {
  const body = document.getElementById("validation-body");
  body.textContent = "";
  const v = state.data.validation;
  const rows = (v && Array.isArray(v.results) && v.results) || [];
  if (!v || rows.length === 0) {
    body.append(el("div", { class: "empty card", role: "status" }, el("h2", { text: t("validation.empty_h") }), el("p", { text: t("validation.empty") })));
    return;
  }
  if (state.data.synthetic) body.append(el("p", { class: "help strong", text: t("validation.synthetic_note") }));
  const tbl = el("table", { class: "data" },
    el("caption", { text: t("validation.caption") }),
    el("thead", {}, el("tr", {},
      el("th", { scope: "col", text: t("validation.col_metric") }), el("th", { scope: "col", text: t("validation.col_scenario") }),
      el("th", { scope: "col", class: "n", text: t("validation.col_value") }), el("th", { scope: "col", class: "n", text: t("validation.col_ci") }),
      el("th", { scope: "col", class: "n", text: t("validation.col_n") }))),
    el("tbody"));
  rows.forEach((r) => {
    const tr = el("tr");
    tr.append(el("th", { scope: "row" }, methodLabel(r.metric) + " ", mlink(r.metric)));
    tr.append(el("td", { text: (hasKey("scenario." + r.scenario) ? t("scenario." + r.scenario) : r.scenario) }));
    tr.append(el("td", { class: "n" }, num(fmtVal(r.metric, r.value), r.metric)));
    tr.append(el("td", { class: "n" }, "[", num(fmtVal(r.metric, r.ci_lo), r.metric), ", ", num(fmtVal(r.metric, r.ci_hi), r.metric), "]"));
    tr.append(el("td", { class: "n" }, num(fmtInt(r.n), r.metric)));
    tbl.tBodies[0].append(tr);
  });
  body.append(el("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": t("validation.caption") }, tbl));
  body.append(el("p", { class: "help", text: t("validation.limits") }));
}

boot("validation.html", async () => { render(); });
