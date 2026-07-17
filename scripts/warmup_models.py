"""
[MODULE]   scripts/warmup_models.py
[TASK]     T6.1 — Server provisioning script (Phase 6)
[SUBTASKS] T6.1.3 model warmup — pre-download CLIP + PaddleOCR weights into the cache
[SUMMARY]  Deploy-time model warmup. Pulls the CLIP and PaddleOCR weights into the running
           user's local cache (HuggingFace under ~/.cache/huggingface for CLIP,
           ~/.paddleocr for PaddleOCR) so the first real request after a cold deploy does
           not pay the multi-hundred-MB download cost mid-pipeline (plan §4 T6.1.3).
           Reuses the app's own load_clip()/load_paddleocr() (app/pipeline/classifier.py,
           app/pipeline/ocr_engine.py) rather than re-declaring model IDs / constructor
           args here, so exactly what production loads is what gets cached — no second
           identifier list to drift out of sync. Imports classifier (torch) before
           ocr_engine (paddlepaddle), matching main.py's lifespan order (the paddle-before-
           torch DLL conflict from TASKS.md §5 / T3.2.4). setup_server.sh runs this once,
           as the ocrsvc service user, at the end of provisioning — before the real
           /etc/ocr-service/env exists — so placeholder values are set for the four
           required env vars purely so app.config.Settings() can instantiate; the loaders
           never read those secrets, and a real env already in place is left untouched.
           Run: `.venv\\Scripts\\python.exe -m scripts.warmup_models`
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T6.1.3
[HISTORY]  2026-07-18  T6.1.3  initial warmup script (reuses load_clip/load_paddleocr)
"""

import logging
import os
import sys

# [T6.1.3] app.config.Settings() (imported transitively below) is instantiated at import
# time and requires these four vars (T1.1.2 fail-fast). This script runs during provisioning
# before the real env file exists, and load_clip()/load_paddleocr() never read these
# secrets — so set obviously-fake placeholders only when unset (setdefault leaves a real
# env intact). Must execute before the app imports below, same pattern as tests/conftest.py.
os.environ.setdefault("OCR_API_KEY", "warmup-placeholder-not-a-secret")
os.environ.setdefault("LARAVEL_WEBHOOK_URL", "https://warmup.invalid/unused")
os.environ.setdefault("LARAVEL_WEBHOOK_KEY", "warmup-placeholder-not-a-secret")
os.environ.setdefault("OPENAI_API_KEY", "warmup-placeholder-not-a-secret")

# Import classifier (torch) before ocr_engine (paddlepaddle) — see [SUMMARY] / T3.2.4.
from app.pipeline.classifier import load_clip  # noqa: E402
from app.pipeline.ocr_engine import load_paddleocr  # noqa: E402

logger = logging.getLogger(__name__)


# [T6.1.3] Pull both model sets into the local cache. Loads CLIP first (torch) then
# PaddleOCR (paddlepaddle) — the same order main.py's lifespan uses — and discards the
# returned handles; the point is the download/caching side effect, not the objects.
# Returns the number of model sets warmed so a caller/test can assert both ran.
def warmup() -> int:
    logger.info("Warming CLIP weights (openai/clip-vit-base-patch32)...")
    load_clip()
    logger.info("CLIP weights cached.")

    logger.info("Warming PaddleOCR weights (det/rec/cls, en)...")
    load_paddleocr()
    logger.info("PaddleOCR weights cached.")

    logger.info("Model warmup complete — both model sets are in the local cache.")
    return 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        warmup()
    except Exception:
        logger.exception("Model warmup failed")
        sys.exit(1)
    sys.exit(0)
