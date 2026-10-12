#!/usr/bin/env bash
# Fetch Natural Earth country outlines (public domain) at BUILD time and clip them to the Gulf window.
# Output: web/data/ne_countries.json. The site never contacts a map tile server and never fetches this at runtime
# from a third party; it only reads the local file.
# If the download fails the script says so and exits non-zero without writing a partial file. The dashboard then
# falls back to an empty background with a graticule. We do not try mirrors or proxies to get around a block.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/../data/ne_countries.json"
REF="${NE_REF:-master}"
URL="https://raw.githubusercontent.com/nvkelso/natural-earth-vector/${REF}/geojson/ne_50m_admin_0_countries.geojson"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Fetching $URL"
if ! curl -fsSL --retry 2 --max-time 120 -o "$TMP/ne.geojson" "$URL"; then
  echo "FAILED: could not download Natural Earth data from $URL" >&2
  echo "The dashboard will use an empty background with a graticule until web/data/ne_countries.json exists." >&2
  exit 1
fi
mkdir -p "$(dirname "$OUT")"
python3 -I "$HERE/clip_basemap.py" "$TMP/ne.geojson" "$OUT.tmp" "$URL" || { echo "FAILED: clip step" >&2; rm -f "$OUT.tmp"; exit 1; }
mv "$OUT.tmp" "$OUT"
echo "Wrote $OUT"
