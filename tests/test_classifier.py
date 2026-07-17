"""
[MODULE]   tests/test_classifier.py
[TASK]     T3.1 — CLIP router (Step 4a)
           T5.1 — Test suite completion
[SUBTASKS] T3.1.3 AC: routing rule unit tests (label/confidence -> branch)
           T3.1.4 AC: printed_report.jpg -> Branch A; handwritten.jpg,
                  medicine_box.jpg -> Branch B; inference <1.5s/image
           T5.1.2 re-verifies T3.1's AC against the real T5.1.1 fixtures (TASKS.md §5,
                  2026-07-17 T3.1 AC note: "Re-verify against real fixtures once
                  T5.1.1 lands (T5.1.2 AC-test pass)")
[SUMMARY]  Loads the real CLIP model (cached locally from earlier manual verification —
           no network call needed) and classifies the real printed_report.jpg,
           handwritten.jpg, and medicine_box.jpg fixtures, exactly matching plan §4
           T3.1's AC table. This closes out the T3.1 AC blocker note that deferred
           real-fixture verification until T5.1.1 existed. route_branch()'s pure
           decision-table logic is also unit tested directly (no model needed).
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T3.1.3, T3.1.4; §5 → T5.1.2
[HISTORY]  2026-07-17  T5.1.2  initial committed test file; re-verifies T3.1 AC against
                                real fixtures (previously only synthetic proxies per
                                TASKS.md §5)
"""

import time
from pathlib import Path

import cv2
import pytest

from app.config import BRANCH_A_PADDLEOCR, BRANCH_B_VISION
from app.pipeline.classifier import classify, load_clip, route_branch, set_clip
from app.pipeline.image_cleaner import clean_image

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module", autouse=True)
def _clip_loaded():
    """Loads the real CLIP model once for this test module (T3.1.1) — cached locally."""
    model, processor = load_clip()
    set_clip(model, processor)


def _vision_ready_gray(name: str):
    """Same input classify() receives in the real pipeline: Step 3's CLAHE vision_ready image, not a raw grayscale conversion."""
    bgr = cv2.imread(str(FIXTURES_DIR / name), cv2.IMREAD_COLOR)
    return clean_image(bgr).vision_ready


@pytest.mark.parametrize(
    "label_index, confidence, expected_branch",
    [
        (0, 0.9, BRANCH_A_PADDLEOCR),
        (0, 0.4, BRANCH_A_PADDLEOCR),  # exactly at threshold -> Branch A (>=)
        (0, 0.39, BRANCH_B_VISION),  # just under threshold -> Branch B fallback
        (1, 0.99, BRANCH_B_VISION),
        (2, 0.99, BRANCH_B_VISION),
        (3, 0.99, BRANCH_B_VISION),
    ],
)
def test_route_branch_decision_table(label_index, confidence, expected_branch):
    """[T3.1.3] AC: label 0 (printed) + confidence >= 0.4 -> Branch A; everything else -> Branch B."""
    assert route_branch(label_index, confidence) == expected_branch


def test_classify_printed_report_routes_to_branch_a():
    """[T3.1.4] AC: printed_report.jpg -> Branch A (paddleocr), inference < 1.5s."""
    gray = _vision_ready_gray("printed_report.jpg")

    start = time.monotonic()
    label_index, confidence = classify(gray)
    elapsed_s = time.monotonic() - start

    assert route_branch(label_index, confidence) == BRANCH_A_PADDLEOCR
    assert elapsed_s < 1.5


def test_classify_handwritten_routes_to_branch_b():
    """[T3.1.4] AC: handwritten.jpg -> Branch B (vision_api)."""
    gray = _vision_ready_gray("handwritten.jpg")
    label_index, confidence = classify(gray)

    assert route_branch(label_index, confidence) == BRANCH_B_VISION


def test_classify_medicine_box_routes_to_branch_b():
    """[T3.1.4] AC: medicine_box.jpg -> Branch B (vision_api)."""
    gray = _vision_ready_gray("medicine_box.jpg")
    label_index, confidence = classify(gray)

    assert route_branch(label_index, confidence) == BRANCH_B_VISION
