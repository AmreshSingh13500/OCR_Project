"""
[MODULE]   app/main.py
[TASK]     T1.1 — Project scaffold
[SUBTASKS] T1.1.1 create repo layout per plan §2 (FastAPI app factory + lifespan skeleton)
[SUMMARY]  FastAPI application entrypoint, started via `uvicorn app.main:app`. Defines
           the `app` instance and an empty lifespan context manager. This file has no
           single owning subtask beyond T1.1.1 scaffolding — later subtasks extend it:
           router mounting (T1.2.3 process endpoint, T1.2.4 health endpoint) and model
           loading at startup (T3.1.1 CLIP, T3.2.1 PaddleOCR) are added in place per
           CODING_RULES.md Rule 3, not duplicated here.
[PLAN]     IMPLEMENTATION_PLAN.md §2 → T1.1.1
[HISTORY]  2026-07-16  T1.1.1  initial FastAPI app skeleton, empty lifespan
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI


# [T1.1.1] App factory skeleton — lifespan body is populated by T3.1.1/T3.2.1 (model loading)
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="OCR Microservice", lifespan=lifespan)
