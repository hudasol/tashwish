"""Tests for the read only release API. All data here is SYNTHETIC (see tests/synth_release.py)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from fastapi.testclient import TestClient  # noqa: E402

from tashwish.api import create_app  # noqa: E402
from tashwish.api import queries as q  # noqa: E402
from tashwish.api.release import Release, ReleaseError  # noqa: E402
from tashwish.attribution import DATASET_ATTRIBUTION  # noqa: E402
from tashwish.interop import marsad  # noqa: E402

from .synth_release import DAYS, GRID, PLACES, SynthRelease, build_synthetic_release  # noqa: E402

FORBIDDEN_KEYS = ("icao", "hex", "callsign", "registration", "tail", "flight", "mmsi", "squawk", "aircraft_id")


@pytest.fixture(scope="module")
def rel(tmp_path_factory) -> SynthRelease:
    return build_synthetic_release(tmp_path_factory.mktemp("synth_release"))


@pytest.fixture(scope="module")
def client(rel) -> TestClient:
    return TestClient(create_app(rel.path, rate_limit_per_minute=0))


def ok(r, status=200):
    assert r.status_code == status, r.text
    return r.json()


def walk_pages(client, url, **params):
    """Follow next_cursor to the end; returns (rows, number of pages)."""
    rows, pages, cursor = [], 0, None
    while True:
        p = {**params, **({"cursor": cursor} if cursor else {})}
        body = ok(client.get(url, params=p))
        rows += body["data"]
        pages += 1
        cursor = body["next_cursor"]
        if not cursor:
            return rows, pages
        assert pages < 500


def all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from all_keys(v)


GET_URLS = [
    "/health",
    "/v1/manifest",
    "/v1/days",
    "/v1/cells?limit=3",
    "/v1/events",
    "/v1/events/synth-ev-001",
    "/v1/coverage?slot=1",
    "/v1/validation",
    "/v1/freshness",
    "/v1/context?lat=25.2&lon=55.3&t=2026-01-10T10:00:00Z",
]


# ---------------------------------------------------------------------- health, headers, banner
def test_health_fields_and_no_big_file_read(rel, monkeypatch):
    app = create_app(rel.path, rate_limit_per_minute=0)
    monkeypatch.setattr(Release, "cursor", lambda self: (_ for _ in ()).throw(AssertionError("health queried parquet")))
    body = ok(TestClient(app).get("/health"))
    assert body["status"] == "ok"
    assert body["dataset_version"] == "synthetic-2026.01.11-test"
    assert body["latest_day"] == DAYS[-1]
    assert 4.9 < body["age_hours"] < 5.2


def test_health_reports_stale_when_old(tmp_path):
    r = build_synthetic_release(tmp_path, age_hours=100)
    body = ok(TestClient(create_app(r.path)).get("/health"))
    assert body["status"] == "stale" and body["age_hours"] > 99


@pytest.mark.parametrize("url", GET_URLS)
def test_required_headers_on_every_endpoint(client, url):
    r = client.get(url)
    assert r.status_code == 200
    assert r.headers["X-Attribution"] == DATASET_ATTRIBUTION
    assert r.headers["X-Data-Class"] == "synthetic"
    assert r.headers["X-Dataset-Version"] == "synthetic-2026.01.11-test"
    assert r.headers["X-Synthetic"] == "true"


@pytest.mark.parametrize("url", GET_URLS)
def test_synthetic_notice_field_on_every_json_body(client, url):
    body = ok(client.get(url))
    assert "SYNTHETIC" in body["synthetic_notice"]
    assert body["data_class"] == "synthetic"


def test_error_responses_also_carry_headers_and_banner(client):
    r = client.get("/v1/cells?stratum=nope")
    assert r.status_code == 422
    assert r.headers["X-Attribution"] == DATASET_ATTRIBUTION and r.headers["X-Synthetic"] == "true"
    assert "synthetic_notice" in r.json()
    r = client.get("/nope")
    assert r.status_code == 404 and r.headers["X-Attribution"] == DATASET_ATTRIBUTION
    assert r.json()["error"]["code"] == "not_found"


def test_observed_release_has_no_synthetic_banner(tmp_path):
    r = build_synthetic_release(tmp_path, data_class="observed")  # test-only: exercises the observed code path
    c = TestClient(create_app(r.path))
    for url in ("/health", "/v1/days", "/v1/cells?limit=2"):
        resp = c.get(url)
        assert resp.headers["X-Data-Class"] == "observed"
        assert "X-Synthetic" not in resp.headers
        assert "synthetic_notice" not in resp.json()


def test_no_aircraft_identifiers_anywhere(client):
    for url in [*GET_URLS, "/v1/events?limit=1000", "/v1/cells?limit=5000", "/v1/coverage?limit=5000"]:
        keys = {str(k).lower() for k in all_keys(client.get(url).json())}
        assert not keys & set(FORBIDDEN_KEYS), (url, keys & set(FORBIDDEN_KEYS))


# ---------------------------------------------------------------------- release metadata
def test_manifest_and_days(client, rel):
    m = ok(client.get("/v1/manifest"))["manifest"]
    assert m["schema"] == "tashwish.release.v1" and m["grid"] == {"h3_res": GRID.h3_res, "bucket_hours": 3}
    d = ok(client.get("/v1/days"))
    assert [x["day"] for x in d["days"]] == list(DAYS) and d["latest_day"] == DAYS[-1]
    assert sum(x["rows"] for x in d["days"]) == len(rel.cb)


def test_validation_and_freshness(client):
    assert ok(client.get("/v1/validation"))["validation"]["headline"]["precision"]["value"] == 0.8
    f = ok(client.get("/v1/freshness"))
    assert f["freshness"]["last_run_status"] == "success" and f["freshness"]["fallback_active"] is False
    assert f["age_hours"] > 4.9


def test_validation_missing_is_404_not_empty(tmp_path):
    r = build_synthetic_release(tmp_path)
    m = json.loads((r.path / "manifest.json").read_text(encoding="utf-8"))
    del m["files"]["validation.json"]
    (r.path / "manifest.json").write_text(json.dumps(m), encoding="utf-8", newline="\n")
    (r.path / "validation.json").unlink()
    resp = TestClient(create_app(r.path)).get("/v1/validation")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "validation_unavailable"


# ---------------------------------------------------------------------- cells
def test_cells_pagination_is_complete_ordered_and_unique(client, rel):
    rows, pages = walk_pages(client, "/v1/cells", day=DAYS[0], limit=7)
    expected = rel.cb[rel.cb.bucket_start.dt.strftime("%Y-%m-%d") == DAYS[0]]
    assert len(rows) == len(expected) and pages == -(-len(expected) // 7)
    keys = [(r["bucket_start"], r["h3"], r["stratum"]) for r in rows]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)


def test_cells_page_cap_is_5000(client):
    assert ok(client.get("/v1/cells?limit=5000"))["limit"] == 5000
    r = client.get("/v1/cells?limit=5001")
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "limit"
    assert client.get("/v1/cells?limit=0").status_code == 422


def test_cells_default_page_is_bounded(client, rel):
    body = ok(client.get("/v1/cells"))
    assert body["count"] == len(rel.cb) and body["next_cursor"] is None  # tiny release fits in one default page


def test_cells_filters(client, rel):
    b = ok(client.get("/v1/cells", params={"day": DAYS[1], "slot": 3, "stratum": "enroute", "status": "ok"}))
    assert b["count"] > 0
    assert all(r["slot"] == 3 and r["stratum"] == "enroute" and r["status"] == "ok" for r in b["data"])
    assert all(r["bucket_start"].startswith(DAYS[1]) for r in b["data"])
    cb = rel.cb
    n = len(cb[(cb.status == "coverage_lost")])
    assert len(walk_pages(client, "/v1/cells", status="coverage_lost", limit=5)[0]) == n


def test_cells_non_ok_rows_never_carry_numbers(client):
    rows = walk_pages(client, "/v1/cells", limit=50)[0]
    non_ok = [r for r in rows if r["status"] != "ok"]
    assert non_ok and all(r["share"] is None and r["ci_lo"] is None and r["ci_hi"] is None for r in non_ok)
    assert all(isinstance(r["share"], float) for r in rows if r["status"] == "ok")


def test_cells_non_ok_rows_are_nulled_even_if_the_builder_leaks_numbers(tmp_path):
    r = build_synthetic_release(tmp_path, leak_estimates=True)
    rows = walk_pages(TestClient(create_app(r.path)), "/v1/cells", limit=100)[0]
    bad = [x for x in rows if x["status"] != "ok" and (x["share"] is not None or x["k_strong"] is not None)]
    assert not bad


def test_cells_unknown_day_is_404_and_bad_day_is_422(client):
    r = client.get("/v1/cells?day=2030-01-01")
    assert r.status_code == 404 and r.json()["error"]["code"] == "day_not_in_release"
    for bad in ("2026-02-30", "20260110", "yesterday", "2026-1-1"):
        r = client.get("/v1/cells", params={"day": bad})
        assert r.status_code == 422, bad


def test_cells_slot_range_follows_the_grid(client):
    assert ok(client.get("/v1/cells?slot=7"))["count"] > 0
    r = client.get("/v1/cells?slot=8")  # 3 hour buckets: slots 0..7
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_slot"


def test_unknown_and_repeated_parameters_are_rejected(client):
    assert client.get("/v1/cells?colour=red").json()["error"]["code"] == "unknown_parameter"
    assert client.get("/v1/cells?slot=1&slot=2").json()["error"]["code"] == "repeated_parameter"


def test_bad_cursors_are_422(client):
    first = ok(client.get("/v1/cells?limit=5"))["next_cursor"]
    assert first
    for bad in ("!!!", "AAAA", "e30", first[:-6]):
        assert client.get("/v1/cells", params={"limit": 5, "cursor": bad}).status_code == 422, bad
    r = client.get("/v1/cells", params={"limit": 5, "cursor": first, "stratum": "high"})  # different filters
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_cursor"
    r = client.get("/v1/events", params={"cursor": first})  # cursor from another endpoint
    assert r.status_code == 422


# ---------------------------------------------------------------------- events, coverage
def test_events_list_and_filters(client):
    all_ev = ok(client.get("/v1/events"))["data"]
    assert [e["event_id"] for e in all_ev] == [f"synth-ev-{i:03d}" for i in range(1, 6)]
    assert isinstance(all_ev[0]["cells"], list) and len(all_ev[0]["cells"]) == 2
    assert all_ev[0]["start"] == "2026-01-10T03:00:00Z"
    kinds = lambda **p: [e["kind"] for e in ok(client.get("/v1/events", params=p))["data"]]  # noqa: E731
    assert kinds(kind="jamming_like") == ["jamming_like", "jamming_like"]
    assert kinds(kind="uncertain") == ["uncertain"]
    assert kinds(min_confidence="high") == ["jamming_like"]
    assert len(kinds(min_confidence="medium")) == 3
    assert len(kinds(uncertain="true")) == 2 and len(kinds(uncertain="false")) == 3


def test_events_time_window(client):
    ids = lambda **p: [e["event_id"] for e in ok(client.get("/v1/events", params=p))["data"]]  # noqa: E731
    assert ids(**{"from": "2026-01-11", "to": "2026-01-11"}) == ["synth-ev-003", "synth-ev-004", "synth-ev-005"]
    assert ids(**{"to": "2026-01-10"}) == ["synth-ev-001", "synth-ev-002"]
    assert ids(**{"from": "2026-01-10T14:00:00Z", "to": "2026-01-10T16:00:00Z"}) == ["synth-ev-002"]
    assert ids(**{"from": "2026-01-12"}) == []


def test_events_invalid_ranges_are_422(client):
    for p in ({"from": "2026-01-11", "to": "2026-01-10"}, {"from": "tomorrow"}, {"to": "2026-13-40"},
              {"from": "2026-01-10T00:00:00+04:00"}, {"kind": "arson"}, {"min_confidence": "certain"}, {"uncertain": "maybe"}):  # fmt: skip
        assert client.get("/v1/events", params=p).status_code == 422, p


def test_events_pagination(client):
    rows, pages = walk_pages(client, "/v1/events", limit=2)
    assert [e["event_id"] for e in rows] == [f"synth-ev-{i:03d}" for i in range(1, 6)] and pages == 3
    rows, _ = walk_pages(client, "/v1/events", limit=1, kind="jamming_like")
    assert len(rows) == 2


def test_event_by_id(client):
    e = ok(client.get("/v1/events/synth-ev-002"))["event"]
    assert e["kind"] == "spoofing_like" and e["cells"] == []
    r = client.get("/v1/events/synth-ev-999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "event_not_found"
    assert client.get("/v1/events/has space").status_code == 422


def test_coverage_filter_and_paging(client, rel):
    rows, pages = walk_pages(client, "/v1/coverage", slot=2, limit=4)
    assert len(rows) == len(rel.cells) and pages == 2 and all(r["slot"] == 2 for r in rows)
    assert client.get("/v1/coverage?slot=99").status_code == 422
    assert len(walk_pages(client, "/v1/coverage", limit=10)[0]) == len(rel.cells) * 8


# ---------------------------------------------------------------------- context
def ctx(client, place="dubai", t="2026-01-10T07:00:00Z", **extra):
    lat, lon = PLACES[place]
    return ok(client.get("/v1/context", params={"lat": lat, "lon": lon, "t": t, **extra}))


def test_context_ok_has_interval_and_event(client):
    c = ctx(client)  # dubai, slot 2 of day 0: ok row inside synthetic event 1
    assert c["schema"] == "tashwish.interference.v1" and c["status"] == "ok"
    rec = c["record"]
    assert rec["kind"] == "jamming_like" and rec["event_id"] == "synth-ev-001"
    assert 0 <= rec["ci_lo"] <= rec["p_interference"] <= rec["ci_hi"] <= 1


def test_context_synthetic_is_never_usable_as_prior(client):
    c = ctx(client)
    assert c["status"] == "ok" and c["usable_as_prior"] is False and "SYNTHETIC" in c["notice"]
    assert c["data_class"] == "synthetic" and "synthetic_notice" in c


def test_context_explicit_statuses_never_a_zero(client):
    seen = {}
    for place in PLACES:
        for slot in range(8):
            t = f"2026-01-10T{slot * 3:02d}:30:00Z"
            c = ctx(client, place, t)
            seen.setdefault(c["status"], c)
            if c["status"] != "ok":
                assert c["usable_as_prior"] is False
                rec = c["record"]
                assert rec["p_interference"] is None and rec["ci_lo"] is None and rec["ci_hi"] is None
                assert rec["kind"] in ("unknown", "jamming_like", "spoofing_like", "both") and rec["kind"] != "none"
                assert rec["data_quality"] == "poor"
    assert {"ok", "insufficient", "coverage_lost"} <= set(seen)
    assert "clear" in seen["insufficient"]["reason"] and "clear" in seen["coverage_lost"]["reason"]


def test_context_no_record_stale_and_out_of_region(client):
    c = ctx(client, t="2026-03-01T00:00:00Z")
    assert c["status"] == "no_record" and c["record"] is None and c["usable_as_prior"] is False
    c = ctx(client, t="2026-03-01T00:00:00Z", mode="nowcast")
    assert c["status"] == "stale" and c["record"] is not None and c["age_hours"] > 48
    assert c["record"]["p_interference"] is None or c["usable_as_prior"] is False
    c = ok(client.get("/v1/context", params={"lat": 51.5, "lon": -0.1, "t": "2026-01-10T07:00:00Z"}))
    assert c["status"] == "out_of_region" and c["record"] is None
    c = ctx(client, "dubai", t="2026-01-10T07:00:00Z", alt_ft=3000)  # low band: no rows exist
    assert c["status"] == "no_record"


def test_context_uncertain_event_is_unknown_not_clear(client):
    c = ctx(client, "bahrain", "2026-01-11T10:00:00Z")  # ok row overlapped only by an event of kind 'uncertain'
    assert c["status"] == "ok" and c["record"]["kind"] == "unknown" and c["record"]["event_id"] is None


def test_context_matches_reference_context_index(client, rel):
    cb = rel.cb.rename(
        columns={"h3": "cell", "bucket_start": "bucket", "share": "share_strong", "ci_lo": "ci_lo_strong", "ci_hi": "ci_hi_strong"}
    )  # fmt: skip
    events = rel.events[rel.events.kind.isin(marsad.EVENT_KINDS)]  # the reference rejects kind 'uncertain'
    fc = marsad.to_geojson(
        cb, events, dataset_version="synthetic-2026.01.11-test", data_class="synthetic", grid=GRID,
        generated_at=rel.generated_at, commit="test0000",
    )  # fmt: skip
    index = marsad.ContextIndex(fc)
    probes = 0
    for place, (lat, lon) in PLACES.items():
        if place == "bahrain":
            continue  # its event is 'uncertain', covered by its own test
        for t in ("2026-01-10T00:00:00Z", "2026-01-10T07:15:00Z", "2026-01-10T13:00:00Z", "2026-01-11T02:59:59Z",
                  "2026-01-11T17:00:00Z", "2026-01-12T05:00:00Z", "2025-12-01T00:00:00Z"):  # fmt: skip
            for alt in (None, 30000, 15000, 5000):
                for mode in ("retrospective", "nowcast"):
                    want = index.query(lat, lon, t, alt, mode=mode)
                    got = ctx(client, place, t, mode=mode, **({} if alt is None else {"alt_ft": alt}))
                    assert got["status"] == want["status"], (place, t, alt, mode)
                    assert got["record"] == want["record"], (place, t, alt, mode)
                    assert got["reason"] == want["reason"] or got["status"] == "ok"
                    if want["age_hours"] is None:
                        assert got["age_hours"] is None
                    else:
                        assert got["age_hours"] == pytest.approx(want["age_hours"])
                    assert got["usable_as_prior"] is False  # only difference: synthetic is never usable
                    probes += 1
    out = index.query(51.5, -0.1, "2026-01-10T00:00:00Z")
    assert out["status"] == "out_of_region"
    assert probes == 280


def test_context_input_validation(client):
    base = {"lat": 25.2, "lon": 55.3, "t": "2026-01-10T07:00:00Z"}
    bad = [
        {"lat": 91}, {"lat": -91}, {"lon": 181}, {"lat": "abc"}, {"lat": "nan"}, {"lon": "inf"},
        {"t": "2026-01-10T07:00:00"}, {"t": "2026-01-10T07:00:00+00:00"}, {"t": "2026-13-10T07:00:00Z"},
        {"t": "2026-01-10"}, {"mode": "forecast"}, {"alt_ft": "nan"}, {"alt_ft": 1e9}, {"alt_ft": "high"},
    ]  # fmt: skip
    for patch in bad:
        r = client.get("/v1/context", params={**base, **patch})
        assert r.status_code == 422, patch
        assert r.json()["error"]["code"] in ("invalid_request", "invalid_t")
    for missing in base:
        assert client.get("/v1/context", params={k: v for k, v in base.items() if k != missing}).status_code == 422


# ---------------------------------------------------------------------- read only, injection, limits
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize(
    "url", ["/health", "/v1/cells", "/v1/events/synth-ev-001", "/v1/context", "/v1/download/NOTICE"]
)
def test_write_methods_return_405(client, method, url):
    r = getattr(client, method)(url)
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "method_not_allowed"
    assert r.headers["X-Attribution"] == DATASET_ATTRIBUTION


def test_release_directory_is_not_modified_by_serving(rel):
    def snapshot():
        return {p.name: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in rel.path.iterdir()}

    before = snapshot()
    c = TestClient(create_app(rel.path))
    for url in GET_URLS:
        c.get(url)
    assert snapshot() == before


INJECTIONS = [
    "'; DROP TABLE events; --",
    "' OR '1'='1",
    "1; SELECT * FROM cell_buckets",
    '" OR ""="',
    "%27%20OR%201%3D1--",
    "\\x00",
]


def test_sql_injection_attempts_are_422_or_empty_never_500(client, rel):
    for evil in INJECTIONS:
        for url, param in (
            ("/v1/cells", "day"), ("/v1/cells", "slot"), ("/v1/cells", "stratum"), ("/v1/cells", "status"),
            ("/v1/cells", "cursor"), ("/v1/cells", "limit"), ("/v1/events", "from"), ("/v1/events", "to"),
            ("/v1/events", "kind"), ("/v1/events", "min_confidence"), ("/v1/events", "uncertain"),
            ("/v1/events", "cursor"), ("/v1/coverage", "slot"), ("/v1/coverage", "cursor"),
            ("/v1/context", "lat"), ("/v1/context", "t"), ("/v1/context", "mode"),
        ):  # fmt: skip
            r = client.get(url, params={param: evil})
            assert r.status_code in (404, 422), (url, param, evil, r.status_code)
    for evil in INJECTIONS:
        for path in ("/v1/events/", "/v1/download/"):
            r = client.get(path + evil)
            assert r.status_code in (404, 405, 422), (path, evil, r.status_code)
    assert ok(client.get("/v1/events"))["count"] == 5  # tables intact
    assert ok(client.get("/v1/cells?limit=5000"))["count"] == len(rel.cb)


def test_sql_in_free_text_values_that_reach_sql_is_treated_as_data(client):
    # event_id has a strict pattern, so a quote can never reach SQL; an id that merely looks odd is a clean 404
    assert client.get("/v1/events/synth-ev-001'--").status_code == 422
    assert client.get("/v1/events/x.OR.1.1").status_code == 404


def test_oversized_query_string_is_414(client):
    r = client.get("/v1/cells?cursor=" + "A" * 3000)
    assert r.status_code == 414 and r.json()["error"]["code"] == "query_too_long"


def test_rate_limiter_returns_429_with_retry_after_and_exempts_health(rel):
    c = TestClient(create_app(rel.path, rate_limit_per_minute=3))
    assert [c.get("/v1/days").status_code for _ in range(3)] == [200, 200, 200]
    r = c.get("/v1/days")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert r.headers["X-Attribution"] == DATASET_ATTRIBUTION
    assert c.get("/health").status_code == 200


def test_rate_limiter_ignores_spoofed_forwarded_header_by_default(rel, monkeypatch):
    monkeypatch.delenv("TASHWISH_TRUSTED_PROXY_HOPS", raising=False)
    c = TestClient(create_app(rel.path, rate_limit_per_minute=2))
    codes = [c.get("/v1/days", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(4)]
    assert codes == [200, 200, 429, 429]


def test_rate_limiter_uses_trusted_hop_when_configured(rel, monkeypatch):
    monkeypatch.setenv("TASHWISH_TRUSTED_PROXY_HOPS", "1")
    c = TestClient(create_app(rel.path, rate_limit_per_minute=1))
    # the rightmost entry is the one the trusted proxy appended; the leftmost is client controlled
    assert c.get("/v1/days", headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}).status_code == 200
    assert c.get("/v1/days", headers={"X-Forwarded-For": "2.2.2.2, 9.9.9.9"}).status_code == 429
    assert c.get("/v1/days", headers={"X-Forwarded-For": "2.2.2.2, 8.8.8.8"}).status_code == 200


def test_rate_limiter_key_store_is_bounded_and_flood_does_not_reset_others():
    from tashwish.api.app import _RateLimiter

    lim = _RateLimiter(2, max_keys=50)
    assert lim.check("victim") is None and lim.check("victim") is None
    assert lim.check("victim") is not None
    for i in range(30):  # fewer new keys than the bound: the victim stays limited
        lim.check(f"flood{i}")
    assert lim.check("victim") is not None
    for i in range(500):
        lim.check(f"flood-more{i}")
    assert len(lim._hits) <= 50


def test_etag_includes_manifest_checksums(rel, tmp_path):
    import shutil

    other = tmp_path / "rel2"
    shutil.copytree(rel.path, other)
    m = json.loads((other / "manifest.json").read_text(encoding="utf-8"))
    m["files"]["checksums.sha256"]["sha256"] = "0" * 64  # same dataset_version, different content hash
    (other / "manifest.json").write_text(json.dumps(m), encoding="utf-8", newline="\n")
    e1 = TestClient(create_app(rel.path, rate_limit_per_minute=0)).get("/v1/days").headers["ETag"]
    e2 = TestClient(create_app(other, rate_limit_per_minute=0)).get("/v1/days").headers["ETag"]
    assert e1 != e2


def test_download_and_304_responses_carry_attribution(client):
    r = client.get("/v1/download/NOTICE")
    assert r.status_code == 200 and r.headers["X-Attribution"] == DATASET_ATTRIBUTION
    first = client.get("/v1/days")
    r304 = client.get("/v1/days", headers={"If-None-Match": first.headers["ETag"]})
    assert r304.status_code == 304 and r304.headers["X-Attribution"] == DATASET_ATTRIBUTION
    miss = client.get("/v1/download/not_listed.bin")
    assert miss.status_code == 404 and miss.headers["X-Attribution"] == DATASET_ATTRIBUTION


def test_unhandled_error_is_a_clean_500_with_headers(rel, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(q, "query_cells", boom)
    r = TestClient(create_app(rel.path), raise_server_exceptions=False).get("/v1/cells")
    assert r.status_code == 500 and "secret" not in r.text
    assert r.json()["error"]["code"] == "internal_error" and r.headers["X-Attribution"] == DATASET_ATTRIBUTION


# ---------------------------------------------------------------------- caching and CORS
def test_etag_and_conditional_get(client):
    r1 = client.get("/v1/cells?limit=3")
    etag = r1.headers["ETag"]
    assert etag and "max-age" in r1.headers["Cache-Control"]
    r2 = client.get("/v1/cells?limit=3", headers={"If-None-Match": etag})
    assert r2.status_code == 304 and r2.content == b"" and r2.headers["ETag"] == etag
    assert r2.headers["X-Attribution"] == DATASET_ATTRIBUTION
    assert client.get("/v1/cells?limit=4").headers["ETag"] != etag


def test_immutable_when_pinned_to_dataset_version_and_conflict_otherwise(client):
    v = "synthetic-2026.01.11-test"
    assert client.get("/v1/days", params={"dataset_version": v}).headers["Cache-Control"].endswith("immutable")
    assert "immutable" not in client.get("/v1/days").headers["Cache-Control"]
    r = client.get("/v1/days", params={"dataset_version": "other"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "dataset_version_mismatch"
    assert r.headers["Cache-Control"] == "no-store"


def test_health_and_freshness_are_not_cached(client):
    assert client.get("/health").headers["Cache-Control"] == "no-cache"
    assert client.get("/v1/freshness").headers["Cache-Control"] == "no-cache"
    assert "ETag" not in client.get("/health").headers


def test_cors_allows_get_only(client):
    r = client.get("/v1/days", headers={"Origin": "https://example.org"})
    assert r.headers["access-control-allow-origin"] == "*"
    assert "X-Attribution" in r.headers["access-control-expose-headers"]
    pre = client.options("/v1/days", headers={"Origin": "https://example.org", "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 400 and "POST" not in pre.headers.get("access-control-allow-methods", "")
    ok_pre = client.options(
        "/v1/days", headers={"Origin": "https://example.org", "Access-Control-Request-Method": "GET"}
    )
    assert ok_pre.status_code == 200 and ok_pre.headers["access-control-allow-methods"] == "GET"


# ---------------------------------------------------------------------- downloads
def test_download_streams_every_listed_file_intact(client, rel):
    files = ok(client.get("/v1/manifest"))["manifest"]["files"]
    assert {"cell_buckets.parquet", "events.parquet", "NOTICE", "checksums.sha256"} <= set(files)
    for name, info in files.items():
        r = client.get(f"/v1/download/{name}")
        assert r.status_code == 200, name
        assert hashlib.sha256(r.content).hexdigest() == info["sha256"] == r.headers["X-Content-SHA256"]
        assert int(r.headers["Content-Length"]) == info["bytes"] == len(r.content)
        assert r.headers["X-Attribution"] == DATASET_ATTRIBUTION
        assert name in r.headers["Content-Disposition"]
    assert (
        client.get("/v1/download/cell_buckets.parquet")
        .headers["content-type"]
        .startswith("application/vnd.apache.parquet")
    )


def test_download_refuses_unlisted_and_traversal(client):
    assert client.get("/v1/download/manifest.json").status_code == 404
    assert client.get("/v1/download/secret.txt").status_code == 404
    for bad in ("..%2Fmanifest.json", "%2e%2e%2fetc%2fpasswd", "a%2Fb", "x" * 200):
        assert client.get(f"/v1/download/{bad}").status_code in (404, 422), bad


# ---------------------------------------------------------------------- openapi, release validation, packaging
def test_openapi_metadata(client):
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "Tashwish release API"
    assert (
        "Research and monitoring tool, not for navigation or safety of life, no attribution to any actor"
        in spec["info"]["description"]
    )
    assert "ODbL" in spec["info"]["description"] and "Apache-2.0" in spec["info"]["description"]
    assert "Apache-2.0" in spec["info"]["license"]["name"] and "ODbL" in spec["info"]["license"]["name"]
    assert {"/health", "/v1/cells", "/v1/events", "/v1/context", "/v1/download/{name}"} <= set(spec["paths"])
    assert all(set(ops) == {"get"} for ops in spec["paths"].values())  # no write operation is documented


def test_startup_refuses_missing_or_inconsistent_releases(tmp_path):
    with pytest.raises(ReleaseError, match="manifest.json not found"):
        create_app(tmp_path / "nowhere")
    r = build_synthetic_release(tmp_path / "a")
    m = json.loads((r.path / "manifest.json").read_text(encoding="utf-8"))
    (r.path / "manifest.json").write_text(json.dumps({**m, "attribution": "mine"}), encoding="utf-8", newline="\n")
    with pytest.raises(ReleaseError, match="attribution"):
        create_app(r.path)
    (r.path / "manifest.json").write_text(
        json.dumps({**m, "data_class": "observed"}), encoding="utf-8", newline="\n"
    )  # rows say synthetic
    with pytest.raises(ReleaseError, match="refusing to mix"):
        create_app(r.path)
    (r.path / "manifest.json").write_text(
        json.dumps({**m, "schema": "tashwish.release.v0"}), encoding="utf-8", newline="\n"
    )
    with pytest.raises(ReleaseError, match="schema"):
        create_app(r.path)


def test_startup_refuses_missing_columns_and_tampered_files(tmp_path):
    import pandas as pd

    r = build_synthetic_release(tmp_path)
    pd.read_parquet(r.path / "coverage.parquet").drop(columns=["presence"]).to_parquet(r.path / "coverage.parquet")
    with pytest.raises(ReleaseError):  # size differs from manifest first
        create_app(r.path)
    r2 = build_synthetic_release(tmp_path / "b")
    p = r2.path / "NOTICE"
    p.write_text(
        p.read_text(encoding="utf-8").replace("a", "b", 1), encoding="utf-8", newline="\n"
    )  # same size, different bytes
    with pytest.raises(ReleaseError, match="sha256"):
        create_app(r2.path, verify_hashes=True)
    assert create_app(r2.path, verify_hashes=False) is not None  # hashing is opt in (cold start cost)


def test_new_manifest_is_picked_up_without_restart(tmp_path):
    r = build_synthetic_release(tmp_path)
    c = TestClient(create_app(r.path))
    assert ok(c.get("/health"))["dataset_version"] == "synthetic-2026.01.11-test"
    m = json.loads((r.path / "manifest.json").read_text(encoding="utf-8"))
    (r.path / "manifest.json").write_text(
        json.dumps({**m, "dataset_version": "synthetic-v2-test"}), encoding="utf-8", newline="\n"
    )
    os.utime(r.path / "manifest.json", ns=(1, 2_000_000_000_000_000_000))
    assert ok(c.get("/health"))["dataset_version"] == "synthetic-v2-test"
    assert c.get("/v1/days").headers["X-Dataset-Version"] == "synthetic-v2-test"


def test_import_of_api_package_does_not_need_fastapi():
    code = "import sys; import tashwish.api; sys.exit(1 if 'fastapi' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_pyproject_api_extra_lists_runtime_and_test_deps():
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if x.startswith("api = "))
    for dep in ("fastapi", "uvicorn", "httpx"):
        assert dep in line
