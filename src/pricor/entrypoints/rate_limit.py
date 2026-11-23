"""Lightweight per-IP sliding-window rate limiter for hosted demo deployments.

Enabled by default when private workspaces are active (`PRICOR_WORKSPACES_DIR`), and off in
local single-database mode unless configured explicitly. Keeps bounded in-memory state per
client IP and returns Pricor's standard JSON error envelope on `429 Too Many Requests`.
"""

import logging
import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

DEFAULT_GENERAL_RPM = 120
DEFAULT_HEAVY_RPM = 30
DEFAULT_WINDOW_SECONDS = 60.0
DEFAULT_MAX_KEYS = 10_000

Bucket = Literal["heavy", "general"]

_RATE_LIMITED_PREFIXES = frozenset(
    {"imports", "output-format", "sheets", "memories", "workspace", "events", "warm-up"}
)
_HEAVY_POST_ROOTS = frozenset({"output-format", "sheets", "memories", "warm-up"})


@dataclass(frozen=True)
class RateLimitConfig:
    general_rpm: int = DEFAULT_GENERAL_RPM
    heavy_rpm: int = DEFAULT_HEAVY_RPM
    window_seconds: float = DEFAULT_WINDOW_SECONDS
    trusted_proxies: int = 1
    max_keys: int = DEFAULT_MAX_KEYS

    def __post_init__(self) -> None:
        if self.general_rpm < 1:
            raise ValueError("general_rpm must be at least 1")
        if self.heavy_rpm < 1:
            raise ValueError("heavy_rpm must be at least 1")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if self.trusted_proxies < 0:
            raise ValueError("trusted_proxies must be non-negative")
        if self.max_keys < 1:
            raise ValueError("max_keys must be at least 1")


def classify_request(method: str, path: str) -> Bucket | None:
    """Return the rate-limit bucket for an HTTP request, or None when exempt."""
    verb = method.upper()
    if verb == "OPTIONS":
        return None
    segments = [part for part in path.split("/") if part]
    if not segments:
        return None
    first = segments[0]
    if first not in _RATE_LIMITED_PREFIXES:
        return None

    if verb == "POST":
        if first == "imports" and (
            len(segments) == 1
            or (len(segments) == 2 and segments[1] == "combined-export")
            or (len(segments) == 5 and segments[2] == "questions" and segments[4] == "ask")
            or (len(segments) == 4 and segments[2] == "fx" and segments[3] == "refresh")
        ):
            return "heavy"
        if first in _HEAVY_POST_ROOTS and len(segments) == 1:
            return "heavy"
        if segments in (["workspace", "claim"], ["workspace", "google"]):
            return "heavy"
    elif verb == "DELETE" and segments == ["workspace", "google"]:
        return "heavy"
    elif verb == "PUT" and first == "imports" and len(segments) == 3 and segments[2] == "header":
        return "heavy"
    elif verb == "PATCH" and first == "memories" and len(segments) == 2:
        return "heavy"
    elif verb == "GET" and segments == ["workspace"]:
        return "heavy"

    return "general"


def extract_client_ip(scope: Scope, *, trusted_proxies: int) -> str:
    """Identify the caller IP, taking the trusted-proxy hop from the right of X-Forwarded-For."""
    if trusted_proxies > 0:
        forwarded: list[str] = []
        for name, value in scope.get("headers") or ():
            if name.lower() == b"x-forwarded-for":
                for raw in value.decode("latin-1").split(","):
                    part = raw.strip()
                    if part:
                        forwarded.append(part)
        if forwarded:
            index = -trusted_proxies if len(forwarded) >= trusted_proxies else 0
            return forwarded[index].lower()

    client = scope.get("client")
    if client and client[0]:
        return str(client[0]).strip().lower()
    return "unknown"


def _rate_limited_response(retry_after: int) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": "rate_limited",
                "message": "too many requests; please wait a moment and try again",
            }
        },
        status_code=429,
        headers={
            "Retry-After": str(retry_after),
            "Cache-Control": "no-store",
        },
    )


class RateLimitMiddleware:
    """Thread-safe, bounded-memory sliding-window ASGI rate limiter."""

    def __init__(
        self,
        app: ASGIApp,
        config: RateLimitConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.config = config or RateLimitConfig()
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: OrderedDict[tuple[Bucket, str], deque[float]] = OrderedDict()

    @property
    def tracked_keys(self) -> int:
        with self._lock:
            return len(self._buckets)

    def _check(self, bucket: Bucket, ip: str) -> int | None:
        window = self.config.window_seconds
        limit = self.config.heavy_rpm if bucket == "heavy" else self.config.general_rpm
        key = (bucket, ip)

        with self._lock:
            now = self._clock()
            timestamps = self._buckets.get(key)
            if timestamps is not None:
                while timestamps and now - timestamps[0] >= window:
                    timestamps.popleft()
                self._buckets.move_to_end(key)
                if len(timestamps) >= limit:
                    remaining = window - (now - timestamps[0])
                    return max(1, math.ceil(remaining))
            else:
                if len(self._buckets) >= self.config.max_keys:
                    self._prune_expired_locked(now, window)
                    while len(self._buckets) >= self.config.max_keys:
                        self._buckets.popitem(last=False)
                timestamps = deque()
                self._buckets[key] = timestamps

            timestamps.append(now)
            return None

    def _prune_expired_locked(self, now: float, window: float) -> None:
        expired = [key for key, dq in self._buckets.items() if not dq or now - dq[-1] >= window]
        for key in expired:
            del self._buckets[key]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "/")
        bucket = classify_request(method, path)
        if bucket is None:
            await self.app(scope, receive, send)
            return

        ip = extract_client_ip(scope, trusted_proxies=self.config.trusted_proxies)
        retry_after = self._check(bucket, ip)
        if retry_after is not None:
            prefix = next((part for part in path.split("/") if part), "")
            logger.warning(
                "rate limit exceeded bucket=%s method=%s prefix=/%s", bucket, method.upper(), prefix
            )
            await _rate_limited_response(retry_after)(scope, receive, send)
            return

        await self.app(scope, receive, send)
