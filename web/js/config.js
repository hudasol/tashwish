// Constants shared by all pages. Source of the attribution URLs: src/tashwish/attribution.py
// (SOURCE_URL, ODBL_URL). The notice TEXT itself is not stored here: it is read from `attribution` in the data files,
// which the release/build step copies verbatim from attribution.py.
export const SOURCE_URL = "https://github.com/adsblol/globe_history";
export const ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/";
export const SOURCE_NAME = "adsb.lol";
export const ODBL_NAME = "Open Database License (ODbL)";
export const BASEMAP_ATTRIBUTION = "Natural Earth (public domain)";

export const DATA_ROOT = "data/";
export const SAMPLE_ROOT = "data/sample_synthetic/";
export const SCHEMA = "tashwish.web.v1";

// Pinned third party libraries. CDN first, then the local copy in web/vendor/ if present.
// Licences: maplibre-gl BSD-3-Clause; deck.gl MIT (umbrella bundle incl. @deck.gl/geo-layers H3HexagonLayer, which needs the h3-js global, Apache-2.0).
export const LIBS = {
  maplibreCss: {
    cdn: "https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.css",
    local: "vendor/maplibre-gl-4.7.1/maplibre-gl.css",
    integrity: "sha384-MinO0mNliZ3vwppuPOUnGa+iq619pfMhLVUXfC4LHwSCvF9H+6P/KO4Q7qBOYV5V",
  },
  maplibre: {
    cdn: "https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js",
    local: "vendor/maplibre-gl-4.7.1/maplibre-gl.js",
    integrity: "sha384-SYKAG6cglRMN0RVvhNeBY0r3FYKNOJtznwA0v7B5Vp9tr31xAHsZC0DqkQ/pZDmj",
  },
  h3: {
    cdn: "https://cdn.jsdelivr.net/npm/h3-js@4.1.0/dist/h3-js.umd.js",
    local: "vendor/h3-js-4.1.0/h3-js.umd.js",
    integrity: "sha384-nKUDlg+fT0U/eEt4KWP9n034kLe/eVj6k7CVjbu6qfRhJdEyinlGajS9+9AU+UZ5",
  },
  deck: {
    cdn: "https://cdn.jsdelivr.net/npm/deck.gl@9.0.38/dist.min.js",
    local: "vendor/deck.gl-9.0.38/dist.min.js",
    integrity: "sha384-tEG529toczQRv/bqd2PyHy5vTO49FMjQri0c1oB44gSkYiNouZz8L9yNTVx0YGl+",
  },
};

// Sequential palette for degraded share (ColorBrewer PuRd-derived; lightness increases monotonically so it stays
// readable under common colour vision deficiencies). Bins are display choices, not statistical thresholds.
export const SHARE_BINS = [0, 0.05, 0.1, 0.2, 0.35, 0.5];
export const PALETTE = {
  light: ["#f1e4ee", "#e1c2dc", "#d08fc4", "#c0539f", "#9c1f73", "#5e0b47"],
  dark: ["#43314a", "#74406f", "#a64f96", "#d46db8", "#f19bd0", "#ffd2ec"],
};
