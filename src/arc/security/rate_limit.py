"""In-memory sliding-window rate limiter.

V2-ADR-026 permits rate limiting; this module enforces it per-IP
without external infrastructure (no Redis, no K8s, no service mesh).

Sliding window algorithm:
- Each key (e.g. IP address) has a list of request timestamps.
- On each request, prune timestamps older than the window.
- If the remaining count < limit, allow and record timestamp.
- Otherwise reject with 429 and Retry-After header.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("arc.rate_limit")


@dataclass
class RateLimitConfig:
    """Configuration for a single rate limit rule."""

    max_requests: int
    window_seconds: int


@dataclass
class SlidingWindowLimiter:
    """In-memory sliding-window rate limiter keyed by string.

    Uses asyncio.Lock for thread safety within a single event loop.

    State is process-local with no background cleanup: fully-expired keys
    are dropped on next access, but keys that are never accessed again keep
    their (expired) timestamps until process restart. Accepted for the
    current single-worker deployment (V2-ADR-026: no external
    infrastructure).
    """

    config: RateLimitConfig
    _timestamps: dict[str, list[float]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def allow(self, key: str) -> tuple[bool, int]:
        """Check whether *key* is allowed under the current window.

        Returns (allowed, remaining) where remaining is the number of
        requests still permitted in the current window.
        """
        now = time.monotonic()
        if self.config.max_requests <= 0:
            # Fail closed on non-positive limits instead of raising
            # IndexError on the empty timestamp list below.
            return False, max(1, self.config.window_seconds)
        cutoff = now - self.config.window_seconds

        async with self._lock:
            timestamps = self._timestamps.get(key, [])
            # Prune expired entries
            timestamps = [t for t in timestamps if t > cutoff]
            if not timestamps:
                # Drop fully-expired keys instead of retaining empty buckets.
                self._timestamps.pop(key, None)

            if len(timestamps) < self.config.max_requests:
                timestamps.append(now)
                self._timestamps[key] = timestamps
                remaining = self.config.max_requests - len(timestamps)
                return True, remaining

            # At limit — do NOT record, return Retry-After
            self._timestamps[key] = timestamps
            oldest = timestamps[0]
            retry_after = max(1, int(oldest + self.config.window_seconds - now) + 1)
            return False, retry_after

    def reset(self, key: str | None = None) -> None:
        """Reset state for testing. If key is None, reset all."""
        if key is None:
            self._timestamps.clear()
        else:
            self._timestamps.pop(key, None)
