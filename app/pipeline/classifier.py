"""
[MODULE]   app/pipeline/classifier.py
[TASK]     T3.1 — CLIP router (Step 4a)
[SUBTASKS] T3.1.1 load clip-vit-base-patch32 at startup (lifespan), CPU, no_grad
           T3.1.3 routing rule: printed label -> Branch A; else/low-confidence -> Branch B
[SUMMARY]  Zero-shot document classification via CLIP (Contrastive Language-Image Pre-training).
           Loads the `openai/clip-vit-base-patch32` model once per worker at startup via
           HuggingFace Transformers on CPU. This module handles model loading and inference
           for routing documents into Branch A (PaddleOCR path) or Branch B (Vision API path).
           `route_branch()` is the decision rule applied to CLIP's output (T3.1.4, which runs
           the actual per-image inference, calls it with the winning label index + score).
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T3.1
[HISTORY]  2026-07-17  T3.1.1  load clip-vit-base-patch32 at startup
           2026-07-17  T3.1.3  add route_branch() routing rule + confidence threshold
"""

import torch
from transformers import CLIPProcessor, CLIPModel

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
