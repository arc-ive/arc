"""Rate limiter tests.

Tests the sliding-window rate limiter core and the FastAPI middleware
integration. Covers:
- sliding window correctness (allow/deny cycle, window rollover)
- concurrent requests capped at the limit (atomic check-and-append)
- non-positive limit fail-closed behavior
- path matching for auth vs webhook endpoints
- 429 response format and headers
- X-RateLimit-* headers on allowed requests
- RATE_LIMIT_ENABLED=0 bypass
- per-key isolation
- X-Forwarded-For spoof resistance (client-controlled headers ignored)
- real production auth router behind the middleware
"""

import asyncio
import os
import time
from unittest.mock import MagicMock

from fastapi import FastAPI
from starlette.testclient import TestClient

from arc.api.auth_routes import auth_router
from arc.api.middleware_rate_limit import (
    RateLimitMiddleware,
    _client_ip,
    _is_rate_limited_path,
    _rate_limit_category,
)
from arc.security.rate_limit import RateLimitConfig, SlidingWindowLimiter

# ── SlidingWindowLimiter unit tests ──────────────────────────────


class TestSlidingWindowLimiter:
    def test_allows_up_to_max_requests(self):
        limiter = SlidingWindowLimiter(config=RateLimitConfig(max_requests=3, window_seconds=60))
        allowed, remaining = asyncio.get_event_loop().run_until_complete(
            limiter.allow("ip:1.2.3.4")
        )
        assert allowed is True
        assert remaining == 2

        allowed, remaining = asyncio.get_event_loop().run_until_complete(
            limiter.allow("ip:1.2.3.4")
        )
        assert allowed is True
        assert remaining == 1

        allowed, remaining = asyncio.get_event_loop().run_until_complete(
            limiter.allow("ip:1.2.3.4")
        )
        assert allowed is True
        assert remaining == 0

    def test_rejects_when_at_limit(self):
        limiter = SlidingWindowLimiter(config=RateLimitConfig(max_requests=2, window_seconds=60))
        loop = asyncio.get_event_loop()
        loop.run_until_complete(limiter.allow("ip:1.2.3.4"))
        loop.run_until_complete(limiter.allow("ip:1.2.3.4"))
        allowed, retry_after = loop.run_until_complete(limiter.allow("ip:1.2.3.4"))
        assert allowed is False
        assert isinstance(retry_after, int)
        assert retry_after >= 1

    def test_window_rollover_allows_again(self):
        limiter = SlidingWindowLimiter(config=RateLimitConfig(max_requests=1, window_seconds=1))
        loop = asyncio.get_event_loop()
        loop.run_until_complete(limiter.allow("ip:1.2.3.4"))
        time.sleep(1.1)
        allowed, remaining = loop.run_until_complete(limiter.allow("ip:1.2.3.4"))
        assert allowed is True
        # Expired entry was pruned, not retained alongside the new one.
        assert len(limiter._timestamps["ip:1.2.3.4"]) == 1

    async def test_concurrent_requests_capped_at_limit(self):
        """Simultaneous allow() calls cannot race past max_requests."""
        limiter = SlidingWindowLimiter(config=RateLimitConfig(max_requests=10, window_seconds=60))
        results = await asyncio.gather(*[limiter.allow("ip:9.9.9.9") for _ in range(50)])
        assert sum(1 for allowed, _ in results if allowed) == 10

    def test_non_positive_limit_rejects_without_storing_key(self):
        """A zero/negative limit fails closed instead of raising IndexError."""
        limiter = SlidingWindowLimiter(config=RateLimitConfig(max_requests=0, window_seconds=60))
        loop = asyncio.get_event_loop()
        allowed, retry_after = loop.run_until_complete(limiter.allow("ip:1.2.3.4"))
        assert allowed is False
        assert retry_after == 60
        assert "ip:1.2.3.4" not in limiter._timestamps

    def test_separate_keys_are_independent(self):
        limiter = SlidingWindowLimiter(config=RateLimitConfig(max_requests=1, window_seconds=60))
        loop = asyncio.get_event_loop()
        loop.run_until_complete(limiter.allow("ip:1.1.1.1"))
        allowed, _ = loop.run_until_complete(limiter.allow("ip:2.2.2.2"))
        assert allowed is True

    def test_reset_clears_all(self):
        limiter = SlidingWindowLimiter(config=RateLimitConfig(max_requests=1, window_seconds=60))
        loop = asyncio.get_event_loop()
        loop.run_until_complete(limiter.allow("ip:1.1.1.1"))
        limiter.reset()
        allowed, _ = loop.run_until_complete(limiter.allow("ip:1.1.1.1"))
        assert allowed is True

    def test_reset_clears_single_key(self):
        limiter = SlidingWindowLimiter(config=RateLimitConfig(max_requests=1, window_seconds=60))
        loop = asyncio.get_event_loop()
        loop.run_until_complete(limiter.allow("ip:1.1.1.1"))
        loop.run_until_complete(limiter.allow("ip:2.2.2.2"))
        limiter.reset("ip:1.1.1.1")
        allowed, _ = loop.run_until_complete(limiter.allow("ip:1.1.1.1"))
        assert allowed is True
        allowed, _ = loop.run_until_complete(limiter.allow("ip:2.2.2.2"))
        assert allowed is False


# ── Path matching tests ─────────────────────────────────────────


class TestPathMatching:
    def test_auth_google_is_limited(self):
        assert _is_rate_limited_path("/auth/google") is True

    def test_auth_callback_is_limited(self):
        assert _is_rate_limited_path("/auth/callback") is True

    def test_auth_logout_is_limited(self):
        assert _is_rate_limited_path("/auth/logout") is True

    def test_auth_logout_all_is_limited(self):
        assert _is_rate_limited_path("/auth/logout-all") is True

    def test_auth_workspaces_not_limited(self):
        assert _is_rate_limited_path("/auth/workspaces") is False

    def test_auth_me_not_limited(self):
        assert _is_rate_limited_path("/auth/me") is False

    def test_webhook_ingestion_is_limited(self):
        assert _is_rate_limited_path("/webhooks/abc-123/events") is True

    def test_webhook_non_events_not_limited(self):
        assert _is_rate_limited_path("/webhooks/abc-123/status") is False

    def test_health_not_limited(self):
        assert _is_rate_limited_path("/health") is False

    def test_api_health_not_limited(self):
        assert _is_rate_limited_path("/api/health") is False

    def test_root_not_limited(self):
        assert _is_rate_limited_path("/") is False

    def test_category_auth(self):
        assert _rate_limit_category("/auth/google") == "auth"

    def test_category_webhook(self):
        assert _rate_limit_category("/webhooks/abc/events") == "webhook"


# ── Client IP extraction tests ──────────────────────────────────


class TestClientIP:
    def test_forwarded_header_is_ignored(self):
        """X-Forwarded-For is client-controlled and must not select buckets."""
        req = MagicMock()
        req.headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}
        req.client = MagicMock()
        req.client.host = "9.9.9.9"
        assert _client_ip(req) == "9.9.9.9"

    def test_real_ip_header_is_ignored(self):
        req = MagicMock()
        req.headers = {"x-real-ip": "1.2.3.4"}
        req.client = MagicMock()
        req.client.host = "9.9.9.9"
        assert _client_ip(req) == "9.9.9.9"

    def test_uses_client_host(self):
        req = MagicMock()
        req.headers = {}
        req.client = MagicMock()
        req.client.host = "9.9.9.9"
        assert _client_ip(req) == "9.9.9.9"

    def test_no_client_returns_unknown(self):
        req = MagicMock()
        req.headers = {}
        req.client = None
        assert _client_ip(req) == "unknown"


# ── Middleware integration tests ─────────────────────────────────


def _build_test_app() -> FastAPI:
    """Minimal FastAPI app with the rate limiter middleware installed."""
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/auth/google")
    async def auth_google():
        return {"ok": True}

    @app.get("/auth/callback")
    async def auth_callback():
        return {"ok": True}

    @app.post("/auth/logout")
    async def auth_logout():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/webhooks/{endpoint_id}/events")
    async def ingest(endpoint_id: str):
        return {"ok": True}

    return app


class TestMiddlewareIntegration:
    def test_auth_endpoint_returns_rate_limit_headers(self):
        """Allowed requests get X-RateLimit-* headers."""
        app = _build_test_app()
        client = TestClient(app)
        response = client.get("/auth/google")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Window" in response.headers

    def test_health_endpoint_no_rate_limit_headers(self):
        """Non-rate-limited paths do not get rate limit headers."""
        app = _build_test_app()
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers

    def test_webhook_endpoint_returns_rate_limit_headers(self):
        app = _build_test_app()
        client = TestClient(app)
        response = client.post("/webhooks/abc-123/events")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" in response.headers

    def test_429_response_format(self):
        """When rate limit exceeded, returns 429 with correct headers."""
        os.environ["RATE_LIMIT_AUTH_MAX"] = "2"
        os.environ["RATE_LIMIT_AUTH_WINDOW"] = "60"
        try:
            app = FastAPI()
            app.add_middleware(RateLimitMiddleware)

            @app.get("/auth/google")
            async def auth_google():
                return {"ok": True}

            client = TestClient(app)
            client.get("/auth/google")
            client.get("/auth/google")
            response = client.get("/auth/google")

            assert response.status_code == 429
            assert response.json() == {"detail": "Rate limit exceeded"}
            assert "Retry-After" in response.headers
            assert "X-RateLimit-Limit" in response.headers
            assert "X-RateLimit-Remaining" in response.headers
            assert response.headers["X-RateLimit-Remaining"] == "0"
        finally:
            os.environ.pop("RATE_LIMIT_AUTH_MAX", None)
            os.environ.pop("RATE_LIMIT_AUTH_WINDOW", None)

    def test_rate_limit_disabled_via_env(self):
        """RATE_LIMIT_ENABLED=0 bypasses all rate limiting."""
        os.environ["RATE_LIMIT_ENABLED"] = "0"
        os.environ["RATE_LIMIT_AUTH_MAX"] = "1"
        try:
            app = FastAPI()
            app.add_middleware(RateLimitMiddleware)

            @app.get("/auth/google")
            async def auth_google():
                return {"ok": True}

            client = TestClient(app)
            for _ in range(20):
                response = client.get("/auth/google")
                assert response.status_code == 200
        finally:
            os.environ.pop("RATE_LIMIT_ENABLED", None)
            os.environ.pop("RATE_LIMIT_AUTH_MAX", None)

    def test_forwarded_header_cannot_bypass_limit(self):
        """Rotating X-Forwarded-For shares one bucket (the TCP peer)."""
        os.environ["RATE_LIMIT_AUTH_MAX"] = "1"
        os.environ["RATE_LIMIT_AUTH_WINDOW"] = "60"
        try:
            app = FastAPI()
            app.add_middleware(RateLimitMiddleware)

            @app.get("/auth/google")
            async def auth_google():
                return {"ok": True}

            client = TestClient(app)
            response1 = client.get("/auth/google", headers={"x-forwarded-for": "1.1.1.1"})
            assert response1.status_code == 200
            # Attacker rotates the header: still the same peer, still limited.
            response2 = client.get("/auth/google", headers={"x-forwarded-for": "2.2.2.2"})
            assert response2.status_code == 429
        finally:
            os.environ.pop("RATE_LIMIT_AUTH_MAX", None)
            os.environ.pop("RATE_LIMIT_AUTH_WINDOW", None)


class TestRealAuthRouterIntegration:
    def test_real_google_login_route_is_rate_limited(self):
        """Production auth router behind the middleware returns 429 at limit."""
        os.environ["RATE_LIMIT_AUTH_MAX"] = "2"
        os.environ["RATE_LIMIT_AUTH_WINDOW"] = "60"
        try:
            app = FastAPI()
            app.add_middleware(RateLimitMiddleware)
            app.include_router(auth_router)
            app.state.google_oidc_service = None

            client = TestClient(app)
            # Google OIDC is unconfigured here, so the handler answers 503;
            # the middleware still counts and headers every allowed request.
            first = client.get("/auth/google")
            assert first.status_code == 503
            assert first.headers["X-RateLimit-Remaining"] == "1"
            second = client.get("/auth/google")
            assert second.status_code == 503
            assert second.headers["X-RateLimit-Remaining"] == "0"

            limited = client.get("/auth/google")
            assert limited.status_code == 429
            assert limited.json() == {"detail": "Rate limit exceeded"}
            assert "Retry-After" in limited.headers
        finally:
            os.environ.pop("RATE_LIMIT_AUTH_MAX", None)
            os.environ.pop("RATE_LIMIT_AUTH_WINDOW", None)
