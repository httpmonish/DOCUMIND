"""
core/loader.py

Turns a file on disk into plain text — the first step of the pipeline.
"""
from pathlib import Path

from pypdf import PdfReader


def load_document(filepath: str) -> str:
    path = Path(filepath)
    extension = path.suffix.lower()

    if extension == ".pdf":
        text = _load_pdf(path)
    elif extension in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"Unsupported file type: {extension}")

    if not text.strip():
        raise ValueError(
            f"{path.name}: no extractable text found. This usually means "
            f"it's a scanned/image-only PDF with no real text layer — "
            f"pypdf can only read text that's actually stored as text."
        )

    return text


def _load_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    page_texts = [page.extract_text() for page in reader.pages]
    return "\n".join(page_texts)