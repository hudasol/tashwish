"""Combine jamming-like and spoofing-like events into one labelled event table.

Rules (all mechanical, all design choices frozen before the held-out run):
  jamming-like only    kind `jamming_like`; uncertain when the jamming event has confidence `low`
  spoofing-like only   kind `spoofing_like`; uncertain when the spoofing event has confidence `medium` (3 or 4 aircraft, or a wide spread)
  both overlapping     kind `both` (a jamming-like event and a spoofing-like event overlap in time and in space,
                       judged at the aircraft's TRUE positions, i.e. the spoofing event's ORIGIN area);
                       uncertain unless both components have confidence `high`
Nothing here attributes cause or actor. `label_uncertain` is a first-class output, never hidden.
"""

from __future__ import annotations

import h3
import numpy as np
import pandas as pd

from .spoofing import haversine_km

SPACE_SLACK_KM = 100.0  # spoofing origin centroid within this distance of a jamming cell centre counts as overlapping
TIME_SLACK = pd.Timedelta(hours=1)


def _jam_overlaps(spoof: pd.Series, jam: pd.DataFrame) -> np.ndarray:
    hits = np.zeros(len(jam), dtype=bool)
    for i, e in enumerate(jam.itertuples()):
        if e.start - TIME_SLACK > spoof["end"] or e.end + TIME_SLACK < spoof["start"]:
            continue
        for c in e.cells.split(","):
            lat, lon = h3.cell_to_latlng(c)
            if haversine_km(lat, lon, spoof["origin_lat"], spoof["origin_lon"]) <= SPACE_SLACK_KM:
                hits[i] = True
                break
    return hits


def combine(jam_events: pd.DataFrame, spoof_events: pd.DataFrame) -> pd.DataFrame:
    cols = ["event_id", "kind", "label_uncertain", "confidence", "start", "end", "lat", "lon", "n_cells", "cells",
            "n_aircraft", "k_degraded", "peak_share", "peak_ci_lo", "min_p", "n_spoof_aircraft", "dest_lat", "dest_lon",
            "dest_spread_km", "median_implied_kt", "share_nominal_accuracy", "components"]  # fmt: skip
    rows = []
    used_jam: set[int] = set()
    for _, s in spoof_events.iterrows():
        hits = _jam_overlaps(s, jam_events) if len(jam_events) else np.array([], dtype=bool)
        idx = np.flatnonzero(hits)
        used_jam.update(int(i) for i in idx)
        j = jam_events.iloc[idx] if len(idx) else None
        if j is not None:
            kind = "both"
            unc = not (s["confidence"] == "high" and (j["confidence"] == "high").all())
            conf = "high" if not unc else "medium"
            comps = f"{s['event_id']}+{'+'.join(j['event_id'])}"
        else:
            kind, unc, conf, comps = "spoofing_like", s["confidence"] != "high", s["confidence"], s["event_id"]
        rows.append({
            "event_id": s["event_id"] if j is None else "B-" + s["event_id"][2:], "kind": kind, "label_uncertain": bool(unc),
            "confidence": conf, "start": s["start"] if j is None else min(s["start"], j["start"].min()),
            "end": s["end"] if j is None else max(s["end"], j["end"].max()),
            "lat": s["origin_lat"], "lon": s["origin_lon"],
            "n_cells": int(j["n_cells"].sum()) if j is not None else 0,
            "cells": ",".join(j["cells"]) if j is not None else "",
            "n_aircraft": int(s["n_aircraft"]) + (int(j["n_total"].sum()) if j is not None else 0),
            "k_degraded": int(j["k_total"].sum()) if j is not None else 0,
            "peak_share": float(j["peak_share"].max()) if j is not None else np.nan,
            "peak_ci_lo": float(j["peak_ci_lo"].max()) if j is not None else np.nan,
            "min_p": float(j["min_p"].min()) if j is not None else np.nan,
            "n_spoof_aircraft": int(s["n_aircraft"]), "dest_lat": s["dest_lat"], "dest_lon": s["dest_lon"],
            "dest_spread_km": s["dest_spread_km"], "median_implied_kt": s["median_implied_kt"],
            "share_nominal_accuracy": s["share_nominal_accuracy"], "components": comps,
        })  # fmt: skip
    for i, e in jam_events.reset_index(drop=True).iterrows():
        if i in used_jam:
            continue
        rows.append({
            "event_id": e["event_id"], "kind": "jamming_like", "label_uncertain": e["confidence"] == "low",
            "confidence": e["confidence"], "start": e["start"], "end": e["end"], "lat": e["lat"], "lon": e["lon"],
            "n_cells": int(e["n_cells"]), "cells": e["cells"], "n_aircraft": int(e["n_total"]), "k_degraded": int(e["k_total"]),
            "peak_share": e["peak_share"], "peak_ci_lo": e["peak_ci_lo"], "min_p": e["min_p"], "n_spoof_aircraft": 0,
            "dest_lat": np.nan, "dest_lon": np.nan, "dest_spread_km": np.nan, "median_implied_kt": np.nan,
            "share_nominal_accuracy": np.nan, "components": e["event_id"],
        })  # fmt: skip
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(["start", "event_id"]).reset_index(drop=True) if len(out) else out
