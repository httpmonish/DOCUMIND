"""tests/test_api.py
Integration and functional tests for the DocuMind FastAPI REST interface.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from tests.engine_helpers import make_engine

VALID_API_KEY = "test-secret-key-that-is-at-least-32-chars-long"


@pytest.fixture
def api_engine(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=True)
    cfg = dataclasses.replace(eng.s, api_key=VALID_API_KEY, env="dev")
    return eng, cfg


def test_startup_fails_closed_without_valid_api_key(api_engine):
    eng, cfg = api_engine
    short_cfg = dataclasses.replace(cfg, api_key="short")
    app = create_app(dm=eng, settings=short_cfg)
    with pytest.raises(RuntimeError, match="DOCUMIND_API_KEY"), TestClient(app):
        pass


def test_healthz_unauthenticated_and_clean_response(api_engine):
    eng, cfg = api_engine
    app = create_app(dm=eng, settings=cfg)
    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "status": "ok",
            "index_chunks": 2,
            "embed_model": cfg.embed_model,
            "schema_version": 1,
            "tau": cfg.min_score,
        }
        assert "paths" not in str(data)
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("Cache-Control") == "no-store"


def test_docs_gated_in_production(api_engine):
    eng, cfg = api_engine
    prod_cfg = dataclasses.replace(cfg, env="prod")
    prod_app = create_app(dm=eng, settings=prod_cfg)
    with TestClient(prod_app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404

    dev_app = create_app(dm=eng, settings=cfg)
    with TestClient(dev_app) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_request_id_header_handling(api_engine):
    eng, cfg = api_engine
    app = create_app(dm=eng, settings=cfg)
    with TestClient(app) as client:
        # Valid custom request ID
        resp = client.get("/healthz", headers={"X-Request-ID": "custom-req-id-12345"})
        assert resp.headers.get("X-Request-ID") == "custom-req-id-12345"

        # Invalid characters or length: gets replaced with UUID
        resp2 = client.get("/healthz", headers={"X-Request-ID": "bad/char!"})
        req_id = resp2.headers.get("X-Request-ID")
        assert req_id != "bad/char!"
        assert len(req_id) >= 8


def test_error_envelope_on_404(api_engine):
    eng, cfg = api_engine
    app = create_app(dm=eng, settings=cfg)
    with TestClient(app) as client:
        resp = client.get("/nonexistent-endpoint")
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "not_found"
        assert "request_id" in data["error"]
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"


def test_ask_happy_path(api_engine):
    eng, cfg = api_engine
    app = create_app(dm=eng, settings=cfg)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/ask",
            headers={"X-API-Key": VALID_API_KEY},
            json={"question": "what is a semaphore", "top_k": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "answered"
        assert "citations" in data
        assert len(data["citations"]) >= 1
        assert "retrieved" not in data  # Never present unless debug enabled
        assert all(len(c["snippet"]) <= 200 for c in data["citations"])


def test_ask_unknown_field_rejected_with_422(api_engine):
    eng, cfg = api_engine
    app = create_app(dm=eng, settings=cfg)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/ask",
            headers={"X-API-Key": VALID_API_KEY},
            json={"question": "what is a semaphore", "extra_malicious_field": True},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "validation_error"


def test_ask_question_length_limit_enforced_with_422(api_engine):
    eng, cfg = api_engine
    app = create_app(dm=eng, settings=cfg)
    with TestClient(app) as client:
        long_q = "a" * 2001
        resp = client.post(
            "/v1/ask",
            headers={"X-API-Key": VALID_API_KEY},
            json={"question": long_q},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"


def test_ask_top_k_bounds_enforced_with_422(api_engine):
    eng, cfg = api_engine
    app = create_app(dm=eng, settings=cfg)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/ask",
            headers={"X-API-Key": VALID_API_KEY},
            json={"question": "what is a semaphore", "top_k": 11},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"


def test_ask_empty_index_returns_409(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=False)
    cfg = dataclasses.replace(eng.s, api_key=VALID_API_KEY, env="dev")
    app = create_app(dm=eng, settings=cfg)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/ask",
            headers={"X-API-Key": VALID_API_KEY},
            json={"question": "what is a semaphore?"},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data["error"]["code"] == "index_empty"


def test_ask_llm_unavailable_returns_502_with_fallback(tmp_path):
    from documind.core.errors import LLMUnavailable

    class BrokenLLM:
        def complete(self, system: str, user: str, max_tokens: int = 600):
            raise LLMUnavailable("API down")

    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=True)
    eng.llm = BrokenLLM()
    cfg = dataclasses.replace(eng.s, api_key=VALID_API_KEY, env="dev")
    app = create_app(dm=eng, settings=cfg)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/ask",
            headers={"X-API-Key": VALID_API_KEY},
            json={"question": "what is a semaphore"},
        )
        assert resp.status_code == 502
        data = resp.json()
        assert data["error"]["code"] == "llm_unavailable"
        assert "fallback" in data["error"]
        fallback = data["error"]["fallback"]
        assert fallback["outcome"] == "abstained"
        assert len(fallback["citations"]) >= 1


def test_debug_gated_by_server_configuration(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=True)

    # Server with debug OFF (default)
    cfg_no_debug = dataclasses.replace(eng.s, api_key=VALID_API_KEY, allow_debug=False)
    app1 = create_app(dm=eng, settings=cfg_no_debug)
    with TestClient(app1) as client:
        resp = client.post(
            "/v1/ask",
            headers={"X-API-Key": VALID_API_KEY},
            json={"question": "what is a semaphore", "debug": True},
        )
        assert resp.status_code == 200
        assert "retrieved" not in resp.json()

    # Server with debug ON
    cfg_debug = dataclasses.replace(eng.s, api_key=VALID_API_KEY, allow_debug=True)
    app2 = create_app(dm=eng, settings=cfg_debug)
    with TestClient(app2) as client:
        resp = client.post(
            "/v1/ask",
            headers={"X-API-Key": VALID_API_KEY},
            json={"question": "what is a semaphore", "debug": True},
        )
        assert resp.status_code == 200
        assert "retrieved" in resp.json()


def test_ask_query_log_format(tmp_path):
    import json

    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=True)
    cfg = dataclasses.replace(eng.s, api_key=VALID_API_KEY, log_questions=False)
    app = create_app(dm=eng, settings=cfg)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/ask",
            headers={"X-API-Key": VALID_API_KEY, "X-Request-ID": "test-req-logger-123"},
            json={"question": "what is a semaphore"},
        )
        assert resp.status_code == 200

    log_file = cfg.home / "logs" / "queries.jsonl"
    assert log_file.exists()
    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    last = lines[-1]
    assert last["interface"] == "api"
    assert last["request_id"] == "test-req-logger-123"
    assert "question" not in last  # Log questions disabled by default
    assert "question_sha256" in last
