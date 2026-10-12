"""adsb.lol `globe_history` source: release naming, ranged resumable download, release selection.

Source: https://github.com/adsblol (repositories globe_history_YYYY), Open Database Licence 1.0.
Each day is a tar split into parts `.aa`, `.ab`, ... (the egress path in some environments cuts connections after
about 100 seconds, so every request is a bounded byte range and downloads resume from the bytes already on disk).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

CHUNK_BYTES = 64 * 1024 * 1024
USER_AGENT = "tashwish/0.1 (+https://github.com/hudasol/tashwish; research, sequential ranged downloads)"
_URL = (
    "https://github.com/adsblol/globe_history_{repo_year}/releases/download/"
    "v{dot}-planes-readsb-{kind}-0/v{dot}-planes-readsb-{kind}-0.tar.{part}"
)
_CR = re.compile(r"bytes (\d+)-(\d+)/(\d+)")
KINDS = ("prod", "staging")


class DayNotAvailable(Exception):
    pass


class DownloadError(Exception):
    pass


@dataclass(frozen=True)
class RangeResult:
    status: int
    body: bytes
    content_range: str | None = None


class Fetcher(Protocol):
    def __call__(self, url: str, start: int, end: int) -> RangeResult: ...


class HttpxFetcher:
    """Real network fetcher. Reuses one client; redirects are followed on every request."""

    def __init__(self, timeout: float = 120.0):
        self._client = httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": USER_AGENT})

    def __call__(self, url: str, start: int, end: int) -> RangeResult:
        r = self._client.get(url, headers={"Range": f"bytes={start}-{end}"})
        return RangeResult(r.status_code, r.content, r.headers.get("content-range"))


def release_url(day: str, kind: str, part: str, repo_year: int) -> str:
    y, m, d = day.split("-")
    return _URL.format(repo_year=repo_year, dot=f"{y}.{m}.{d}", kind=kind, part=part)


def _parse_cr(cr: str | None) -> tuple[int, int, int] | None:
    m = _CR.search(cr or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _retrying(fetch: Fetcher, url: str, start: int, end: int, retries: int, sleep: Callable[[float], None]):
    """Return a validated RangeResult or None for 404. Raises DownloadError after exhausting retries."""
    last: Exception | str = ""
    for attempt in range(retries):
        try:
            r = fetch(url, start, end)
        except (httpx.HTTPError, OSError) as e:  # network cut, timeout, reset
            last = e
        else:
            if r.status == 404:
                return None
            cr = _parse_cr(r.content_range)
            if r.status == 206 and cr and cr[0] == start and len(r.body) == cr[1] - cr[0] + 1:
                return r
            last = f"bad response status={r.status} cr={r.content_range} len={len(r.body)}"
        sleep(min(2.0 * (attempt + 1), 30.0))
    raise DownloadError(f"{url} bytes {start}-{end}: {last}")


def part_total(fetch: Fetcher, url: str, retries: int = 6, sleep: Callable[[float], None] = time.sleep) -> int | None:
    r = _retrying(fetch, url, 0, 0, retries, sleep)
    if r is None:
        return None
    cr = _parse_cr(r.content_range)
    assert cr is not None
    return cr[2]


def list_parts(
    fetch: Fetcher, day: str, kind: str, repo_year: int, sleep: Callable[[float], None] = time.sleep
) -> list[tuple[str, int]]:
    """Existing parts for (day, kind) in order, as (url, total_bytes)."""
    parts: list[tuple[str, int]] = []
    for i in range(26 * 26):
        suffix = chr(97 + i // 26) + chr(97 + i % 26)
        url = release_url(day, kind, suffix, repo_year)
        total = part_total(fetch, url, sleep=sleep)
        if total is None:
            break
        parts.append((url, total))
    return parts


def choose_release(
    fetch: Fetcher, day: str, sleep: Callable[[float], None] = time.sleep
) -> tuple[str, int, list[tuple[str, int]]]:
    """Pick (kind, repo_year, parts): the release with more bytes, per the archive README. Ties go to prod."""
    year = int(day[:4])
    best: tuple[str, int, list[tuple[str, int]]] | None = None
    for repo_year in dict.fromkeys([year, year + 1, year - 1]):
        for kind in KINDS:
            parts = list_parts(fetch, day, kind, repo_year, sleep)
            if not parts:
                continue
            if best is None or sum(t for _, t in parts) > sum(t for _, t in best[2]):
                best = (kind, repo_year, parts)
        if best is not None:
            return best
    raise DayNotAvailable(day)


def download_part(
    fetch: Fetcher,
    url: str,
    dest: Path,
    total: int,
    chunk: int = CHUNK_BYTES,
    retries: int = 8,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Download `url` to `dest`, resuming from the bytes already there. Verifies the final size."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    meta = dest.with_suffix(dest.suffix + ".meta")
    have = dest.stat().st_size if dest.exists() else 0
    if have > total or (meta.exists() and json.loads(meta.read_text()).get("total") != total):
        dest.unlink(missing_ok=True)
        have = 0
    meta.write_text(json.dumps({"url": url, "total": total}))
    with open(dest, "ab") as f:
        while have < total:
            end = min(have + chunk, total) - 1
            r = _retrying(fetch, url, have, end, retries, sleep)
            if r is None:
                raise DownloadError(f"{url} vanished at byte {have}")
            cr = _parse_cr(r.content_range)
            assert cr is not None
            if cr[2] != total:
                raise DownloadError(f"{url} changed size {total} -> {cr[2]} during download")
            f.write(r.body)
            f.flush()
            have += len(r.body)
    if dest.stat().st_size != total:
        raise DownloadError(f"{dest} size {dest.stat().st_size} != expected {total}")
