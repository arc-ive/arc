"""Rate-limit middleware for Arc.

Applies per-IP sliding-window rate limiting to auth endpoints and
webhook ingestion. Non-matching paths pass through unconditionally.

Configuration is via environment variables (same pattern as CSRFMiddleware).
Defaults are permissive for development; production should tighten them.

Auth endpoints protected:
  GET /auth/google        (login redirect)
  GET /auth/callback      (OAuth callback)
  POST /auth/logout       (single session)
  POST /auth/logout-all   (all sessions)

Webhook ingestion protected:
  POST /webhooks/{endpoint_id}/events

Development-only endpoints (e.g. POST /internal/dev/auth/login) are NOT
rate-limited: they are mounted only when APP_ENV=development and never
exist in production.

Client identity is request.client.host (the direct TCP peer). Forwarding
headers such as X-Forwarded-For are deliberately ignored: the repository
has no trusted reverse-proxy configuration, so client-controlled headers
must not select rate-limit buckets.

State is process-local: each worker keeps independent buckets. The current
single-worker deployment accepts this model (V2-ADR-026: no external
infrastructure); this is not a distributed limiter.
"""

import logging
import os
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from arc.security.rate_limit import RateLimitConfig, SlidingWindowLimiter

logger = logging.getLogger("arc.rate_limit")

# Default limits (safe for production, generous for dev)
_DEFAULT_AUTH_MAX = 30
_DEFAULT_AUTH_WINDOW = 60
_DEFAULT_WEBHOOK_MAX = 100
_DEFAULT_WEBHOOK_WINDOW = 60


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default


# Paths matched by startswith — order matters for /auth/ prefix
_AUTH_PREFIXES = ("/auth/",)
_AUTH_EXACT = frozenset({"/auth/google", "/auth/callback", "/auth/logout", "/auth/logout-all"})
_WEBHOOK_PREFIX = "/webhooks/"


def _is_rate_limited_path(path: str) -> bool:
    """Return True if path should be rate-limited."""
    if path in _AUTH_EXACT:
        return True
    for prefix in _AUTH_PREFIXES:
        if path.startswith(prefix):
            return False
    if path.startswith(_WEBHOOK_PREFIX) and path.endswith("/events"):
        return True
    return False


def _rate_limit_category(path: str) -> str:
    """Return 'auth' or 'webhook'."""
    if path.startswith(_WEBHOOK_PREFIX):
        return "webhook"
    return "auth"


def _client_ip(request: Request) -> str:
    """Return the direct peer IP used for rate-limit bucketing.

    Forwarding headers (X-Forwarded-For, X-Real-IP, Forwarded) are
    deliberately ignored: they are client-controlled and the repository
    has no trusted-proxy configuration, so trusting them would let any
    sender mint fresh rate-limit buckets and bypass the limiter.
    """
    if request.client:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding-window rate limiter on auth and webhook endpoints."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self._auth_limiter = SlidingWindowLimiter(
            config=RateLimitConfig(
                max_requests=_env_int("RATE_LIMIT_AUTH_MAX", _DEFAULT_AUTH_MAX),
                window_seconds=_env_int("RATE_LIMIT_AUTH_WINDOW", _DEFAULT_AUTH_WINDOW),
            )
        )
        self._webhook_limiter = SlidingWindowLimiter(
            config=RateLimitConfig(
                max_requests=_env_int("RATE_LIMIT_WEBHOOK_MAX", _DEFAULT_WEBHOOK_MAX),
                window_seconds=_env_int("RATE_LIMIT_WEBHOOK_WINDOW", _DEFAULT_WEBHOOK_WINDOW),
            )
        )
        self._skip = os.getenv("RATE_LIMIT_ENABLED", "1") == "0"
        logger.info(
            "rate_limit_init auth_max=%d auth_window=%d webhook_max=%d "
            "webhook_window=%d enabled=%s",
            self._auth_limiter.config.max_requests,
            self._auth_limiter.config.window_seconds,
            self._webhook_limiter.config.max_requests,
            self._webhook_limiter.config.window_seconds,
            not self._skip,
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self._skip:
            return await call_next(request)

        path = request.url.path
        if not _is_rate_limited_path(path):
            return await call_next(request)

        category = _rate_limit_category(path)
        ip = _client_ip(request)
        key = f"{category}:{ip}"

        limiter = self._auth_limiter if category == "auth" else self._webhook_limiter
        allowed, remaining_or_retry = await limiter.allow(key)

        if not allowed:
            retry_after = remaining_or_retry
            logger.warning(
                "rate_limit_rejected category=%s ip=%s path=%s retry_after=%d",
                category,
                ip,
                path,
                retry_after,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limiter.config.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Window": str(limiter.config.window_seconds),
                },
            )

        response = await call_next(request)
        remaining = remaining_or_retry
        response.headers["X-RateLimit-Limit"] = str(limiter.config.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Window"] = str(limiter.config.window_seconds)
        return response
