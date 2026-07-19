"""
[MODULE]   app/pipeline/ocr_engine.py
[TASK]     T3.2 — PaddleOCR engine (Step 4b, Branch A)
           T8.2 — Multi-language documents + extraction fidelity (additive)
           T8.4 — Non-English field values in English + explicit OCR non-English detect
[SUBTASKS] T3.2.1 initialize PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False) once at startup
           T3.2.2 extract_text(): OCR ocr_ready image, join lines top-to-bottom, log confidence
           T3.2.3 extract_text_async(): asyncio.Lock + run_in_executor thread-safety guard
           T3.2.4 should_reroute_to_vision(): <20-char fallback rule, logs the reroute
           T8.2.2 OcrResult(text, mean_confidence) + <0.80 mean-confidence reroute rule
           T8.4.2 should_reroute_to_vision(): non-Latin-script reroute (use vision to translate)
[SUMMARY]  Local CPU OCR engine for Branch A (printed documents). `load_paddleocr()`
           initializes a single PaddleOCR instance at app startup (lifespan) — angle
           classification on (photographed documents may be slightly rotated), English,
           CPU-only. Mirrors classifier.py's load/set/get pattern so the loaded engine is
           wired into main.py's lifespan once and made available to pipeline code without
           threading it through every call signature. `extract_text()` runs OCR on the
           `ocr_ready` binary image and joins detected lines in top-to-bottom reading
           order — sorted explicitly by each box's y-coordinate rather than trusting
           PaddleOCR's own internal detection order (which empirically is already sorted,
           but that's an implementation detail of the library, not a contract). PaddleOCR
           itself is not thread-safe under concurrent calls within one process, so
           `extract_text_async()` is the only entry point pipeline code should call from
           request-handling paths — it serializes access with an `asyncio.Lock` and runs
           the blocking OCR call via `run_in_executor` so the event loop is never blocked
           by CPU-bound inference. Gunicorn's 4 worker processes still give 4-way
           parallelism; the lock only serializes calls within a single worker process.
           `should_reroute_to_vision()` is a separate decision step the orchestrator
           (T4.3) calls after getting OCR text — it doesn't reroute anything itself
           (extract_text() has no notion of "branches"), it just answers whether this
           page's OCR output is too short (T3.2.4) or too low-confidence (T8.2.2) to
           trust and logs when it is. Since T8.2.2, extract_text()/extract_text_async()
           return `OcrResult(text, mean_confidence)` — the mean of PaddleOCR's per-line
           recognition confidences — because this engine only reads `lang='en'`: an
           Arabic/foreign-script or badly degraded page still "reads" as long-but-garbled
           Latin text at low confidence, which the char-count rule alone would wrongly
           trust and the LLM would then plausibilize into fabricated values (the observed
           wrong-doctor-name failure). Low mean confidence → vision, which reads any
           language natively. It imports
           `BRANCH_B_VISION` from app/config.py, not from classifier.py — importing
           classifier.py (torch) here hit a real Windows DLL conflict with paddlepaddle
           (paddle-before-torch import order breaks torch's shm.dll load); config.py has
           no ML dependencies, so it can't trigger that conflict.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T3.2.1, T3.2.2, T3.2.3, T3.2.4
[HISTORY]  2026-07-17  T3.2.1  initialize PaddleOCR at startup
           2026-07-17  T3.2.2  add extract_text() — OCR + top-to-bottom join + confidence log
           2026-07-17  T3.2.3  add extract_text_async() — asyncio.Lock + run_in_executor guard
           2026-07-17  T3.2.4  add should_reroute_to_vision() — <20-char fallback rule;
                                imports BRANCH_B_VISION from app/config.py (not
                                classifier.py) to avoid a torch/paddle DLL load-order
                                conflict — see classifier.py [HISTORY] for the full story
           2026-07-19  T8.2.2  extract_text()/extract_text_async() now return
                                OcrResult(text, mean_confidence);
                                should_reroute_to_vision() gains an optional
                                mean_confidence arg and a <0.80 reroute rule — internal
                                refactor only (Rule 7B, full suite re-verified green);
                                no schemas.py/routes.py/webhook_client.py/error-string
                                changes (Rule 7 gate n/a)
           2026-07-19  T8.4.2  add _non_latin_letter_ratio() + a third reroute trigger in
                                should_reroute_to_vision() (>10% non-Latin script ->
                                vision). Signature unchanged (backward compatible);
                                internal refactor only (Rule 7B), no contract surface
"""

import asyncio
import logging
import unicodedata
from dataclasses import dataclass
from typing import Optional

import numpy as np
from paddleocr import PaddleOCR

from app.config import BRANCH_B_VISION

logger = logging.getLogger(__name__)

# [T8.4.2] Above this share of non-Latin alphabetic characters in the OCR output, the
# page contains meaningful non-English (Arabic/Kurdish/…) script — route it to vision,
# which reads any language and (per the T8.4.1 prompt) returns accurate English. Small
# so a stray non-Latin glyph in an otherwise-English page doesn't trip it.
_MAX_NON_LATIN_RATIO = 0.10

# [T3.2.4] Per plan §4 T3.2.4 exactly — below this many characters, PaddleOCR likely
# failed to read the page (blank, garbled, or misrouted) and vision is the safer bet.
_MIN_OCR_CHARS = 20

# [T8.2.2] Below this mean per-line recognition confidence, the text is likely garbled —
# typically a non-Latin-script page read by this en-only engine, or a badly degraded
# print. Clean English prints score ~0.90+; trusting garbled text is what lets the LLM
# plausibilize wrong names, so vision (reads any language) is the safer bet. Tunable in
# T7.2 alongside the other thresholds.
_MIN_OCR_MEAN_CONFIDENCE = 0.80


# [T8.2.2] extract_text()'s return shape: the joined text plus the mean of PaddleOCR's
# per-line recognition confidences (0.0 when nothing was detected) so the reroute
# decision can consider quality, not just quantity, of the OCR output.
@dataclass
class OcrResult:
    text: str
    mean_confidence: float


# [T3.2.1] Initialize PaddleOCR once at app startup (lifespan) — CPU only; angle
# classification on since photographed documents may be slightly rotated.
def load_paddleocr() -> PaddleOCR:
    """Load the PaddleOCR engine. Returns a ready-to-use PaddleOCR instance."""
    return PaddleOCR(use_angle_cls=True, lang="en", use_gpu=False)


# Module-level storage (populated by lifespan in main.py via Rule 3)
_paddle_ocr: PaddleOCR = None


def set_paddleocr(ocr: PaddleOCR) -> None:
    """Called by main.py lifespan to wire the loaded engine into this module."""
    global _paddle_ocr
    _paddle_ocr = ocr


def get_paddleocr() -> PaddleOCR:
    """Retrieve the cached PaddleOCR engine."""
    if _paddle_ocr is None:
        raise RuntimeError("PaddleOCR engine not loaded — check lifespan initialization")
    return _paddle_ocr


# [T3.2.2] Runs PaddleOCR on the ocr_ready binary image. PaddleOCR returns [None] rather
# than an empty list when no text is detected (empirically verified) — handled explicitly
# rather than assuming a list. Lines are sorted by each box's top-left y-coordinate before
# joining, so the output reading order is guaranteed by our own code, not an assumption
# about the library's internal detection order.
def extract_text(ocr_ready: np.ndarray) -> OcrResult:
    """
    Run PaddleOCR on an ocr_ready binary image. Returns an OcrResult with detected text
    lines joined top-to-bottom (newline-separated) and the mean per-line recognition
    confidence (T8.2.2); text="" / confidence=0.0 if no text is detected. Per-line
    confidence is logged at DEBUG per plan §4 T3.2.2.
    """
    ocr = get_paddleocr()
    result = ocr.ocr(ocr_ready, cls=True)

    lines = result[0] if result else None
    if not lines:
        return OcrResult(text="", mean_confidence=0.0)

    lines_sorted = sorted(lines, key=lambda line: min(point[1] for point in line[0]))

    texts = []
    confidences = []
    for _box, (text, confidence) in lines_sorted:
        logger.debug("OCR line: text=%r confidence=%.4f", text, confidence)
        texts.append(text)
        confidences.append(float(confidence))

    return OcrResult(
        text="\n".join(texts),
        mean_confidence=sum(confidences) / len(confidences),
    )


# [T3.2.3] The shared PaddleOCR instance is not thread-safe under concurrent calls
# within one process — this lock serializes access so only one extract_text() call
# touches the engine at a time in this worker. Gunicorn's 4 worker processes each get
# their own instance (loaded independently at startup), so this still gives 4-way
# parallelism across the deployment; it only serializes within a single process.
_paddle_ocr_lock = asyncio.Lock()


async def extract_text_async(ocr_ready: np.ndarray) -> OcrResult:
    """
    Thread-safe async entry point for extract_text() — the one pipeline code should call
    from request-handling paths. Serializes access to the shared PaddleOCR engine via
    an asyncio.Lock, and runs the blocking OCR call in the default executor so the event
    loop stays free to handle other work while inference runs.
    """
    async with _paddle_ocr_lock:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, extract_text, ocr_ready)


# [T8.4.2] Share of alphabetic characters that are NOT Latin script — the explicit
# "OCR saw non-English text" signal. Non-alphabetic characters (digits, punctuation,
# whitespace) are ignored so a numbers-heavy English page isn't misjudged. A character
# with no Unicode name (rare control/private-use) counts as non-Latin (conservative).
def _non_latin_letter_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    non_latin = 0
    for ch in letters:
        try:
            if "LATIN" not in unicodedata.name(ch):
                non_latin += 1
        except ValueError:
            non_latin += 1
    return non_latin / len(letters)


# [T3.2.4] Per plan §4 T3.2.4 exactly (char rule). Doesn't perform the reroute itself —
# the orchestrator (T4.3) owns branch dispatch — just answers the question and logs when
# the answer is yes, so the reroute is visible in the logs even before T4.3 exists.
# [T8.2.2] mean_confidence (optional so the char rule can still be checked alone) adds
# the quality gate: long-but-garbled output — an Arabic/foreign-script page read by this
# en-only engine, or a badly degraded print — passes the char count but must not be
# trusted, or the LLM downstream plausibilizes wrong values from mangled text.
# [T8.4.2] A third trigger: if the OCR text itself contains meaningful non-Latin script
# (the user's "if OCR detects non-English, use vision for accurate translation"),
# reroute so vision reads it and returns accurate English (T8.4.1 prompt). NOTE: this
# en-only PaddleOCR rarely emits non-Latin characters — for a foreign-script page the
# confidence gate above is the practical trigger; this check is the explicit, correct,
# and forward-compatible signal (fires immediately if the engine is ever made
# multilingual, and catches any non-Latin the recognizer does emit).
def should_reroute_to_vision(text: str, mean_confidence: Optional[float] = None) -> bool:
    """
    True when a Branch-A page's OCR output should be rerouted to Branch B (vision):
    <20 chars (T3.2.4's fallback rule), mean recognition confidence below 0.80
    (T8.2.2's quality gate — skipped when mean_confidence is None), or the text is
    substantially non-Latin script (T8.4.2 — use vision for accurate translation).
    """
    if len(text) < _MIN_OCR_CHARS:
        logger.warning(
            "OCR fallback: only %d char(s) extracted (<%d threshold) — rerouting page to %s",
            len(text), _MIN_OCR_CHARS, BRANCH_B_VISION,
        )
        return True
    if mean_confidence is not None and mean_confidence < _MIN_OCR_MEAN_CONFIDENCE:
        logger.warning(
            "OCR fallback: mean confidence %.3f (<%.2f threshold) — likely garbled/"
            "non-English text, rerouting page to %s",
            mean_confidence, _MIN_OCR_MEAN_CONFIDENCE, BRANCH_B_VISION,
        )
        return True
    non_latin_ratio = _non_latin_letter_ratio(text)
    if non_latin_ratio > _MAX_NON_LATIN_RATIO:
        logger.warning(
            "OCR fallback: %.0f%% non-Latin script detected (>%.0f%% threshold) — "
            "rerouting page to %s for accurate translation",
            non_latin_ratio * 100, _MAX_NON_LATIN_RATIO * 100, BRANCH_B_VISION,
        )
        return True
    return False
