"""
[MODULE]   app/pipeline/orchestrator.py
[TASK]     T4.3 — Pipeline orchestrator
           T1.2 — Auth & API endpoints
           T5.2 — Security hardening (app level)
           T8.1 — Generalized any-document extraction (additive contract update)
           T8.2 — Multi-language documents + extraction fidelity (additive)
           T8.3 — Vision-path accuracy (original-image passthrough)
[SUBTASKS] T8.1.3 success path sets error_message=ALL_FIELDS_NULL_MESSAGE when every
                  extracted field is null (wires T4.1.5's signal into the webhook)
           T8.2.2 thread OcrResult(text, mean_confidence) into the reroute decision
           T8.3.1 send the ORIGINAL color image (not cleaned.vision_ready) to the vision LLM
           T1.2.2 import ProcessRequest from app.schemas instead of a local duplicate
           T4.3.1 _run_extraction() wiring Steps 2->5; direct images skip Step 2b
           T4.3.2 processing_path assignment (native_pdf/paddleocr/vision_api); vision
                  wins any mixed-page case
           T4.3.3 error mapping table — 7 exception -> error_message strings exactly
                  per plan
           T4.3.4 top-level try/except: every accepted request -> exactly one webhook
                  call
           T4.3.5 per-request timing log: total ms + per-step ms
           T5.2.2 log extracted-field presence booleans at INFO, actual values at
                  DEBUG only, on the success path
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
           'paddleocr'. `ProcessRequest` is now imported from `app.schemas` (T1.2.2) —
           it used to be defined here as a plain dataclass since schemas.py didn't exist
           yet; now that it does, this module consumes the canonical Pydantic model
           instead of keeping a second, drifting definition (CLAUDE.md: internal code may
           be refactored freely provided the full pytest suite stays green — every
           existing call site here already constructed it via keyword args only, so the
           dataclass-to-BaseModel swap is behavior-preserving). `_run_extraction()`
           (T4.3.1) does Steps 2-5 and returns/raises;
           `run_pipeline()` (T4.3.4) wraps it in a top-level try/except so exactly one
           webhook call happens either way — the success branch builds a 'success'
           payload from `_run_extraction()`'s result (setting error_message to T4.1.5's
           frozen ALL_FIELDS_NULL_MESSAGE when every extracted field is null — the
           unreadable-document signal, T8.1.3), the except branch maps whatever
           was raised via `map_exception_to_error_message()` (T4.3.3, the frozen
           7-exception -> error_message lookup from plan §4 T4.3.3's table, keyed by
           exact exception type — never isinstance — since those exception classes were
           deliberately kept flat with no shared hierarchy for exactly this reason, see
           T1.3.3's note) into an error payload with `processing_path=None` and
           `extracted_data=None`; anything not in the table falls through to "Internal
           processing error" with the full traceback logged. `send_webhook()` itself
           never raises to its caller (T4.2.2/T4.2.3's CRITICAL-log contract), so
           calling it exactly once after the try/except/else has resolved is sufficient
           to guarantee the "exactly one webhook per accepted request" AC — there is no
           code path that calls it zero or twice. `_StepTimings`/`_timed()` (T4.3.5)
           accumulate elapsed milliseconds per named step (`step2a_download`,
           `step2b_pdf_detect`, `step3_clean`, `step4a_classify`, `step4b_ocr`,
           `step5_llm`, `step6_webhook`) across the whole call — a multi-page request's
           Steps 3-4 run once per page, so their samples are summed rather than
           overwritten — and `run_pipeline()` logs one line with the total wall-clock ms
           plus that per-step breakdown at the very end, on both the success and error
           paths (a `_timed()` block records its elapsed time on the way out even if the
           block raised). `_log_extracted_data_privacy_safe()` (T5.2.2) runs on the
           success branch only, right before the webhook payload is built: an INFO log
           with per-field presence booleans (never the values), and a DEBUG log with the
           actual field values — CLAUDE.md's "medical field values at DEBUG only" rule
           enforced structurally here rather than left to caller discipline.
[PLAN]     IMPLEMENTATION_PLAN.md §4 -> T4.3.1, T4.3.2, T4.3.3, T4.3.4, T4.3.5; T1.2.2
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
           2026-07-17  T4.3.4  extracted Steps 2-5 out of run_pipeline() into
                                _run_extraction() (T4.3.1's tag moves with it, no
                                behavior change) so run_pipeline() itself becomes the
                                top-level try/except that maps any raised exception via
                                map_exception_to_error_message() and guarantees exactly
                                one send_webhook() call per request; no schemas.py/
                                routes.py/webhook_client.py/error-string changes
                                (Rule 7 gate n/a) — reuses build_webhook_payload()'s
                                existing contract fields unchanged
           2026-07-17  T4.3.5  add _StepTimings/_timed() and thread `timings` through
                                _run_extraction()/_extract_from_pages(); run_pipeline()
                                logs one "Pipeline request timing" line per request
                                (total_ms + per-step ms) on both the success and error
                                paths; no schemas.py/routes.py/webhook_client.py/
                                error-string changes (Rule 7 gate n/a) — logging-only
                                addition, no change to any existing return value/payload
                                shape
           2026-07-17  T1.2.2  replaced the local ProcessRequest dataclass with an
                                import from the newly-built app.schemas — Rule 7 gate
                                checked: same 6 fields, same 3 required/3 optional split,
                                additive/contract-safe; no behavior change (BaseModel
                                construction via keyword args is drop-in compatible with
                                the dataclass it replaces), full suite re-verified green
           2026-07-17  T5.2.2  add _log_extracted_data_privacy_safe(), called from
                                run_pipeline()'s success branch right before the webhook
                                payload is built — logs an INFO line with per-field
                                presence booleans only, and a separate DEBUG line with
                                the actual field values, so a deployment running at the
                                default INFO level never has medical field values in its
                                logs; no schemas.py/routes.py/webhook_client.py/
                                error-string changes here (Rule 7 gate n/a — this only
                                adds new log lines, no change to the webhook payload
                                itself or any return value)
           2026-07-18  T8.1.3  success path now sets error_message=ALL_FIELDS_NULL_MESSAGE
                                (T4.1.5's existing frozen string, reused verbatim — no
                                string edited/added) when is_all_fields_null() — closes
                                the gap where T4.1.5 defined the signal but run_pipeline
                                always sent error_message=None on success; Rule 7 gate
                                checked: error_message was already a nullable key, its
                                type/meaning unchanged, behavior matches plan §8-2's
                                already-documented contract — additive/contract-safe
           2026-07-19  T8.2.2  _extract_from_pages() consumes ocr_engine's new
                                OcrResult and passes mean_confidence into
                                should_reroute_to_vision() — internal refactor (Rule 7B),
                                no payload-shape/error-string changes (Rule 7 gate n/a)
           2026-07-19  T8.3.1  _extract_from_pages() now appends the ORIGINAL color image
                                to vision_images (was cleaned.vision_ready) — vision LLM
                                reads the undegraded photo; classification + PaddleOCR
                                still use cleaned images. Internal refactor (Rule 7B),
                                no payload-shape/error-string changes (Rule 7 gate n/a)
"""

import logging
import time
from contextlib import contextmanager

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
from app.pipeline.llm_extractor import (
    ALL_FIELDS_NULL_MESSAGE,
    LLMError,
    extract_from_images,
    extract_from_text,
    is_all_fields_null,
)
from app.pipeline.pdf_handler import (
    CorruptFileError,
    PasswordProtectedError,
    convert_scanned_pdf,
    extract_native_text,
    open_pdf,
)
from app.pipeline.webhook_client import build_webhook_payload, send_webhook
from app.schemas import ProcessRequest
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


# [T4.3.5] Accumulates elapsed milliseconds per named step across one run_pipeline()
# call. A dict (not a fixed dataclass) because a multi-page request runs Steps 3-4
# once per page — record() sums repeat samples into the same key instead of overwriting,
# so the final log line reports total time spent in each step, not just the last page's.
class _StepTimings:
    def __init__(self) -> None:
        self._ms: dict[str, float] = {}

    def record(self, step: str, elapsed_ms: float) -> None:
        self._ms[step] = self._ms.get(step, 0.0) + elapsed_ms

    def as_dict(self) -> dict[str, float]:
        return {step: round(ms, 1) for step, ms in self._ms.items()}


# [T4.3.5] Times one named step and records it into `timings`, even if the timed block
# raises — a failed request still gets partial per-step timing up to the point of
# failure, which is exactly what's useful for diagnosing where a slow/failing request
# spent its time.
@contextmanager
def _timed(timings: _StepTimings, step: str):
    start = time.monotonic()
    try:
        yield
    finally:
        timings.record(step, (time.monotonic() - start) * 1000)


# [T5.2.2] Privacy-safe logging of extracted medical data (CLAUDE.md: "medical field
# values at DEBUG only"). Field *presence* is not sensitive on its own (it's just a
# shape descriptor — "did the LLM find a diagnosis or not"), so it's safe at INFO; the
# actual values (patient name, diagnosis, etc.) are only ever logged at DEBUG, which is
# off by default (config.py's LOG_LEVEL default is INFO).
def _log_extracted_data_privacy_safe(extracted_data: dict) -> None:
    presence = {field: value is not None for field, value in extracted_data.items()}
    logger.info("Extracted data field presence: %s", presence)
    logger.debug("Extracted data field values: %s", extracted_data)


def _decode_image_bytes(data: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


def _pil_to_bgr(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)


# [T4.3.1] Steps 3+4 for one or more page images: cleans each, classifies it, and
# extracts via PaddleOCR or vision per page. A page routed to Branch A whose OCR yield
# is too low (T3.2.4) is rerouted to vision. [T4.3.5] Per-step timing is accumulated
# across all pages into the same 'step3_clean'/'step4a_classify'/'step4b_ocr' keys —
# a 3-page request's Step 3 time is the sum of cleaning all 3 pages, not just one.
async def _extract_from_pages(
    images: list[np.ndarray], case_id: str, timings: _StepTimings
) -> tuple[dict, str]:
    ocr_texts: list[str] = []
    vision_images: list[np.ndarray] = []
    needs_vision = False

    for image in images:
        with _timed(timings, "step3_clean"):
            cleaned = clean_image(image, case_id=case_id)
        # [T8.3.1] The vision LLM gets the ORIGINAL color image, not cleaned.vision_ready.
        # OpenCV cleaning (grayscale + CLAHE + text-based deskew) exists to help PaddleOCR
        # (Branch A); it degrades GPT-4o vision — it discards color and the deskew can
        # mis-rotate a photo whose dominant "text pixels" aren't text (e.g. an ultrasound
        # cone), smearing small header text like a clinic/doctor name. classification and
        # the PaddleOCR path still use the cleaned images; only what's sent to the LLM
        # changes. (T2.2.4 already kept CLAHE-gray over binary "because binarization
        # destroys detail the vision model needs" — this takes that one step further.)
        vision_images.append(image)

        with _timed(timings, "step4a_classify"):
            label_index, confidence = classify(cleaned.vision_ready)
        branch = route_branch(label_index, confidence)

        if branch == BRANCH_A_PADDLEOCR:
            with _timed(timings, "step4b_ocr"):
                ocr_result = await extract_text_async(cleaned.ocr_ready)
            # [T8.2.2] Reroute on low mean confidence too, not just low char count —
            # garbled-but-long OCR output (non-English script, degraded print) must go
            # to vision instead of feeding the LLM mangled text it would "correct".
            if not should_reroute_to_vision(ocr_result.text, ocr_result.mean_confidence):
                ocr_texts.append(ocr_result.text)
                continue

        needs_vision = True

    # [T4.3.2] processing_path per plan §4 T4.3.2 exactly: 'paddleocr' only when every
    # page's OCR output was trusted; 'vision_api' wins the instant any single page needed
    # vision (originally routed there, or rerouted after a low-yield OCR result) — a
    # mixed-page document is never reported as 'paddleocr'. All pages' original images
    # (T8.3.1) are sent together in that case, since extract_from_text/extract_from_images
    # are mutually exclusive (no single call can mix raw text and images).
    with _timed(timings, "step5_llm"):
        if needs_vision:
            return extract_from_images(vision_images), BRANCH_B_VISION
        return extract_from_text("\n".join(ocr_texts)), BRANCH_A_PADDLEOCR


# [T4.3.1] Steps 2 through 5 for one accepted request: download -> detect content kind
# -> native-PDF text / scanned-PDF pages / direct-image passthrough -> clean -> classify
# -> OCR-or-vision -> LLM. A native PDF's text layer goes straight to Step 5 (no
# cleaning/classification needed for a real text layer); a directly-attached image (not
# inside a PDF) skips straight to Step 3, same as a scanned PDF's rasterized pages. Step 6
# (webhook) deliberately isn't built here — run_pipeline() owns it so it can guarantee
# exactly one webhook call regardless of whether this function raises (T4.3.4).
# [T4.3.5] `timings` is threaded through (not a module global) so concurrent requests
# never share or clobber each other's per-step measurements.
async def _run_extraction(req: ProcessRequest, timings: _StepTimings) -> tuple[dict, str]:
    with _timed(timings, "step2a_download"):
        buffer = await download_file(req.file_url)
    data = buffer.read()
    kind = detect_content_kind(data)

    if kind == ContentKind.PDF:
        with _timed(timings, "step2b_pdf_detect"):
            doc = open_pdf(data)
            native_result = extract_native_text(doc)
        if native_result is not None:
            with _timed(timings, "step5_llm"):
                extracted_data = extract_from_text(native_result.text)
            return extracted_data, "native_pdf"
        with _timed(timings, "step2b_pdf_detect"):
            scanned = convert_scanned_pdf(data, doc.page_count)
            images = [_pil_to_bgr(page) for page in scanned.images]
        return await _extract_from_pages(images, req.case_id, timings)
    if kind == ContentKind.IMAGE:
        image = _decode_image_bytes(data)
        return await _extract_from_pages([image], req.case_id, timings)
    raise UnsupportedFileError("Detected content is neither a PDF nor an image")


# [T4.3.4] Top-level try/except per plan §4 T4.3.4: every accepted request produces
# exactly one webhook call, success or error, never zero and never two. Any exception
# raised anywhere in _run_extraction's chain (typed pipeline exceptions or an
# unanticipated bug) is mapped via T4.3.3's map_exception_to_error_message() into an
# error payload instead of propagating — build_webhook_payload()/send_webhook() are
# called exactly once, after the try/except has already decided success vs. error, so
# there's no path that calls send_webhook zero or twice. send_webhook() itself never
# raises to its caller either way (T4.2.2/T4.2.3's CRITICAL-log contract), so this is
# the only place a webhook failure could otherwise go unnoticed.
# [T4.3.5] Logs one timing line per request: total wall-clock ms for the whole call plus
# the per-step ms breakdown from `timings` — recorded even on the error path, since
# _timed() records elapsed time on the way out regardless of whether the timed block
# raised, so a failed request's log line still shows where the time went up to failure.
async def run_pipeline(req: ProcessRequest) -> None:
    bind_case_context(req.case_id, req.message_id)
    request_start = time.monotonic()
    timings = _StepTimings()

    try:
        extracted_data, processing_path = await _run_extraction(req, timings)
    except Exception as exc:
        error_message = map_exception_to_error_message(exc)
        logger.warning("Pipeline request failed: error_message=%r", error_message)
        payload = build_webhook_payload(
            case_id=req.case_id,
            message_id=req.message_id,
            status="error",
            processing_path=None,
            extracted_data=None,
            error_message=error_message,
        )
    else:
        _log_extracted_data_privacy_safe(extracted_data)
        # [T8.1.3] T4.1.5's unreadable-document signal, finally wired into the payload:
        # every field null (incl. T8.1.1's document_type/summary/details — the T8.1.2
        # prompt instructs all-null for unreadable documents) -> status stays "success"
        # (Manual Review is Laravel's call, PRD §6.2) but error_message carries the
        # frozen ALL_FIELDS_NULL_MESSAGE so Laravel can flag it. Any readable document
        # has at least document_summary set -> error_message stays None.
        all_null = is_all_fields_null(extracted_data)
        if all_null:
            logger.warning("All extracted fields null - flagging possible unreadable document")
        payload = build_webhook_payload(
            case_id=req.case_id,
            message_id=req.message_id,
            status="success",
            processing_path=processing_path,
            extracted_data=extracted_data,
            error_message=ALL_FIELDS_NULL_MESSAGE if all_null else None,
        )

    with _timed(timings, "step6_webhook"):
        await send_webhook(payload)

    total_ms = round((time.monotonic() - request_start) * 1000, 1)
    logger.info("Pipeline request timing: total_ms=%s steps_ms=%s", total_ms, timings.as_dict())
