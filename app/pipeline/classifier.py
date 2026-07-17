"""
[MODULE]   app/pipeline/classifier.py
[TASK]     T3.1 — CLIP router (Step 4a)
[SUBTASKS] T3.1.1 load clip-vit-base-patch32 at startup (lifespan), CPU, no_grad
           T3.1.3 routing rule: printed label -> Branch A; else/low-confidence -> Branch B
           T3.1.4 classify(): CLIP inference on the vision_ready (CLAHE grayscale -> RGB) image
           T3.1.5 log label + confidence per page (case_id via logging contextvar, T1.1.3)
[SUMMARY]  Zero-shot document classification via CLIP (Contrastive Language-Image Pre-training).
           Loads the `openai/clip-vit-base-patch32` model once per worker at startup via
           HuggingFace Transformers on CPU. This module handles model loading and inference
           for routing documents into Branch A (PaddleOCR path) or Branch B (Vision API path).
           `classify()` runs CLIP zero-shot scoring against `CLIP_LABELS` on the
           `vision_ready` grayscale image (converted to RGB — CLIP expects 3-channel input),
           logging the winning label + confidence per call (case_id is picked up
           automatically from the logging contextvar set up in T1.1.3 — not passed in
           here); `route_branch()` turns its (label_index, confidence) output into a
           branch decision.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T3.1
[HISTORY]  2026-07-17  T3.1.1  load clip-vit-base-patch32 at startup
           2026-07-17  T3.1.3  add route_branch() routing rule + confidence threshold
           2026-07-17  T3.1.4  add classify() — CLIP inference on vision_ready image
           2026-07-17  T3.1.5  log label + confidence per classify() call
"""

import logging

import cv2
import numpy as np
import torch
from transformers import CLIPProcessor, CLIPModel

from app.config import CLIP_LABELS

logger = logging.getLogger(__name__)

# [T3.1.3] Per plan §4 T3.1.3 exactly — below this confidence, vision is the safe fallback
# even when the top label happens to be the printed one.
_ROUTING_CONFIDENCE_THRESHOLD = 0.4

# [T3.1.3] Reuses the exact processing_path contract strings (IMPLEMENTATION_PLAN.md §1,
# CODING_RULES.md Rule 7) rather than inventing separate branch names — T4.3.2 sets
# processing_path directly from this value.
BRANCH_A_PADDLEOCR = "paddleocr"
BRANCH_B_VISION = "vision_api"


# [T3.1.1] Load openai/clip-vit-base-patch32 model once at app startup (lifespan).
# Uses CPU inference via torch.no_grad() to avoid allocating unnecessary GPU memory.
def load_clip() -> tuple[CLIPModel, CLIPProcessor]:
    """
    Load CLIP model and processor from HuggingFace on CPU without gradient computation.
    Returns (model, processor) tuple; model is in eval mode.
    """
    with torch.no_grad():
        model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        model.eval()
        model = model.to("cpu")

    return model, processor


# Module-level storage (populated by lifespan in main.py via Rule 3)
_clip_model: CLIPModel = None
_clip_processor: CLIPProcessor = None


def set_clip(model: CLIPModel, processor: CLIPProcessor) -> None:
    """Called by main.py lifespan to wire the loaded models into this module."""
    global _clip_model, _clip_processor
    _clip_model = model
    _clip_processor = processor


def get_clip() -> tuple[CLIPModel, CLIPProcessor]:
    """Retrieve the cached CLIP model and processor."""
    if _clip_model is None or _clip_processor is None:
        raise RuntimeError("CLIP model not loaded — check lifespan initialization")
    return _clip_model, _clip_processor


# [T3.1.3] label_index 0 is CLIP_LABELS' printed-document label (app/config.py); indices
# 1-3 are handwritten/scan/photo. Low confidence overrides even a printed-label win,
# since vision is the safe fallback (plan §4 T3.1.3) when CLIP itself isn't sure.
def route_branch(top_label_index: int, confidence: float) -> str:
    """
    Decide Branch A (paddleocr) vs Branch B (vision_api) from CLIP's top prediction.
    Returns one of the frozen processing_path values BRANCH_A_PADDLEOCR / BRANCH_B_VISION.
    """
    if top_label_index == 0 and confidence >= _ROUTING_CONFIDENCE_THRESHOLD:
        return BRANCH_A_PADDLEOCR
    return BRANCH_B_VISION


# [T3.1.4] Runs CLIP zero-shot scoring against CLIP_LABELS on the vision_ready image.
# vision_ready (image_cleaner.CleanedImage) is single-channel CLAHE grayscale — CLIP was
# trained on 3-channel images, so it's converted to RGB (channel-replicated, no color
# information is invented) before going through the processor.
# [T3.1.5] Logs the winning label + confidence at INFO on every call — this is a routing
# decision, not a medical field value, so it isn't subject to CLAUDE.md's DEBUG-only rule
# for patient data. case_id/message_id are picked up automatically by JsonFormatter
# (app/utils/logging.py, T1.1.3) from the contextvar bound for the current pipeline run —
# this function doesn't need a case_id parameter.
def classify(vision_ready: np.ndarray) -> tuple[int, float]:
    """
    Run CLIP zero-shot classification on a vision_ready grayscale image.
    Returns (top_label_index, confidence) where confidence is the softmax probability
    of the winning label among CLIP_LABELS.
    """
    model, processor = get_clip()
    rgb = cv2.cvtColor(vision_ready, cv2.COLOR_GRAY2RGB)

    inputs = processor(text=CLIP_LABELS, images=rgb, return_tensors="pt", padding=True)
    with torch.no_grad():
        outputs = model(**inputs)

    probs = outputs.logits_per_image.softmax(dim=1)[0]
    top_label_index = int(torch.argmax(probs))
    confidence = float(probs[top_label_index])

    logger.info(
        "CLIP classification: label=%r confidence=%.4f",
        CLIP_LABELS[top_label_index], confidence,
    )

    return top_label_index, confidence
