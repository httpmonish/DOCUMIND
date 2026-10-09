"""tests/security/test_upload.py
Security and integration tests for document upload pipeline, content validation,
isolated worker extraction, limits enforcement, and atomic replacement.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter
from starlette.testclient import TestClient

from documind.core.config import Settings
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from tests.engine_helpers import make_engine

VALID_KEY = "test_key_minimum_32_characters_long_for_security_checks"


@pytest.fixture
def test_app(tmp_path: Path):
    settings = Settings(
        api_key=VALID_KEY,
        home=tmp_path,
        max_upload_mb=1,  # 1 MB for testing upload cap
        max_pages=5,  # 5 pages for testing page cap
    )
    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=False)
    # Ensure embedder and settings are attached
    eng.settings = settings
    app = create_app(dm=eng, settings=settings)
    return app, eng, settings


def test_oversized_upload_aborts_with_413_and_leaves_no_partial_file(test_app, tmp_path: Path):
    app, _, settings = test_app
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    # Upload 1.5 MB file (cap is 1 MB)
    large_payload = b"A" * (1024 * 1024 + 1024 * 512)
    files = {"file": ("large_doc.txt", large_payload, "text/plain")}

    resp = client.post("/v1/documents", files=files, headers=headers)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "document_too_large"

    # Verify no partial temporary files left in uploads directory
    uploads_dir = settings.home / "uploads"
    if uploads_dir.exists():
        temp_files = list(uploads_dir.glob("tmp_*"))
        assert len(temp_files) == 0


def test_pdf_with_invalid_header_returns_415(test_app):
    app, _, _ = test_app
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    # PDF extension but text content without %PDF- header
    files = {"file": ("fake.pdf", b"This is not a real PDF file content", "application/pdf")}
    resp = client.post("/v1/documents", files=files, headers=headers)
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "unsupported_media_type"


def test_txt_with_nul_byte_returns_415(test_app):
    app, _, _ = test_app
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    files = {"file": ("corrupt.txt", b"Hello\x00world", "text/plain")}
    resp = client.post("/v1/documents", files=files, headers=headers)
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "unsupported_media_type"


def test_truncated_corrupt_pdf_returns_422(test_app):
    app, _, _ = test_app
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    # Starts with %PDF- but contains completely corrupt garbage
    corrupt_pdf = b"%PDF-1.4\ncorrupted trailer and EOF missing"
    files = {"file": ("corrupt.pdf", corrupt_pdf, "application/pdf")}
    resp = client.post("/v1/documents", files=files, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "document_unreadable"


def test_encrypted_pdf_returns_422(test_app, tmp_path: Path):
    app, _, _ = test_app
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    # Generate an encrypted PDF with pypdf
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret_password")
    buf = io.BytesIO()
    writer.write(buf)
    encrypted_bytes = buf.getvalue()

    files = {"file": ("locked.pdf", encrypted_bytes, "application/pdf")}
    resp = client.post("/v1/documents", files=files, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "document_unreadable"


def test_pdf_exceeding_page_cap_returns_413(test_app):
    app, _, _ = test_app
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    # Page cap is 5 in test_app, create 8 pages from fixture
    fixture = Path("tests/fixtures/hello.pdf")
    reader = PdfReader(str(fixture))
    writer = PdfWriter()
    for _ in range(8):
        writer.add_page(reader.pages[0])
    buf = io.BytesIO()
    writer.write(buf)

    files = {"file": ("many_pages.pdf", buf.getvalue(), "application/pdf")}
    resp = client.post("/v1/documents", files=files, headers=headers)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "document_too_large"


def test_worker_timeout_returns_422(test_app):
    app, _, _ = test_app
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    fixture = Path("tests/fixtures/hello.pdf")
    files = {"file": ("slow.pdf", fixture.read_bytes(), "application/pdf")}

    # Mock subprocess.run to raise TimeoutExpired
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="worker", timeout=1)):
        resp = client.post("/v1/documents", files=files, headers=headers)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "document_unreadable"


def test_duplicate_upload_returns_200_unchanged(test_app):
    app, _, _ = test_app
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    content = b"Single line of unique text for duplicate testing"
    files = {"file": ("sample.txt", content, "text/plain")}

    resp1 = client.post("/v1/documents", files=files, headers=headers)
    assert resp1.status_code == 201
    assert resp1.json()["status"] == "indexed"

    # Upload identical content
    files2 = {"file": ("sample.txt", content, "text/plain")}
    resp2 = client.post("/v1/documents", files=files2, headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "unchanged"


def test_conflict_on_different_content_without_replace(test_app):
    app, _, _ = test_app
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    files1 = {"file": ("file.txt", b"Version one of this file", "text/plain")}
    resp1 = client.post("/v1/documents", files=files1, headers=headers)
    assert resp1.status_code == 201

    # Upload different content with same name and replace=false
    files2 = {"file": ("file.txt", b"Version two with different content", "text/plain")}
    resp2 = client.post("/v1/documents", files=files2, headers=headers)
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "conflict"


def test_replace_leaves_no_stale_high_index_chunks(test_app):
    app, eng, _ = test_app
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    # Upload a long document resulting in multiple chunks (e.g. 600 words)
    long_text = ("word " * 600).encode("utf-8")
    files1 = {"file": ("doc.txt", long_text, "text/plain")}
    resp1 = client.post("/v1/documents", files=files1, headers=headers)
    assert resp1.status_code == 201
    initial_chunks = resp1.json()["chunks"]
    assert initial_chunks > 1
    assert eng.chunk_count("doc.txt") == initial_chunks

    # Now replace with a short document (e.g. 5 words -> exactly 1 chunk)
    short_text = b"Just five small words here"
    files2 = {"file": ("doc.txt", short_text, "text/plain")}
    resp2 = client.post("/v1/documents?replace=true", files=files2, headers=headers)
    assert resp2.status_code == 201
    assert resp2.json()["chunks"] == 1

    # Assert vector store contains strictly 1 chunk now and no stale chunks
    assert eng.chunk_count("doc.txt") == 1


def test_index_real_10_page_pdf_and_ask(tmp_path: Path):
    # Test setting with max_pages high enough to allow 10 pages
    settings = Settings(
        api_key=VALID_KEY,
        home=tmp_path,
        max_pages=20,
        max_upload_mb=50,
    )
    eng, _, _ = make_engine(tmp_path, NumpyStore(), fill=False)
    eng.settings = settings
    app = create_app(dm=eng, settings=settings)
    client = TestClient(app)
    headers = {"X-API-Key": VALID_KEY}

    # Build a 10-page PDF from fixture
    fixture = Path("tests/fixtures/hello.pdf")
    reader = PdfReader(str(fixture))
    writer = PdfWriter()
    for _ in range(10):
        writer.add_page(reader.pages[0])
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    # Upload 10-page PDF
    files = {"file": ("ten_page.pdf", pdf_bytes, "application/pdf")}
    resp = client.post("/v1/documents", files=files, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["source"] == "ten_page.pdf"
    assert eng.chunk_count("ten_page.pdf") >= 1

    # Query the indexed document
    ask_resp = client.post(
        "/v1/ask",
        json={"question": "Hello DocuMind", "top_k": 3},
        headers=headers,
    )
    assert ask_resp.status_code == 200
    data = ask_resp.json()
    assert "citations" in data
