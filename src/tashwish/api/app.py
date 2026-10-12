"""FastAPI application factory for the read only Tashwish release API. See docs/API.md."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..attribution import DATASET_ATTRIBUTION
from ..interop.marsad import STALENESS_MAX_AGE_HOURS
from . import queries as q
from .release import API_SCHEMA, Release, ReleaseError

log = logging.getLogger("tashwish.api")

SAFETY_STATEMENT = "Research and monitoring tool, not for navigation or safety of life, no attribution to any actor"
DESCRIPTION = f"""
Read only JSON API over a versioned Tashwish release (aggregated GNSS interference indicators derived from public
ADS-B data over the Gulf).

**{SAFETY_STATEMENT}.**

* `insufficient`, `coverage_lost`, `no_record`, `stale` and `out_of_region` are explicit statuses. They are never a
  zero and never mean "clear". Estimates are `null` unless the status is `ok`.
* A response carries the attribution in the `X-Attribution` header and in the body. Releases built from synthetic data
  also send `X-Synthetic: true` and a top level `synthetic_notice`.
* Licences: data ODbL 1.0 (derived database), code Apache-2.0.
* No aircraft identifiers are stored or served. Every list is paged and capped.
"""
DATA_LICENCE = {"name": "ODbL-1.0", "url": "https://opendatacommons.org/licenses/odbl/1-0/"}
EXPOSED_HEADERS = ["ETag", "X-Attribution", "X-Data-Class", "X-Dataset-Version", "X-Synthetic", "Retry-After"]
NO_CACHE_PATHS = {"/health", "/v1/freshness"}
MAX_QUERY_CHARS = 2048
DOWNLOAD_NAME_RE = r"^[A-Za-z0-9._-]{1,128}$"
EVENT_ID_RE = r"^[A-Za-z0-9_.:-]{1,128}$"
CURSOR_RE = r"^[A-Za-z0-9_-]{1,1024}$"
CONTEXT_TS_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"

CONTENT_TYPES = {
    ".parquet": "application/vnd.apache.parquet",
    ".json": "application/json",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".sha256": "text/plain; charset=utf-8",
}

Stratum = Literal["enroute", "high", "mid", "low"]
Status = Literal["ok", "insufficient", "coverage_lost"]
EventKind = Literal["jamming_like", "spoofing_like", "both", "uncertain"]
Confidence = Literal["low", "medium", "high"]
Mode = Literal["retrospective", "nowcast"]


class _RateLimiter:
    """Sliding window per client key, in memory (single process; the free tier runs one). 0 disables it."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> int | None:
        """None if allowed, else seconds to wait."""
        if self.per_minute <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            dq = self._hits[key]
            while dq and now - dq[0] > 60:
                dq.popleft()
            if len(dq) >= self.per_minute:
                return max(1, int(60 - (now - dq[0])) + 1)
            dq.append(now)
            if len(self._hits) > 10_000:  # bound memory under a key flood
                self._hits.clear()
        return None


def _etag(rel: Release, request: Request) -> str:
    items = sorted(request.query_params.multi_items())
    h = hashlib.sha256(f"{rel.dataset_version}|{request.url.path}|{items}".encode()).hexdigest()[:24]
    return f'W/"{h}"'


def _release_headers(rel: Release) -> dict[str, str]:
    h = {
        "X-Attribution": DATASET_ATTRIBUTION,
        "X-Data-Class": rel.data_class,
        "X-Dataset-Version": rel.dataset_version,
        "X-Content-Type-Options": "nosniff",
    }
    if rel.synthetic:
        h["X-Synthetic"] = "true"
    return h


def _error_body(rel: Release, code: str, message: str, details=None) -> dict:
    body: dict = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    if rel.synthetic:
        body["synthetic_notice"] = rel.notice
    return body


def _envelope(rel: Release, **fields) -> dict:
    body = {
        "schema": API_SCHEMA,
        "dataset_version": rel.dataset_version,
        "data_class": rel.data_class,
        "attribution": DATASET_ATTRIBUTION,
    }
    if rel.synthetic:
        body["synthetic_notice"] = rel.notice
    body.update(fields)
    return body


def create_app(release_dir: str | Path, *, rate_limit_per_minute: int | None = None, verify_hashes: bool | None = None):
    """Build the application for a release directory. Raises `ReleaseError` if the directory is not a valid release."""
    release = Release(release_dir, verify_hashes=verify_hashes)
    limiter = _RateLimiter(
        int(os.environ.get("TASHWISH_RATE_LIMIT_PER_MIN", "300"))
        if rate_limit_per_minute is None
        else rate_limit_per_minute
    )

    app = FastAPI(
        title="Tashwish release API",
        version=__version__,
        description=DESCRIPTION,
        summary=SAFETY_STATEMENT,
        license_info={"name": "Apache-2.0 (code); ODbL-1.0 (data)", "url": DATA_LICENCE["url"]},
        contact={"name": "Tashwish", "url": "https://github.com/hudasol/tashwish"},
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.release = release

    def rel() -> Release:
        return app.state.release

    # ------------------------------------------------------------------ errors
    @app.exception_handler(q.ApiError)
    async def _api_error(request: Request, exc: q.ApiError):
        return JSONResponse(_error_body(rel(), exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]), "message": e["msg"]}
            for e in exc.errors()
        ]
        names = ", ".join(d["field"] for d in details)
        return JSONResponse(
            _error_body(rel(), "invalid_request", f"invalid request parameters: {names}", details), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        msg = {
            404: "no such resource",
            405: "this API is read only: only GET is supported",
        }.get(exc.status_code, str(exc.detail))
        return JSONResponse(_error_body(rel(), code, msg), status_code=exc.status_code, headers=dict(exc.headers or {}))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        resp = JSONResponse(_error_body(rel(), "internal_error", "internal error"), status_code=500)
        for k, v in _release_headers(rel()).items():  # ServerErrorMiddleware bypasses the middleware below
            resp.headers[k] = v
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # ------------------------------------------------------------------ middleware
    @app.middleware("http")
    async def guard(request: Request, call_next):
        r = rel()
        r.refresh()
        r = rel()
        hdrs = _release_headers(r)
        path = request.url.path

        def reject(status: int, code: str, message: str, extra: dict | None = None) -> JSONResponse:
            resp = JSONResponse(_error_body(r, code, message), status_code=status)
            for k, v in {**hdrs, "Cache-Control": "no-store", **(extra or {})}.items():
                resp.headers[k] = v
            return resp

        if len(request.url.query) > MAX_QUERY_CHARS:
            return reject(414, "query_too_long", f"query string is longer than {MAX_QUERY_CHARS} characters")
        if path != "/health":
            client = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
                request.client.host if request.client else "unknown"
            )
            wait = limiter.check(client)
            if wait is not None:
                return reject(
                    429,
                    "rate_limited",
                    "too many requests; slow down and use ETag revalidation",
                    {"Retry-After": str(wait)},
                )
        etag = _etag(r, request)
        cacheable = request.method == "GET" and path not in NO_CACHE_PATHS and path.startswith("/v1/")
        if cacheable and etag in [t.strip() for t in request.headers.get("if-none-match", "").split(",")]:
            return Response(
                status_code=304, headers={**hdrs, "ETag": etag, "Cache-Control": _cache_control(r, request)}
            )
        resp = await call_next(request)
        for k, v in hdrs.items():
            resp.headers[k] = v
        if resp.status_code == 200 and request.method == "GET":
            if path in NO_CACHE_PATHS:
                resp.headers["Cache-Control"] = "no-cache"
            else:
                resp.headers["Cache-Control"] = _cache_control(r, request)
                resp.headers["ETag"] = etag
        else:
            resp.headers["Cache-Control"] = "no-store"
        return resp

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["If-None-Match"],
        allow_credentials=False,
        expose_headers=EXPOSED_HEADERS,
        max_age=86400,
    )

    # ------------------------------------------------------------------ shared dependencies
    def strict(*allowed: str):
        """Reject unknown and repeated query parameters, and a dataset_version that is not the loaded one."""
        names = {*allowed, "dataset_version"}

        def dep(request: Request) -> None:
            seen: set[str] = set()
            for k, _ in request.query_params.multi_items():
                if k not in names:
                    raise q.ApiError(
                        422, "unknown_parameter", f"unknown query parameter {k!r}; allowed: {sorted(names)}"
                    )
                if k in seen:
                    raise q.ApiError(422, "repeated_parameter", f"query parameter {k!r} must appear once")
                seen.add(k)
            want = request.query_params.get("dataset_version")
            if want is not None and want != rel().dataset_version:
                raise q.ApiError(
                    409,
                    "dataset_version_mismatch",
                    f"requested dataset_version does not match the loaded release ({rel().dataset_version})",
                )

        return Depends(dep)

    def check_day(day: str | None) -> None:
        if day is None:
            return
        try:
            date.fromisoformat(day)
        except ValueError:
            raise q.ApiError(422, "invalid_day", f"day must be a real calendar date YYYY-MM-DD, got {day!r}") from None

    # ------------------------------------------------------------------ endpoints
    @app.get("/health", tags=["service"], summary="Liveness and dataset age (cheap; used as the platform health check)")
    def health():
        r = rel()
        age = r.age_hours()
        body = {
            "status": "stale" if age > STALENESS_MAX_AGE_HOURS else "ok",
            "dataset_version": r.dataset_version,
            "latest_day": r.manifest["latest_day"],
            "age_hours": age,
            "data_class": r.data_class,
        }
        if r.synthetic:
            body["synthetic_notice"] = r.notice
        return body

    @app.get("/v1/manifest", tags=["release"], summary="Release manifest", dependencies=[strict()])
    def manifest():
        return _envelope(rel(), manifest=rel().manifest)

    @app.get(
        "/v1/days", tags=["release"], summary="Days in the release with split and row counts", dependencies=[strict()]
    )
    def days():
        r = rel()
        return _envelope(r, latest_day=r.manifest["latest_day"], grid=r.manifest["grid"], days=r.manifest["days"])

    @app.get(
        "/v1/cells",
        tags=["data"],
        summary="Cell/bucket indicators (paged, at most 5000 rows per page)",
        description=(
            "Rows are ordered by bucket_start, h3, stratum. `share`, `ci_lo`, `ci_hi` and `k_strong` are null unless "
            "`status` is `ok`: `insufficient` and `coverage_lost` are not zero and not 'clear'. Follow `next_cursor`."
        ),
        dependencies=[strict("day", "slot", "stratum", "status", "limit", "cursor")],
    )
    def cells(
        day: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$", description="UTC day, YYYY-MM-DD")] = None,
        slot: Annotated[int | None, Query(ge=0, le=23, description="UTC bucket index within the day")] = None,
        stratum: Stratum | None = None,
        status: Status | None = None,
        limit: Annotated[int, Query(ge=1, le=q.MAX_CELLS_PAGE)] = q.DEFAULT_CELLS_PAGE,
        cursor: Annotated[str | None, Query(pattern=CURSOR_RE)] = None,
    ):
        check_day(day)
        rows, nxt = q.query_cells(rel(), day=day, slot=slot, stratum=stratum, status=status, limit=limit, cursor=cursor)
        return _envelope(rel(), count=len(rows), limit=limit, next_cursor=nxt, data=rows)

    @app.get(
        "/v1/events",
        tags=["data"],
        summary="Detected events (paged)",
        description="Events overlapping [from, to]. A date bound means the whole UTC day. Ordered by start, event_id.",
        dependencies=[strict("from", "to", "kind", "min_confidence", "uncertain", "limit", "cursor")],
    )
    def events(
        t_from: Annotated[str | None, Query(alias="from", pattern=q.TS_RE.pattern)] = None,
        t_to: Annotated[str | None, Query(alias="to", pattern=q.TS_RE.pattern)] = None,
        kind: EventKind | None = None,
        min_confidence: Confidence | None = None,
        uncertain: bool | None = None,
        limit: Annotated[int, Query(ge=1, le=q.MAX_EVENTS_PAGE)] = q.DEFAULT_EVENTS_PAGE,
        cursor: Annotated[str | None, Query(pattern=CURSOR_RE)] = None,
    ):
        rows, nxt = q.query_events(
            rel(), t_from=t_from, t_to=t_to, kind=kind, min_confidence=min_confidence, uncertain=uncertain,
            limit=limit, cursor=cursor,
        )  # fmt: skip
        return _envelope(rel(), count=len(rows), limit=limit, next_cursor=nxt, data=rows)

    @app.get("/v1/events/{event_id}", tags=["data"], summary="One event", dependencies=[strict()])
    def event(event_id: Annotated[str, PathParam(pattern=EVENT_ID_RE)]):
        e = q.get_event(rel(), event_id)
        if e is None:
            raise q.ApiError(404, "event_not_found", "no event with that id in this release")
        return _envelope(rel(), event=e)

    @app.get(
        "/v1/coverage",
        tags=["data"],
        summary="Receiver coverage model per cell, slot and stratum (paged)",
        dependencies=[strict("slot", "stratum", "limit", "cursor")],
    )
    def coverage(
        slot: Annotated[int | None, Query(ge=0, le=23)] = None,
        stratum: Stratum | None = None,
        limit: Annotated[int, Query(ge=1, le=q.MAX_COVERAGE_PAGE)] = q.DEFAULT_COVERAGE_PAGE,
        cursor: Annotated[str | None, Query(pattern=CURSOR_RE)] = None,
    ):
        rows, nxt = q.query_coverage(rel(), slot=slot, stratum=stratum, limit=limit, cursor=cursor)
        return _envelope(rel(), count=len(rows), limit=limit, next_cursor=nxt, data=rows)

    @app.get(
        "/v1/validation",
        tags=["release"],
        summary="Validation results shipped with the release",
        dependencies=[strict()],
    )
    def validation():
        v = rel().validation()
        if v is None:
            raise q.ApiError(404, "validation_unavailable", "this release has no validation.json")
        return _envelope(rel(), validation=v)

    @app.get("/v1/freshness", tags=["release"], summary="Pipeline freshness (not cached)", dependencies=[strict()])
    def freshness():
        r = rel()
        return _envelope(r, freshness=r.freshness(), age_hours=r.age_hours(), max_age_hours=STALENESS_MAX_AGE_HOURS)

    @app.get(
        "/v1/context",
        tags=["context"],
        summary="Interference context prior for a position and time (tashwish.interference.v1)",
        description=(
            "Semantics of `tashwish.interop.marsad.ContextIndex` (docs/MARSAD_INTERFACE.md section 4). Malformed input "
            "is HTTP 422. Every other outcome is HTTP 200 with a `status`; only `ok` is usable as a prior, and never "
            "from a synthetic release."
        ),
        dependencies=[strict("lat", "lon", "t", "alt_ft", "mode")],
    )
    def context(
        lat: Annotated[float, Query(ge=-90, le=90)],
        lon: Annotated[float, Query(ge=-180, le=180)],
        t: Annotated[str, Query(pattern=CONTEXT_TS_RE, description="ISO 8601 UTC, ends in Z")],
        alt_ft: Annotated[float | None, Query(ge=-2000, le=100000, description="barometric altitude, feet")] = None,
        mode: Mode = "retrospective",
    ):
        try:
            when = datetime.fromisoformat(t[:-1] + "+00:00")
        except ValueError:
            raise q.ApiError(422, "invalid_t", f"t is not a real UTC timestamp: {t!r}") from None
        out = q.query_context(rel(), lat, lon, when, alt_ft, mode, max_age_hours=STALENESS_MAX_AGE_HOURS)
        if rel().synthetic:
            out["synthetic_notice"] = rel().notice
        return out

    @app.get(
        "/v1/download/{name}",
        tags=["release"],
        summary="Download a file listed in the manifest",
        description="Streams a release file. The SHA-256 is in `X-Content-SHA256` and in the manifest.",
        dependencies=[strict()],
        response_class=StreamingResponse,
    )
    def download(name: Annotated[str, PathParam(pattern=DOWNLOAD_NAME_RE)]):
        info = rel().file_info(name)
        if info is None:
            raise q.ApiError(404, "file_not_listed", "no such file in the release manifest; see /v1/manifest")
        path: Path = info["abs_path"]

        def chunks() -> Iterator[bytes]:
            with path.open("rb") as f:
                while chunk := f.read(1 << 16):
                    yield chunk

        ctype = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        if name in ("NOTICE", "DATA_CARD.md", "checksums.sha256"):
            ctype = CONTENT_TYPES.get(Path(name).suffix.lower(), "text/plain; charset=utf-8")
        return StreamingResponse(
            chunks(),
            media_type=ctype,
            headers={
                "Content-Length": str(path.stat().st_size),
                "Content-Disposition": f'attachment; filename="{name}"',
                "X-Content-SHA256": str(info["sha256"]),
            },
        )

    return app


def _cache_control(r: Release, request: Request) -> str:
    if request.query_params.get("dataset_version") == r.dataset_version:
        return "public, max-age=31536000, immutable"
    return "public, max-age=300, must-revalidate"


def create_app_from_env():
    """Uvicorn factory: `uvicorn tashwish.api.app:create_app_from_env --factory`. Needs TASHWISH_RELEASE_DIR."""
    d = os.environ.get("TASHWISH_RELEASE_DIR")
    if not d:
        raise ReleaseError("set TASHWISH_RELEASE_DIR to the release directory")
    return create_app(d)
