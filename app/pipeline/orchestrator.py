"""
[MODULE]   app/pipeline/orchestrator.py
[TASK]     T4.3 — Pipeline orchestrator
[SUBTASKS] T4.3.1 run_pipeline() wiring Steps 2->6; direct images skip Step 2b
[SUMMARY]  Wires the full pipeline together for one accepted request: download (Step 2a)
           -> native/scanned PDF detection (Step 2b) or direct-image passthrough ->
           OpenCV cleaning (Step 3) -> CLIP routing + PaddleOCR/vision extraction
           (Step 4) -> OpenAI structured extraction (Step 5) -> Laravel webhook delivery
           (Step 6). A native PDF (text layer > NATIVE_PDF_MIN_CHARS) skips straight from
           Step 2b to Step 5; an image attached directly (not inside a PDF) skips Step 2b
           entirely and starts at Step 3 — same as a scanned PDF's rasterized pages. If
           any page ends up needing vision (originally routed there, or rerouted after a
           low-yield OCR result per T3.2.4), the whole call uses the vision path with
           every page's image rather than mixing text and image content in one LLM call
           (extract_from_text/extract_from_images are mutually exclusive); T4.3.2 owns
           formally verifying that "vision wins mixed" rule. `schemas.py` (T1.2.2)
           doesn't exist yet, so `ProcessRequest` is defined here as the first formal
           definition of the PRD §4.1 request shape (same precedent as T4.1.1's
           EXTRACTED_DATA_JSON_SCHEMA and T4.2.1's build_webhook_payload) — T1.2.2 must
           mirror it when built. This subtask is happy-path wiring only: the 7-exception
           error mapping (T4.3.3) and the top-level try/except guaranteeing exactly one
           webhook per accepted request (T4.3.4) are separate subtasks not yet applied
           here, so any exception raised in this chain currently propagates uncaught
           (same "bare call, error handling comes later" pattern as T4.1.2/T4.2.1).
[PLAN]     IMPLEMENTATION_PLAN.md §4 -> T4.3.1
[HISTORY]  2026-07-17  T4.3.1  initial run_pipeline() wiring Steps 2->6 — new module, no
                                schemas.py/routes.py/webhook_client.py/error-string
                                changes (Rule 7 gate n/a)
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
    UnsupportedFileError,
    detect_content_kind,
    download_file,
)
from app.pipeline.image_cleaner import clean_image
from app.pipeline.llm_extractor import extract_from_images, extract_from_text
from app.pipeline.pdf_handler import convert_scanned_pdf, extract_native_text, open_pdf
from app.pipeline.webhook_client import build_webhook_payload, send_webhook
from app.utils.logging import bind_case_context

logger = logging.getLogger(__name__)


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


# Steps 3+4 for one or more page images: cleans each, classifies it, and extracts via
# PaddleOCR or vision per page. A page routed to Branch A whose OCR yield is too low
# (T3.2.4) is rerouted to vision. Per plan §4 T4.3.2 ("vision wins mixed"), if *any* page
# ends up needing vision, the whole call uses the vision path with every page's
# vision_ready image instead of mixing text and image content in one LLM call.
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
