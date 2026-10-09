"""tests/security/test_auth.py
Security test suite for API key authentication, timing-safe checks, and host bypass protection.
"""

from __future__ import annotations

import dataclasses
import logging

import pytest
from fastapi.testclient import TestClient

from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from tests.engine_helpers import make_engine

VALID_API_KEY = "sk-documind-test-secret-key-32chars"


@pytest.fixture
def auth_client(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=True)
    cfg = dataclasses.replace(eng.s, api_key=VALID_API_KEY, env="dev")
    app = create_app(dm=eng, settings=cfg)
    with TestClient(app) as client:
        yield client, cfg


def test_missing_api_key_returns_401(auth_client):
    client, _ = auth_client
    resp = client.get("/v1/documents")
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "unauthorized"
    assert "error" in data


def test_incorrect_api_key_returns_401(auth_client):
    client, _ = auth_client
    wrong_key = "wrong-key-that-does-not-match-at-all-32"
    resp = client.get("/v1/documents", headers={"X-API-Key": wrong_key})
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "unauthorized"


def test_non_ascii_api_key_returns_401_not_500(auth_client):
    client, _ = auth_client
    # Non-ASCII sequences must be safely digested without raising internal errors
    resp = client.get(
        "/v1/documents",
        headers=[(b"x-api-key", "🔑-invalid-unicode-key-1234567890".encode())],
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "unauthorized"


def test_correct_api_key_succeeds(auth_client):
    client, _ = auth_client
    resp = client.get("/v1/documents", headers={"X-API-Key": VALID_API_KEY})
    assert resp.status_code == 200
    docs = resp.json()
    assert isinstance(docs, list)


def test_malformed_host_header_on_protected_route_does_not_bypass_auth(auth_client):
    client, _ = auth_client
    # CVE-2026-48710 protection: malformed host header must not bypass dependency-based auth
    for bad_host in ["badhost.com", "localhost:9999", "attacker.com:80", "127.0.0.1:evil"]:
        resp = client.get("/v1/documents", headers={"Host": bad_host})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized"


def test_healthz_does_not_require_key(auth_client):
    client, _ = auth_client
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_startup_refuses_to_run_with_missing_key(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore())
    cfg = dataclasses.replace(eng.s, api_key="", env="dev")
    app = create_app(dm=eng, settings=cfg)
    with pytest.raises(RuntimeError, match="DOCUMIND_API_KEY"), TestClient(app):
        pass


def test_startup_refuses_to_run_with_short_key(tmp_path):
    eng, _, _ = make_engine(tmp_path, NumpyStore())
    cfg = dataclasses.replace(eng.s, api_key="short-key-only-20-c", env="dev")
    app = create_app(dm=eng, settings=cfg)
    with pytest.raises(RuntimeError, match="at least 32 characters"), TestClient(app):
        pass


def test_api_key_never_appears_in_captured_logs_or_errors(auth_client, caplog):
    client, _ = auth_client
    canary_probe = "probe-val-never-logged-9876543210"
    with caplog.at_level(logging.DEBUG):
        resp = client.get("/v1/documents", headers={"X-API-Key": canary_probe})
    assert resp.status_code == 401
    assert canary_probe not in resp.text
    for record in caplog.records:
        assert canary_probe not in record.getMessage()
