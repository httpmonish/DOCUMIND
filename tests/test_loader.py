from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.errors import PdfStreamError

from documind.core.loader import load_document


def test_load_txt_happy_path(tmp_path: Path):
    f = tmp_path / "sample.txt"
    f.write_text("Hello from a txt file", encoding="utf-8")
    assert load_document(str(f)) == "Hello from a txt file"


def test_load_md_happy_path(tmp_path: Path):
    f = tmp_path / "sample.md"
    f.write_text("# Markdown Title\nSome content here.", encoding="utf-8")
    assert "# Markdown Title" in load_document(str(f))


def test_load_empty_file_raises_value_error(tmp_path: Path):
    f = tmp_path / "empty.txt"
    f.write_text("   \n\t  ", encoding="utf-8")
    with pytest.raises(ValueError, match="no extractable text found"):
        load_document(str(f))


def test_load_unsupported_extension_raises_value_error(tmp_path: Path):
    f = tmp_path / "document.docx"
    f.write_text("dummy docx content", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file type"):
        load_document(str(f))


def test_load_missing_file_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_document("does_not_exist.txt")


def test_load_invalid_utf8_raises_unicode_decode_error(tmp_path: Path):
    f = tmp_path / "bad_encoding.txt"
    f.write_bytes(b"\xff\xfe\xfa\xfb")
    with pytest.raises(UnicodeDecodeError):
        load_document(str(f))


def test_load_hello_pdf_fixture():
    fixture_path = Path("tests/fixtures/hello.pdf")
    assert fixture_path.exists()
    assert fixture_path.stat().st_size < 5120  # < 5 KB
    text = load_document(str(fixture_path))
    assert "Hello DocuMind" in text


def test_load_blank_pdf_raises_value_error(tmp_path: Path):
    blank_pdf = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with blank_pdf.open("wb") as f:
        writer.write(f)

    with pytest.raises(ValueError, match="no extractable text found"):
        load_document(str(blank_pdf))


def test_load_corrupt_pdf_raises_pdf_stream_error(tmp_path: Path):
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"not a pdf")
    with pytest.raises(PdfStreamError):
        load_document(str(bad_pdf))
