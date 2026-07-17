"""
[MODULE]   app/pipeline/ocr_engine.py
[TASK]     T3.2 — PaddleOCR engine (Step 4b, Branch A)
[SUBTASKS] T3.2.1 initialize PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False) once at startup
[SUMMARY]  Local CPU OCR engine for Branch A (printed documents). `load_paddleocr()`
           initializes a single PaddleOCR instance at app startup (lifespan) — angle
           classification on (photographed documents may be slightly rotated), English,
           CPU-only. Mirrors classifier.py's load/set/get pattern so the loaded engine is
           wired into main.py's lifespan once and made available to pipeline code without
           threading it through every call signature.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T3.2.1
[HISTORY]  2026-07-17  T3.2.1  initialize PaddleOCR at startup
"""

from paddleocr import PaddleOCR


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
