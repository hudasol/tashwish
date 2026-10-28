"""Tests for the Marsad context export. All data here is SYNTHETIC (tashwish.interop.synthetic); nothing is observed."""

import copy
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from tashwish import config as cfg
from tashwish.attribution import SYNTHETIC_ATTRIBUTION
from tashwish.interop.marsad import (
    SCHEMA_ID,
    ContextIndex,
    build_records,
    read_parquet_records,
    to_geojson,
    to_parquet,
    validate_feature_collection,
)
from tashwish.interop.synthetic import synthetic_cells

SAMPLE = Path(__file__).resolve().parents[1] / "interop" / "samples" / "marsad_context_SYNTHETIC_sample.geojson"
KW = {
    "dataset_version": "SYNTHETIC-test",
    "data_class": "synthetic",
    "generated_at": "2026-01-02T00:00:00Z",
    "commit": "t",
}


@pytest.fixture(scope="module")
def synth():
    return synthetic_cells(seed=7)


@pytest.fixture()
def fc(synth):
    return to_geojson(*synth, **KW)


def feat(fc, status=None, kind=None, band="enroute"):
    for f in fc["features"]:
        p = f["properties"]
        if (status is None or p["status"] == status) and (kind is None or p["kind"] == kind) and p["alt_band"] == band:
            return f
    raise AssertionError("no such feature")


def test_valid_and_schema_fields(fc):
    assert validate_feature_collection(fc) == []
    assert fc["schema"] == SCHEMA_ID == "tashwish.interference.v1"
    assert fc["attribution"] == SYNTHETIC_ATTRIBUTION
    assert "SYNTHETIC" in fc["notice"] and fc["data_class"] == "synthetic"
    assert json.loads(json.dumps(fc, allow_nan=False)) == fc


def test_not_ok_rows_never_report_a_number_or_none(fc):
    for f in fc["features"]:
        p = f["properties"]
        if p["status"] != "ok":
            assert p["p_interference"] is None and p["ci_lo"] is None and p["ci_hi"] is None
            assert p["kind"] == "unknown" and p["data_quality"] == "poor"
    assert {f["properties"]["status"] for f in fc["features"]} >= {"ok", "insufficient", "coverage_lost"}


def test_event_attached_only_to_overlapping_cell_and_bucket(fc, synth):
    cb, ev = synth
    hits = [f["properties"] for f in fc["features"] if f["properties"]["event_id"]]
    assert len(hits) == 1
    assert hits[0]["h3"] == ev["cells"].iloc[0] and hits[0]["kind"] == "jamming_like"
    assert hits[0]["bucket_start"] == "2026-01-01T09:00:00Z"
    assert feat(fc, "ok", "none") is not None


def test_none_only_in_event_stratum(fc):
    high = [f["properties"] for f in fc["features"] if f["properties"]["alt_band"] == "high"]
    assert high and all(p["kind"] == "unknown" for p in high)


def test_spoofing_event_without_cells_uses_its_latlon_cell(synth):
    cb, _ = synth
    row = cb[(cb.status == "ok") & (cb.stratum == "enroute")].iloc[0]
    import h3

    lat, lon = h3.cell_to_latlng(row["cell"])
    ev = pd.DataFrame([{"event_id": "S-1", "kind": "spoofing_like", "start": row["bucket"],
                        "end": row["bucket"] + pd.Timedelta(hours=1), "lat": lat, "lon": lon, "cells": ""}])  # fmt: skip
    r = build_records(cb, ev)
    hit = r[(r.h3 == row["cell"]) & (r.bucket_start == row["bucket"]) & (r.alt_band == "enroute")].iloc[0]
    assert hit.kind == "spoofing_like" and hit.event_id == "S-1"


def test_overlapping_kinds_merge_to_both_and_smallest_id(synth):
    cb, ev = synth
    sp = ev.assign(event_id="A-0", kind="spoofing_like")
    r = build_records(cb, pd.concat([ev, sp], ignore_index=True))
    hit = r[r.event_id.notna()].iloc[0]
    assert hit.kind == "both" and hit.event_id == "A-0"


def test_bad_inputs_raise(synth):
    cb, ev = synth
    with pytest.raises(ValueError):
        build_records(cb.drop(columns=["coverage_class"]), ev)
    with pytest.raises(ValueError):
        build_records(cb, ev.assign(kind="uncertain"))
    with pytest.raises(ValueError):
        to_geojson(cb, ev, **{**KW, "data_class": "bogus"})
    bad = cb.copy()
    bad.loc[bad.status == "ok", "share_strong"] = float("nan")
    with pytest.raises(ValueError):
        build_records(bad, ev)


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda f: f.update(schema="tashwish.interference.v2"), "schema"),
        (lambda f: f.update(attribution="x"), "attribution"),
        (lambda f: f.update(notice="plain"), "SYNTHETIC"),
        (lambda f: f.update(data_class="observed"), "data_class"),
        (lambda f: feat(f, "insufficient")["properties"].update(p_interference=0.0), "null unless status is ok"),
        (lambda f: feat(f, "insufficient")["properties"].update(kind="none"), "must not have kind 'none'"),
        (lambda f: feat(f, "ok", "none")["properties"].update(ci_lo=0.99), "ci_lo"),
        (lambda f: feat(f, "ok", "none")["properties"].update(n_obs=1), "n_obs"),
        (lambda f: feat(f, "ok", "none")["properties"].update(event_id="E"), "event_id must be null"),
        (lambda f: feat(f, "ok", "jamming_like")["properties"].update(event_id=None), "needs an event_id"),
        (lambda f: feat(f, "ok", "none")["properties"].update(bucket_start="2026-01-01T07:00:00Z"), "aligned"),
        (lambda f: feat(f, "ok", "none")["properties"].update(h3="zzz"), "h3"),
        (lambda f: feat(f, "ok", "none")["properties"].update(extra=1), "unknown properties"),
        (lambda f: feat(f, "ok", "none")["properties"].pop("kind"), "missing"),
        (lambda f: feat(f, "ok", "none")["geometry"].update(type="Point"), "geometry"),
        (lambda f: f["features"].append(copy.deepcopy(f["features"][0])), "duplicate"),
    ],
)
def test_validator_catches(fc, mutate, fragment):
    bad = copy.deepcopy(fc)
    mutate(bad)
    errs = validate_feature_collection(bad)
    assert errs and any(fragment in e for e in errs), errs


def test_geojson_file_roundtrip_and_sample_file(tmp_path, synth):
    p = tmp_path / "x_SYNTHETIC.geojson"
    fc = to_geojson(*synth, **KW, path=p)
    assert json.loads(p.read_text(encoding="utf-8")) == fc
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert "SYNTHETIC" in SAMPLE.name and sample["data_class"] == "synthetic" and "SYNTHETIC" in sample["notice"]
    assert validate_feature_collection(sample) == []
    assert sample == to_geojson(*synthetic_cells(seed=7), dataset_version="SYNTHETIC-sample-1", data_class="synthetic",
                                generated_at="2026-01-02T00:00:00Z", commit="synthetic-sample")  # fmt: skip


def test_parquet_equivalent_to_geojson(tmp_path, synth, fc):
    p = to_parquet(*synth, tmp_path / "ctx_SYNTHETIC.parquet", **KW)
    df, md = read_parquet_records(p)
    assert md["tashwish.schema"] == SCHEMA_ID and json.loads(md["tashwish.grid"])["h3_res"] == cfg.GRID_MAIN.h3_res
    assert len(df) == len(fc["features"])
    assert set(df["data_class"]) == {"synthetic"} and set(df["attribution"]) == {SYNTHETIC_ATTRIBUTION}
    a = df.sort_values(["h3", "bucket_start", "alt_band"]).reset_index(drop=True)
    b = pd.DataFrame([f["properties"] for f in fc["features"]])
    b = b.sort_values(["h3", "bucket_start", "alt_band"]).reset_index(drop=True)
    assert list(a["h3"]) == list(b["h3"]) and list(a["status"]) == list(b["status"])
    assert list(a["kind"]) == list(b["kind"]) and list(a["n_obs"]) == list(b["n_obs"])
    assert a["p_interference"].isna().tolist() == b["p_interference"].isna().tolist()
    assert (a["bucket_start"].dt.strftime("%Y-%m-%dT%H:%M:%SZ") == b["bucket_start"]).all()
    assert pq.read_schema(p).field("n_obs").type == "int32"


def test_query_retrospective_states(fc):
    idx = ContextIndex(fc)
    ok = feat(fc, "ok", "jamming_like")["properties"]
    import h3

    lat, lon = h3.cell_to_latlng(ok["h3"])
    r = idx.query(lat, lon, "2026-01-01T10:30:00Z", alt_ft=36000)
    assert r["status"] == "ok" and r["usable_as_prior"] and r["record"]["event_id"] == "SYN-J-0001"
    assert r["data_class"] == "synthetic" and r["attribution"] == SYNTHETIC_ATTRIBUTION
    ins = feat(fc, "insufficient")["properties"]
    lat, lon = h3.cell_to_latlng(ins["h3"])
    r = idx.query(lat, lon, "2026-01-01T07:00:00Z", alt_ft=36000)
    assert r["status"] == "insufficient" and not r["usable_as_prior"] and r["record"]["p_interference"] is None
    lost = feat(fc, "coverage_lost")["properties"]
    lat, lon = h3.cell_to_latlng(lost["h3"])
    assert idx.query(lat, lon, "2026-01-01T10:00:00Z", 36000)["status"] == "coverage_lost"


def test_query_missing_is_never_zero_or_ok(fc):
    idx = ContextIndex(fc)
    r = idx.query(25.2, 55.3, "2026-01-05T10:00:00Z", 36000)  # no record at this time
    assert r["status"] == "no_record" and r["record"] is None and not r["usable_as_prior"]
    r = idx.query(25.2, 55.3, "2026-01-01T10:00:00Z", 500)  # no low band
    assert r["status"] == "no_record"
    assert idx.query(10.0, 10.0, "2026-01-01T10:00:00Z")["status"] == "out_of_region"
    for bad in (
        (95, 55, "2026-01-01T10:00:00Z", None),
        (25, 55, "2026-01-01 10:00", None),
        (25, 55, "2026-01-01T10:00:00Z", "x"),
    ):
        with pytest.raises(ValueError):
            idx.query(*bad)  # type: ignore[arg-type]


def test_query_nowcast_staleness(fc):
    idx = ContextIndex(fc)
    ok = feat(fc, "ok", "jamming_like")["properties"]
    import h3

    lat, lon = h3.cell_to_latlng(ok["h3"])
    fresh = idx.query(lat, lon, "2026-01-01T13:00:00Z", 36000, mode="nowcast")
    assert fresh["status"] == "ok" and fresh["age_hours"] == pytest.approx(1.0)
    stale = idx.query(lat, lon, "2026-01-04T12:00:00Z", 36000, mode="nowcast")
    assert stale["status"] == "stale" and not stale["usable_as_prior"] and stale["age_hours"] > fc["max_age_hours"]
    early = idx.query(lat, lon, "2026-01-01T05:00:00Z", 36000, mode="nowcast")
    assert early["status"] == "no_record"


def test_altitude_band_selection(fc):
    idx = ContextIndex(fc)
    high = feat(fc, band="high")["properties"]
    import h3

    lat, lon = h3.cell_to_latlng(high["h3"])
    assert idx.query(lat, lon, "2026-01-01T07:00:00Z", 30000)["record"]["alt_band"] == "high"
    assert (
        idx.query(lat, lon, "2026-01-01T07:00:00Z", 15000)["record"]["alt_band"] == "enroute"
    )  # no mid row: falls back
    assert idx.query(lat, lon, "2026-01-01T07:00:00Z")["record"]["alt_band"] == "enroute"
