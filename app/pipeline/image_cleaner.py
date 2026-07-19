"""
[MODULE]   app/pipeline/image_cleaner.py
[TASK]     T2.2 — OpenCV pre-processing (Step 3)
[SUBTASKS] T2.2.1 grayscale conversion (BGR→GRAY)
           T2.2.2 deskew via minAreaRect (Hough-line fallback) + confidence gate
           T2.2.3 CLAHE on grayscale before thresholding (glare/lighting fix)
           T2.2.4 adaptive threshold; clean_image() pipeline returns CleanedImage
           T2.2.5 DEBUG_SAVE_IMAGES dumps each stage to scratch dir with case_id prefix
[SUMMARY]  Deterministic image-cleaning pipeline for Step 3: `clean_image()` runs
           grayscale → deskew → CLAHE → adaptive threshold, returning a `CleanedImage`
           with both an OCR-ready binary image (PaddleOCR, Branch A) and the
           pre-threshold CLAHE grayscale "vision_ready" image. Since T8.3.1,
           vision_ready's consumer is CLIP classification (T3.1.4) only — the LLM vision
           path receives the ORIGINAL color image from the orchestrator instead, because
           this cleaning (built for OCR) degrades what a vision LLM reads best. Runs on
           in-memory numpy arrays only, never touches disk
           unless `DEBUG_SAVE_IMAGES=true`, in which case each stage is written to the
           gitignored `debug_images/` scratch dir prefixed with the caller's `case_id`
           (T2.2.5) — a no-op otherwise. `deskew()` estimates the skew angle from
           thresholded foreground pixels via minAreaRect, falling back to Hough line
           detection when there isn't enough foreground to trust that estimate; it skips
           rotation entirely below a small-angle/low-confidence gate so it never makes an
           already-straight image worse. `apply_clahe()` runs on the deskewed grayscale
           before any thresholding — fixes glare/uneven lighting on photographed pages
           and medicine blister packs.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T2.2.1, T2.2.2, T2.2.3, T2.2.4, T2.2.5
[HISTORY]  2026-07-17  T2.2.1  initial grayscale conversion
           2026-07-17  T2.2.2  deskew with minAreaRect/Hough estimation + confidence gate
           2026-07-17  T2.2.3  CLAHE contrast enhancement
           2026-07-17  T2.2.4  adaptive threshold + clean_image() pipeline + CleanedImage
           2026-07-17  T2.2.5  DEBUG_SAVE_IMAGES per-stage dump; clean_image() gained
                                optional case_id param — internal signature, no external
                                contract, additive default so existing callers are unaffected
           2026-07-19  (doc)   T8.3.1 changed vision_ready's consumer: the orchestrator
                                now sends the ORIGINAL color image to the LLM vision path;
                                vision_ready feeds CLIP classification only. No code
                                change in this file — header/comments synced to match
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.config import settings

# [T2.2.5] Gitignored scratch dir (see .gitignore) — never committed, never the only copy
# of anything; purely a debugging aid enabled by DEBUG_SAVE_IMAGES.
_DEBUG_IMAGE_DIR = Path("debug_images")

# [T2.2.2] Below this angle, rotating does more harm (interpolation blur) than good.
_DESKEW_MIN_ANGLE_DEG = 0.5
# [T2.2.2] Fewer foreground pixels than this makes minAreaRect's angle unreliable —
# fall back to Hough line detection instead of trusting a noisy estimate.
_MIN_FOREGROUND_PIXELS = 100
# [T2.2.3] Per plan §4 T2.2.3 exactly.
_CLAHE_CLIP_LIMIT = 2.0
_CLAHE_TILE_GRID_SIZE = (8, 8)
# [T2.2.4] Per plan §4 T2.2.4 exactly.
_ADAPTIVE_THRESH_BLOCK_SIZE = 31
_ADAPTIVE_THRESH_C = 15


# [T2.2.1] BGR→GRAY conversion — first step of the cleaning pipeline.
def to_grayscale(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


# [T2.2.2] Primary angle estimator: fit a minimum-area rectangle around thresholded
# foreground (text) pixels. Returns None when there's too little foreground to trust.
# Points must be in (x, y) order — np.where gives (row, col) i.e. (y, x), so it's
# reversed below. OpenCV >= 4.5 reports minAreaRect's angle in [0, 90) rather than the
# older (-90, 0] convention, so the correction is "subtract 90 when width < height",
# not the classic "angle < -45" check (empirically verified against known rotations).
def _estimate_angle_min_area_rect(gray: np.ndarray) -> Optional[float]:
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ys, xs = np.where(thresh > 0)
    if xs.shape[0] < _MIN_FOREGROUND_PIXELS:
        return None
    coords = np.column_stack((xs, ys)).astype(np.float32)
    (_center, (rect_w, rect_h), angle) = cv2.minAreaRect(coords)
    if rect_w < rect_h:
        angle -= 90
    return angle


# [T2.2.2] Fallback angle estimator: median angle of near-horizontal Hough line
# segments, used when minAreaRect doesn't have enough foreground to be reliable.
def _estimate_angle_hough(gray: np.ndarray) -> Optional[float]:
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10
    )
    if lines is None:
        return None
    angles = [
        angle
        for x1, y1, x2, y2 in lines[:, 0]
        if -45 <= (angle := np.degrees(np.arctan2(y2 - y1, x2 - x1))) <= 45
    ]
    if not angles:
        return None
    return float(np.median(angles))


# [T2.2.2] Deskews a grayscale image. Skips rotation (returns input unchanged) when no
# estimator is confident enough or the estimated angle is negligible — avoids making an
# already-straight image worse, which is a bigger accuracy risk than leaving skew as-is.
def deskew(gray: np.ndarray) -> np.ndarray:
    angle = _estimate_angle_min_area_rect(gray)
    if angle is None:
        angle = _estimate_angle_hough(gray)

    if angle is None or abs(angle) < _DESKEW_MIN_ANGLE_DEG:
        return gray

    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


# [T2.2.3] Contrast-limited adaptive histogram equalization — run on grayscale before
# any thresholding so uneven lighting/glare (e.g. a photographed medicine blister pack)
# doesn't get baked into a bad binary threshold downstream.
def apply_clahe(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=_CLAHE_CLIP_LIMIT, tileGridSize=_CLAHE_TILE_GRID_SIZE)
    return clahe.apply(gray)


@dataclass
class CleanedImage:
    ocr_ready: np.ndarray
    vision_ready: np.ndarray


# [T2.2.5] Writes one pipeline stage to the debug scratch dir. No-op unless
# DEBUG_SAVE_IMAGES is set, so the pipeline stays in-memory-only by default (CLAUDE.md).
def _debug_save_stage(case_id: Optional[str], stage: str, image: np.ndarray) -> None:
    if not settings.DEBUG_SAVE_IMAGES:
        return
    _DEBUG_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    prefix = case_id or "unknown"
    cv2.imwrite(str(_DEBUG_IMAGE_DIR / f"{prefix}_{stage}.png"), image)


# [T2.2.4] Full Step-3 pipeline: grayscale → deskew → CLAHE → adaptive threshold.
# ocr_ready is the binarized output (PaddleOCR, Branch A); vision_ready is the
# pre-threshold CLAHE grayscale — since T8.3.1 consumed by CLIP classification (T3.1.4)
# only, the LLM vision path gets the original color image from the orchestrator.
# [T2.2.5] case_id is optional (defaults to None → "unknown" prefix) since the pipeline
# orchestrator that owns per-request case IDs (T4.3) doesn't exist yet; it's only ever
# used to name debug dumps, never to change cleaning behavior.
def clean_image(image: np.ndarray, case_id: Optional[str] = None) -> CleanedImage:
    gray = to_grayscale(image)
    _debug_save_stage(case_id, "1_grayscale", gray)

    deskewed = deskew(gray)
    _debug_save_stage(case_id, "2_deskewed", deskewed)

    vision_ready = apply_clahe(deskewed)
    _debug_save_stage(case_id, "3_clahe_vision_ready", vision_ready)

    ocr_ready = cv2.adaptiveThreshold(
        vision_ready,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        _ADAPTIVE_THRESH_BLOCK_SIZE,
        _ADAPTIVE_THRESH_C,
    )
    _debug_save_stage(case_id, "4_threshold_ocr_ready", ocr_ready)

    return CleanedImage(ocr_ready=ocr_ready, vision_ready=vision_ready)
