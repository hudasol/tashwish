"""SYNTHETIC test helpers. Everything built here is invented for tests and is never real observation data.

Nothing produced by this module may be written to data/interim; tests write only to tmp_path.
"""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from collections.abc import Callable

from tashwish.ingest.source import RangeResult

SYNTHETIC = True
DAY = "2026-03-02"
DAY0 = 1772409600.0  # 2026-03-02T00:00:00Z


def pt(off, lat, lon, alt=35000, gs=450.0, trk=90.0, flags=0, ac=None, src="adsb_icao", vr=0, galt=None):
    """One trace point in readsb layout (indices 0..10)."""
    return [off, lat, lon, alt, gs, trk, flags, vr, ac, src, galt]


def ac_obj(nic=11, nac_p=11, **kw):
    d = {
        "type": "adsb_icao",
        "version": 2,
        "nic": nic,
        "rc": 7,
        "nac_p": nac_p,
        "nac_v": 2,
        "sil": 3,
        "sil_type": "perhour",
    }
    d.update(kw)
    return d


def trace_obj(icao, points, ts0=DAY0, t="A320"):
    return {"icao": icao, "timestamp": ts0, "trace": points, "r": "SYN", "t": t}


def gz(obj) -> bytes:
    return gzip.compress(json.dumps(obj).encode(), 6, mtime=0)


def make_tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mtime = 0
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


class FakeServer:
    """Serves byte blobs by URL with HTTP Range semantics and optional failure injection."""

    def __init__(self, blobs: dict[str, bytes]):
        self.blobs = blobs
        self.requests: list[tuple[str, int, int]] = []
        self.fail_hook: Callable[[str, int, int, int], str | None] | None = None
        self._n = 0

    def __call__(self, url: str, start: int, end: int) -> RangeResult:
        self.requests.append((url, start, end))
        self._n += 1
        if url not in self.blobs:
            return RangeResult(404, b"")
        blob = self.blobs[url]
        mode = self.fail_hook(url, start, end, self._n) if self.fail_hook else None
        if mode == "raise":
            import httpx

            raise httpx.ReadError("simulated connection reset")
        end = min(end, len(blob) - 1)
        body = blob[start : end + 1]
        cr = f"bytes {start}-{end}/{len(blob)}"
        if mode == "truncate":
            body = body[: max(1, len(body) // 2)]
        if mode == "bad_status":
            return RangeResult(200, blob)
        return RangeResult(206, body, cr)
