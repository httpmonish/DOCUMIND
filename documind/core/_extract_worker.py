"""documind/core/_extract_worker.py
Isolated subprocess worker for PDF parsing and text extraction.
Runs memory-constrained and enforces page count limits to isolate parser crashes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _apply_memory_limit() -> None:
    """Apply best-effort memory limit on POSIX systems (1.5 GB)."""
    try:
        import resource

        # 1.5 GB in bytes
        limit_bytes = 1536 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    except (ImportError, AttributeError, ValueError, OSError):
        # Unsupported on Windows or restricted environments
        pass


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m documind.core._extract_worker <pdf_path>", file=sys.stderr)
        sys.exit(1)

    _apply_memory_limit()

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    max_pages = int(os.getenv("DOCUMIND_MAX_PAGES", "500"))

    try:
        from pypdf import PdfReader
        from pypdf.errors import FileNotDecryptedError, PdfReadError, PdfStreamError

        reader = PdfReader(str(pdf_path))
        if getattr(reader, "is_encrypted", False):
            try:
                # Some PDFs are encrypted with empty password; if not, exit
                if reader.decrypt("") == 0:
                    print("PDF_ENCRYPTED: Password-protected PDF", file=sys.stderr)
                    sys.exit(4)
            except Exception:
                print("PDF_ENCRYPTED: Password-protected PDF", file=sys.stderr)
                sys.exit(4)

        num_pages = len(reader.pages)

        if num_pages > max_pages:
            print(
                f"PAGE_LIMIT_EXCEEDED: PDF has {num_pages} pages, exceeding cap of {max_pages}",
                file=sys.stderr,
            )
            sys.exit(2)

        page_texts = []
        for i, page in enumerate(reader.pages):
            try:
                txt = page.extract_text()
                if txt:
                    page_texts.append(txt)
            except Exception as page_err:
                print(f"Warning: page {i} extract failed: {page_err}", file=sys.stderr)

        full_text = "\n".join(page_texts).strip()
        if not full_text:
            print("NO_TEXT: No extractable text found in PDF", file=sys.stderr)
            sys.exit(3)

        sys.stdout.buffer.write(full_text.encode("utf-8"))
        sys.stdout.buffer.flush()
        sys.exit(0)

    except (PdfReadError, PdfStreamError, FileNotDecryptedError) as pdf_err:
        print(f"PDF_CORRUPT: {pdf_err}", file=sys.stderr)
        sys.exit(4)
    except Exception as exc:
        print(f"EXTRACTION_FAILED: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
