"""documind/interfaces/ratelimit.py
Thread-safe in-memory token bucket rate limiter for DocuMind API.
Limits requests per key identity without storing or logging raw API keys.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections.abc import Callable


class TokenBucketLimiter:
    """In-memory thread-safe token bucket rate limiter with injectable clock."""

    def __init__(
        self,
        rate_per_min: int = 20,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.rate_per_min = rate_per_min
        self.capacity = float(rate_per_min)
        self.fill_rate = float(rate_per_min) / 60.0  # tokens per second
        self.clock = clock or time.monotonic
        self._lock = threading.Lock()
        # Identity hash -> (tokens, last_update_time)
        self._buckets: dict[str, tuple[float, float]] = {}

    @staticmethod
    def derive_identity(api_key: str) -> str:
        """Derive an 8-char hex identity from key hash without storing the secret."""
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:8]

    def consume(self, identity: str) -> tuple[bool, int]:
        """Attempt to consume 1 token for the identity.
        Returns:
            (allowed: bool, retry_after_seconds: int)
        """
        now = self.clock()
        with self._lock:
            tokens, last_time = self._buckets.get(identity, (self.capacity, now))

            # Replenish tokens based on elapsed time
            elapsed = max(0.0, now - last_time)
            tokens = min(self.capacity, tokens + elapsed * self.fill_rate)

            if tokens >= 1.0:
                self._buckets[identity] = (tokens - 1.0, now)
                return True, 0

            # Not enough tokens; calculate seconds until at least 1 token is available
            deficit = 1.0 - tokens
            retry_after = math.ceil(deficit / self.fill_rate) if self.fill_rate > 0 else 60
            self._buckets[identity] = (tokens, now)
            return False, max(1, retry_after)


class MultiActionRateLimiter:
    """Manages rate limits for multiple distinct actions (e.g. ask, upload, session)."""

    DEFAULT_POLICIES: dict[str, tuple[float, float]] = {
        # action -> (capacity, refill_tokens_per_second)
        "ask": (10.0, 10.0 / 60.0),  # 10 / min
        "upload": (5.0, 5.0 / 3600.0),  # 5 / hr
        "session_create_hour": (5.0, 5.0 / 3600.0),  # 5 / hr
        "session_create_day": (20.0, 20.0 / 86400.0),  # 20 / day
        "general": (60.0, 60.0 / 60.0),  # 60 / min
        "default": (60.0, 60.0 / 60.0),  # 60 / min
    }

    def __init__(
        self,
        policies: dict[str, tuple[float, float]] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.policies = policies or dict(self.DEFAULT_POLICIES)
        self.clock = clock or time.monotonic
        self._lock = threading.Lock()
        # (action, identity) -> (tokens, last_update_time)
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}

    def consume(self, action: str, identity: str) -> tuple[bool, int]:
        """Attempt to consume 1 token for given action and identity.
        Returns (allowed, retry_after_seconds).
        """
        default_policy = self.policies.get("default", (20.0, 20.0 / 60.0))
        capacity, fill_rate = self.policies.get(action, default_policy)
        now = self.clock()
        key = (action, identity)

        with self._lock:
            tokens, last_time = self._buckets.get(key, (capacity, now))
            elapsed = max(0.0, now - last_time)
            tokens = min(capacity, tokens + elapsed * fill_rate)

            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return True, 0

            deficit = 1.0 - tokens
            retry_after = math.ceil(deficit / fill_rate) if fill_rate > 0 else 60
            self._buckets[key] = (tokens, now)
            return False, max(1, retry_after)
