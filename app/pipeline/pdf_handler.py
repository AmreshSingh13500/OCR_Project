"""
[MODULE]   app/pipeline/pdf_handler.py
[TASK]     T2.1 — Smart PDF detection (Step 2b)
[SUBTASKS] T2.1.1 PyMuPDF open; password detection → PasswordProtectedError (exact PRD string)
           T2.1.2 native text extraction from first MAX_PDF_PAGES_OCR pages, >100 chars gate
           T2.1.3 scanned branch: pdf2image conversion, keep first MAX_PDF_PAGES_OCR images
[SUMMARY]  Opens the downloaded PDF bytes with PyMuPDF and detects password protection
           before any other Step-2b logic runs. Per plan T2.1.1, both a `fitz.FileDataError`
           raised while opening and a truthy `doc.needs_pass` after opening are treated as
           password protection — PyMuPDF raises FileDataError for some encrypted PDFs it
           can't parse without a password, while others open but flag `needs_pass`.
           `extract_native_text()` reads the first MAX_PDF_PAGES_OCR pages' text layer;
           native PDFs clear NATIVE_PDF_MIN_CHARS easily and return a NativePdfResult,
           scanned/image-only PDFs don't and get None — the caller then calls
           `convert_scanned_pdf()`, which rasterizes up to MAX_PDF_PAGES_CONVERT pages
           (PRD hard cap) via pdf2image and keeps only the first MAX_PDF_PAGES_OCR images
           for the rest of the pipeline. Requires poppler-utils on the host (T2.1.4).
           Zero-page/corrupt handling (T2.1.5) lands in this file too, under its own tag.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T2.1.1, T2.1.2, T2.1.3
[HISTORY]  2026-07-16  T2.1.1  initial PyMuPDF open + password detection
           2026-07-16  T2.1.2  native text extraction + NativePdfResult
           2026-07-16  T2.1.3  scanned-branch pdf2image conversion + ScannedPdfResult
"""

from dataclasses import dataclass
from typing import List, Optional

import fitz
from PIL import Image
from pdf2image import convert_from_bytes

from app.config import (
    MAX_PDF_PAGES_CONVERT,
    MAX_PDF_PAGES_OCR,
    NATIVE_PDF_MIN_CHARS,
    PDF2IMAGE_DPI,
)


# [T2.1.1] Exact PRD string — frozen per CODING_RULES.md Rule 7 (error_message contract).
class PasswordProtectedError(Exception):
    pass


# [T2.1.1] Opens PDF bytes with PyMuPDF; a FileDataError at open time and a truthy
# needs_pass flag after a successful open are both observed PyMuPDF behaviors for
# encrypted PDFs (which one occurs depends on the PDF's encryption scheme).
def open_pdf(data: bytes) -> fitz.Document:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except fitz.FileDataError as exc:
        raise PasswordProtectedError("Password protected document") from exc

    if doc.needs_pass:
        raise PasswordProtectedError("Password protected document")

    return doc


@dataclass
class NativePdfResult:
    text: str


# [T2.1.2] Extract text from up to the first MAX_PDF_PAGES_OCR pages. A real text layer
# (native PDF) clears NATIVE_PDF_MIN_CHARS easily; a scanned/image-only PDF doesn't —
# that gap is the signal used to route between the native-text and scanned branches.
def extract_native_text(doc: fitz.Document) -> Optional[NativePdfResult]:
    page_limit = min(doc.page_count, MAX_PDF_PAGES_OCR)
    text = "".join(doc[i].get_text() for i in range(page_limit)).strip()
    if len(text) > NATIVE_PDF_MIN_CHARS:
        return NativePdfResult(text=text)
    return None


@dataclass
class ScannedPdfResult:
    images: List[Image.Image]


# [T2.1.3] Rasterizes up to MAX_PDF_PAGES_CONVERT pages (PRD §6.4 hard cap on any PDF),
# then keeps only the first MAX_PDF_PAGES_OCR images for the pipeline — the rest are
# discarded, never sent downstream (PRD Step 2 / §8 clarification #4).
def convert_scanned_pdf(data: bytes, page_count: int) -> ScannedPdfResult:
    last_page = min(page_count, MAX_PDF_PAGES_CONVERT)
    images = convert_from_bytes(
        data, dpi=PDF2IMAGE_DPI, first_page=1, last_page=last_page
    )
    return ScannedPdfResult(images=images[:MAX_PDF_PAGES_OCR])
