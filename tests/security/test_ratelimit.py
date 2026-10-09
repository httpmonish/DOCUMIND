"""tests/security/test_ratelimit.py
Tests for in-memory token bucket rate limiting and retry-after headers.
"""

from __future__ import annotations

import dataclasses

from fastapi.testclient import TestClient

from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from documind.interfaces.ratelimit import TokenBucketLimiter
from tests.engine_helpers import make_engine

KEY_A = "test-secret-key-identity-aaa-32chars"
KEY_B = "test-secret-key-identity-bbb-32chars"


class MockClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def test_token_bucket_allows_capacity_and_rejects_subsequent():
    clock = MockClock()
    limiter = TokenBucketLimiter(rate_per_min=5, clock=clock)
    identity = "user1"

    # Consume all 5 tokens
    for _ in range(5):
        allowed, retry = limiter.consume(identity)
        assert allowed is True
        assert retry == 0

    # 6th request must be rejected with positive retry_after
    allowed, retry = limiter.consume(identity)
    assert allowed is False
    assert retry > 0

    # Advance clock by 12 seconds (1 token at 5 tokens/min = 1 token / 12s)
    clock.advance(12.0)
    allowed, retry = limiter.consume(identity)
    assert allowed is True


def test_exhausting_one_key_does_not_affect_another_key():
    clock = MockClock()
    limiter = TokenBucketLimiter(rate_per_min=2, clock=clock)

    # Exhaust identity A
    assert limiter.consume("user_a")[0] is True
    assert limiter.consume("user_a")[0] is True
    assert limiter.consume("user_a")[0] is False

    # Identity B is untouched
    assert limiter.consume("user_b")[0] is True
    assert limiter.consume("user_b")[0] is True
    assert limiter.consume("user_b")[0] is False


def test_api_rate_limiting_integration(tmp_path):
    clock = MockClock()
    limiter = TokenBucketLimiter(rate_per_min=20, clock=clock)

    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=True)
    cfg = dataclasses.replace(eng.s, api_key=KEY_A, rate_limit_per_min=20)
    app = create_app(dm=eng, settings=cfg, limiter=limiter)

    with TestClient(app) as client:
        # First 20 requests succeed
        for _ in range(20):
            resp = client.get("/v1/documents", headers={"X-API-Key": KEY_A})
            assert resp.status_code == 200

        # 21st request rejected with 429 and Retry-After header
        resp_429 = client.get("/v1/documents", headers={"X-API-Key": KEY_A})
        assert resp_429.status_code == 429
        assert resp_429.json()["error"]["code"] == "rate_limited"
        assert "Retry-After" in resp_429.headers
        retry_val = int(resp_429.headers["Retry-After"])
        assert retry_val >= 1

        # Advance clock by 60 seconds (bucket completely refills)
        clock.advance(60.0)
        resp_ok = client.get("/v1/documents", headers={"X-API-Key": KEY_A})
        assert resp_ok.status_code == 200
