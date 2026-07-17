"""
[MODULE]   tests/test_image_cleaner.py
[TASK]     T2.2 — OpenCV pre-processing (Step 3)
           T5.1 — Test suite completion
[SUBTASKS] T2.2.1 AC: grayscale conversion — shape/dtype
           T2.2.2 AC: deskew — skewed fixture becomes ~horizontal (within ±1°), skips
                  rotation on an already-straight/blank image
           T2.2.3 AC: CLAHE — contrast (std dev) increases on a low-contrast image
           T2.2.4 AC: clean_image() end-to-end — ocr_ready strictly binary, vision_ready
                  retains grayscale detail, <2s per image
           T2.2.5 AC: DEBUG_SAVE_IMAGES=true writes each stage with case_id prefix; off -> no-op
[SUMMARY]  Tests image_cleaner.py's full Step-3 pipeline. Uses a synthetically rotated
           version of the real printed_report.jpg fixture (T5.1.1) for the deskew AC
           instead of a purely synthetic array, so the rotation-recovery check runs
           against realistic document content. Backfills T2.2's ad hoc verification
           (see SUBTASKS.md) with a committed pytest file.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T2.2.1, T2.2.2, T2.2.3, T2.2.4, T2.2.5; §5 -> T5.1.2
[HISTORY]  2026-07-17  T5.1.2  initial committed test file
"""

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.config import settings
from app.pipeline.image_cleaner import (
    CleanedImage,
    apply_clahe,
    clean_image,
    deskew,
    to_grayscale,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_bgr(name: str) -> np.ndarray:
    return cv2.imread(str(FIXTURES_DIR / name), cv2.IMREAD_COLOR)


def test_to_grayscale_shape_and_dtype():
    """[T2.2.1] AC: grayscale output has shape (H, W) and dtype uint8."""
    bgr = _load_bgr("printed_report.jpg")
    gray = to_grayscale(bgr)

    assert gray.shape == bgr.shape[:2]
    assert gray.dtype == np.uint8


def _rotate(gray: np.ndarray, angle_deg: float) -> np.ndarray:
    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    return cv2.warpAffine(gray, matrix, (w, h), borderValue=255)


def _estimate_skew_via_min_area_rect(gray: np.ndarray) -> float:
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ys, xs = np.where(thresh > 0)
    coords = np.column_stack((xs, ys)).astype(np.float32)
    (_center, (rect_w, rect_h), angle) = cv2.minAreaRect(coords)
    if rect_w < rect_h:
        angle -= 90
    return angle


def test_deskew_corrects_rotated_document_within_one_degree():
    """[T2.2.2] AC: a skewed document fixture becomes ~horizontal (within ±1°) after deskew()."""
    gray = to_grayscale(_load_bgr("printed_report.jpg"))
    skewed = _rotate(gray, 5.0)

    corrected = deskew(skewed)
    residual_angle = _estimate_skew_via_min_area_rect(corrected)

    assert abs(residual_angle) <= 1.0


def test_deskew_skips_rotation_on_blank_image():
    """[T2.2.2] AC: a blank image (no reliable foreground) passes through unchanged rather than being rotated on a noisy estimate."""
    blank = np.full((400, 400), 255, dtype=np.uint8)
    assert np.array_equal(deskew(blank), blank)


def test_apply_clahe_increases_contrast_on_low_contrast_image():
    """[T2.2.3] AC: CLAHE increases the standard deviation of a low-contrast grayscale image."""
    low_contrast = np.full((200, 200), 128, dtype=np.uint8)
    low_contrast[50:150, 50:150] = 140  # a faint low-contrast block
    enhanced = apply_clahe(low_contrast)

    assert enhanced.std() > low_contrast.std()
    assert enhanced.shape == low_contrast.shape
    assert enhanced.dtype == np.uint8


def test_clean_image_end_to_end_on_real_fixture():
    """[T2.2.4] AC: clean_image() on a real document image returns a strictly-binary ocr_ready image, a non-thresholded vision_ready image, and runs in <2s."""
    bgr = _load_bgr("printed_report.jpg")

    start = time.monotonic()
    cleaned = clean_image(bgr)
    elapsed_s = time.monotonic() - start

    assert isinstance(cleaned, CleanedImage)
    assert cleaned.ocr_ready.shape == cleaned.vision_ready.shape
    assert set(np.unique(cleaned.ocr_ready).tolist()) <= {0, 255}
    assert len(np.unique(cleaned.vision_ready)) > 2  # not binarized — retains grayscale detail
    assert elapsed_s < 2.0


def test_clean_image_debug_save_images_writes_stages_with_case_id_prefix(monkeypatch, tmp_path):
    """[T2.2.5] AC: DEBUG_SAVE_IMAGES=true writes each pipeline stage prefixed with case_id; off -> no directory is created."""
    debug_dir = tmp_path / "debug_images"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "DEBUG_SAVE_IMAGES", False)

    bgr = _load_bgr("printed_report.jpg")
    clean_image(bgr, case_id="case-debug-test")
    assert not debug_dir.exists()

    monkeypatch.setattr(settings, "DEBUG_SAVE_IMAGES", True)
    clean_image(bgr, case_id="case-debug-test")

    assert debug_dir.exists()
    written = {p.name for p in debug_dir.iterdir()}
    assert written == {
        "case-debug-test_1_grayscale.png",
        "case-debug-test_2_deskewed.png",
        "case-debug-test_3_clahe_vision_ready.png",
        "case-debug-test_4_threshold_ocr_ready.png",
    }
