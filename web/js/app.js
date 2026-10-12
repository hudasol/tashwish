import {
  boot, state, t, el, num, mlink, methodHref, methodLabel, fmtInt, fmtPct, fmtDec, fmtP, fmtStamp, slotLabel, pad2,
  loadDay, attributionPlain, hasKey,
} from "./common.js";
import { sortableTable } from "./table.js";
import { loadLibs } from "./vendor-loader.js";
import { MapView, rowClass, shareBin, isDark, GREY, GLYPH } from "./mapview.js";
import { SHARE_BINS, PALETTE, SOURCE_URL, ODBL_URL, BASEMAP_ATTRIBUTION } from "./config.js";

const S = {
  idx: 0, playing: false, timer: null, show: { share: true, cov: false, events: true },
  selEvent: null, rows: [], cov: [], dayDoc: null, view: null, libsOk: false, bound: false, lastPick: null, token: 0,
};

const D = () => state.data;
const days = () => D().manifest.days.map((d) => d.day);
const nBuckets = () => days().length * D().slots;
const idxToDaySlot = (i) => ({ day: days()[Math.floor(i / D().slots)], slot: i % D().slots, dayIdx: Math.floor(i / D().slots) });

function bucketBounds(i) {
  const { day, slot } = idxToDaySlot(i);
  const bh = D().bucketHours;
  const start = Date.parse(day + "T00:00:00Z") + slot * bh * 3600000;
  return [start, start + bh * 3600000];
}
function isoToIdx(iso) {
  const ms = Date.parse(iso);
  const first = Date.parse(days()[0] + "T00:00:00Z");
  const i = Math.floor((ms - first) / (D().bucketHours * 3600000));
  return Math.max(0, Math.min(nBuckets() - 1, i));
}
function activeEvents(i) {
  const [a, b] = bucketBounds(i);
  return D().events_list.filter((e) => Date.parse(e.start) < b && Date.parse(e.end) > a);
}

/* ---------- toggles, slider ---------- */
function bindControls() {
  if (S.bound) return;
  S.bound = true;
  const slider = document.getElementById("slider");
  slider.addEventListener("input", () => select(Number(slider.value), { announce: true }));
  slider.addEventListener("keydown", (e) => {
    const step = D().slots;
    if (e.key === "PageUp") { e.preventDefault(); select(Math.min(nBuckets() - 1, S.idx + step), { announce: true }); }
    if (e.key === "PageDown") { e.preventDefault(); select(Math.max(0, S.idx - step), { announce: true }); }
  });
  document.getElementById("btn-prev").addEventListener("click", () => select(Math.max(0, S.idx - 1), { announce: true }));
  document.getElementById("btn-next").addEventListener("click", () => select(Math.min(nBuckets() - 1, S.idx + 1), { announce: true }));
  document.getElementById("btn-play").addEventListener("click", togglePlay);
  ["share", "cov", "events"].forEach((k) => document.getElementById("lay-" + k).addEventListener("change", (e) => { S.show[k] = e.target.checked; paintMap(); }));
  document.getElementById("btn-export").addEventListener("click", exportImage);
  document.getElementById("table-view").addEventListener("toggle", () => { if (document.getElementById("table-view").open) renderCellsTable(); });
}

function togglePlay() {
  S.playing = !S.playing;
  const b = document.getElementById("btn-play");
  b.setAttribute("aria-pressed", String(S.playing));
  b.textContent = S.playing ? t("time.pause") : t("time.play");
  clearInterval(S.timer);
  if (S.playing) {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    S.timer = setInterval(() => {
      if (S.idx >= nBuckets() - 1) { togglePlay(); return; }
      select(S.idx + 1, { announce: false });
    }, reduce ? 1800 : 900);
  } else {
    announce();
  }
}

function announce() {
  const { day, slot } = idxToDaySlot(S.idx);
  const c = counts();
  document.getElementById("sr-live").textContent = t("time.live", {
    day, slot: slotLabel(slot, D().bucketHours), ok: c.ok, insuff: c.insuff, lost: c.lost, nocov: c.nocov, events: activeEvents(S.idx).length,
  });
}

function counts() {
  const c = { ok: 0, insuff: 0, lost: 0, nocov: 0 };
  S.rows.forEach((r) => { c[rowClass(r)]++; });
  return c;
}

async function select(i, o = {}) {
  S.idx = i;
  const token = ++S.token;
  const { day, slot, dayIdx } = idxToDaySlot(i);
  const slider = document.getElementById("slider");
  if (Number(slider.value) !== i) slider.value = String(i);
  let doc = null;
  try { doc = await loadDay(day); } catch (e) { doc = null; }
  if (token !== S.token) return;
  S.dayDoc = doc;
  const covRows = D().coverage && D().coverage.cells ? D().coverage.cells : [];
  const covBySlot = covRows.filter((r) => r.slot === slot);
  const covMap = new Map(covBySlot.map((r) => [r.h3, r.class]));
  S.cov = covBySlot;
  S.rows = ((doc && doc.cells) || []).filter((r) => r[1] === slot).map((r) => ({
    h3: r[0], slot: r[1], n: r[2], k: r[3], lo: r[4], hi: r[5], status: r[6], cov: r[7] || covMap.get(r[0]),
    share: r[2] > 0 ? r[3] / r[2] : null,
  }));
  const msg = document.getElementById("map-msg");
  msg.textContent = doc ? "" : t("map.day_missing", { day });
  msg.hidden = !!doc;
  renderReadout();
  paintMap();
  if (document.getElementById("table-view").open) renderCellsTable();
  renderEventsHighlight();
  if (o.announce && !S.playing) announce();
  const meta = D().manifest.days[dayIdx];
  document.getElementById("slider").setAttribute("aria-valuetext", day + ", " + slotLabel(slot, D().bucketHours) + (meta ? ", " + t("split." + meta.split) : ""));
}

function renderReadout() {
  const { day, slot, dayIdx } = idxToDaySlot(S.idx);
  const meta = D().manifest.days[dayIdx];
  const r = document.getElementById("time-readout");
  r.textContent = "";
  r.append(el("strong", { text: day }), " ", el("span", { dir: "ltr", text: slotLabel(slot, D().bucketHours) }), " (", t("split." + (meta ? meta.split : "dev")), "). ");
  const c = counts();
  r.append(t("time.cells") + " ", num(fmtInt(S.rows.length), "n_aircraft"), ": ",
    num(fmtInt(c.ok), "status"), " " + t("status.ok") + ", ",
    num(fmtInt(c.insuff), "status"), " " + t("status.insufficient") + ", ",
    num(fmtInt(c.lost), "status"), " " + t("status.coverage_lost") + ", ",
    num(fmtInt(c.nocov), "status"), " " + t("status.no_coverage") + ". ");
  const ev = activeEvents(S.idx);
  r.append(t("time.events") + " ", num(fmtInt(ev.length), "n_cells"), ".");
  const dl = document.getElementById("slider-days");
  if (!dl) {
    const ds = days();
    const row = el("div", { class: "slider-ends", id: "slider-days", dir: "ltr", "aria-hidden": "true" }, el("span", { text: ds[0] }), el("span", { text: ds[ds.length - 1] }));
    document.querySelector(".time-row").after(row);
  }
}

/* ---------- map ---------- */
function paintMap() {
  if (!S.view) return;
  S.view.setLayers({ rows: S.rows, cov: S.cov, events: activeEvents(S.idx), selected: S.selEvent, show: S.show });
}

async function initMap() {
  const msg = document.getElementById("map-msg");
  msg.textContent = t("map.loading");
  try {
    const rep = await loadLibs();
    S.libReport = rep;
  } catch (e) {
    msg.textContent = t("map.libs_failed");
    S.libsOk = false;
    return;
  }
  S.view = new MapView({
    container: "map", bbox: D().bbox, styleUrl: "map/style.json", basemapUrl: "data/ne_countries.json",
    onPick: (obj, click) => { if (obj) { S.lastPick = obj; renderCellDetail(obj); } },
    onTheme: () => { renderLegend(); paintMap(); },
  });
  try {
    await S.view.init();
    S.libsOk = true;
    msg.textContent = "";
    if (!S.view.hasBasemap) { msg.textContent = t("map.no_basemap"); }
    document.getElementById("map").setAttribute("data-ready", "1");
    paintMap();
  } catch (e) {
    console.error(e);
    msg.textContent = t("map.libs_failed");
  }
}

/* ---------- legend, cell detail ---------- */
function swatch(cls, style) { return el("span", { class: "sw " + cls, style: style || null, "aria-hidden": "true" }); }

function renderLegend() {
  const box = document.getElementById("legend");
  box.textContent = "";
  const pal = isDark() ? PALETTE.dark : PALETTE.light;
  box.append(el("p", { class: "legend-h", text: t("legend.share") }));
  const ul = el("ul", { class: "legend-list share" });
  SHARE_BINS.forEach((lo, i) => {
    const hi = SHARE_BINS[i + 1];
    const lab = hi === undefined ? fmtPct(lo, 0) + " +" : fmtPct(lo, 0) + " to " + fmtPct(hi, 0);
    ul.append(el("li", {}, swatch("share", "background:" + pal[i]), el("span", { dir: "ltr", text: lab })));
  });
  box.append(ul);
  box.append(el("p", { class: "legend-h", text: t("legend.not_assessed") }));
  const u2 = el("ul", { class: "legend-list" });
  u2.append(
    el("li", {}, swatch("p-insuff"), el("span", {}, el("strong", { text: t("status.insufficient") + ": " }), t("legend.insufficient"))),
    el("li", {}, swatch("p-lost"), el("span", {}, el("strong", { text: t("status.coverage_lost") + ": " }), t("legend.lost"))),
    el("li", {}, swatch("p-nocov"), el("span", {}, el("strong", { text: t("status.no_coverage") + ": " }), t("legend.nocov"))),
    el("li", {}, swatch("blank"), el("span", {}, el("strong", { text: t("legend.blank_h") + ": " }), t("legend.blank"))),
    el("li", {}, swatch("marginal"), el("span", {}, el("strong", { text: t("coverage.marginal") + ": " }), t("legend.marginal"))),
  );
  box.append(u2);
  if (S.show.cov) {
    box.append(el("p", { class: "legend-h", text: t("legend.coverage") }));
    box.append(el("ul", { class: "legend-list" },
      el("li", {}, swatch("c-covered"), el("span", { text: t("coverage.covered") })),
      el("li", {}, swatch("c-marginal"), el("span", { text: t("coverage.marginal") })),
      el("li", {}, swatch("p-nocov"), el("span", { text: t("coverage.no_coverage") }))));
  }
  box.append(el("p", { class: "legend-h", text: t("legend.events") }), el("ul", { class: "legend-list" },
    el("li", {}, swatch("ev"), el("span", { text: t("legend.event_outline") }))));
}

function statusText(r) {
  const c = rowClass(r);
  return c === "ok" ? t("status.ok") : c === "lost" ? t("status.coverage_lost") : c === "nocov" ? t("status.no_coverage") : t("status.insufficient");
}

function renderCellDetail(r) {
  const box = document.getElementById("cell-detail");
  box.textContent = "";
  if (!r) { box.append(el("p", { class: "help", text: t("cell.none") })); return; }
  const dl = el("dl", { class: "kv" });
  const add = (label, key, val) => dl.append(el("dt", {}, label + " ", key ? mlink(key) : null), el("dd", {}, val));
  add(t("table.col_h3"), null, el("code", { text: r.h3 }));
  add(methodLabel("status"), "status", el("strong", { text: statusText(r) }));
  add(methodLabel("coverage_class"), "coverage_class", t("coverage." + r.cov));
  add(methodLabel("n_aircraft"), "n_aircraft", num(fmtInt(r.n), "n_aircraft"));
  add(methodLabel("k_strong"), "k_strong", num(fmtInt(r.k), "k_strong"));
  if (rowClass(r) === "ok") {
    add(methodLabel("degraded_share"), "degraded_share", num(fmtPct(r.share), "degraded_share"));
    add(t("table.col_ci"), "ci_lo", el("span", {}, "[", num(fmtPct(r.lo), "ci_lo"), ", ", num(fmtPct(r.hi), "ci_hi"), "]"));
  } else {
    add(methodLabel("degraded_share"), "degraded_share", el("span", { class: "na", text: t("cell.not_assessed") }));
  }
  box.append(dl);
}

/* ---------- accessible table ---------- */
function renderCellsTable() {
  const wrap = document.getElementById("cells-table");
  wrap.textContent = "";
  document.getElementById("table-note").textContent = t("table.note", { n: S.rows.length });
  const { day, slot } = idxToDaySlot(S.idx);
  const cols = [
    { id: "h3", label: t("table.col_h3"), value: (r) => r.h3, cell: (r) => el("button", { type: "button", class: "linkbtn", onclick: () => { renderCellDetail(r); document.getElementById("h-cell").scrollIntoView({ block: "nearest" }); }, text: r.h3 }) },
    { id: "status", label: methodLabel("status"), methodKey: "status", value: (r) => statusText(r), cell: (r) => statusText(r) },
    { id: "cov", label: methodLabel("coverage_class"), methodKey: "coverage_class", value: (r) => r.cov, cell: (r) => t("coverage." + r.cov) },
    { id: "n", label: methodLabel("n_aircraft"), methodKey: "n_aircraft", numeric: true, value: (r) => r.n, cell: (r) => num(fmtInt(r.n), "n_aircraft") },
    { id: "k", label: methodLabel("k_strong"), methodKey: "k_strong", numeric: true, value: (r) => r.k, cell: (r) => num(fmtInt(r.k), "k_strong") },
    { id: "share", label: methodLabel("degraded_share"), methodKey: "degraded_share", numeric: true, value: (r) => (rowClass(r) === "ok" ? r.share : null), cell: (r) => (rowClass(r) === "ok" ? num(fmtPct(r.share), "degraded_share") : el("span", { class: "na", text: t("cell.not_assessed") })) },
    { id: "lo", label: methodLabel("ci_lo"), methodKey: "ci_lo", numeric: true, value: (r) => r.lo, cell: (r) => (r.lo === null ? t("common.na") : num(fmtPct(r.lo), "ci_lo")) },
    { id: "hi", label: methodLabel("ci_hi"), methodKey: "ci_hi", numeric: true, value: (r) => r.hi, cell: (r) => (r.hi === null ? t("common.na") : num(fmtPct(r.hi), "ci_hi")) },
  ];
  wrap.append(sortableTable(cols, S.rows, { caption: t("table.caption", { day, slot: slotLabel(slot, D().bucketHours) }), sort: { id: "share", dir: "desc" } }));
}

/* ---------- events ---------- */
function renderEvents() {
  const wrap = document.getElementById("events-table");
  wrap.textContent = "";
  const evs = D().events_list;
  if (!evs.length) { wrap.append(el("p", { class: "empty", text: t("events.none") })); renderEvidence(null); return; }
  const kind = (e) => t("kind." + e.kind);
  const cols = [
    { id: "id", label: t("events.col_id"), value: (e) => e.event_id, cell: (e) => el("button", { type: "button", class: "linkbtn", "aria-pressed": String(S.selEvent === e.event_id), onclick: () => selectEvent(e.event_id, true), text: e.event_id }) },
    { id: "kind", label: methodLabel("kind"), methodKey: "kind", value: kind, cell: (e) => kind(e) + (e.label_uncertain ? " (" + t("events.uncertain_short") + ")" : "") },
    { id: "conf", label: methodLabel("confidence"), methodKey: "confidence", value: (e) => ({ low: 0, medium: 1, high: 2 }[e.confidence]), cell: (e) => t("confidence." + e.confidence) },
    { id: "start", label: t("events.col_start"), value: (e) => e.start, cell: (e) => el("span", { class: "nowrap", dir: "ltr", text: fmtStamp(e.start) }) },
    { id: "end", label: t("events.col_end"), value: (e) => e.end, cell: (e) => el("span", { class: "nowrap", dir: "ltr", text: fmtStamp(e.end) }) },
    { id: "cells", label: methodLabel("n_cells"), methodKey: "n_cells", numeric: true, value: (e) => e.n_cells, cell: (e) => num(fmtInt(e.n_cells), "n_cells") },
    { id: "peak", label: methodLabel("peak_share"), methodKey: "peak_share", numeric: true, value: (e) => e.peak_share, cell: (e) => num(fmtPct(e.peak_share), "peak_share") },
    { id: "p", label: methodLabel("min_p"), methodKey: "min_p", numeric: true, value: (e) => e.min_p, cell: (e) => num(fmtP(e.min_p), "min_p") },
  ];
  wrap.append(sortableTable(cols, evs, { caption: t("events.caption"), sort: { id: "start", dir: "asc" }, rowClass: (e) => (e.event_id === S.selEvent ? "sel" : "") }));
  renderEvidence(evs.find((e) => e.event_id === S.selEvent) || null);
}

function renderEventsHighlight() {
  document.querySelectorAll("#events-table tbody tr").forEach((tr) => {
    const id = tr.querySelector("button") && tr.querySelector("button").textContent;
    tr.classList.toggle("sel", id === S.selEvent);
    const b = tr.querySelector("button");
    if (b) b.setAttribute("aria-pressed", String(id === S.selEvent));
  });
}

function selectEvent(id, jump) {
  S.selEvent = id;
  const ev = D().events_list.find((e) => e.event_id === id);
  renderEventsHighlight();
  renderEvidence(ev);
  if (ev && jump) {
    select(isoToIdx(ev.start), { announce: true });
    if (S.view) S.view.fitTo(ev.lon, ev.lat, 6);
  } else paintMap();
}

function renderEvidence(ev) {
  const box = document.getElementById("evidence-body");
  box.textContent = "";
  if (!ev) { box.append(el("p", { class: "help", text: t("evidence.none") })); return; }
  box.append(el("h4", { class: "ev-id", text: ev.event_id }));
  const dl = el("dl", { class: "kv" });
  const add = (key, val) => dl.append(el("dt", {}, el("a", { href: methodHref(key), text: methodLabel(key) })), el("dd", {}, val));
  add("kind", t("kind." + ev.kind));
  add("label_uncertain", ev.label_uncertain ? t("common.yes") : t("common.no"));
  add("confidence", t("confidence." + ev.confidence));
  dl.append(el("dt", { text: t("events.col_start") }), el("dd", { class: "nowrap", dir: "ltr", text: fmtStamp(ev.start) }));
  dl.append(el("dt", { text: t("events.col_end") }), el("dd", { class: "nowrap", dir: "ltr", text: fmtStamp(ev.end) }));
  add("n_cells", num(fmtInt(ev.n_cells), "n_cells"));
  add("n_aircraft", num(fmtInt(ev.n_aircraft), "n_aircraft"));
  add("k_degraded", num(fmtInt(ev.k_degraded), "k_degraded"));
  add("peak_share", num(fmtPct(ev.peak_share), "peak_share"));
  add("peak_ci_lo", num(fmtPct(ev.peak_ci_lo), "peak_ci_lo"));
  add("min_p", num(fmtP(ev.min_p), "min_p"));
  add("lat", num(fmtDec(ev.lat, 3), "lat"));
  add("lon", num(fmtDec(ev.lon, 3), "lon"));
  box.append(dl);
  const evd = ev.evidence || {};
  const keys = Object.keys(evd);
  if (keys.length) {
    box.append(el("h5", { text: t("evidence.free") }));
    const d2 = el("dl", { class: "kv" });
    keys.forEach((k) => {
      const key = "evidence." + k;
      const v = evd[k];
      const shown = typeof v === "number" ? (Number.isInteger(v) ? fmtInt(v) : (Math.abs(v) < 1 ? fmtPct(v) : fmtDec(v, 2))) : String(v);
      d2.append(el("dt", {}, el("a", { href: methodHref(key), text: methodLabel(key) })), el("dd", {}, typeof v === "number" ? num(shown, key) : shown));
    });
    box.append(d2);
  }
  const ml = el("ul", { class: "inline" });
  (ev.methods || []).forEach((a) => ml.append(el("li", {}, el("a", { href: "methods.html#" + a, text: a }))));
  box.append(el("h5", { text: t("evidence.methods") }), ml);
  box.append(el("button", { type: "button", class: "btn", text: t("evidence.show_on_map"), onclick: () => selectEvent(ev.event_id, true) }));
}

/* ---------- downloads ---------- */
function renderDownloads() {
  const body = document.getElementById("dl-body");
  body.textContent = "";
  const d = D();
  const syn = d.synthetic;
  body.append(el("p", { text: t(syn ? "dl.intro_syn" : "dl.intro") }));
  const base = state.base;
  const files = [["manifest.json", "dl.f_manifest"], ["events.json", "dl.f_events"], ["coverage.json", "dl.f_coverage"], ["validation.json", "dl.f_validation"], ["methods.json", "dl.f_methods"]];
  const ul = el("ul", { class: "dl-list" });
  files.forEach(([f, k]) => ul.append(el("li", {}, el("a", { href: base + f, download: "", text: (syn ? "SYNTHETIC " : "") + f }), " - " + t(k))));
  d.manifest.days.forEach((x) => ul.append(el("li", {}, el("a", { href: base + "days/" + x.day + ".json", download: "", text: (syn ? "SYNTHETIC " : "") + "days/" + x.day + ".json" }), " - " + t("dl.f_day"))));
  body.append(ul);
  body.append(el("h3", { text: t("dl.placeholders") }));
  body.append(el("ul", { class: "dl-list" },
    el("li", {}, el("span", { class: "placeholder", "aria-disabled": "true", text: "tashwish_cells_" + (syn ? "SYNTHETIC_" : "") + "v0.parquet" }), " - " + t("dl.p_cells")),
    el("li", {}, el("span", { class: "placeholder", "aria-disabled": "true", text: "tashwish_events_" + (syn ? "SYNTHETIC_" : "") + "v0.csv" }), " - " + t("dl.p_events")),
    el("li", {}, el("span", { class: "placeholder", "aria-disabled": "true", text: "DATA_CARD.md" }), " - " + t("dl.p_card"))));
  const n = el("p", { class: "notice", lang: "en", dir: "ltr" });
  const a = attributionPlain();
  const i1 = a.indexOf("adsb.lol"), i2 = a.indexOf("Open Database License (ODbL)");
  if (i1 >= 0 && i2 >= 0) n.append(a.slice(0, i1), el("a", { href: SOURCE_URL, text: "adsb.lol" }), a.slice(i1 + 8, i2), el("a", { href: ODBL_URL, text: "Open Database License (ODbL)" }), a.slice(i2 + 28));
  else n.append(a);
  body.append(n);
}

/* ---------- export ---------- */
function wrapText(ctx, text, maxW) {
  const words = text.split(" ");
  const lines = [];
  let cur = "";
  words.forEach((w) => {
    const test = cur ? cur + " " + w : w;
    if (ctx.measureText(test).width > maxW && cur) { lines.push(cur); cur = w; } else cur = test;
  });
  if (cur) lines.push(cur);
  return lines;
}

async function exportImage() {
  if (!S.view || !S.libsOk) return;
  const btn = document.getElementById("btn-export");
  btn.disabled = true;
  try {
    const src = await S.view.snapshotCanvas();
    const W = src.width, H = src.height;
    const k = W / 960; // scale text with image width
    const pad = 14 * k, fs = 13 * k;
    const syn = D().synthetic;
    const dark = isDark();
    const fg = dark ? "#f3e9ee" : "#2a2326", bg = dark ? "#17141a" : "#ffffff";
    const rtl = state.lang === "ar";
    const tmp = document.createElement("canvas").getContext("2d");
    tmp.font = fs + "px system-ui, sans-serif";
    const { day, slot } = idxToDaySlot(S.idx);
    const lines = [];
    const addWrapped = (text) => wrapText(tmp, text, W - 2 * pad).forEach((l) => lines.push(l));
    addWrapped(attributionPlain());
    addWrapped("Source: " + SOURCE_URL + "   Licence: " + ODBL_URL);
    addWrapped(BASEMAP_ATTRIBUTION + ". " + t("footer.libs"));
    addWrapped(t("banner.safety"));
    const bannerH = syn ? 46 * k : 0;
    const titleH = 30 * k;
    const legendH = 38 * k;
    const footH = lines.length * (fs * 1.35) + pad * 1.5;
    const out = document.createElement("canvas");
    out.width = W; out.height = Math.round(bannerH + titleH + H + legendH + footH);
    const g = out.getContext("2d");
    g.fillStyle = bg; g.fillRect(0, 0, out.width, out.height);
    let y = 0;
    if (syn) {
      g.fillStyle = "#b00020"; g.fillRect(0, 0, W, bannerH);
      g.fillStyle = "#fff"; g.font = "bold " + 26 * k + "px system-ui, sans-serif"; g.textBaseline = "middle"; g.textAlign = "center";
      g.fillText(t("banner.synthetic") + " - " + t("banner.synthetic_sub"), W / 2, bannerH / 2, W - 2 * pad);
      y += bannerH;
    }
    g.fillStyle = fg; g.textBaseline = "middle";
    g.font = "bold " + 16 * k + "px system-ui, sans-serif";
    g.direction = rtl ? "rtl" : "ltr"; g.textAlign = rtl ? "right" : "left";
    g.fillText(t("export.title", { day, slot: slotLabel(slot, D().bucketHours) }), rtl ? W - pad : pad, y + titleH / 2, W - 2 * pad);
    y += titleH;
    g.drawImage(src, 0, y);
    if (syn) { // watermark inside the map area
      g.save(); g.translate(W / 2, y + H / 2); g.rotate(-0.35);
      g.fillStyle = "rgba(176,0,32,0.28)"; g.font = "bold " + 90 * k + "px system-ui, sans-serif"; g.textAlign = "center"; g.direction = "ltr";
      g.fillText("SYNTHETIC SAMPLE", 0, 0); g.restore();
    }
    y += H;
    // legend strip
    const pal = isDark() ? PALETTE.dark : PALETTE.light;
    g.direction = rtl ? "rtl" : "ltr"; g.textAlign = "left"; g.font = fs * 0.9 + "px system-ui, sans-serif";
    let x = pad;
    g.fillStyle = fg; g.direction = "ltr";
    g.fillText(t("legend.share") + ":", x, y + legendH / 2);
    x += g.measureText(t("legend.share") + ":").width + 8 * k;
    SHARE_BINS.forEach((lo, i) => {
      g.fillStyle = pal[i]; g.fillRect(x, y + legendH / 2 - 8 * k, 18 * k, 16 * k);
      g.strokeStyle = fg; g.lineWidth = 1; g.strokeRect(x, y + legendH / 2 - 8 * k, 18 * k, 16 * k);
      g.fillStyle = fg; const lab = Math.round(lo * 100) + "%";
      g.fillText(lab, x + 21 * k, y + legendH / 2); x += 21 * k + g.measureText(lab).width + 10 * k;
    });
    const grey = GREY[dark ? "dark" : "light"];
    [["status.insufficient", "insuff"], ["status.coverage_lost", "lost"], ["status.no_coverage", "nocov"]].forEach(([key, id]) => {
      g.fillStyle = "rgb(" + grey[id].join(",") + ")"; g.fillRect(x, y + legendH / 2 - 8 * k, 16 * k, 16 * k);
      g.strokeStyle = fg; g.strokeRect(x, y + legendH / 2 - 8 * k, 16 * k, 16 * k);
      g.fillStyle = fg; g.textAlign = "center"; g.fillText(GLYPH[id], x + 8 * k, y + legendH / 2); g.textAlign = "left";
      const lab = t(key);
      if (x + 20 * k + g.measureText(lab).width < W) g.fillText(lab, x + 20 * k, y + legendH / 2);
      x += 24 * k + g.measureText(lab).width;
    });
    y += legendH;
    // footer notice (always present in the image)
    g.fillStyle = dark ? "#2a2530" : "#f6eef1"; g.fillRect(0, y, W, out.height - y);
    g.fillStyle = fg; g.font = fs + "px system-ui, sans-serif"; g.textAlign = "left"; g.direction = "ltr"; g.textBaseline = "top";
    lines.forEach((l, i) => g.fillText(l, pad, y + pad * 0.75 + i * fs * 1.35));
    const blob = await new Promise((res) => out.toBlob(res, "image/png"));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "tashwish-" + day + "-slot" + slot + (syn ? "-SYNTHETIC" : "") + ".png";
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    document.getElementById("sr-live").textContent = t("export.done");
  } finally {
    btn.disabled = false;
  }
}

/* ---------- boot ---------- */
async function render(isRerender) {
  const d = D();
  const wm = document.getElementById("watermark");
  wm.hidden = !d.synthetic;
  wm.textContent = d.synthetic ? t("banner.synthetic") : "";
  const slider = document.getElementById("slider");
  slider.max = String(nBuckets() - 1);
  slider.setAttribute("aria-label", t("time.slider"));
  document.getElementById("btn-play").textContent = S.playing ? t("time.pause") : t("time.play");
  document.getElementById("btn-prev").textContent = "‹";
  document.getElementById("btn-next").textContent = "›";
  const sd = document.getElementById("slider-days"); if (sd) sd.remove();
  renderLegend();
  renderDownloads();
  renderEvents();
  renderCellDetail(S.lastPick && S.lastPick);
  bindControls();
  if (!isRerender) {
    const high = d.events_list.find((e) => e.confidence === "high") || d.events_list[0];
    S.idx = high ? isoToIdx(high.start) + 1 : nBuckets() - 1;
    S.idx = Math.min(S.idx, nBuckets() - 1);
    if (high) S.selEvent = high.event_id;
    renderEvents();
    await select(S.idx, {});
    initMap();
  } else {
    await select(S.idx, {});
    renderEvents();
  }
}

boot("index.html", render);
