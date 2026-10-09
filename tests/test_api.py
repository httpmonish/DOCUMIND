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
