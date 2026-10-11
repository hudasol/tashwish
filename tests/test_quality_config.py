import pandas as pd
import pyarrow as pa

from tashwish.config import REGION, Region
from tashwish.ingest.pipeline import IngestConfig, day_bounds_ms
from tashwish.ingest.quality import metric_population, quality_report
from tashwish.ingest.trace import COLUMNS, ParsedTrace
from tashwish.schema import POINT_SCHEMA


def table_from_rows(rows):
    p = ParsedTrace()
    for r in rows:
        for c in COLUMNS:
            p.cols[c].append(r.get(c))
    arrays = [pa.array(p.cols[f.name], type=f.type) for f in POINT_SCHEMA]
    return pa.Table.from_arrays(arrays, schema=POINT_SCHEMA)


BASE = {"ts": 1772409600000 + 3600_000 * 3, "lat": 25.0, "lon": 55.0, "on_ground": False, "src_type": "adsb_icao",
        "data_class": "observed", "icao24": "a", "alt_baro_ft": 30000, "q_carried": False}  # fmt: skip


def test_metric_population_excludes_vehicles_and_ground():
    rows = [
        {**BASE, "nic": 11},
        {**BASE, "icao24": "v", "src_type": "adsb_icao_nt", "on_ground": True, "alt_baro_ft": None, "nic": 10},
        {**BASE, "icao24": "g", "on_ground": True, "alt_baro_ft": None, "nic": 8},
    ]
    df = table_from_rows(rows).to_pandas()
    assert list(metric_population(df)["icao24"]) == ["a"]


def test_quality_report_known_values():
    rows = [
        {**BASE, "icao24": f"x{i}", "nic": n, "nac_p": p, "version": 2}
        for i, (n, p) in enumerate([(11, 11), (11, 11), (2, 3), (8, 8)])
    ]
    rep = quality_report(table_from_rows(rows), "2026-03-02", {"trace_files": 4})
    assert rep["rows"] == 4 and rep["aircraft"] == 4
    assert (
        rep["share_nic_below_4"] == 0.25 and rep["share_nac_p_below_5"] == 0.25 and rep["share_nac_p_below_8"] == 0.25
    )
    assert rep["hourly_rows"][3] == 4 and rep["hours_without_rows"][0] == 0
    assert rep["field_presence_rate"]["nic"] == 1.0 and rep["field_presence_rate"]["sda"] == 0.0
    assert rep["nic_distribution"] == {"2": 1, "8": 1, "11": 2}


def test_empty_report():
    assert quality_report(POINT_SCHEMA.empty_table(), "2026-03-02", {})["empty"] is True


def test_region_defaults_and_membership():
    assert (REGION.lat_min, REGION.lat_max, REGION.lon_min, REGION.lon_max) == (22.0, 31.0, 46.0, 62.0)
    assert REGION.contains(25.2, 55.3) and not REGION.contains(21.9, 55.3) and not REGION.contains(25.0, 62.1)


def test_params_key_depends_on_every_parameter(tmp_path):
    base = IngestConfig(tmp_path, tmp_path)
    keys = {
        base.params_key(),
        IngestConfig(tmp_path, tmp_path, max_age_s=60.0).params_key(),
        IngestConfig(tmp_path, tmp_path, region=Region(lat_min=21.0)).params_key(),
        IngestConfig(tmp_path, tmp_path, data_class="synthetic").params_key(),
    }
    assert len(keys) == 4


def test_day_bounds():
    a, b = day_bounds_ms("2026-03-02")
    assert b - a == 86_400_000 and pd.Timestamp(a, unit="ms", tz="UTC").isoformat() == "2026-03-02T00:00:00+00:00"
