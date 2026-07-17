"""
[MODULE]   tests/test_pdf_handler.py
[TASK]     T2.1 — Smart PDF detection (Step 2b)
           T5.1 — Test suite completion
[SUBTASKS] T2.1.1 AC: password.pdf -> PasswordProtectedError; native.pdf opens normally
           T2.1.2 AC: native.pdf -> text path (NativePdfResult, >100 chars)
           T2.1.3 AC: scanned.pdf -> <=3 images kept (MAX_PDF_PAGES_OCR), page cap honored
           T2.1.5 AC: zero-page PDF -> CorruptFileError
           T5.1.2 backfilled committed pytest coverage for T2.1 using T5.1.1's real
                  fixtures (previously verified ad hoc per SUBTASKS.md)
[SUMMARY]  Tests pdf_handler.py against T5.1.1's real fixtures: native.pdf (real text
           layer, >100 chars) and password.pdf (AES-256 encrypted) are exercised for
           real; a zero-page PDF can't be produced by PyMuPDF itself (it refuses to
           save one), so that case stays covered via a mocked fitz.open, same as its
           original ad hoc verification. convert_scanned_pdf() against the real
           4-page scanned.pdf fixture is skipped on this Windows dev box (no
           poppler-utils / pdftoppm — see TASKS.md §5) and should be re-run once
           poppler is available (T6.1's Linux target, or a local install).
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T2.1.1, T2.1.2, T2.1.3, T2.1.5; §5 → T5.1.2
[HISTORY]  2026-07-17  T5.1.2  initial committed test file using real native.pdf/
                                password.pdf/scanned.pdf fixtures (backfills T2.1's
                                ad hoc verification)
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

import fitz
import pytest

from app.pipeline.pdf_handler import (
    CorruptFileError,
    NATIVE_PDF_MIN_CHARS,
    PasswordProtectedError,
    convert_scanned_pdf,
    extract_native_text,
    open_pdf,
)
from tests.fixtures.ground_truth import GROUND_TRUTH

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_HAS_POPPLER = shutil.which("pdftoppm") is not None


def _read(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def test_open_pdf_native_pdf_opens_normally():
    """[T2.1.1] AC: a plain (unencrypted) PDF opens without raising."""
    doc = open_pdf(_read("native.pdf"))
    assert doc.page_count == 1


def test_open_pdf_password_protected_raises_exact_message():
    """[T2.1.1] AC: password.pdf raises PasswordProtectedError with the exact frozen PRD string."""
    with pytest.raises(PasswordProtectedError, match="Password protected document"):
        open_pdf(_read("password.pdf"))


def test_open_pdf_zero_page_raises_corrupt_file_error(monkeypatch):
    """[T2.1.5] AC: a PDF that opens but has zero pages raises CorruptFileError.

    PyMuPDF itself refuses to save a real zero-page PDF, so this mocks fitz.open —
    same approach as T2.1.5's original ad hoc verification (see SUBTASKS.md).
    """

    @dataclass
    class _ZeroPageDoc:
        needs_pass: bool = False
        page_count: int = 0

    monkeypatch.setattr(fitz, "open", lambda **kwargs: _ZeroPageDoc())
    with pytest.raises(CorruptFileError):
        open_pdf(b"irrelevant, fitz.open is mocked")


def test_extract_native_text_native_pdf_returns_result_with_expected_content():
    """[T2.1.2] AC: native.pdf's text layer clears NATIVE_PDF_MIN_CHARS and contains the fabricated fixture content."""
    doc = open_pdf(_read("native.pdf"))
    result = extract_native_text(doc)

    assert result is not None
    assert len(result.text) > NATIVE_PDF_MIN_CHARS
    expected = GROUND_TRUTH["native.pdf"]
    assert expected["patient_name"] in result.text
    assert expected["diagnosis"] in result.text


def test_extract_native_text_scanned_pdf_returns_none():
    """[T2.1.2]/[T2.1.3] AC: scanned.pdf has no text layer -> extract_native_text returns None, routing to the scanned/pdf2image branch."""
    doc = open_pdf(_read("scanned.pdf"))
    assert extract_native_text(doc) is None


@pytest.mark.skipif(not _HAS_POPPLER, reason="poppler-utils (pdftoppm) not installed on this dev box")
def test_convert_scanned_pdf_keeps_first_max_pages_ocr_images():
    """[T2.1.3] AC: scanned.pdf (4 pages) -> convert_scanned_pdf keeps only the first MAX_PDF_PAGES_OCR (3) images."""
    data = _read("scanned.pdf")
    doc = fitz.open(stream=data, filetype="pdf")
    result = convert_scanned_pdf(data, doc.page_count)

    assert len(result.images) == 3
