"""Arrow schema for the ingested point table and the rules that keep synthetic data apart from observed data."""

from __future__ import annotations

import re
from pathlib import Path

import pyarrow as pa

from .config import DATA_CLASS_OBSERVED, DATA_CLASS_SYNTHETIC, SCHEMA_VERSION

POINT_SCHEMA = pa.schema(
    [
        ("icao24", pa.string()),
        ("ts", pa.timestamp("ms", tz="UTC")),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("alt_baro_ft", pa.int32()),
        ("on_ground", pa.bool_()),
        ("alt_geom_ft", pa.int32()),
        ("gs_kt", pa.float32()),
        ("track_deg", pa.float32()),
        ("baro_rate_fpm", pa.int32()),
        ("flags", pa.int8()),
        ("src_type", pa.string()),
        ("ac_type", pa.string()),
        ("category", pa.string()),
        ("version", pa.int8()),
        ("nic", pa.int8()),
        ("rc_m", pa.int32()),
        ("nac_p", pa.int8()),
        ("nac_v", pa.int8()),
        ("sil", pa.int8()),
        ("sil_type", pa.string()),
        ("sda", pa.int8()),
        ("gva", pa.int8()),
        ("nic_baro", pa.int8()),
        ("q_age_s", pa.float32()),
        ("q_carried", pa.bool_()),
        ("data_class", pa.string()),
    ],
    metadata={b"tashwish.schema_version": SCHEMA_VERSION.encode()},
)

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def points_filename(day: str, data_class: str = DATA_CLASS_OBSERVED) -> str:
    """File name for a day of ingested points. Synthetic data always carries `_synthetic_` in its name."""
    if not _DAY_RE.match(day):
        raise ValueError(f"day must be YYYY-MM-DD, got {day!r}")
    if data_class == DATA_CLASS_OBSERVED:
        return f"points_{day}.parquet"
    if data_class == DATA_CLASS_SYNTHETIC:
        return f"points_synthetic_{day}.parquet"
    raise ValueError(f"unknown data_class {data_class!r}")


def assert_data_class_matches(table: pa.Table, path: Path, data_class: str) -> None:
    """Refuse to mix observed and synthetic data: the file name, the column and the declared class must agree."""
    is_synth_name = "_synthetic_" in path.name or "synthetic" in path.parent.name
    if (data_class == DATA_CLASS_SYNTHETIC) != is_synth_name:
        raise ValueError(f"data_class={data_class!r} does not match path {path}")
    if "data_class" in table.column_names:
        values = set(table.column("data_class").unique().to_pylist())
        if values - {data_class}:
            raise ValueError(f"table contains data_class values {values} but declared {data_class!r}")
