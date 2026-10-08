"""documind/core/ingest.py
Idempotent document ingestion pipeline: scanning, validation, chunking, embedding, storage.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from pypdf import PdfReader

from documind.core.chunker import chunk_document
from documind.core.config import Settings
from documind.core.errors import DocumentTooLarge, DocumentUnreadable, DocuMindError
from documind.core.loader import load_document
from documind.core.types import Chunk, Embedder, VectorStore

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}


@dataclass(frozen=True, slots=True)
class IndexReport:
    indexed: list[str]
    skipped: list[str]
    failed: list[tuple[str, str]]
    chunks: int
    seconds: float


def normalize_source(path: Path | PureWindowsPath | str, root: Path | str) -> str:
    """Normalize a document file path relative to indexing root with POSIX separators."""
    root_resolved = Path(root).resolve()

    if isinstance(path, PureWindowsPath):
        # Convert PureWindowsPath parts to POSIX relative path
        posix_str = path.as_posix()
        path_resolved = (root_resolved / posix_str).resolve()
    else:
        path_resolved = Path(path).resolve()

    try:
        rel = path_resolved.relative_to(root_resolved)
    except ValueError as err:
        raise ValueError(f"Path '{path}' is outside root '{root}'") from err

    rel_posix = rel.as_posix()
    if rel_posix in {".", ""}:
        raise ValueError("Path cannot be equal to root directory")

    if rel_posix.startswith("../") or rel_posix == "..":
        raise ValueError(f"Path '{path}' escapes root")

    return rel_posix


def compute_file_sha256(path: Path) -> str:
    """Compute sha256 of file bytes in 1 MB blocks."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _validate_file_limits(path: Path, source: str, settings: Settings) -> None:
    max_bytes = settings.max_file_mb * 1024 * 1024
    size = path.stat().st_size
    if size > max_bytes:
        raise DocumentTooLarge(
            source,
            f"File size {size / (1024 * 1024):.1f} MB exceeds limit {settings.max_file_mb} MB",
        )

    if path.suffix.lower() == ".pdf":
        try:
            reader = PdfReader(str(path))
            page_count = len(reader.pages)
            if page_count > settings.max_pages:
                raise DocumentTooLarge(
                    source,
                    f"Page count {page_count} exceeds limit {settings.max_pages}",
                )
        except DocumentTooLarge:
            raise
        except Exception as err:
            raise DocumentUnreadable(source, f"Cannot inspect PDF pages: {err}") from err


def _collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]

    collected: list[Path] = []
    for item in sorted(target.rglob("*")):
        if not item.is_file():
            continue
        # Skip hidden files and components
        if any(part.startswith(".") for part in item.relative_to(target).parts):
            continue
        if item.suffix.lower() in SUPPORTED_EXTENSIONS:
            collected.append(item)
    return sorted(collected)


def index_path(
    path: Path,
    root: Path,
    embedder: Embedder,
    store: VectorStore,
    settings: Settings,
) -> IndexReport:
    """Index a single file or directory into the vector store."""
    t0 = time.perf_counter()
    target_path = Path(path).resolve()
    root_path = Path(root).resolve()

    files = _collect_files(target_path)
    indexed: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []
    total_chunks = 0

    for file_path in files:
        try:
            source = normalize_source(file_path, root_path)
        except ValueError as err:
            failed.append((str(file_path), str(err)))
            continue

        try:
            _validate_file_limits(file_path, source, settings)
            sha = compute_file_sha256(file_path)

            # Idempotency check: skip if identical sha already indexed
            if store.doc_sha(source) == sha:
                skipped.append(source)
                continue

            # Load document
            text = load_document(str(file_path))

            # Chunk document
            raw_chunks = chunk_document(
                {"text": text, "source": source},
                chunk_size=settings.chunk_size,
                overlap=settings.overlap,
            )

            typed_chunks = [
                Chunk(
                    id=c["id"],
                    text=c["text"],
                    source=source,
                    chunk_index=c["chunk_index"],
                    doc_sha256=sha,
                )
                for c in raw_chunks
            ]

            # Atomic update for source: delete stale chunks first
            store.delete_source(source)
            write_succeeded = False
            try:
                vectors = embedder.embed_documents([c.text for c in typed_chunks])
                store.upsert(typed_chunks, vectors)
                write_succeeded = True
            finally:
                if not write_succeeded:
                    # Clean up partial writes so no corrupt/orphaned state remains
                    store.delete_source(source)

            indexed.append(source)
            total_chunks += len(typed_chunks)

        except DocuMindError as err:
            failed.append((source, str(err)))
            if target_path.is_file():
                raise
        except Exception as err:
            unreadable = DocumentUnreadable(source, str(err))
            failed.append((source, str(unreadable)))
            if target_path.is_file():
                raise unreadable from err

    elapsed = time.perf_counter() - t0
    return IndexReport(
        indexed=indexed,
        skipped=skipped,
        failed=failed,
        chunks=total_chunks,
        seconds=elapsed,
    )
