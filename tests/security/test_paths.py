"""tests/security/test_paths.py
Security tests verifying path traversal prevention, filename sanitization,
and Windows reserved device name rejections.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from documind.core.config import Settings
from documind.core.ingest import safe_upload_name
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from tests.engine_helpers import make_engine

VALID_KEY = "test_key_minimum_32_characters_long_for_security_checks"


def test_safe_upload_name_path_traversal() -> None:
    # Directory traversal via POSIX separators
    assert safe_upload_name("../../etc/passwd") == "passwd"
    # Directory traversal via Windows separators
    assert safe_upload_name(r"..\..\x") == "x"
    # Absolute paths
    assert safe_upload_name("/var/log/syslog.txt") == "syslog.txt"
    assert safe_upload_name("C:\\Windows\\System32\\calc.exe") == "calc.exe"


def test_safe_upload_name_nul_bytes() -> None:
    with pytest.raises(ValueError, match="NUL"):
        safe_upload_name("foo\x00bar.txt")


def test_safe_upload_name_windows_reserved() -> None:
    with pytest.raises(ValueError, match="reserved"):
        safe_upload_name("CON.txt")
    with pytest.raises(ValueError, match="reserved"):
        safe_upload_name("nul")
    with pytest.raises(ValueError, match="reserved"):
        safe_upload_name("aux.pdf")
    with pytest.raises(ValueError, match="reserved"):
        safe_upload_name("COM1.txt")
    with pytest.raises(ValueError, match="reserved"):
        safe_upload_name("LPT3.md")
    with pytest.raises(ValueError, match="reserved"):
        safe_upload_name("con.tar.gz")


def test_safe_upload_name_empty_and_dots() -> None:
    with pytest.raises(ValueError):
        safe_upload_name("")
    with pytest.raises(ValueError):
        safe_upload_name("   ")
    with pytest.raises(ValueError):
        safe_upload_name(".")
    with pytest.raises(ValueError):
        safe_upload_name("...")


def test_safe_upload_name_dot_stem_missing() -> None:
    with pytest.raises(ValueError, match="stem"):
        safe_upload_name(".pdf")
    with pytest.raises(ValueError, match="stem"):
        safe_upload_name(".txt")


def test_safe_upload_name_300_chars() -> None:
    long_name = ("a" * 296) + ".txt"
    sanitized = safe_upload_name(long_name)
    assert len(sanitized) == 100
    assert sanitized == "a" * 100


def test_resolved_upload_path_stays_inside_uploads(tmp_path: Path) -> None:
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Test an adversarial filename
    raw = "../../etc/passwd"
    clean = safe_upload_name(raw)
    sha_prefix = "0123456789abcdef"
    final_path = (uploads_dir / f"{sha_prefix}_{clean}").resolve()

    assert final_path.is_relative_to(uploads_dir.resolve())
    assert final_path.name == "0123456789abcdef_passwd"


def test_delete_source_path_traversal_returns_422(tmp_path: Path) -> None:
    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=True)
    settings = Settings(api_key=VALID_KEY, home=tmp_path)
    app = create_app(dm=eng, settings=settings)
    client = TestClient(app)

    headers = {"X-API-Key": VALID_KEY}

    # Path traversal with encoded ..
    resp = client.delete("/v1/documents/%2e%2e%2fetc/passwd", headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unprocessable_entity"

    resp2 = client.delete("/v1/documents/..%2fpasswd", headers=headers)
    assert resp2.status_code == 422

    # Leading slash
    resp3 = client.delete("/v1/documents//etc/passwd", headers=headers)
    assert resp3.status_code == 422
