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
