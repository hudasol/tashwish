"""Clip a Natural Earth countries GeoJSON to the Gulf window (lat 18..34, lon 42..65).

usage: clip_basemap.py INPUT.geojson OUTPUT.json SOURCE_URL
Only the standard library is used. Sutherland-Hodgman clipping against the rectangle; fine for display outlines.
Natural Earth is public domain (https://www.naturalearthdata.com/about/terms-of-use/).
"""

import datetime
import hashlib
import json
import sys

WEST, SOUTH, EAST, NORTH = 42.0, 18.0, 65.0, 34.0


def clip_ring(ring):
    def clip(points, inside, intersect):
        out = []
        if not points:
            return out
        prev = points[-1]
        for cur in points:
            if inside(cur):
                if not inside(prev):
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(intersect(prev, cur))
            prev = cur
        return out

    def ix(x0):
        return lambda a, b: (x0, a[1] + (b[1] - a[1]) * (x0 - a[0]) / (b[0] - a[0]))

    def iy(y0):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y0 - a[1]) / (b[1] - a[1]), y0)

    pts = [tuple(p[:2]) for p in ring[:-1]]
    pts = clip(pts, lambda p: p[0] >= WEST, ix(WEST))
    pts = clip(pts, lambda p: p[0] <= EAST, ix(EAST))
    pts = clip(pts, lambda p: p[1] >= SOUTH, iy(SOUTH))
    pts = clip(pts, lambda p: p[1] <= NORTH, iy(NORTH))
    if len(pts) < 3:
        return None
    pts.append(pts[0])
    return [[round(x, 3), round(y, 3)] for x, y in pts]


def main(src, dst, url):
    raw = open(src, "rb").read()
    gj = json.loads(raw)
    feats = []
    for f in gj["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out = []
        for poly in polys:
            rings = [clip_ring(r) for r in poly]
            if rings[0] is None:
                continue
            out.append([r for r in rings if r is not None])
        if not out:
            continue
        p = f["properties"]
        feats.append(
            {
                "type": "Feature",
                "properties": {"name": p.get("NAME") or p.get("ADMIN"), "iso_a3": p.get("ISO_A3")},
                "geometry": {"type": "MultiPolygon", "coordinates": out},
            }
        )
    doc = {
        "type": "FeatureCollection",
        "name": "ne_countries_gulf",
        "_provenance": {
            "source": "Natural Earth ne_50m_admin_0_countries (public domain)",
            "url": url,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "fetched_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "clip_window": {"west": WEST, "south": SOUTH, "east": EAST, "north": NORTH},
        },
        "features": feats,
    }
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    print(f"kept {len(feats)} countries")


if __name__ == "__main__":
    main(*sys.argv[1:4])
