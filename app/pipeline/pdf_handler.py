"""
[MODULE]   app/pipeline/pdf_handler.py
[TASK]     T2.1 — Smart PDF detection (Step 2b)
[SUBTASKS] T2.1.1 PyMuPDF open; password detection → PasswordProtectedError (exact PRD string)
[SUMMARY]  Opens the downloaded PDF bytes with PyMuPDF and detects password protection
           before any other Step-2b logic runs. Per plan T2.1.1, both a `fitz.FileDataError`
           raised while opening and a truthy `doc.needs_pass` after opening are treated as
           password protection — PyMuPDF raises FileDataError for some encrypted PDFs it
           can't parse without a password, while others open but flag `needs_pass`. Native-
           vs-scanned text extraction (T2.1.2), scanned-branch image conversion (T2.1.3),
           and zero-page/corrupt handling (T2.1.5) land in this file too, under their own
           subtask tags.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T2.1.1
[HISTORY]  2026-07-16  T2.1.1  initial PyMuPDF open + password detection
"""

import fitz


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
