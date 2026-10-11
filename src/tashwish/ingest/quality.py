"""Data-quality report for one ingested day. Pure function of the point table and parser counters."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd
import pyarrow as pa

from ..config import SRC_NON_TRANSPONDER

QUALITY_FIELDS = ["version", "nic", "rc_m", "nac_p", "nac_v", "sil", "sil_type", "sda", "gva", "nic_baro"]


def metric_population(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that count towards aircraft metrics: not a non-transponder emitter, not on the ground."""
    return df[(df["src_type"] != SRC_NON_TRANSPONDER) & (~df["on_ground"])]


def _dist(s: pd.Series) -> dict[str, int]:
    return {str(int(k)): int(v) for k, v in s.dropna().value_counts().sort_index().items()}


def quality_report(table: pa.Table, day: str, parse_stats: Counter | dict[str, int]) -> dict[str, Any]:
    df = table.to_pandas()
    n = len(df)
    rep: dict[str, Any] = {"day": day, "rows": n, "parse_stats": dict(parse_stats)}
    if n == 0:
        rep["empty"] = True
        return rep
    rep["aircraft"] = int(df["icao24"].nunique())
    rep["rows_by_src_type"] = {str(k): int(v) for k, v in df["src_type"].fillna("null").value_counts().items()}
    rep["rows_on_ground"] = int(df["on_ground"].sum())
    rep["duplicate_icao_ts_rows"] = int(df.duplicated(["icao24", "ts"]).sum())
    rep["ts_min"] = df["ts"].min().isoformat()
    rep["ts_max"] = df["ts"].max().isoformat()
    mp = metric_population(df)
    rep["metric_population"] = {
        "rows": int(len(mp)),
        "aircraft": int(mp["icao24"].nunique()),
        "excluded_non_transponder_rows": int((df["src_type"] == SRC_NON_TRANSPONDER).sum()),
        "excluded_on_ground_rows": int(((df["src_type"] != SRC_NON_TRANSPONDER) & df["on_ground"]).sum()),
    }
    hours = mp["ts"].dt.hour
    rep["hourly_rows"] = [int((hours == h).sum()) for h in range(24)]
    rep["hourly_aircraft"] = [int(mp.loc[hours == h, "icao24"].nunique()) for h in range(24)]
    rep["hours_without_rows"] = [h for h in range(24) if rep["hourly_rows"][h] == 0]
    if len(mp):
        rep["field_presence_rate"] = {f: round(float(mp[f].notna().mean()), 4) for f in QUALITY_FIELDS}
        rep["share_rows_carrying_own_quality"] = round(float((~mp["q_carried"] & mp["nic"].notna()).mean()), 4)
        rep["share_rows_with_quality"] = round(float(mp["nic"].notna().mean()), 4)
        withq = mp[mp["nic"].notna()]
        rep["nic_distribution"] = _dist(withq["nic"])
        rep["nac_p_distribution"] = _dist(withq["nac_p"])
        rep["version_row_distribution"] = _dist(mp["version"])
        modal = mp.dropna(subset=["version"]).groupby("icao24")["version"].agg(lambda s: s.mode().iloc[0])
        rep["version_aircraft_distribution"] = _dist(modal)
        if len(withq):
            rep["share_nic_below_4"] = round(float((withq["nic"] < 4).mean()), 4)
            rep["share_nac_p_below_5"] = round(float((withq["nac_p"] < 5).mean()), 4)
            rep["share_nac_p_below_8"] = round(float((withq["nac_p"] < 8).mean()), 4)
        rep["altitude_ft_percentiles"] = {
            str(q): float(mp["alt_baro_ft"].quantile(q / 100)) for q in (1, 10, 50, 90, 99)
        }
    return rep
