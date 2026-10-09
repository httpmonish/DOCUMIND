"""tests/test_ingest.py
Unit and integration tests for source normalization and the ingest pipeline.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

import numpy as np
import pytest
from pypdf import PdfWriter

from documind.core.chunker import chunk_document
from documind.core.config import Settings
from documind.core.errors import DocumentTooLarge, DocumentUnreadable
from documind.core.ingest import index_path, normalize_source
from documind.core.vector_store import ChromaStore
from tests.fake_embedder import FakeEmbedder


def test_normalize_source_nested_dirs(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    sub = root / "sub" / "topic"
    sub.mkdir(parents=True)
    target = sub / "notes.md"
    target.touch()

    assert normalize_source(target, root) == "sub/topic/notes.md"


def test_normalize_source_windows_style(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    sub = root / "unit1"
    sub.mkdir(parents=True)
    target = sub / "lecture.txt"
    target.touch()

    win_path = PureWindowsPath("unit1\\lecture.txt")
    assert normalize_source(win_path, root) == "unit1/lecture.txt"


def test_normalize_source_parent_escape(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    outside = tmp_path / "other" / "secret.txt"
    outside.parent.mkdir()
    outside.touch()

    with pytest.raises(ValueError, match="outside root"):
        normalize_source(outside, root)


def test_normalize_source_symlink_outside(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside secret")

    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks not supported in this environment")

    with pytest.raises(ValueError, match="outside root"):
        normalize_source(link, root)


def test_normalize_source_equal_to_root(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()

    with pytest.raises(ValueError, match="equal to root"):
        normalize_source(root, root)


def test_normalize_source_unicode_and_spaces(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    f = root / "folder space" / "résumé 2026.txt"
    f.parent.mkdir()
    f.touch()

    assert normalize_source(f, root) == "folder space/résumé 2026.txt"


# ----------------- Pipeline Tests -----------------


SetupType = tuple[Path, Path, FakeEmbedder, ChromaStore, Settings]


@pytest.fixture
def test_setup(tmp_path: Path) -> SetupType:
    docs_root = tmp_path / "corpus"
    docs_root.mkdir()
    chroma_dir = tmp_path / "chroma"
    store = ChromaStore(chroma_dir, "bge-small-en-v1.5", 384)
    embedder = FakeEmbedder()
    settings = Settings(chunk_size=20, overlap=5)
    return docs_root, chroma_dir, embedder, store, settings


def test_index_happy_path(test_setup: SetupType) -> None:
    docs_root, _, embedder, store, settings = test_setup
    sample = docs_root / "guide.md"
    sample.write_text("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi")

    report = index_path(sample, docs_root, embedder, store, settings)
    assert report.indexed == ["guide.md"]
    assert report.skipped == []
    assert report.failed == []

    expected_chunks = chunk_document(
        {"text": sample.read_text(), "source": "guide.md"},
        chunk_size=settings.chunk_size,
        overlap=settings.overlap,
    )
    assert store.count_for("guide.md") == len(expected_chunks)


def test_index_idempotent_skip(test_setup: SetupType) -> None:
    docs_root, _, embedder, store, settings = test_setup
    sample = docs_root / "doc.txt"
    sample.write_text("first second third fourth fifth sixth seventh eighth ninth tenth")

    r1 = index_path(sample, docs_root, embedder, store, settings)
    assert r1.indexed == ["doc.txt"]

    r2 = index_path(sample, docs_root, embedder, store, settings)
    assert r2.skipped == ["doc.txt"]
    assert r2.indexed == []


def test_index_file_shrunk_no_stale_chunks(test_setup: SetupType) -> None:
    docs_root, _, embedder, store, settings = test_setup
    sample = docs_root / "notes.md"
    words = [f"word_{i}" for i in range(100)]
    sample.write_text(" ".join(words))

    r1 = index_path(sample, docs_root, embedder, store, settings)
    assert r1.indexed == ["notes.md"]
    old_count = store.count_for("notes.md")
    assert old_count > 2

    # Shrink file to 15 words (fits in 1 chunk)
    sample.write_text("only a few words now in the shrunk file")
    r2 = index_path(sample, docs_root, embedder, store, settings)
    assert r2.indexed == ["notes.md"]

    new_count = store.count_for("notes.md")
    assert new_count == 1
    assert store.count() == 1


def test_index_corrupt_pdf_in_directory(test_setup: SetupType) -> None:
    docs_root, _, embedder, store, settings = test_setup
    good = docs_root / "good.txt"
    good.write_text("good file text content for indexing")

    bad = docs_root / "corrupt.pdf"
    bad.write_bytes(b"invalid pdf data bytes")

    report = index_path(docs_root, docs_root, embedder, store, settings)
    assert "good.txt" in report.indexed
    assert any("corrupt.pdf" in f[0] for f in report.failed)


def test_index_oversize_file(test_setup: SetupType) -> None:
    docs_root, _, embedder, store, _ = test_setup
    oversize = docs_root / "big.txt"
    oversize.write_text("content")

    # Set limit to 0 MB
    tiny_settings = Settings(max_file_mb=0)
    with pytest.raises(DocumentTooLarge):
        index_path(oversize, docs_root, embedder, store, tiny_settings)


def test_index_pdf_page_cap(test_setup: SetupType) -> None:
    docs_root, _, embedder, store, _ = test_setup
    pdf_path = docs_root / "three_pages.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    with pdf_path.open("wb") as f:
        writer.write(f)

    cap_settings = Settings(max_pages=2)
    with pytest.raises(DocumentTooLarge):
        index_path(pdf_path, docs_root, embedder, store, cap_settings)


def test_index_crash_cleanup_no_partial_chunks(test_setup: SetupType) -> None:
    docs_root, _, _, store, settings = test_setup
    sample = docs_root / "fail.txt"
    sample.write_text("some words that produce multiple chunks for indexing test")

    class CrashingEmbedder:
        model_id = "crashing"
        dim = 384

        def embed_documents(self, texts: list[str]) -> np.ndarray:
            raise RuntimeError("Simulated crash in embedder!")

        def embed_query(self, text: str) -> np.ndarray:
            return np.zeros(384, dtype=np.float32)

    with pytest.raises(DocumentUnreadable):
        index_path(sample, docs_root, CrashingEmbedder(), store, settings)

    # Partial source must be cleaned up
    assert store.count_for("fail.txt") == 0
    assert store.doc_sha("fail.txt") is None


def test_index_path_missing_path_raises_file_not_found(test_setup: SetupType) -> None:
    docs_root, embedder, _, store, settings = test_setup
    missing = docs_root / "nonexistent.md"
    with pytest.raises(FileNotFoundError):
        index_path(missing, docs_root, embedder, store, settings)
