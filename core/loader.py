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
        reader = PdfReader(str(path))
        page_texts = []
        for page in reader.pages:
            page_texts.append(page.extract_text())
        return "\n".join(page_texts)
    elif extension in {".txt", ".md"}:
        return path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"Unsupported file type: {extension}")