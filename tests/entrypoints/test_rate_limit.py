"""Tests for the per-IP sliding-window rate-limit ASGI middleware."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pricor.entrypoints.rate_limit import (
    DEFAULT_GENERAL_RPM,
    DEFAULT_HEAVY_RPM,
    RateLimitConfig,
    RateLimitMiddleware,
    classify_request,
    extract_client_ip,
)


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_app(
    *,
    general_rpm: int = 5,
    heavy_rpm: int = 2,
    window_seconds: float = 60.0,
    trusted_proxies: int = 1,
    max_keys: int = 10_000,
    clock: FakeClock | None = None,
) -> tuple[TestClient, FakeClock]:
    tick = clock or FakeClock()
    inner = FastAPI()

    @inner.get("/")
    def index():
        return {"page": "home"}

    @inner.get("/config")
    def config():
        return {"demo": True}

    @inner.get("/samples")
    def samples():
        return {"samples": []}

    @inner.get("/health")
    def health():
        return {"ok": True}

    @inner.get("/workspace")
    def workspace():
        return {"link": "http://test/#w=abc"}

    @inner.get("/workspace/current")
    def workspace_current():
        return {"link": "http://test/#w=abc"}

    @inner.post("/workspace/claim")
    def workspace_claim():
        return {"link": "http://test/#w=abc"}

    @inner.post("/events", status_code=204)
    def events():
        return None

    @inner.post("/warm-up")
    def warm_up():
        return {"models": "ready"}

    @inner.post("/imports", status_code=201)
    def create_import():
        return {"id": "s1"}

    @inner.get("/imports/{session_id}/preview")
    def preview(session_id: str):
        return {"id": session_id}

    @inner.post("/imports/{session_id}/questions/{qid}/ask")
    def ask(session_id: str, qid: str):
        return {"reply": "ok"}

    @inner.post("/imports/combined-export")
    def combined_export():
        return {"ok": True}

    @inner.post("/imports/{session_id}/fx/refresh")
    def fx_refresh(session_id: str):
        return {"ok": True}

    @inner.post("/output-format", status_code=201)
    def upload_format():
        return {"ok": True}

    @inner.post("/sheets")
    def sheets():
        return {"sheets": ["Sheet1"]}

    @inner.post("/memories", status_code=201)
    def memories():
        return {"id": "m1"}

    wrapped = RateLimitMiddleware(
        inner,
        RateLimitConfig(
            general_rpm=general_rpm,
            heavy_rpm=heavy_rpm,
            window_seconds=window_seconds,
            trusted_proxies=trusted_proxies,
            max_keys=max_keys,
        ),
        clock=tick,
    )
    return TestClient(wrapped, raise_server_exceptions=False), tick


# -- route classification ---------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/", None),
        ("GET", "/assets/app.js", None),
        ("GET", "/config", None),
        ("GET", "/samples", None),
        ("GET", "/samples/demo", None),
        ("GET", "/health", None),
        ("GET", "/api/health", None),
        ("GET", "/docs", None),
        ("OPTIONS", "/imports", None),
        ("POST", "/imports", "heavy"),
        ("POST", "/imports/", "heavy"),
        ("POST", "//imports///", "heavy"),
        ("POST", "/imports/combined-export", "heavy"),
        ("POST", "/imports/s1/questions/q1/ask", "heavy"),
        ("POST", "/imports/s1/fx/refresh", "heavy"),
        ("PUT", "/imports/s1/header", "heavy"),
        ("POST", "/output-format", "heavy"),
        ("POST", "/sheets", "heavy"),
        ("POST", "/memories", "heavy"),
        ("PATCH", "/memories/m1", "heavy"),
        ("POST", "/warm-up", "heavy"),
        ("GET", "/workspace", "heavy"),
        ("POST", "/workspace/claim", "heavy"),
        ("POST", "/workspace/google", "heavy"),
        ("DELETE", "/workspace/google", "heavy"),
        ("POST", "/events", "general"),
        ("POST", "/events/", "general"),
        ("POST", "//events/", "general"),
        ("GET", "/workspace/current", "general"),
        ("GET", "/imports/s1", "general"),
        ("GET", "/imports/s1/preview", "general"),
        ("POST", "/imports/s1/answers", "general"),
        ("POST", "/imports/s1/approve", "general"),
        ("GET", "/output-format", "general"),
        ("GET", "/memories", "general"),
    ],
)
def test_route_classification(method, path, expected):
    assert classify_request(method, path) == expected


# -- client IP extraction ---------------------------------------------------------


def _scope(client_ip: str | None = "10.0.0.1", headers: list[tuple[bytes, bytes]] | None = None):
    return {
        "type": "http",
        "method": "POST",
        "path": "/events",
        "headers": headers or [],
        "client": (client_ip, 12345) if client_ip is not None else None,
    }


def test_extract_client_ip_uses_rightmost_forwarded_ip_for_single_trusted_proxy():
    scope = _scope(
        client_ip="169.254.1.1",
        headers=[(b"x-forwarded-for", b"1.2.3.4, 203.0.113.9")],
    )
    # Spoofed leftmost IP 1.2.3.4 is ignored; Cloud Run appended 203.0.113.9.
    assert extract_client_ip(scope, trusted_proxies=1) == "203.0.113.9"


def test_extract_client_ip_combines_multiple_forwarded_headers_in_order():
    scope = _scope(
        client_ip="169.254.1.1",
        headers=[
            (b"x-forwarded-for", b"1.2.3.4"),
            (b"x-forwarded-for", b"198.51.100.7"),
        ],
    )
    assert extract_client_ip(scope, trusted_proxies=1) == "198.51.100.7"


def test_extract_client_ip_supports_multiple_trusted_proxies():
    scope = _scope(
        client_ip="10.0.0.5",
        headers=[(b"x-forwarded-for", b"1.1.1.1, 203.0.113.42, 34.120.0.1")],
    )
    assert extract_client_ip(scope, trusted_proxies=2) == "203.0.113.42"


def test_extract_client_ip_ignores_forwarded_header_when_trusted_proxies_is_zero():
    scope = _scope(
        client_ip="192.0.2.10",
        headers=[(b"x-forwarded-for", b"1.2.3.4")],
    )
    assert extract_client_ip(scope, trusted_proxies=0) == "192.0.2.10"


def test_extract_client_ip_falls_back_to_client_host_when_header_missing_or_blank():
    assert extract_client_ip(_scope(client_ip="192.0.2.55"), trusted_proxies=1) == "192.0.2.55"
    assert (
        extract_client_ip(
            _scope(client_ip="192.0.2.55", headers=[(b"x-forwarded-for", b" , ")]),
            trusted_proxies=1,
        )
        == "192.0.2.55"
    )
    assert extract_client_ip(_scope(client_ip=None), trusted_proxies=1) == "unknown"


# -- rate limiting behavior -------------------------------------------------------


def test_exempt_paths_are_never_rate_limited():
    client, _ = make_app(general_rpm=1, heavy_rpm=1)
    for _ in range(10):
        assert client.get("/").status_code == 200
        assert client.get("/config").status_code == 200
        assert client.get("/samples").status_code == 200
        assert client.get("/health").status_code == 200


def test_general_bucket_limits_events_and_returns_standard_429_envelope():
    client, clock = make_app(general_rpm=2, heavy_rpm=1, window_seconds=60.0)
    headers = {"x-forwarded-for": "203.0.113.10"}

    assert client.post("/events", headers=headers).status_code == 204
    clock.advance(10.0)
    assert client.post("/events", headers=headers).status_code == 204
    clock.advance(5.0)

    blocked = client.post("/events", headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers["cache-control"] == "no-store"
    assert int(blocked.headers["retry-after"]) == 45
    assert blocked.json() == {
        "error": {
            "code": "rate_limited",
            "message": "too many requests; please wait a moment and try again",
        }
    }

    # Once the oldest request expires from the 60s window, traffic resumes.
    clock.advance(45.0)
    assert client.post("/events", headers=headers).status_code == 204


def test_heavy_bucket_limits_imports_and_warm_up_separately_from_general():
    client, _ = make_app(general_rpm=5, heavy_rpm=2)
    headers = {"x-forwarded-for": "203.0.113.20"}

    assert client.post("/imports", headers=headers).status_code == 201
    assert client.post("/warm-up", headers=headers).status_code == 200
    assert client.post("/imports", headers=headers).status_code == 429
    assert client.post("/warm-up", headers=headers).status_code == 429
    assert client.post("/imports/", headers=headers).status_code == 429

    # General bucket is still available for the same IP.
    assert client.post("/events", headers=headers).status_code == 204
    assert client.get("/imports/s1/preview", headers=headers).status_code == 200


def test_different_ips_have_independent_buckets_and_spoofed_prefix_cannot_bypass():
    client, _ = make_app(general_rpm=1, heavy_rpm=1, trusted_proxies=1)

    # First IP exhausts its quota.
    assert client.post("/imports", headers={"x-forwarded-for": "1.1.1.1, 203.0.113.1"}).status_code == 201
    # Spoofing a different leftmost IP while Cloud Run appends the same real IP still blocks.
    assert client.post("/imports", headers={"x-forwarded-for": "9.9.9.9, 203.0.113.1"}).status_code == 429
    # A different real IP is unaffected.
    assert client.post("/imports", headers={"x-forwarded-for": "9.9.9.9, 203.0.113.2"}).status_code == 201


def test_max_keys_bounds_memory_under_many_distinct_ips():
    clock = FakeClock()
    inner = FastAPI()

    @inner.post("/events", status_code=204)
    def events():
        return None

    middleware = RateLimitMiddleware(
        inner,
        RateLimitConfig(general_rpm=2, heavy_rpm=1, max_keys=5),
        clock=clock,
    )
    client = TestClient(middleware, raise_server_exceptions=False)

    for i in range(20):
        assert client.post("/events", headers={"x-forwarded-for": f"198.51.100.{i}"}).status_code == 204

    assert middleware.tracked_keys <= 5


def test_rate_limiter_is_thread_safe_under_concurrent_requests():
    client, _ = make_app(general_rpm=50, heavy_rpm=5)
    barrier = threading.Barrier(12)

    def hit(_: int) -> int:
        barrier.wait()
        return client.post("/imports", headers={"x-forwarded-for": "203.0.113.77"}).status_code

    with ThreadPoolExecutor(max_workers=12) as pool:
        statuses = list(pool.map(hit, range(12)))

    assert statuses.count(201) == 5
    assert statuses.count(429) == 7


def test_defaults_are_generous_for_multi_file_testers():
    assert DEFAULT_GENERAL_RPM >= 60
    assert DEFAULT_HEAVY_RPM >= 20


def test_rate_limit_log_omits_client_ip_and_cookie(caplog):
    client, _ = make_app(general_rpm=1, heavy_rpm=1)
    headers = {"x-forwarded-for": "203.0.113.99", "cookie": "pricor_workspace=secret_token_123"}

    assert client.post("/events", headers=headers).status_code == 204
    with caplog.at_level("WARNING", logger="pricor.entrypoints.rate_limit"):
        assert client.post("/events", headers=headers).status_code == 429

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "bucket=general" in message
    assert "prefix=/events" in message
    assert "203.0.113.99" not in message
    assert "secret_token_123" not in message


def test_lifespan_scope_passes_through_without_rate_limiting():
    client, _ = make_app(general_rpm=1, heavy_rpm=1)
    # Using TestClient as a context manager triggers ASGI lifespan startup & shutdown.
    with client:
        assert client.get("/health").status_code == 200

