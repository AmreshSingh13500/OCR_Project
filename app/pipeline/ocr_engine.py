"""
[MODULE]   app/pipeline/ocr_engine.py
[TASK]     T3.2 — PaddleOCR engine (Step 4b, Branch A)
[SUBTASKS] T3.2.1 initialize PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False) once at startup
           T3.2.2 extract_text(): OCR ocr_ready image, join lines top-to-bottom, log confidence
           T3.2.3 extract_text_async(): asyncio.Lock + run_in_executor thread-safety guard
           T3.2.4 should_reroute_to_vision(): <20-char fallback rule, logs the reroute
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
           page's OCR output is too short to trust and logs when it is. It imports
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
"""

import asyncio
import logging

import numpy as np
from paddleocr import PaddleOCR

from app.config import BRANCH_B_VISION

logger = logging.getLogger(__name__)

# [T3.2.4] Per plan §4 T3.2.4 exactly — below this many characters, PaddleOCR likely
# failed to read the page (blank, garbled, or misrouted) and vision is the safer bet.
_MIN_OCR_CHARS = 20


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
def extract_text(ocr_ready: np.ndarray) -> str:
    """
    Run PaddleOCR on an ocr_ready binary image. Returns detected text lines joined
    top-to-bottom (newline-separated); "" if no text is detected. Per-line confidence
    is logged at DEBUG per plan §4 T3.2.2.
    """
    ocr = get_paddleocr()
    result = ocr.ocr(ocr_ready, cls=True)

    lines = result[0] if result else None
    if not lines:
        return ""

    lines_sorted = sorted(lines, key=lambda line: min(point[1] for point in line[0]))

    texts = []
    for _box, (text, confidence) in lines_sorted:
        logger.debug("OCR line: text=%r confidence=%.4f", text, confidence)
        texts.append(text)

    return "\n".join(texts)


# [T3.2.3] The shared PaddleOCR instance is not thread-safe under concurrent calls
# within one process — this lock serializes access so only one extract_text() call
# touches the engine at a time in this worker. Gunicorn's 4 worker processes each get
# their own instance (loaded independently at startup), so this still gives 4-way
# parallelism across the deployment; it only serializes within a single process.
_paddle_ocr_lock = asyncio.Lock()


async def extract_text_async(ocr_ready: np.ndarray) -> str:
    """
    Thread-safe async entry point for extract_text() — the one pipeline code should call
    from request-handling paths. Serializes access to the shared PaddleOCR engine via
    an asyncio.Lock, and runs the blocking OCR call in the default executor so the event
    loop stays free to handle other work while inference runs.
    """
    async with _paddle_ocr_lock:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, extract_text, ocr_ready)


# [T3.2.4] Per plan §4 T3.2.4 exactly. Doesn't perform the reroute itself — the
# orchestrator (T4.3) owns branch dispatch — just answers the question and logs when
# the answer is yes, so the reroute is visible in the logs even before T4.3 exists.
def should_reroute_to_vision(text: str) -> bool:
    """
    True when a Branch-A page's OCR output is too short to trust (<20 chars per the
    plan's fallback rule) and should be rerouted to Branch B (vision) instead.
    """
    if len(text) < _MIN_OCR_CHARS:
        logger.warning(
            "OCR fallback: only %d char(s) extracted (<%d threshold) — rerouting page to %s",
            len(text), _MIN_OCR_CHARS, BRANCH_B_VISION,
        )
        return True
    return False
