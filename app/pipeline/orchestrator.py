"""
[MODULE]   app/pipeline/orchestrator.py
[TASK]     T4.3 — Pipeline orchestrator
[SUBTASKS] T4.3.1 run_pipeline() wiring Steps 2->6; direct images skip Step 2b
           T4.3.2 processing_path assignment (native_pdf/paddleocr/vision_api); vision
                  wins any mixed-page case
           T4.3.3 error mapping table — 7 exception -> error_message strings exactly
                  per plan
[SUMMARY]  Wires the full pipeline together for one accepted request: download (Step 2a)
           -> native/scanned PDF detection (Step 2b) or direct-image passthrough ->
           OpenCV cleaning (Step 3) -> CLIP routing + PaddleOCR/vision extraction
           (Step 4) -> OpenAI structured extraction (Step 5) -> Laravel webhook delivery
           (Step 6). A native PDF (text layer > NATIVE_PDF_MIN_CHARS) skips straight from
           Step 2b to Step 5 with processing_path='native_pdf'; an image attached
           directly (not inside a PDF) skips Step 2b entirely and starts at Step 3 — same
           as a scanned PDF's rasterized pages. Per plan §4 T4.3.2 exactly: if any page
           ends up needing vision (originally routed there, or rerouted after a low-yield
           OCR result per T3.2.4), processing_path is 'vision_api' for the whole request
           and every page's image is sent together (extract_from_text/extract_from_images
           are mutually exclusive — no single call can mix raw text and images); only
           when every page's OCR output was trusted does processing_path stay
           'paddleocr'. `map_exception_to_error_message()` (T4.3.3) holds the frozen
           7-exception -> error_message lookup from plan §4 T4.3.3's table, keyed by
           exact exception type (never isinstance) since those exception classes were
           deliberately kept flat with no shared hierarchy for exactly this reason (see
           T1.3.3's note); anything not in the table falls through to "Internal
           processing error" with the full traceback logged. `schemas.py` (T1.2.2)
           doesn't exist yet, so `ProcessRequest` is defined here as the first formal
           definition of the PRD §4.1 request shape (same precedent as T4.1.1's
           EXTRACTED_DATA_JSON_SCHEMA and T4.2.1's build_webhook_payload) — T1.2.2 must
           mirror it when built. These three subtasks don't yet add up to a fault-
           tolerant pipeline: map_exception_to_error_message() is a pure mapping
           function, not wired into a try/except anywhere, so an exception raised in
           run_pipeline's chain still propagates uncaught today — the top-level
           try/except guaranteeing exactly one webhook per accepted request (T4.3.4) is
           what will call this mapping and is a separate subtask not yet applied here.
[PLAN]     IMPLEMENTATION_PLAN.md §4 -> T4.3.1, T4.3.2, T4.3.3
[HISTORY]  2026-07-17  T4.3.1  initial run_pipeline() wiring Steps 2->6 — new module, no
                                schemas.py/routes.py/webhook_client.py/error-string
                                changes (Rule 7 gate n/a)
           2026-07-17  T4.3.2  tagged the processing_path decision in
                                _extract_from_pages() (vision wins any mixed-page case,
                                per plan §4 T4.3.2 exactly) and added dedicated
                                mixed-page/reroute/multi-page-success tests — no
                                behavior change from T4.3.1's implementation, formal
                                verification + tagging only; no schemas.py/routes.py/
                                webhook_client.py/error-string changes (Rule 7 gate n/a)
           2026-07-17  T4.3.3  add _ERROR_MESSAGES + map_exception_to_error_message() —
                                Rule 7 gate checked: these are the 7 *existing* frozen
                                error_message strings from plan §4 T4.3.3's table
                                (already fixed at plan-authoring time, none invented
                                here), reproduced verbatim, not edited — additive/
                                contract-safe; no schemas.py/routes.py/webhook_client.py
                                changes
"""

import logging
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from PIL import Image

# NOTE: keep classifier (torch) imported before ocr_engine (paddlepaddle) — same Windows
# DLL conflict documented in app/main.py and TASKS.md §5 (2026-07-17, T3.2.4 note):
# importing paddlepaddle before torch in one process breaks torch's shm.dll load. This
# module is the only place besides main.py where both get imported together, so the
# import order here matters just as much as it does there — do not reorder.
from app.pipeline.classifier import classify, route_branch
from app.pipeline.ocr_engine import extract_text_async, should_reroute_to_vision

from app.config import BRANCH_A_PADDLEOCR, BRANCH_B_VISION
from app.pipeline.downloader import (
    ContentKind,
    DownloadError,
    FileTooLargeError,
    UnsupportedFileError,
    detect_content_kind,
    download_file,
)
from app.pipeline.image_cleaner import clean_image
from app.pipeline.llm_extractor import LLMError, extract_from_images, extract_from_text
from app.pipeline.pdf_handler import (
    CorruptFileError,
    PasswordProtectedError,
    convert_scanned_pdf,
    extract_native_text,
    open_pdf,
)
from app.pipeline.webhook_client import build_webhook_payload, send_webhook
from app.utils.logging import bind_case_context

logger = logging.getLogger(__name__)


# [T4.3.3] Exact 7-exception -> error_message mapping per plan §4 T4.3.3 — every string
# is frozen (CODING_RULES.md Rule 7): never edit an existing value, only add new rows.
# A flat dict keyed by exact exception type (not an isinstance chain) by design — the
# downloader/pdf_handler exceptions were deliberately kept as flat Exception subclasses
# with no shared hierarchy specifically to keep this lookup unambiguous (see T1.3.3's
# note): no exception type can ever match more than one row here.
_ERROR_MESSAGES: dict[type[Exception], str] = {
    PasswordProtectedError: "Password protected document",
    DownloadError: "Failed to download source file",
    FileTooLargeError: "File exceeds size limit",
    UnsupportedFileError: "Unsupported file type",
    CorruptFileError: "Corrupt or unreadable file",
    LLMError: "AI extraction service unavailable",
}

# [T4.3.3] The plan's 7th row ("any uncaught Exception") — the only row that also
# requires a full traceback in the logs, since anything not in _ERROR_MESSAGES is by
# definition an unanticipated bug rather than a recognized failure mode.
_DEFAULT_ERROR_MESSAGE = "Internal processing error"


# [T4.3.3] Maps a pipeline exception to its exact frozen error_message string. Falls
# through to _DEFAULT_ERROR_MESSAGE for anything not in the table, logging the full
# traceback in that case (plan §4 T4.3.3) so an unanticipated bug is never silently
# swallowed. Does not catch anything itself — wiring this into a top-level try/except
# that guarantees exactly one webhook per request is T4.3.4's job.
def map_exception_to_error_message(exc: Exception) -> str:
    message = _ERROR_MESSAGES.get(type(exc))
    if message is not None:
        return message
    logger.error("Unmapped exception during pipeline execution: %r", exc, exc_info=exc)
    return _DEFAULT_ERROR_MESSAGE


# [T4.3.1] First formal definition of the PRD §4.1 ProcessRequest shape — schemas.py
# (T1.2.2) doesn't exist yet. file_type/file_name/source_channel are carried for contract
# completeness but unused by run_pipeline itself: content kind is always re-derived from
# magic bytes (T1.3.2), never trusted from the caller-supplied file_type.
@dataclass
class ProcessRequest:
    case_id: str
    message_id: str
    file_url: str
    file_type: Optional[str] = None
    file_name: Optional[str] = None
    source_channel: Optional[str] = None


def _decode_image_bytes(data: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


def _pil_to_bgr(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)


# [T4.3.1] Steps 3+4 for one or more page images: cleans each, classifies it, and
# extracts via PaddleOCR or vision per page. A page routed to Branch A whose OCR yield
# is too low (T3.2.4) is rerouted to vision.
async def _extract_from_pages(images: list[np.ndarray], case_id: str) -> tuple[dict, str]:
    ocr_texts: list[str] = []
    vision_images: list[np.ndarray] = []
    needs_vision = False

    for image in images:
        cleaned = clean_image(image, case_id=case_id)
        vision_images.append(cleaned.vision_ready)

        label_index, confidence = classify(cleaned.vision_ready)
        branch = route_branch(label_index, confidence)

        if branch == BRANCH_A_PADDLEOCR:
            text = await extract_text_async(cleaned.ocr_ready)
            if not should_reroute_to_vision(text):
                ocr_texts.append(text)
                continue

        needs_vision = True

    # [T4.3.2] processing_path per plan §4 T4.3.2 exactly: 'paddleocr' only when every
    # page's OCR output was trusted; 'vision_api' wins the instant any single page needed
    # vision (originally routed there, or rerouted after a low-yield OCR result) — a
    # mixed-page document is never reported as 'paddleocr'. All pages' vision_ready
    # images are sent together in that case, since extract_from_text/extract_from_images
    # are mutually exclusive (no single call can mix raw text and images).
    if needs_vision:
        return extract_from_images(vision_images), BRANCH_B_VISION
    return extract_from_text("\n".join(ocr_texts)), BRANCH_A_PADDLEOCR


# [T4.3.1] Wires Steps 2 through 6 for one accepted request: download -> detect content
# kind -> native-PDF text / scanned-PDF pages / direct-image passthrough -> clean ->
# classify -> OCR-or-vision -> LLM -> webhook. A native PDF's text layer goes straight to
# Step 5 (no cleaning/classification needed for a real text layer); a directly-attached
# image (not inside a PDF) skips straight to Step 3, same as a scanned PDF's rasterized
# pages. Error mapping (T4.3.3) and the top-level try/except that guarantees exactly one
# webhook per request (T4.3.4) are separate subtasks — not yet applied here.
async def run_pipeline(req: ProcessRequest) -> None:
    bind_case_context(req.case_id, req.message_id)

    buffer = await download_file(req.file_url)
    data = buffer.read()
    kind = detect_content_kind(data)

    if kind == ContentKind.PDF:
        doc = open_pdf(data)
        native_result = extract_native_text(doc)
        if native_result is not None:
            extracted_data = extract_from_text(native_result.text)
            processing_path = "native_pdf"
        else:
            scanned = convert_scanned_pdf(data, doc.page_count)
            images = [_pil_to_bgr(page) for page in scanned.images]
            extracted_data, processing_path = await _extract_from_pages(images, req.case_id)
    elif kind == ContentKind.IMAGE:
        image = _decode_image_bytes(data)
        extracted_data, processing_path = await _extract_from_pages([image], req.case_id)
    else:
        raise UnsupportedFileError("Detected content is neither a PDF nor an image")

    payload = build_webhook_payload(
        case_id=req.case_id,
        message_id=req.message_id,
        status="success",
        processing_path=processing_path,
        extracted_data=extracted_data,
        error_message=None,
    )
    await send_webhook(payload)
