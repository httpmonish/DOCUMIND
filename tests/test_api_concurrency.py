"""tests/test_api_concurrency.py
Concurrency tests verifying that read queries (/v1/ask) run concurrently
without unnecessary serialization, and that queries are not blocked by upload write locks.
"""

from __future__ import annotations

import concurrent.futures
import time
from pathlib import Path

from starlette.testclient import TestClient

from documind.core.config import Settings
from documind.core.types import Usage
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from tests.engine_helpers import make_engine
from tests.fake_llm import FakeLLM

VALID_KEY = "test_key_minimum_32_characters_long_for_security_checks"


class SlowLLM(FakeLLM):
    """Fake LLM that sleeps for a controlled duration to test concurrency."""

    def __init__(self, delay_s: float = 0.3) -> None:
        super().__init__(reply="A semaphore is a counter. [S1]")
        self.delay_s = delay_s

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        time.sleep(self.delay_s)
        return super().complete(system, user, max_tokens=max_tokens)


def test_concurrent_ask_requests_run_in_parallel(tmp_path: Path):
    settings = Settings(api_key=VALID_KEY, home=tmp_path)
    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=True)
    eng.llm = SlowLLM(delay_s=0.3)
    eng.settings = settings

    app = create_app(dm=eng, settings=settings)
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    def do_ask():
        resp = client.post(
            "/v1/ask",
            json={"question": "what is a semaphore"},
            headers=headers,
        )
        return resp.status_code, resp.json()

    # Issue 2 requests concurrently
    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(do_ask)
        f2 = executor.submit(do_ask)
        res1 = f1.result()
        res2 = f2.result()
    elapsed = time.perf_counter() - t0

    assert res1[0] == 200
    assert res2[0] == 200

    # If serialized, elapsed time would be >= 0.60 seconds (2 * 0.3)
    # When running concurrently, elapsed time is well below 0.55 seconds
    assert elapsed < 0.55, f"Expected concurrent execution < 0.55s, got {elapsed:.3f}s"


def test_ask_not_blocked_by_write_lock(tmp_path: Path):
    settings = Settings(api_key=VALID_KEY, home=tmp_path)
    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=True)
    eng.settings = settings

    app = create_app(dm=eng, settings=settings)
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    # Simulate an ongoing write lock held by an upload
    lock = app.state.write_lock
    lock.acquire()
    try:
        # /v1/ask must proceed without blocking on the write lock
        resp = client.post(
            "/v1/ask",
            json={"question": "what is a semaphore"},
            headers=headers,
        )
        assert resp.status_code == 200
    finally:
        lock.release()
