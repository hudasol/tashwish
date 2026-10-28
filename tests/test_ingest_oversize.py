"""A trace member above the size limit is skipped and counted, not parsed."""

from pathlib import Path

from tashwish.ingest import pipeline
from tashwish.ingest.pipeline import IngestConfig, parse_archive


def test_oversize_member_is_skipped_and_counted(tmp_path, monkeypatch):
    members = [("./traces/aa/trace_full_000001.json", b"x" * 100), ("./traces/bb/trace_full_000002.json", b"y" * 5000)]
    monkeypatch.setattr(pipeline, "iter_trace_members", lambda paths: iter(members))
    monkeypatch.setattr(pipeline, "MAX_MEMBER_BYTES", 1000)
    monkeypatch.setattr(pipeline, "_parse_member", lambda args: ({c: [] for c in pipeline.COLUMNS}, pipeline.Counter()))
    cfg = IngestConfig(out_dir=Path(tmp_path), spool_dir=Path(tmp_path), workers=1)
    table, stats = parse_archive([Path("unused")], "2026-03-25", cfg)
    assert table.num_rows == 0
    assert stats["skipped_oversize"] == 1
    assert stats["skipped_oversize_bytes"] == 5000
    assert stats["trace_files"] == 1
