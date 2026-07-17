"""
[MODULE]   app/pipeline/classifier.py
[TASK]     T3.1 — CLIP router (Step 4a)
[SUBTASKS] T3.1.1 load clip-vit-base-patch32 at startup (lifespan), CPU, no_grad
[SUMMARY]  Zero-shot document classification via CLIP (Contrastive Language-Image Pre-training).
           Loads the `openai/clip-vit-base-patch32` model once per worker at startup via
           HuggingFace Transformers on CPU. This module handles model loading and inference
           for routing documents into Branch A (PaddleOCR path) or Branch B (Vision API path).
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T3.1
[HISTORY]  2026-07-17  T3.1.1  load clip-vit-base-patch32 at startup
"""

import torch
from transformers import CLIPProcessor, CLIPModel


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
