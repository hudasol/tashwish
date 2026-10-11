"""Parse one readsb `trace_full_*.json` file into columnar rows for the Gulf box.

Trace point layout (readsb README-json, "trace jsons"):
  0 seconds after file timestamp | 1 lat | 2 lon | 3 alt_baro ft or "ground" or null | 4 gs kt | 5 track deg
  6 flags | 7 baro rate fpm | 8 aircraft object or null | 9 type/source | 10 geometric alt | 11 geometric rate
  12 ias | 13 roll
flags: 1 = no position for 20 s before this point, 2 = new leg, 4 = rate is geometric, 8 = altitude is geometric.

Quality semantics (documented in docs/DATA_QUALITY.md): the quality fields of a point are those of the most
recent aircraft object at or before it, if that object is at most `max_age_s` old; `q_carried` says whether the
point itself carried the object. The state is updated by every point of the trace, including points outside the
study box, so the carry-forward is correct at the box boundary.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..config import DATA_CLASS_OBSERVED, QUALITY_MAX_AGE_S, REGION, Region

COLUMNS = [
    "icao24", "ts", "lat", "lon", "alt_baro_ft", "on_ground", "alt_geom_ft", "gs_kt", "track_deg",
    "baro_rate_fpm", "flags", "src_type", "ac_type", "category", "version", "nic", "rc_m", "nac_p", "nac_v",
    "sil", "sil_type", "sda", "gva", "nic_baro", "q_age_s", "q_carried", "data_class",
]  # fmt: skip


@dataclass
class ParsedTrace:
    cols: dict[str, list[Any]] = field(default_factory=lambda: {c: [] for c in COLUMNS})
    stats: Counter = field(default_factory=Counter)

    def __len__(self) -> int:
        return len(self.cols["ts"])


def _as_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == v:
        return int(v)
    return None


def _as_float(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and v == v:
        return float(v)
    return None


def _as_str(v: Any) -> str | None:
    return v if isinstance(v, str) else None


def parse_trace(
    obj: dict[str, Any],
    day_start_ms: int,
    day_end_ms: int,
    region: Region = REGION,
    max_age_s: float = QUALITY_MAX_AGE_S,
    data_class: str = DATA_CLASS_OBSERVED,
) -> ParsedTrace:
    out = ParsedTrace()
    st = out.stats
    icao = obj.get("icao")
    trace = obj.get("trace")
    ts0 = _as_float(obj.get("timestamp"))
    if not isinstance(icao, str) or not isinstance(trace, list) or ts0 is None:
        st["malformed_file"] += 1
        return out
    ac_type = _as_str(obj.get("t"))
    state_t: int | None = None
    state_ac: dict[str, Any] | None = None
    category: str | None = None
    last_t: int | None = None
    cols = out.cols
    for p in trace:
        if not isinstance(p, list) or len(p) < 7:
            st["malformed_point"] += 1
            continue
        off = _as_float(p[0])
        lat = _as_float(p[1])
        lon = _as_float(p[2])
        if off is None or lat is None or lon is None:
            st["malformed_point"] += 1
            continue
        t_ms = round((ts0 + off) * 1000)
        if last_t is not None and t_ms < last_t:
            st["non_monotonic_time"] += 1
        last_t = t_ms
        ac = p[8] if len(p) > 8 and isinstance(p[8], dict) else None
        if ac is not None:
            state_t, state_ac = t_ms, ac
            c = _as_str(ac.get("category"))
            if c:
                category = c
        if not region.contains(lat, lon):
            continue
        if not (day_start_ms <= t_ms < day_end_ms):
            st["outside_day"] += 1
            continue
        q: dict[str, Any] | None = None
        carried = False
        age: float | None = None
        if ac is not None:
            q, age = ac, 0.0
        elif state_ac is not None and state_t is not None:
            a = (t_ms - state_t) / 1000.0
            if 0.0 <= a <= max_age_s:
                q, age, carried = state_ac, a, True
            else:
                st["quality_too_old"] += 1
        alt = p[3]
        on_ground = alt == "ground"
        q = q or {}
        cols["icao24"].append(icao)
        cols["ts"].append(t_ms)
        cols["lat"].append(lat)
        cols["lon"].append(lon)
        cols["alt_baro_ft"].append(None if on_ground else _as_int(alt))
        cols["on_ground"].append(on_ground)
        cols["alt_geom_ft"].append(_as_int(p[10]) if len(p) > 10 else None)
        cols["gs_kt"].append(_as_float(p[4]))
        cols["track_deg"].append(_as_float(p[5]))
        cols["baro_rate_fpm"].append(_as_int(p[7]))
        cols["flags"].append(_as_int(p[6]))
        cols["src_type"].append(_as_str(p[9]) if len(p) > 9 else None)
        cols["ac_type"].append(ac_type)
        cols["category"].append(category)
        cols["version"].append(_as_int(q.get("version")))
        cols["nic"].append(_as_int(q.get("nic")))
        cols["rc_m"].append(_as_int(q.get("rc")))
        cols["nac_p"].append(_as_int(q.get("nac_p")))
        cols["nac_v"].append(_as_int(q.get("nac_v")))
        cols["sil"].append(_as_int(q.get("sil")))
        cols["sil_type"].append(_as_str(q.get("sil_type")))
        cols["sda"].append(_as_int(q.get("sda")))
        cols["gva"].append(_as_int(q.get("gva")))
        cols["nic_baro"].append(_as_int(q.get("nic_baro")))
        cols["q_age_s"].append(age)
        cols["q_carried"].append(carried)
        cols["data_class"].append(data_class)
    st["points_kept"] += len(out)
    return out


def parse_gz(
    raw: bytes,
    day_start_ms: int,
    day_end_ms: int,
    region: Region = REGION,
    max_age_s: float = QUALITY_MAX_AGE_S,
    data_class: str = DATA_CLASS_OBSERVED,
) -> ParsedTrace:
    """Decode a gzip-compressed trace file; returns an empty result (with a counted reason) if undecodable."""
    try:
        obj = json.loads(gzip.decompress(raw))
    except (OSError, EOFError, ValueError):
        res = ParsedTrace()
        res.stats["undecodable_file"] += 1
        return res
    if not isinstance(obj, dict):
        res = ParsedTrace()
        res.stats["malformed_file"] += 1
        return res
    return parse_trace(obj, day_start_ms, day_end_ms, region, max_age_s, data_class)
