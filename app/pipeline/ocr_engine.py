"""
[MODULE]   app/pipeline/ocr_engine.py
[TASK]     T3.2 — PaddleOCR engine (Step 4b, Branch A)
[SUBTASKS] T3.2.1 initialize PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False) once at startup
           T3.2.2 extract_text(): OCR ocr_ready image, join lines top-to-bottom, log confidence
[SUMMARY]  Local CPU OCR engine for Branch A (printed documents). `load_paddleocr()`
           initializes a single PaddleOCR instance at app startup (lifespan) — angle
           classification on (photographed documents may be slightly rotated), English,
           CPU-only. Mirrors classifier.py's load/set/get pattern so the loaded engine is
           wired into main.py's lifespan once and made available to pipeline code without
           threading it through every call signature. `extract_text()` runs OCR on the
           `ocr_ready` binary image and joins detected lines in top-to-bottom reading
           order — sorted explicitly by each box's y-coordinate rather than trusting
           PaddleOCR's own internal detection order (which empirically is already sorted,
           but that's an implementation detail of the library, not a contract).
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T3.2.1, T3.2.2
[HISTORY]  2026-07-17  T3.2.1  initialize PaddleOCR at startup
           2026-07-17  T3.2.2  add extract_text() — OCR + top-to-bottom join + confidence log
"""

import logging

import numpy as np
from paddleocr import PaddleOCR

logger = logging.getLogger(__name__)


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
