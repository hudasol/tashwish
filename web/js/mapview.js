import { SHARE_BINS, PALETTE, BASEMAP_ATTRIBUTION } from "./config.js";

export const isDark = () => window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;

const BASE = {
  light: { bg: "#e6ecef", land: "#f7f2f0", line: "#8f8286", grat: "#b9aeb2" },
  dark: { bg: "#10131a", land: "#1f232c", line: "#6b6f7c", grat: "#3a3f4b" },
};

// Row classes. A cell is coloured by share ONLY when it is "ok". Everything else has its own look.
export function rowClass(r) {
  if (r.status === "coverage_lost") return "lost";
  if (r.cov === "no_coverage") return "nocov";
  if (r.status === "insufficient") return "insuff";
  if (r.status === "ok") return "ok";
  return "insuff"; // unknown status: never draw as a share colour
}

export function shareBin(share) {
  let b = 0;
  for (let i = 0; i < SHARE_BINS.length; i++) if (share >= SHARE_BINS[i]) b = i;
  return b;
}
export const hexToRgb = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];

function graticule() {
  const feats = [];
  for (let lon = 36; lon <= 70; lon += 2) feats.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[lon, 10], [lon, 40]] } });
  for (let lat = 10; lat <= 40; lat += 2) feats.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[36, lat], [70, lat]] } });
  return { type: "FeatureCollection", features: feats };
}

// Not-assessed cell looks: solid greys (never a share colour) plus a glyph so the meaning does not rest on grey alone.
export const GLYPH = { insuff: "/", lost: "X", nocov: "|" };
export const GREY = {
  light: { insuff: [196, 196, 205], lost: [120, 120, 132], nocov: [238, 238, 242] },
  dark: { insuff: [84, 88, 100], lost: [150, 154, 168], nocov: [44, 47, 56] },
};
export const GLYPH_COLOR = { light: [40, 38, 48, 255], dark: [235, 236, 244, 255] };

export class MapView {
  constructor(opts) {
    this.o = opts; // {container, bbox, onPick, basemapUrl, styleUrl}
    this.map = null;
    this.overlay = null;
    this.hasBasemap = false;
    this.patterns = true;
  }

  async init() {
    const style = await (await fetch(this.o.styleUrl)).json();
    style.sources.graticule.data = graticule();
    try {
      const r = await fetch(this.o.basemapUrl, { cache: "no-cache" });
      if (!r.ok) throw new Error(String(r.status));
      const gj = await r.json();
      style.sources.countries.data = gj;
      this.hasBasemap = true;
    } catch (e) {
      // Fall back to an empty background with the graticule.
      style.layers = style.layers.filter((l) => l.source !== "countries");
      delete style.sources.countries;
      this.hasBasemap = false;
    }
    const b = this.o.bbox;
    this.theme = isDark() ? "dark" : "light";
    this.map = new maplibregl.Map({
      container: this.o.container,
      style,
      bounds: [[b.west, b.south], [b.east, b.north]],
      fitBoundsOptions: { padding: 8 },
      attributionControl: false,
      preserveDrawingBuffer: true,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
      minZoom: 3,
      maxZoom: 10,
      cooperativeGestures: false,
    });
    this.map.touchZoomRotate.disableRotation();
    this.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    if (this.hasBasemap) this.map.addControl(new maplibregl.AttributionControl({ compact: false, customAttribution: BASEMAP_ATTRIBUTION }), "bottom-right");
    this.overlay = new deck.MapboxOverlay({ interleaved: true, layers: [] });
    this.map.addControl(this.overlay);
    await new Promise((res) => this.map.once("load", res));
    this.applyTheme();
    this.map.getCanvas().setAttribute("aria-hidden", "true");
    this.ro = new ResizeObserver(() => this.map.resize());
    this.ro.observe(document.getElementById(this.o.container));
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { this.applyTheme(); this.o.onTheme && this.o.onTheme(); });
  }

  applyTheme() {
    this.theme = isDark() ? "dark" : "light";
    const c = BASE[this.theme];
    const m = this.map;
    m.setPaintProperty("background", "background-color", c.bg);
    if (this.hasBasemap) {
      m.setPaintProperty("countries-fill", "fill-color", c.land);
      m.setPaintProperty("countries-line", "line-color", c.line);
    }
    m.setPaintProperty("graticule", "line-color", c.grat);
  }

  // params: {rows (day cells for bucket), cov (coverage rows for slot), events (active events), selected, show:{share,cov,events}}
  setLayers(p) {
    const dark = this.theme === "dark";
    const pal = (dark ? PALETTE.dark : PALETTE.light).map(hexToRgb);
    const lineSoft = dark ? [255, 255, 255, 50] : [60, 40, 50, 70];
    const grey = GREY[dark ? "dark" : "light"];
    const gcol = GLYPH_COLOR[dark ? "dark" : "light"];
    const pat = (id, data, name) => [
      new deck.H3HexagonLayer({
        id, data, getHexagon: (d) => d.h3, extruded: false, filled: true, stroked: true, pickable: true,
        getFillColor: [...grey[name], 255], getLineColor: dark ? [220, 220, 230, 160] : [40, 40, 50, 150], lineWidthUnits: "pixels", getLineWidth: 1,
        onHover: (i) => this.o.onPick(i.object || null, false), onClick: (i) => this.o.onPick(i.object || null, true),
        updateTriggers: { getFillColor: [dark] },
      }),
      new deck.TextLayer({
        id: id + "-glyph", data: data.map((d) => { const [la, lo] = h3.cellToLatLng(d.h3); return { p: [lo, la] }; }),
        getPosition: (d) => d.p, getText: () => GLYPH[name], getSize: 15, sizeUnits: "pixels", getColor: gcol, fontWeight: 700,
        getTextAnchor: "middle", getAlignmentBaseline: "center", pickable: false, updateTriggers: { getColor: [dark] },
      }),
    ];
    const layers = [];
    const show = p.show;
    if (show.cov && p.cov) {
      const tint = { covered: dark ? [90, 190, 200, 70] : [40, 140, 150, 60], marginal: dark ? [240, 190, 80, 110] : [225, 160, 30, 110] };
      layers.push(new deck.H3HexagonLayer({
        id: "cov-tint", data: p.cov.filter((d) => d.class !== "no_coverage"), getHexagon: (d) => d.h3, extruded: false, filled: true, stroked: true,
        getFillColor: (d) => tint[d.class], getLineColor: dark ? [240, 190, 80, 140] : [150, 100, 10, 120], lineWidthUnits: "pixels", getLineWidth: 0.5,
        pickable: false, updateTriggers: { getFillColor: [dark] },
      }));
      layers.push(...pat("cov-none", p.cov.filter((d) => d.class === "no_coverage"), "nocov"));
    }
    if (show.share && p.rows) {
      const ok = p.rows.filter((r) => rowClass(r) === "ok");
      layers.push(new deck.H3HexagonLayer({
        id: "share-ok", data: ok, getHexagon: (d) => d.h3, extruded: false, filled: true, stroked: true, pickable: true,
        getFillColor: (d) => [...pal[shareBin(d.share)], 235],
        getLineColor: (d) => (d.cov === "marginal" ? (dark ? [255, 200, 90, 255] : [140, 80, 0, 255]) : lineSoft),
        getLineWidth: (d) => (d.cov === "marginal" ? 2 : 0.7), lineWidthUnits: "pixels",
        onHover: (i) => this.o.onPick(i.object || null, false), onClick: (i) => this.o.onPick(i.object || null, true),
        updateTriggers: { getFillColor: [dark], getLineColor: [dark] },
      }));
      layers.push(...pat("share-insuff", p.rows.filter((r) => rowClass(r) === "insuff"), "insuff"));
      layers.push(...pat("share-lost", p.rows.filter((r) => rowClass(r) === "lost"), "lost"));
      layers.push(...pat("share-nocov", p.rows.filter((r) => rowClass(r) === "nocov"), "nocov"));
    }
    if (show.events && p.events) {
      const sel = p.selected;
      p.events.forEach((ev) => {
        const isSel = ev.event_id === sel;
        layers.push(new deck.H3HexagonLayer({
          id: "event-" + ev.event_id, data: ev.cells.map((h) => ({ h3: h })), getHexagon: (d) => d.h3, extruded: false, filled: false, stroked: true,
          getLineColor: isSel ? (dark ? [255, 255, 255, 255] : [20, 10, 30, 255]) : (dark ? [255, 150, 200, 255] : [110, 10, 70, 255]),
          getLineWidth: isSel ? 4 : 2.5, lineWidthUnits: "pixels", pickable: false,
          updateTriggers: { getLineColor: [isSel, dark], getLineWidth: [isSel] },
        }));
      });
      layers.push(new deck.ScatterplotLayer({
        id: "event-centres", data: p.events, getPosition: (e) => [e.lon, e.lat], getRadius: 7, radiusUnits: "pixels", stroked: true, filled: true,
        getFillColor: dark ? [30, 20, 40, 255] : [255, 255, 255, 255], getLineColor: dark ? [255, 200, 230, 255] : [110, 10, 70, 255], lineWidthUnits: "pixels", getLineWidth: 3,
        updateTriggers: { getFillColor: [dark], getLineColor: [dark] },
      }));
    }
    this.overlay.setProps({ layers });
  }

  fitTo(lon, lat, zoom) { this.map.easeTo({ center: [lon, lat], zoom: Math.max(this.map.getZoom(), zoom || 6), duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 600 }); }

  // Resolves to the map canvas after a fresh render (preserveDrawingBuffer is on).
  snapshotCanvas() {
    return new Promise((resolve) => {
      this.map.once("render", () => resolve(this.map.getCanvas()));
      this.map.triggerRepaint();
    });
  }
}
