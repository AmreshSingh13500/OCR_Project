"""
[MODULE]   app/pipeline/image_cleaner.py
[TASK]     T2.2 — OpenCV pre-processing (Step 3)
[SUBTASKS] T2.2.1 grayscale conversion (BGR→GRAY)
[SUMMARY]  Deterministic image-cleaning pipeline for Step 3: grayscale → deskew → CLAHE →
           adaptive threshold, producing both an OCR-ready binary image and a CLAHE
           grayscale "vision_ready" image for the LLM vision path (binarization destroys
           detail the vision model needs). Runs on in-memory numpy arrays only, never
           touches disk except under DEBUG_SAVE_IMAGES (T2.2.5).
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T2.2.1
[HISTORY]  2026-07-17  T2.2.1  initial grayscale conversion
"""

import cv2
import numpy as np


# [T2.2.1] BGR→GRAY conversion — first step of the cleaning pipeline.
def to_grayscale(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
