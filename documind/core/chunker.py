"""core/chunker.py
Splits raw text into smaller overlapping pieces ("chunks").
"""

from typing import Any


def chunk_text(text: str, chunk_size: int = 200, overlap: int = 30) -> list[str]:
    if chunk_size <= 0:
        raise ValueError(f"chunk_size ({chunk_size}) must be positive.")
    if not (0 <= overlap < chunk_size):
        raise ValueError(f"overlap ({overlap}) must be between 0 and chunk_size.")

    words = text.split()
    if not words:
        return []

    step = chunk_size - overlap
    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += step

    return chunks


def chunk_document(
    document: dict[str, Any], chunk_size: int = 200, overlap: int = 30
) -> list[dict[str, Any]]:
    pieces = chunk_text(document["text"], chunk_size=chunk_size, overlap=overlap)
    source = document["source"]

    return [
        {
            "id": f"{source}_chunk_{i:04d}",
            "text": piece,
            "source": source,
            "chunk_index": i,
        }
        for i, piece in enumerate(pieces)
    ]
