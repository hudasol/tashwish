import { LIBS } from "./config.js";

function addScript(url, integrity) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = url;
    s.async = false;
    if (integrity) { s.integrity = integrity; s.crossOrigin = "anonymous"; }
    s.onload = () => resolve(url);
    s.onerror = () => { s.remove(); reject(new Error("failed " + url)); };
    document.head.appendChild(s);
  });
}

function addCss(url, integrity) {
  return new Promise((resolve, reject) => {
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = url;
    if (integrity) { l.integrity = integrity; l.crossOrigin = "anonymous"; }
    l.onload = () => resolve(url);
    l.onerror = () => { l.remove(); reject(new Error("failed " + url)); };
    document.head.appendChild(l);
  });
}

async function withFallback(add, spec) {
  try {
    return { url: await add(spec.cdn, spec.integrity), from: "cdn" };
  } catch (e) {
    return { url: await add(spec.local, spec.integrity), from: "vendor" };
  }
}

// Loads maplibre-gl and deck.gl (pinned). Resolves to a short report of where each came from.
export async function loadLibs() {
  const report = {};
  report.css = await withFallback(addCss, LIBS.maplibreCss);
  report.maplibre = await withFallback(addScript, LIBS.maplibre);
  report.h3 = await withFallback(addScript, LIBS.h3);
  report.deck = await withFallback(addScript, LIBS.deck);
  if (!window.maplibregl || !window.deck || !window.h3) throw new Error("map libraries did not initialise");
  return report;
}
