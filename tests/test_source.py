import json

import pytest

from tashwish.ingest.source import (
    DayNotAvailable,
    DownloadError,
    choose_release,
    download_part,
    list_parts,
    part_total,
    release_url,
)

from .synth import FakeServer

NOSLEEP = lambda s: None  # noqa: E731


def test_release_url_format():
    u = release_url("2026-03-02", "prod", "aa", 2026)
    assert u == (
        "https://github.com/adsblol/globe_history_2026/releases/download/"
        "v2026.03.02-planes-readsb-prod-0/v2026.03.02-planes-readsb-prod-0.tar.aa"
    )


def blobs(day="2026-03-02", prod=(b"A" * 100, b"B" * 50), staging=None, year=2026):
    d = {}
    for kind, parts in (("prod", prod), ("staging", staging)):
        for i, data in enumerate(parts or ()):
            d[release_url(day, kind, "ab"[:0] + chr(97) + chr(97 + i), year)] = data
    return d


def test_list_parts_stops_at_first_missing():
    fs = FakeServer(blobs())
    parts = list_parts(fs, "2026-03-02", "prod", 2026, NOSLEEP)
    assert [t for _, t in parts] == [100, 50]
    assert list_parts(fs, "2026-03-02", "staging", 2026, NOSLEEP) == []


def test_choose_release_prefers_larger_and_ties_go_to_prod():
    fs = FakeServer(blobs(prod=(b"x" * 10,), staging=(b"y" * 20,)))
    assert choose_release(fs, "2026-03-02", NOSLEEP)[0] == "staging"
    fs = FakeServer(blobs(prod=(b"x" * 10,), staging=(b"y" * 10,)))
    assert choose_release(fs, "2026-03-02", NOSLEEP)[0] == "prod"


def test_choose_release_finds_adjacent_year_repo():
    # the 2026 repository holds some days of December 2025
    fs = FakeServer(blobs(day="2025-12-20", year=2026))
    kind, repo_year, parts = choose_release(fs, "2025-12-20", NOSLEEP)
    assert (kind, repo_year, len(parts)) == ("prod", 2026, 2)


def test_choose_release_raises_when_day_missing():
    with pytest.raises(DayNotAvailable):
        choose_release(FakeServer({}), "2026-03-02", NOSLEEP)


def test_download_exact_bytes_in_chunks(tmp_path):
    data = bytes(range(256)) * 40
    url = "u://a"
    fs = FakeServer({url: data})
    dest = tmp_path / "aa"
    download_part(fs, url, dest, len(data), chunk=1000, sleep=NOSLEEP)
    assert dest.read_bytes() == data
    assert [(a, b) for _, a, b in fs.requests] == [
        (0, 999),
        (1000, 1999),
        (2000, 2999),
        (3000, 3999),
        (4000, 4999),
        (5000, 5999),
        (6000, 6999),
        (7000, 7999),
        (8000, 8999),
        (9000, 9999),
        (10000, 10239),
    ]


def test_download_resumes_from_existing_bytes(tmp_path):
    data = bytes(range(256)) * 40
    url = "u://a"
    dest = tmp_path / "aa"
    dest.write_bytes(data[:3000])
    (tmp_path / "aa.meta").write_text(json.dumps({"url": url, "total": len(data)}), encoding="utf-8", newline="\n")
    fs = FakeServer({url: data})
    download_part(fs, url, dest, len(data), chunk=4096, sleep=NOSLEEP)
    assert dest.read_bytes() == data
    assert fs.requests[0][1] == 3000, "must not re-download the first 3000 bytes"


def test_download_discards_corrupt_oversized_partial(tmp_path):
    data = b"z" * 500
    dest = tmp_path / "aa"
    dest.write_bytes(b"q" * 900)
    fs = FakeServer({"u://a": data})
    download_part(fs, "u://a", dest, len(data), chunk=200, sleep=NOSLEEP)
    assert dest.read_bytes() == data


@pytest.mark.parametrize("mode", ["raise", "truncate", "bad_status"])
def test_transient_failures_are_retried(tmp_path, mode):
    data = bytes(range(200)) * 10
    fs = FakeServer({"u://a": data})
    fs.fail_hook = lambda url, s, e, n: mode if n in (1, 2, 5) else None
    download_part(fs, "u://a", tmp_path / "aa", len(data), chunk=500, sleep=NOSLEEP)
    assert (tmp_path / "aa").read_bytes() == data


def test_persistent_failure_raises_download_error(tmp_path):
    fs = FakeServer({"u://a": b"x" * 100})
    fs.fail_hook = lambda *a: "raise"
    with pytest.raises(DownloadError):
        download_part(fs, "u://a", tmp_path / "aa", 100, chunk=50, retries=3, sleep=NOSLEEP)


def test_size_change_during_download_is_detected(tmp_path):
    fs = FakeServer({"u://a": b"x" * 100})
    with pytest.raises(DownloadError):
        download_part(fs, "u://a", tmp_path / "aa", 90, chunk=50, sleep=NOSLEEP)


def test_part_total_reads_content_range():
    fs = FakeServer({"u://a": b"x" * 123})
    assert part_total(fs, "u://a", sleep=NOSLEEP) == 123
    assert part_total(fs, "u://missing", sleep=NOSLEEP) is None
