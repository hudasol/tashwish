import { DATA_ROOT, SAMPLE_ROOT, SCHEMA, SOURCE_URL, ODBL_URL, SOURCE_NAME, ODBL_NAME } from "./config.js";

const LS_LANG = "tashwish.lang";
export const state = {
  lang: "en",
  dict: {},
  fallback: {},
  base: SAMPLE_ROOT,
  data: null,
  warned: new Set(),
};

/* ---------- storage (wrapped, may throw) ---------- */
function lsGet(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* ignore */ } }

/* ---------- i18n ---------- */
async function fetchJson(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}

export async function initI18n() {
  const stored = lsGet(LS_LANG);
  const nav = (navigator.language || "en").toLowerCase();
  state.lang = stored === "ar" || stored === "en" ? stored : nav.startsWith("ar") ? "ar" : "en";
  state.fallback = await fetchJson("i18n/en.json");
  state.dict = state.lang === "en" ? state.fallback : await fetchJson("i18n/ar.json");
  applyLangAttrs();
}

function applyLangAttrs() {
  const h = document.documentElement;
  h.lang = state.lang;
  h.dir = state.lang === "ar" ? "rtl" : "ltr";
}

export async function setLang(lang) {
  state.lang = lang;
  lsSet(LS_LANG, lang);
  state.dict = lang === "en" ? state.fallback : await fetchJson("i18n/ar.json");
  applyLangAttrs();
}

export function t(key, vars) {
  let s = state.dict[key];
  if (s === undefined) s = state.fallback[key];
  if (s === undefined) {
    if (!state.warned.has(key)) { state.warned.add(key); console.warn("missing i18n key", key); }
    return key;
  }
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  return s;
}

export const hasKey = (k) => state.dict[k] !== undefined || state.fallback[k] !== undefined;

export function applyI18n(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll("[data-i18n-label]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nLabel)); });
  root.querySelectorAll("[data-i18n-title]").forEach((el) => { el.setAttribute("title", t(el.dataset.i18nTitle)); });
  const title = document.body.dataset.titleKey;
  if (title) document.title = t(title) + " | Tashwish";
}

/* ---------- number and date formatting ---------- */
const nf = () => new Intl.NumberFormat(state.lang === "ar" ? "ar-u-nu-latn" : "en-US");
export const fmtInt = (n) => (n === null || n === undefined ? t("common.na") : nf().format(n));
export const fmtPct = (x, d = 1) => (x === null || x === undefined ? t("common.na") : (x * 100).toFixed(d) + "%");
export const fmtDec = (x, d = 2) => (x === null || x === undefined ? t("common.na") : Number(x).toFixed(d));
export const fmtP = (p) => (p === null || p === undefined ? t("common.na") : Number(p).toExponential(2));
export const pad2 = (n) => String(n).padStart(2, "0");
export const fmtStamp = (iso) => (iso ? iso.replace("T", " ").replace(/:\d\dZ$/, "") + " UTC" : t("common.na"));

export function slotLabel(slot, bucketHours) {
  const a = slot * bucketHours, b = a + bucketHours;
  return pad2(a) + ":00 to " + pad2(b) + ":00 UTC";
}

/* ---------- method links ---------- */
export function methodAnchor(key) {
  const m = state.data && state.data.methods && state.data.methods.metrics && state.data.methods.metrics[key];
  if (m && m.method_anchor) return m.method_anchor;
  if (!state.warned.has("m:" + key)) { state.warned.add("m:" + key); console.warn("no method entry for", key); }
  return "unmapped";
}
export const methodHref = (key) => "methods.html#" + methodAnchor(key);

export function methodLabel(key) {
  const m = state.data && state.data.methods && state.data.methods.metrics && state.data.methods.metrics[key];
  if (!m) return key;
  return (state.lang === "ar" ? m.label_ar : m.label_en) || m.label_en || key;
}

// A displayed number: a span carrying data-method (see docs/DASHBOARD.md). Clicking opens the method section.
export function num(text, key) {
  const s = document.createElement("span");
  s.className = "num";
  s.textContent = text;
  s.dataset.method = methodHref(key);
  s.title = t("common.method_for", { name: methodLabel(key) });
  return s;
}

export function mlink(key, text) {
  const a = document.createElement("a");
  a.href = methodHref(key);
  a.className = "mlink";
  a.textContent = text === undefined ? t("common.method") : text;
  a.setAttribute("aria-label", t("common.method_for", { name: methodLabel(key) }));
  return a;
}

document.addEventListener("click", (e) => {
  const n = e.target.closest && e.target.closest("[data-method]");
  if (!n || e.target.closest("a, button")) return;
  window.open(n.dataset.method, "_blank", "noopener");
});

/* ---------- element helper ---------- */
export function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids) if (kid !== null && kid !== undefined) e.append(kid);
  return e;
}

/* ---------- data loading ---------- */
async function tryJson(url) {
  try {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) return null;
    const ct = r.headers.get("content-type") || "";
    if (!/json|text\/plain|octet/.test(ct)) return null;
    return await r.json();
  } catch (e) { return null; }
}

export function normaliseBbox(b) {
  if (!b) return null;
  if (Array.isArray(b)) return { west: b[0], south: b[1], east: b[2], north: b[3] };
  return b;
}

export async function loadData() {
  let base = DATA_ROOT;
  let manifest = await tryJson(base + "manifest.json");
  if (!manifest) { base = SAMPLE_ROOT; manifest = await tryJson(base + "manifest.json"); }
  if (!manifest) throw new Error(t("error.no_data"));
  const names = ["events", "coverage", "validation", "methods"];
  const files = await Promise.all(names.map((n) => tryJson(base + n + ".json")));
  const data = { base, manifest, events: files[0], coverage: files[1], validation: files[2], methods: files[3], missing: [] };
  names.forEach((n, i) => { if (!files[i]) data.missing.push(n); });
  // contract checks: schema, one data class everywhere (never mix synthetic and observed)
  const dc = manifest.data_class;
  if (manifest.schema !== SCHEMA) throw new Error(t("error.schema", { schema: String(manifest.schema) }));
  if (dc !== "synthetic" && dc !== "observed") throw new Error(t("error.data_class"));
  for (const n of names) {
    const f = data[n];
    if (f && f.data_class !== dc) throw new Error(t("error.mixed"));
  }
  data.dataClass = dc;
  data.synthetic = dc === "synthetic";
  data.events_list = (data.events && (Array.isArray(data.events) ? data.events : data.events.events)) || [];
  data.bbox = normaliseBbox(manifest.bbox);
  data.bucketHours = (manifest.grid && manifest.grid.bucket_hours) || 3;
  data.slots = Math.round(24 / data.bucketHours);
  state.data = data;
  state.base = base;
  return data;
}

const dayCache = new Map();
export function loadDay(day) {
  if (!dayCache.has(day)) dayCache.set(day, tryJson(state.base + "days/" + day + ".json").then((d) => {
    if (d && d.data_class !== state.data.dataClass) throw new Error(t("error.mixed"));
    return d;
  }));
  return dayCache.get(day);
}

/* ---------- freshness ---------- */
export function freshness() {
  const m = state.data.manifest;
  const now = Date.now();
  const gen = Date.parse(m.generated_at);
  const latestEnd = Date.parse(m.latest_day + "T00:00:00Z") + 24 * 3600 * 1000;
  const genAge = (now - gen) / 3600000;
  const dayAge = (now - latestEnd) / 3600000;
  const age = Math.max(genAge, dayAge);
  const level = age > 7 * 24 ? "red" : age > 48 ? "amber" : "ok";
  return { level, genAge, dayAge, age };
}

/* ---------- chrome: banners, header, footer ---------- */
function linkedAttribution(text) {
  const frag = document.createDocumentFragment();
  const i1 = text.indexOf(SOURCE_NAME);
  const i2 = text.indexOf(ODBL_NAME);
  if (i1 < 0 || i2 < 0) { frag.append(text); return frag; }
  const a1 = el("a", { href: SOURCE_URL, text: SOURCE_NAME, rel: "noopener" });
  const a2 = el("a", { href: ODBL_URL, text: ODBL_NAME, rel: "noopener" });
  frag.append(text.slice(0, i1), a1, text.slice(i1 + SOURCE_NAME.length, i2), a2, text.slice(i2 + ODBL_NAME.length));
  return frag;
}

export function attributionPlain() { return (state.data && state.data.manifest.attribution) || ""; }

const NAV = [
  ["index.html", "nav.dashboard"],
  ["methods.html", "nav.methods"],
  ["validation.html", "nav.validation"],
  ["index.html#downloads", "nav.downloads"],
];

export function mountChrome(page, onLang) {
  const d = state.data;
  const top = document.getElementById("chrome-top");
  const foot = document.getElementById("chrome-footer");
  top.textContent = "";
  foot.textContent = "";

  const sticky = el("div", { class: "sticky-banners", id: "sticky-banners" });
  if (d && d.synthetic) {
    sticky.append(el("div", { class: "synthetic-banner", role: "note", id: "synthetic-banner" },
      el("strong", { class: "syn-big", text: t("banner.synthetic") }),
      el("span", { class: "syn-small", text: t("banner.synthetic_sub") })));
  }
  sticky.append(el("div", { class: "safety-banner", role: "note", id: "safety-banner", text: t("banner.safety") }));

  const langBtn = el("button", {
    type: "button", id: "lang-toggle", class: "btn", lang: state.lang === "ar" ? "en" : "ar",
    "aria-label": t("lang.switch_label"), text: state.lang === "ar" ? "English" : "العربية",
    onclick: async () => { await setLang(state.lang === "ar" ? "en" : "ar"); await onLang(); document.getElementById("lang-toggle").focus(); },
  });
  const nav = el("nav", { "aria-label": t("nav.label"), class: "nav" });
  NAV.forEach(([href, key]) => {
    const a = el("a", { href, text: t(key) });
    if (href === page) a.setAttribute("aria-current", "page");
    nav.append(a);
  });
  const header = el("header", { class: "site-header" },
    el("div", { class: "bar" },
      el("a", { class: "brand", href: "index.html" }, el("span", { text: "Tashwish" }), " ", el("span", { lang: "ar", text: "تشويش" })),
      nav, langBtn));
  top.append(el("a", { class: "skip", href: "#main", text: t("nav.skip") }), sticky, header);

  const fresh = renderFreshness();
  if (fresh) header.after(fresh);

  // footer
  const a = attributionPlain();
  const notice = el("p", { class: "notice", id: "attribution", lang: "en", dir: "ltr" });
  notice.append(linkedAttribution(a));
  const inner = el("div", { class: "footer-inner" },
    notice,
    el("p", { text: t("footer.licences") }),
    el("p", { text: t("footer.basemap") + " " + t("footer.libs") }),
    el("p", {}, t("footer.downloads_pre") + " ", el("a", { href: "index.html#downloads", text: t("nav.downloads") }), ". ",
      t("footer.version", { version: d ? d.manifest.dataset_version : "", commit: d ? d.manifest.code_commit : "" })),
    el("p", { class: "safety-foot", text: t("banner.safety") }));
  foot.append(inner);

  // banner height for scroll padding
  const upd = () => document.documentElement.style.setProperty("--banner-h", sticky.offsetHeight + "px");
  upd();
  if (window.ResizeObserver) new ResizeObserver(upd).observe(sticky);
}

function renderFreshness() {
  const d = state.data;
  if (!d) return null;
  const f = freshness();
  const m = d.manifest;
  const wrap = el("section", { class: "freshness", "data-level": f.level, "aria-labelledby": "fresh-h" });
  wrap.append(el("h2", { id: "fresh-h", class: "fresh-h", text: t("fresh.title") }));
  const stateWord = t("fresh.state_" + f.level);
  const line = el("p", { class: "fresh-line" });
  line.append(el("strong", { text: stateWord + ". " }));
  line.append(t("fresh.generated") + " ", el("span", { class: "nowrap", dir: "ltr" }, fmtStamp(m.generated_at)), " (",
    num(fmtInt(Math.max(0, Math.round(f.genAge))), "generated_at"), " " + t("fresh.hours_ago") + "). ");
  line.append(t("fresh.latest_day") + " ", num(m.latest_day, "latest_day"), ". ");
  if (f.level !== "ok") line.append(t(f.level === "red" ? "fresh.warn_red" : "fresh.warn_amber") + " ");
  if (m.freshness_hours_hint) line.append(t("fresh.hint") + " ", num(fmtInt(m.freshness_hours_hint), "freshness_hours_hint"), " " + t("fresh.hours") + ". ");
  line.append(t("fresh.class") + " ", el("strong", { text: t("class." + d.dataClass) }), ".");
  wrap.append(line);
  return wrap;
}

export function showFatal(msg) {
  const main = document.getElementById("main");
  main.textContent = "";
  main.append(el("div", { class: "fatal", role: "alert" }, el("h1", { text: t("error.title") }), el("p", { text: msg })));
}

export async function boot(page, render) {
  await initI18n();
  applyI18n();
  try {
    await loadData();
  } catch (e) {
    mountChrome(page, async () => { await boot(page, render); });
    applyI18n();
    showFatal(e.message);
    return;
  }
  const rerender = async () => { applyI18n(); mountChrome(page, rerender); await render(true); };
  mountChrome(page, rerender);
  applyI18n();
  await render(false);
}
