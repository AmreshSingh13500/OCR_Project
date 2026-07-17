"""
[MODULE]   tests/test_pipeline_e2e.py
[TASK]     T4.3 — Pipeline orchestrator
[SUBTASKS] T4.3.1 run_pipeline() wiring Steps 2->6; direct images skip Step 2b
[SUMMARY]  Unit tests for orchestrator.py's run_pipeline() wiring. All of run_pipeline's
           collaborators (download, PDF handling, CLIP, PaddleOCR, OpenAI, webhook) are
           monkeypatched at the orchestrator module level so this exercises only the
           branching/wiring logic itself — each collaborator already has its own
           correctness verified in its own subtask (real fixture-based tests for these
           paths are T5.1's job, once tests/fixtures/ exists). Covers only the happy-path
           scenarios T4.3.1 wires: native PDF text path, scanned/printed image ->
           paddleocr path, and a direct (non-PDF) image -> vision_api path. Error mapping
           (T4.3.3) and the guaranteed-one-webhook try/except (T4.3.4) aren't built yet,
           so error scenarios aren't tested here.
[PLAN]     IMPLEMENTATION_PLAN.md §4 -> T4.3.1
[HISTORY]  2026-07-17  T4.3.1  initial happy-path wiring tests (native_pdf, paddleocr,
                                vision_api)
"""

import io
from dataclasses import dataclass

import numpy as np
import pytest

from app.pipeline import orchestrator
from app.pipeline.downloader import ContentKind
from app.pipeline.image_cleaner import CleanedImage
from app.pipeline.orchestrator import ProcessRequest, run_pipeline


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
async def test_run_pipeline_unsupported_content_raises(monkeypatch):
    """[T4.3.1] Neither PDF nor image magic bytes -> UnsupportedFileError (mapping to a webhook error is T4.3.3's job)."""
    from app.pipeline.downloader import UnsupportedFileError

    monkeypatch.setattr(orchestrator, "download_file", _async_return(io.BytesIO(b"not a real file")))
    monkeypatch.setattr(orchestrator, "detect_content_kind", lambda data: ContentKind.UNSUPPORTED)

    with pytest.raises(UnsupportedFileError):
        await run_pipeline(ProcessRequest(case_id="case-4", message_id="msg-4", file_url="https://x/file.bin"))


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


def _record_webhook(sink: list):
    async def _fn(payload):
        sink.append(payload)
    return _fn


def _fail(message: str):
    def _fn(*args, **kwargs):
        raise AssertionError(message)
    return _fn
