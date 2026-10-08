import pytest

from documind.core.config import load_settings
from documind.core.types import Chunk


def test_chunk_valid():
    chunk = Chunk(
        id="doc.md_chunk_0000",
        text="Sample text",
        source="doc.md",
        chunk_index=0,
        doc_sha256="abc123",
    )
    assert chunk.id == "doc.md_chunk_0000"
    assert chunk.text == "Sample text"


def test_chunk_rejects_empty_or_whitespace_text():
    with pytest.raises(ValueError, match="empty chunk text"):
        Chunk(
            id="doc.md_chunk_0000",
            text="   \n\t ",
            source="doc.md",
            chunk_index=0,
            doc_sha256="abc123",
        )


def test_chunk_rejects_negative_index():
    with pytest.raises(ValueError, match="negative chunk_index"):
        Chunk(
            id="doc.md_chunk_0000",
            text="Valid text",
            source="doc.md",
            chunk_index=-1,
            doc_sha256="abc123",
        )


def test_config_defaults(monkeypatch):
    monkeypatch.delenv("DOCUMIND_HOME", raising=False)
    monkeypatch.delenv("DOCUMIND_CHUNK_SIZE", raising=False)
    monkeypatch.delenv("DOCUMIND_OVERLAP", raising=False)
    settings = load_settings()
    assert settings.chunk_size == 200
    assert settings.overlap == 30
    assert settings.top_k == 5
    assert settings.max_file_mb == 50
    assert settings.max_pages == 500


def test_config_invalid_integer(monkeypatch):
    monkeypatch.setenv("DOCUMIND_CHUNK_SIZE", "not_a_number")
    with pytest.raises(ValueError, match="DOCUMIND_CHUNK_SIZE"):
        load_settings()


def test_config_non_positive_integer(monkeypatch):
    monkeypatch.setenv("DOCUMIND_CHUNK_SIZE", "0")
    with pytest.raises(ValueError, match="DOCUMIND_CHUNK_SIZE"):
        load_settings()


def test_config_overlap_larger_than_chunk_size(monkeypatch):
    monkeypatch.setenv("DOCUMIND_CHUNK_SIZE", "100")
    monkeypatch.setenv("DOCUMIND_OVERLAP", "100")
    with pytest.raises(ValueError, match="DOCUMIND_OVERLAP"):
        load_settings()
