"""
[MODULE]   tests/test_pipeline_e2e.py
[TASK]     T4.3 — Pipeline orchestrator
[SUBTASKS] T4.3.1 run_pipeline() wiring Steps 2->6; direct images skip Step 2b
           T4.3.2 processing_path assignment (native_pdf/paddleocr/vision_api); vision
                  wins any mixed-page case
           T4.3.3 error mapping table — 7 exception -> error_message strings exactly
                  per plan
           T4.3.4 top-level try/except: every accepted request -> exactly one webhook
                  call
[SUMMARY]  Unit tests for orchestrator.py's run_pipeline() wiring. All of run_pipeline's
           collaborators (download, PDF handling, CLIP, PaddleOCR, OpenAI, webhook) are
           monkeypatched at the orchestrator module level so this exercises only the
           branching/wiring logic itself — each collaborator already has its own
           correctness verified in its own subtask (real fixture-based tests for these
           paths are T5.1's job, once tests/fixtures/ exists). Covers the single-page
           happy paths T4.3.1 wires (native PDF text, scanned/printed -> paddleocr,
           direct image -> vision_api) plus T4.3.2's multi-page processing_path rule:
           a mixed page set (one paddleocr page + one vision page, or one clean OCR page
           + one low-yield-reroute page) reports 'vision_api' and sends every page's
           image, never mixing text and images in one LLM call; an all-paddleocr multi-
           page set stays 'paddleocr' with concatenated text. Verifies T4.3.3's
           map_exception_to_error_message() against all 7 rows of the plan's table
           (parametrized) plus the fallback row's traceback logging. Verifies T4.3.4's
           guarantee end-to-end through run_pipeline() itself: a mapped exception raised
           during extraction (PasswordProtectedError) and an unmapped one (RuntimeError)
           each produce exactly one webhook call with status='error',
           processing_path=None, extracted_data=None, and the correct error_message.
[PLAN]     IMPLEMENTATION_PLAN.md §4 -> T4.3.1, T4.3.2, T4.3.3, T4.3.4
[HISTORY]  2026-07-17  T4.3.1  initial happy-path wiring tests (native_pdf, paddleocr,
                                vision_api)
           2026-07-17  T4.3.2  add mixed-page tests: vision-routed page mixed with a
                                paddleocr page, low-OCR-yield reroute mixed with a clean
                                OCR page, and an all-paddleocr multi-page control case
           2026-07-17  T4.3.3  add parametrized map_exception_to_error_message() tests
                                for all 7 plan-table rows + the fallback traceback-log
                                assertion
           2026-07-17  T4.3.4  add run_pipeline() error-path tests: mapped exception ->
                                exactly one error webhook with the frozen message;
                                unmapped exception -> exactly one error webhook with
                                'Internal processing error' + traceback logged
"""

import io
import logging
from dataclasses import dataclass

import numpy as np
import pytest

from app.pipeline import orchestrator
from app.pipeline.downloader import ContentKind, DownloadError, FileTooLargeError, UnsupportedFileError
from app.pipeline.image_cleaner import CleanedImage
from app.pipeline.llm_extractor import LLMError
from app.pipeline.orchestrator import ProcessRequest, run_pipeline
from app.pipeline.pdf_handler import CorruptFileError, PasswordProtectedError


@dataclass
class _FakeDoc:
    page_count: int


@dataclass
class _FakeScannedResult:
    images: list


def _fake_cleaned_image() -> CleanedImage:
    array = np.zeros((10, 10), dtype=np.uint8)
    return CleanedImage(ocr_ready=array, vision_ready=array)


@pytest.mark.asyncio
async def test_run_pipeline_native_pdf_uses_text_path(monkeypatch):
    """[T4.3.1] Native PDF (text layer found) skips cleaning/classify/OCR and calls extract_from_text; processing_path='native_pdf'."""
    sent_payloads = []

    monkeypatch.setattr(orchestrator, "download_file", _async_return(io.BytesIO(b"%PDF-fake")))
    monkeypatch.setattr(orchestrator, "detect_content_kind", lambda data: ContentKind.PDF)
    monkeypatch.setattr(orchestrator, "open_pdf", lambda data: _FakeDoc(page_count=1))
    monkeypatch.setattr(
        orchestrator, "extract_native_text",
        lambda doc: _NativeResult(text="a long native pdf text layer" * 10),
    )
    monkeypatch.setattr(
        orchestrator, "extract_from_text",
        lambda text: {"patient_name": "Jane Doe", "doctor_name": None, "diagnosis": None,
                       "procedure": None, "cost": None, "medicines": None},
    )
    monkeypatch.setattr(orchestrator, "send_webhook", _record_webhook(sent_payloads))
    # Should never be called on the native-text path.
    monkeypatch.setattr(orchestrator, "clean_image", _fail("clean_image should not run"))
    monkeypatch.setattr(orchestrator, "classify", _fail("classify should not run"))

    await run_pipeline(ProcessRequest(case_id="case-1", message_id="msg-1", file_url="https://x/doc.pdf"))

    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload["processing_path"] == "native_pdf"
    assert payload["status"] == "success"
    assert payload["extracted_data"]["patient_name"] == "Jane Doe"
    assert payload["error_message"] is None


@pytest.mark.asyncio
async def test_run_pipeline_scanned_printed_page_uses_paddleocr_path(monkeypatch):
    """[T4.3.1] Scanned PDF, page classified as printed -> Branch A -> extract_from_text on OCR output; processing_path='paddleocr'."""
    sent_payloads = []

    monkeypatch.setattr(orchestrator, "download_file", _async_return(io.BytesIO(b"%PDF-fake")))
    monkeypatch.setattr(orchestrator, "detect_content_kind", lambda data: ContentKind.PDF)
    monkeypatch.setattr(orchestrator, "open_pdf", lambda data: _FakeDoc(page_count=1))
    monkeypatch.setattr(orchestrator, "extract_native_text", lambda doc: None)
    monkeypatch.setattr(
        orchestrator, "convert_scanned_pdf",
        lambda data, page_count: _FakeScannedResult(images=[_FakePilImage()]),
    )
    monkeypatch.setattr(orchestrator, "_pil_to_bgr", lambda image: np.zeros((10, 10, 3), dtype=np.uint8))
    monkeypatch.setattr(orchestrator, "clean_image", lambda image, case_id=None: _fake_cleaned_image())
    monkeypatch.setattr(orchestrator, "classify", lambda vision_ready: (0, 0.9))
    monkeypatch.setattr(orchestrator, "route_branch", lambda label, conf: "paddleocr")
    monkeypatch.setattr(orchestrator, "extract_text_async", _async_return("printed report text, plenty of characters"))
    monkeypatch.setattr(orchestrator, "should_reroute_to_vision", lambda text: False)
    monkeypatch.setattr(
        orchestrator, "extract_from_text",
        lambda text: {"patient_name": None, "doctor_name": "Dr. Smith", "diagnosis": None,
                       "procedure": None, "cost": None, "medicines": None},
    )
    monkeypatch.setattr(orchestrator, "send_webhook", _record_webhook(sent_payloads))
    monkeypatch.setattr(orchestrator, "extract_from_images", _fail("extract_from_images should not run"))

    await run_pipeline(ProcessRequest(case_id="case-2", message_id="msg-2", file_url="https://x/scan.pdf"))

    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload["processing_path"] == "paddleocr"
    assert payload["extracted_data"]["doctor_name"] == "Dr. Smith"


@pytest.mark.asyncio
async def test_run_pipeline_direct_image_handwritten_uses_vision_path(monkeypatch):
    """[T4.3.1] Direct (non-PDF) image skips Step 2b; handwritten -> Branch B -> extract_from_images; processing_path='vision_api'."""
    sent_payloads = []

    monkeypatch.setattr(orchestrator, "download_file", _async_return(io.BytesIO(b"\xff\xd8\xff-fake-jpeg")))
    monkeypatch.setattr(orchestrator, "detect_content_kind", lambda data: ContentKind.IMAGE)
    monkeypatch.setattr(orchestrator, "_decode_image_bytes", lambda data: np.zeros((10, 10, 3), dtype=np.uint8))
    monkeypatch.setattr(orchestrator, "clean_image", lambda image, case_id=None: _fake_cleaned_image())
    monkeypatch.setattr(orchestrator, "classify", lambda vision_ready: (1, 0.8))
    monkeypatch.setattr(orchestrator, "route_branch", lambda label, conf: "vision_api")
    monkeypatch.setattr(
        orchestrator, "extract_from_images",
        lambda images: {"patient_name": None, "doctor_name": None, "diagnosis": "flu",
                         "procedure": None, "cost": None, "medicines": None},
    )
    monkeypatch.setattr(orchestrator, "send_webhook", _record_webhook(sent_payloads))
    monkeypatch.setattr(orchestrator, "extract_text_async", _fail("extract_text_async should not run"))
    monkeypatch.setattr(orchestrator, "extract_from_text", _fail("extract_from_text should not run"))

    await run_pipeline(ProcessRequest(case_id="case-3", message_id="msg-3", file_url="https://x/photo.jpg"))

    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload["processing_path"] == "vision_api"
    assert payload["extracted_data"]["diagnosis"] == "flu"


@pytest.mark.asyncio
async def test_run_pipeline_mixed_pages_one_vision_page_wins_vision_path(monkeypatch):
    """[T4.3.2] AC: page 1 routes paddleocr, page 2 routes vision_api -> whole request reports 'vision_api', both pages' images sent, extract_from_text never called."""
    sent_payloads = []
    captured_images = []

    monkeypatch.setattr(orchestrator, "download_file", _async_return(io.BytesIO(b"%PDF-fake")))
    monkeypatch.setattr(orchestrator, "detect_content_kind", lambda data: ContentKind.PDF)
    monkeypatch.setattr(orchestrator, "open_pdf", lambda data: _FakeDoc(page_count=2))
    monkeypatch.setattr(orchestrator, "extract_native_text", lambda doc: None)
    monkeypatch.setattr(
        orchestrator, "convert_scanned_pdf",
        lambda data, page_count: _FakeScannedResult(images=[_FakePilImage(), _FakePilImage()]),
    )
    monkeypatch.setattr(orchestrator, "_pil_to_bgr", lambda image: np.zeros((10, 10, 3), dtype=np.uint8))
    monkeypatch.setattr(orchestrator, "clean_image", lambda image, case_id=None: _fake_cleaned_image())
    monkeypatch.setattr(orchestrator, "classify", lambda vision_ready: (0, 0.9))
    monkeypatch.setattr(orchestrator, "route_branch", _sequence_fn(["paddleocr", "vision_api"]))
    monkeypatch.setattr(orchestrator, "extract_text_async", _async_return("first page ocr text, plenty long enough"))
    monkeypatch.setattr(orchestrator, "should_reroute_to_vision", lambda text: False)

    def _fake_extract_from_images(images):
        captured_images.extend(images)
        return {"patient_name": None, "doctor_name": None, "diagnosis": None,
                "procedure": None, "cost": None, "medicines": None}

    monkeypatch.setattr(orchestrator, "extract_from_images", _fake_extract_from_images)
    monkeypatch.setattr(orchestrator, "extract_from_text", _fail("extract_from_text should not run when any page needs vision"))
    monkeypatch.setattr(orchestrator, "send_webhook", _record_webhook(sent_payloads))

    await run_pipeline(ProcessRequest(case_id="case-5", message_id="msg-5", file_url="https://x/mixed.pdf"))

    assert len(sent_payloads) == 1
    assert sent_payloads[0]["processing_path"] == "vision_api"
    assert len(captured_images) == 2  # both pages' vision_ready images sent, not just the vision-routed one


@pytest.mark.asyncio
async def test_run_pipeline_mixed_pages_low_ocr_yield_reroute_wins_vision_path(monkeypatch):
    """[T4.3.2] AC: both pages route paddleocr but page 2's OCR yield is too low (T3.2.4 reroute) -> whole request reports 'vision_api'."""
    sent_payloads = []
    captured_images = []

    monkeypatch.setattr(orchestrator, "download_file", _async_return(io.BytesIO(b"%PDF-fake")))
    monkeypatch.setattr(orchestrator, "detect_content_kind", lambda data: ContentKind.PDF)
    monkeypatch.setattr(orchestrator, "open_pdf", lambda data: _FakeDoc(page_count=2))
    monkeypatch.setattr(orchestrator, "extract_native_text", lambda doc: None)
    monkeypatch.setattr(
        orchestrator, "convert_scanned_pdf",
        lambda data, page_count: _FakeScannedResult(images=[_FakePilImage(), _FakePilImage()]),
    )
    monkeypatch.setattr(orchestrator, "_pil_to_bgr", lambda image: np.zeros((10, 10, 3), dtype=np.uint8))
    monkeypatch.setattr(orchestrator, "clean_image", lambda image, case_id=None: _fake_cleaned_image())
    monkeypatch.setattr(orchestrator, "classify", lambda vision_ready: (0, 0.9))
    monkeypatch.setattr(orchestrator, "route_branch", lambda label, conf: "paddleocr")
    monkeypatch.setattr(
        orchestrator, "extract_text_async",
        _sequence_async_fn(["plenty of readable text on this page", "x"]),
    )
    monkeypatch.setattr(orchestrator, "should_reroute_to_vision", _sequence_fn([False, True]))

    def _fake_extract_from_images(images):
        captured_images.extend(images)
        return {"patient_name": None, "doctor_name": None, "diagnosis": None,
                "procedure": None, "cost": None, "medicines": None}

    monkeypatch.setattr(orchestrator, "extract_from_images", _fake_extract_from_images)
    monkeypatch.setattr(orchestrator, "extract_from_text", _fail("extract_from_text should not run when a page is rerouted to vision"))
    monkeypatch.setattr(orchestrator, "send_webhook", _record_webhook(sent_payloads))

    await run_pipeline(ProcessRequest(case_id="case-6", message_id="msg-6", file_url="https://x/mixed2.pdf"))

    assert len(sent_payloads) == 1
    assert sent_payloads[0]["processing_path"] == "vision_api"
    assert len(captured_images) == 2


@pytest.mark.asyncio
async def test_run_pipeline_multi_page_all_paddleocr_stays_paddleocr_path(monkeypatch):
    """[T4.3.2] AC: both pages route paddleocr and OCR succeeds on both -> processing_path stays 'paddleocr' (not mixed), text concatenated."""
    sent_payloads = []
    captured_text = {}

    monkeypatch.setattr(orchestrator, "download_file", _async_return(io.BytesIO(b"%PDF-fake")))
    monkeypatch.setattr(orchestrator, "detect_content_kind", lambda data: ContentKind.PDF)
    monkeypatch.setattr(orchestrator, "open_pdf", lambda data: _FakeDoc(page_count=2))
    monkeypatch.setattr(orchestrator, "extract_native_text", lambda doc: None)
    monkeypatch.setattr(
        orchestrator, "convert_scanned_pdf",
        lambda data, page_count: _FakeScannedResult(images=[_FakePilImage(), _FakePilImage()]),
    )
    monkeypatch.setattr(orchestrator, "_pil_to_bgr", lambda image: np.zeros((10, 10, 3), dtype=np.uint8))
    monkeypatch.setattr(orchestrator, "clean_image", lambda image, case_id=None: _fake_cleaned_image())
    monkeypatch.setattr(orchestrator, "classify", lambda vision_ready: (0, 0.9))
    monkeypatch.setattr(orchestrator, "route_branch", lambda label, conf: "paddleocr")
    monkeypatch.setattr(
        orchestrator, "extract_text_async",
        _sequence_async_fn(["page one text long enough", "page two text long enough"]),
    )
    monkeypatch.setattr(orchestrator, "should_reroute_to_vision", lambda text: False)

    def _fake_extract_from_text(text):
        captured_text["value"] = text
        return {"patient_name": None, "doctor_name": None, "diagnosis": None,
                "procedure": None, "cost": None, "medicines": None}

    monkeypatch.setattr(orchestrator, "extract_from_text", _fake_extract_from_text)
    monkeypatch.setattr(orchestrator, "extract_from_images", _fail("extract_from_images should not run when no page needs vision"))
    monkeypatch.setattr(orchestrator, "send_webhook", _record_webhook(sent_payloads))

    await run_pipeline(ProcessRequest(case_id="case-7", message_id="msg-7", file_url="https://x/two_page_scan.pdf"))

    assert len(sent_payloads) == 1
    assert sent_payloads[0]["processing_path"] == "paddleocr"
    assert "page one text long enough" in captured_text["value"]
    assert "page two text long enough" in captured_text["value"]


@pytest.mark.asyncio
async def test_run_pipeline_unsupported_content_sends_error_webhook(monkeypatch):
    """[T4.3.4] AC: neither PDF nor image magic bytes -> UnsupportedFileError caught by the top-level try/except -> exactly one error webhook, error_message='Unsupported file type'."""
    sent_payloads = []

    monkeypatch.setattr(orchestrator, "download_file", _async_return(io.BytesIO(b"not a real file")))
    monkeypatch.setattr(orchestrator, "detect_content_kind", lambda data: ContentKind.UNSUPPORTED)
    monkeypatch.setattr(orchestrator, "send_webhook", _record_webhook(sent_payloads))

    await run_pipeline(ProcessRequest(case_id="case-4", message_id="msg-4", file_url="https://x/file.bin"))

    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload["status"] == "error"
    assert payload["processing_path"] is None
    assert payload["extracted_data"] is None
    assert payload["error_message"] == "Unsupported file type"


@pytest.mark.asyncio
async def test_run_pipeline_mapped_exception_sends_exactly_one_error_webhook(monkeypatch):
    """[T4.3.4] AC: a mapped exception (PasswordProtectedError) raised during extraction -> exactly one webhook call, status='error', processing_path=None, extracted_data=None, frozen error_message."""
    sent_payloads = []

    monkeypatch.setattr(orchestrator, "download_file", _async_return(io.BytesIO(b"%PDF-fake")))
    monkeypatch.setattr(orchestrator, "detect_content_kind", lambda data: ContentKind.PDF)
    monkeypatch.setattr(orchestrator, "open_pdf", _raise(PasswordProtectedError("Password protected document")))
    monkeypatch.setattr(orchestrator, "send_webhook", _record_webhook(sent_payloads))

    await run_pipeline(ProcessRequest(case_id="case-8", message_id="msg-8", file_url="https://x/locked.pdf"))

    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload["status"] == "error"
    assert payload["processing_path"] is None
    assert payload["extracted_data"] is None
    assert payload["error_message"] == "Password protected document"


@pytest.mark.asyncio
async def test_run_pipeline_unmapped_exception_sends_exactly_one_internal_error_webhook(monkeypatch, caplog):
    """[T4.3.4] AC: an unanticipated exception during extraction still produces exactly one webhook call, status='error', error_message='Internal processing error', traceback logged."""
    sent_payloads = []

    monkeypatch.setattr(orchestrator, "download_file", _async_return(io.BytesIO(b"%PDF-fake")))
    monkeypatch.setattr(orchestrator, "detect_content_kind", _raise(RuntimeError("something nobody anticipated")))
    monkeypatch.setattr(orchestrator, "send_webhook", _record_webhook(sent_payloads))

    with caplog.at_level(logging.ERROR):
        await run_pipeline(ProcessRequest(case_id="case-9", message_id="msg-9", file_url="https://x/whatever"))

    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload["status"] == "error"
    assert payload["error_message"] == "Internal processing error"
    assert any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize(
    "exc, expected_message",
    [
        (PasswordProtectedError("x"), "Password protected document"),
        (DownloadError("x"), "Failed to download source file"),
        (FileTooLargeError("x"), "File exceeds size limit"),
        (UnsupportedFileError("x"), "Unsupported file type"),
        (CorruptFileError("x"), "Corrupt or unreadable file"),
        (LLMError("x"), "AI extraction service unavailable"),
        (ValueError("some unanticipated bug"), "Internal processing error"),
    ],
)
def test_map_exception_to_error_message_matches_plan_table(exc, expected_message):
    """[T4.3.3] AC: each of the plan's 7 exception rows (incl. the uncaught-Exception fallback) maps to its exact frozen error_message string."""
    assert orchestrator.map_exception_to_error_message(exc) == expected_message


def test_map_exception_to_error_message_logs_traceback_for_unmapped_exception(caplog):
    """[T4.3.3] AC: an unmapped exception ("any uncaught Exception" row) logs the full traceback, per plan §4 T4.3.3."""
    with caplog.at_level(logging.ERROR):
        try:
            raise ValueError("boom")
        except ValueError as exc:
            message = orchestrator.map_exception_to_error_message(exc)

    assert message == "Internal processing error"
    assert any(record.exc_info for record in caplog.records)


# --- test helpers -----------------------------------------------------------------

@dataclass
class _NativeResult:
    text: str


class _FakePilImage:
    def convert(self, mode):
        return self


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


def _raise(exc: Exception):
    """Sync replacement raising `exc` when called — for monkeypatching a sync collaborator to fail."""
    def _fn(*args, **kwargs):
        raise exc
    return _fn


def _sequence_fn(values: list):
    """Returns each value in order on successive calls — one per page, in call order."""
    values_iter = iter(values)

    def _fn(*args, **kwargs):
        return next(values_iter)
    return _fn


def _sequence_async_fn(values: list):
    values_iter = iter(values)

    async def _fn(*args, **kwargs):
        return next(values_iter)
    return _fn


def _record_webhook(sink: list):
    async def _fn(payload):
        sink.append(payload)
    return _fn


def _fail(message: str):
    def _fn(*args, **kwargs):
        raise AssertionError(message)
    return _fn
