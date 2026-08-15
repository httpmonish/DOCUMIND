"""
core/chunker.py

Splits raw text into smaller overlapping pieces ("chunks").
"""


def chunk_text(text: str, chunk_size: int = 200, overlap: int = 30) -> list[str]:
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