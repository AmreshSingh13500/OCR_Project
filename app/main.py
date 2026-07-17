"""
[MODULE]   app/main.py
[TASK]     T1.1 — Project scaffold
           T1.2 — Auth & API endpoints
           T3.1 — CLIP router (Step 4a)
           T3.2 — PaddleOCR engine (Step 4b)
[SUBTASKS] T1.1.1 create repo layout per plan §2 (FastAPI app factory + lifespan skeleton)
           T1.1.3 configure JSON logging at startup
           T1.2.3 mount the app.api.routes router (POST /api/v1/process)
           T3.1.1 load CLIP model at startup (lifespan)
           T3.2.1 load PaddleOCR engine at startup (lifespan)
[SUMMARY]  FastAPI application entrypoint, started via `uvicorn app.main:app`. Defines
           the `app` instance and a lifespan context manager that configures JSON logging
           and loads the CLIP and PaddleOCR models on startup, then mounts the
           app.api.routes router (POST /api/v1/process, GET /health). This file has no
           single owning subtask beyond T1.1.x scaffolding — later subtasks extend it in
           place per CODING_RULES.md Rule 3.
[PLAN]     IMPLEMENTATION_PLAN.md §2 → T1.1.1, T1.1.3; §4 T1.2.3, T3.1, T3.2
[HISTORY]  2026-07-16  T1.1.1  initial FastAPI app skeleton, empty lifespan
           2026-07-16  T1.1.3  wire configure_logging() into lifespan startup
           2026-07-17  T3.1.1  load CLIP model at startup in lifespan
           2026-07-17  T3.2.1  load PaddleOCR engine at startup in lifespan
           2026-07-17  T3.2.4  added defensive import-order comment (classifier before
                                ocr_engine) after discovering a torch/paddlepaddle DLL
                                conflict on Windows dev boxes — order unchanged, just
                                documented so it's never accidentally reordered
           2026-07-17  T1.2.3  mount app.api.routes' router via app.include_router()
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

# NOTE: keep classifier (torch) imported before ocr_engine (paddlepaddle). On at least
# one Windows dev machine, importing paddlepaddle before torch in the same process
# breaks torch's DLL loading (WinError 127 on torch/lib/shm.dll) — a native library
# conflict between the two frameworks, not an app bug. Not reproduced as a problem in
# this order; likely Windows-only since the deploy target is Ubuntu (T6.1), but keep
# this import order defensively until verified moot on the Linux target (see TASKS.md
# §5, 2026-07-17 T3.2.4 note, for the full investigation).
from app.pipeline.classifier import load_clip, set_clip
from app.pipeline.ocr_engine import load_paddleocr, set_paddleocr
from app.api.routes import router
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


# [T1.1.1] App factory skeleton — model loading is populated by T3.1.1/T3.2.1
# [T1.1.3] JSON logging is configured before the app starts serving requests
# [T3.1.1] CLIP model is loaded at startup with torch.no_grad() for inference-only mode
# [T3.2.1] PaddleOCR engine is loaded at startup, CPU-only
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    # Load CLIP model for zero-shot classification (T3.1.1)
    logger.info("Loading CLIP model (openai/clip-vit-base-patch32)...")
    clip_model, clip_processor = load_clip()
    app.state.clip_model = clip_model
    app.state.clip_processor = clip_processor
    set_clip(clip_model, clip_processor)
    logger.info("CLIP model loaded successfully")

    # Load PaddleOCR engine for Branch A text extraction (T3.2.1)
    logger.info("Loading PaddleOCR engine...")
    paddle_ocr = load_paddleocr()
    app.state.paddle_ocr = paddle_ocr
    set_paddleocr(paddle_ocr)
    logger.info("PaddleOCR engine loaded successfully")

    yield


app = FastAPI(title="OCR Microservice", lifespan=lifespan)

# [T1.2.3] Mounts POST /api/v1/process (and GET /health, T1.2.4) under the root app.
app.include_router(router)
