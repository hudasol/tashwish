import json

import pyarrow.parquet as pq
import pytest

from tashwish.config import DATA_CLASS_OBSERVED, DATA_CLASS_SYNTHETIC
from tashwish.ingest.pipeline import IngestConfig, ingest_day, is_complete, read_manifest
from tashwish.ingest.source import DownloadError, release_url
from tashwish.schema import POINT_SCHEMA, assert_data_class_matches, points_filename

from .synth import DAY, FakeServer, ac_obj, gz, make_tar, pt, trace_obj

NOSLEEP = lambda s: None  # noqa: E731


def build_day_blobs(split_at=None):
    """SYNTHETIC archive for DAY: three aircraft and one ground vehicle, tar split in two parts mid-member."""
    members = {
        "traces/aa/trace_full_aaaaaa.json": gz(
            trace_obj(
                "aaaaaa",
                [
                    pt(100, 25.0, 55.0, ac=ac_obj(nic=11, nac_p=11)),
                    pt(160, 25.1, 55.1),
                    pt(220, 25.2, 55.2, ac=ac_obj(nic=2, nac_p=3)),
                ],
            )
        ),
        "traces/bb/trace_full_bbbbbb.json": gz(
            trace_obj(
                "bbbbbb", [pt(50, 24.0, 54.0, ac=ac_obj(nic=8, nac_p=8)), pt(3600 * 5, 24.1, 54.1, ac=ac_obj(nic=8))]
            )
        ),
        "traces/cc/trace_full_cccccc.json": gz(trace_obj("cccccc", [pt(10, 50.0, 10.0)])),  # outside the Gulf box
        "traces/dd/trace_full_dddddd.json": gz(
            trace_obj("dddddd", [pt(30, 25.0, 55.3, alt="ground", gs=15.0, src="adsb_icao_nt", ac=ac_obj(nic=10))])
        ),
        "heatmap/ignored.json.gz": b"not a trace",
    }
    tar = make_tar(members)
    cut = split_at or len(tar) // 2 + 7  # an arbitrary byte, not a block boundary
    return {
        release_url(DAY, "prod", "aa", 2026): tar[:cut],
        release_url(DAY, "prod", "ab", 2026): tar[cut:],
    }


def cfg(tmp_path, **kw):
    return IngestConfig(out_dir=tmp_path / "interim", spool_dir=tmp_path / "spool", chunk_bytes=2048, **kw)


def test_end_to_end_rows_manifest_quality_and_cleanup(tmp_path):
    fs = FakeServer(build_day_blobs())
    rec = ingest_day(DAY, cfg(tmp_path), fetch=fs, sleep=NOSLEEP, log=lambda m: None)
    out = tmp_path / "interim" / points_filename(DAY)
    t = pq.read_table(out)
    assert t.schema.remove_metadata() == POINT_SCHEMA.remove_metadata()
    assert t.num_rows == 6  # 3 + 2 + 0 + 1; the aircraft outside the box contributes nothing
    d = t.to_pydict()
    assert d["ts"] == sorted(d["ts"])
    assert set(d["data_class"]) == {DATA_CLASS_OBSERVED}
    a = [(n, c) for i, n, c in zip(d["icao24"], d["nic"], d["q_carried"], strict=True) if i == "aaaaaa"]
    assert a == [(11, False), (11, True), (2, False)]
    # manifest and quality report
    man = read_manifest(tmp_path / "interim" / "manifest.jsonl")
    assert (
        len(man) == 1
        and man[0]["rows"] == 6
        and man[0]["status"] == "complete"
        and man[0]["out_sha256"] == rec["out_sha256"]
    )
    q = json.loads((tmp_path / "interim" / "quality" / f"{DAY}.json").read_text())
    assert q["rows"] == 6 and q["metric_population"]["excluded_non_transponder_rows"] == 1
    assert q["parse_stats"]["trace_files"] == 4
    # spool cleaned
    assert not any(p.is_file() for p in (tmp_path / "spool").rglob("*"))


def test_second_run_is_a_noop(tmp_path):
    fs = FakeServer(build_day_blobs())
    c = cfg(tmp_path)
    ingest_day(DAY, c, fetch=fs, sleep=NOSLEEP, log=lambda m: None)
    n = len(fs.requests)
    res = ingest_day(DAY, c, fetch=fs, sleep=NOSLEEP, log=lambda m: None)
    assert res.get("skipped") and len(fs.requests) == n and is_complete(c, DAY)


def test_changed_parameters_invalidate_completeness(tmp_path):
    fs = FakeServer(build_day_blobs())
    ingest_day(DAY, cfg(tmp_path), fetch=fs, sleep=NOSLEEP, log=lambda m: None)
    assert not is_complete(cfg(tmp_path, max_age_s=30.0), DAY)


def test_output_bytes_are_deterministic(tmp_path):
    shas = []
    for sub in ("one", "two"):
        base = tmp_path / sub
        rec = ingest_day(DAY, cfg(base), fetch=FakeServer(build_day_blobs()), sleep=NOSLEEP, log=lambda m: None)
        shas.append(rec["out_sha256"])
    assert shas[0] == shas[1]


def test_deterministic_across_split_points(tmp_path):
    a = ingest_day(
        DAY, cfg(tmp_path / "a"), fetch=FakeServer(build_day_blobs(split_at=1000)), sleep=NOSLEEP, log=lambda m: None
    )
    b = ingest_day(
        DAY, cfg(tmp_path / "b"), fetch=FakeServer(build_day_blobs(split_at=3333)), sleep=NOSLEEP, log=lambda m: None
    )
    assert a["out_sha256"] == b["out_sha256"]


def test_interrupted_run_resumes_from_spool_and_never_marks_complete(tmp_path):
    blobs = build_day_blobs()
    first_part = release_url(DAY, "prod", "aa", 2026)
    fs = FakeServer(blobs)
    # first run: the connection dies for good once 2 chunks of part .aa have arrived
    fs.fail_hook = lambda url, s, e, n: "raise" if (url == first_part and s >= 4096) else None
    c = cfg(tmp_path)
    with pytest.raises(DownloadError):
        ingest_day(DAY, c, fetch=fs, sleep=NOSLEEP, log=lambda m: None)
    assert not is_complete(c, DAY)
    assert read_manifest(tmp_path / "interim" / "manifest.jsonl") == []
    assert not (tmp_path / "interim" / points_filename(DAY)).exists()
    # second run with a healthy network: continues, does not restart part .aa from byte 0
    fs2 = FakeServer(blobs)
    ingest_day(DAY, c, fetch=fs2, sleep=NOSLEEP, log=lambda m: None)
    data_requests = [(s, e) for u, s, e in fs2.requests if u == first_part and e - s > 0]
    assert data_requests and data_requests[0][0] == 4096
    assert pq.read_table(tmp_path / "interim" / points_filename(DAY)).num_rows == 6


def test_synthetic_class_uses_synthetic_filenames_and_cannot_be_mixed(tmp_path):
    fs = FakeServer(build_day_blobs())
    c = cfg(tmp_path, data_class=DATA_CLASS_SYNTHETIC)
    ingest_day(DAY, c, fetch=fs, sleep=NOSLEEP, log=lambda m: None)
    assert (tmp_path / "interim" / f"points_synthetic_{DAY}.parquet").exists()
    assert not (tmp_path / "interim" / points_filename(DAY)).exists()
    t = pq.read_table(tmp_path / "interim" / f"points_synthetic_{DAY}.parquet")
    with pytest.raises(ValueError):
        assert_data_class_matches(t, tmp_path / "interim" / points_filename(DAY), DATA_CLASS_SYNTHETIC)
    with pytest.raises(ValueError):
        assert_data_class_matches(t, tmp_path / f"points_synthetic_{DAY}.parquet", DATA_CLASS_OBSERVED)


def test_points_filename_validation():
    assert points_filename("2026-03-02") == "points_2026-03-02.parquet"
    assert points_filename("2026-03-02", "synthetic") == "points_synthetic_2026-03-02.parquet"
    with pytest.raises(ValueError):
        points_filename("2026/03/02")
    with pytest.raises(ValueError):
        points_filename("2026-03-02", "other")


def test_workers_give_identical_output(tmp_path):
    a = ingest_day(
        DAY, cfg(tmp_path / "w1", workers=1), fetch=FakeServer(build_day_blobs()), sleep=NOSLEEP, log=lambda m: None
    )
    b = ingest_day(
        DAY, cfg(tmp_path / "w2", workers=2), fetch=FakeServer(build_day_blobs()), sleep=NOSLEEP, log=lambda m: None
    )
    assert a["out_sha256"] == b["out_sha256"]
