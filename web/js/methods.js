import { boot, state, t, el, methodLabel } from "./common.js";

function render() {
  const body = document.getElementById("methods-body");
  body.textContent = "";
  const d = state.data;
  const metrics = (d.methods && (d.methods.metrics || d.methods)) || null;
  if (!d.methods || !metrics) {
    body.append(el("p", { class: "empty", text: t("methods.none") }));
    return;
  }
  const groups = new Map();
  Object.entries(metrics).forEach(([key, v]) => {
    if (!v || typeof v !== "object" || !v.method_anchor) return;
    if (!groups.has(v.method_anchor)) groups.set(v.method_anchor, []);
    groups.get(v.method_anchor).push([key, v]);
  });
  const toc = el("nav", { "aria-label": t("methods.toc"), class: "toc" }, el("h2", { text: t("methods.toc") }));
  const ul = el("ul");
  [...groups.keys()].sort().forEach((a) => ul.append(el("li", {}, el("a", { href: "#" + a, text: a }))));
  toc.append(ul);
  body.append(toc);
  [...groups.keys()].sort().forEach((a) => {
    const sec = el("section", { id: a, class: "panel method-sec", "aria-labelledby": "h-" + a });
    sec.append(el("h2", { id: "h-" + a, text: a }));
    sec.append(el("p", { class: "help" }, t("methods.spec_pre") + " ", el("code", { text: "docs/METHODOLOGY.md#" + a }), "."));
    const tbl = el("table", { class: "data" },
      el("caption", { class: "sr-only", text: t("methods.caption", { anchor: a }) }),
      el("thead", {}, el("tr", {}, el("th", { scope: "col", text: t("methods.col_field") }), el("th", { scope: "col", text: t("methods.col_label") }), el("th", { scope: "col", text: t("methods.col_label_other") }))),
      el("tbody"));
    groups.get(a).sort((x, y) => x[0].localeCompare(y[0])).forEach(([key, v]) => {
      const other = state.lang === "ar" ? v.label_en : v.label_ar;
      tbl.tBodies[0].append(el("tr", {}, el("th", { scope: "row" }, el("code", { text: key })),
        el("td", { lang: state.lang, text: methodLabel(key) }),
        el("td", { lang: state.lang === "ar" ? "en" : "ar", text: other || "" })));
    });
    sec.append(el("div", { class: "table-wrap" }, tbl));
    body.append(sec);
  });
  const un = el("section", { id: "unmapped", class: "panel method-sec", "aria-labelledby": "h-unmapped" },
    el("h2", { id: "h-unmapped", text: t("methods.unmapped_h") }), el("p", { text: t("methods.unmapped") }));
  body.append(un);
}

boot("methods.html", async () => { render(); });
