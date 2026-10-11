import pyarrow.parquet as pq

from tashwish.metrics.loader import load_points
from tashwish.schema import points_filename

from .test_pipeline import DAY, FakeServer, build_day_blobs, cfg, ingest_day


def test_loader_returns_utc_timestamps_whatever_the_machine_timezone(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Dubai")
    ingest_day(DAY, cfg(tmp_path), fetch=FakeServer(build_day_blobs()), sleep=lambda s: None, log=lambda m: None)
    df = load_points(tmp_path / "interim", [DAY])
    assert str(df.ts.dt.tz) == "UTC"
    assert df.ts.min() >= __import__("pandas").Timestamp("2026-03-02T00:00:00Z")
    assert len(df) == pq.read_table(tmp_path / "interim" / points_filename(DAY)).num_rows
