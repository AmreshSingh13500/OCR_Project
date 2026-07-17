"""
[MODULE]   app/api/routes.py
[TASK]     T1.2 — Auth & API endpoints
[SUBTASKS] T1.2.3 POST /api/v1/process — validate -> BackgroundTask -> 202 immediately
[SUMMARY]  HTTP surface of the microservice. POST /api/v1/process is the Laravel-facing
           ingestion endpoint (Bearer-authenticated via T1.2.1's require_api_key
           dependency; the request body is validated against schemas.ProcessRequest,
           422 on a malformed body). Once validation passes, the actual pipeline
           (download/clean/classify/OCR/LLM/webhook, app.pipeline.orchestrator.run_pipeline)
           is handed to FastAPI's BackgroundTasks so the handler returns 202 immediately —
           the pipeline's own duration never affects response latency, satisfying the
           "100% asynchronous / zero blocking" contract regardless of file size.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.2.3
[HISTORY]  2026-07-17  T1.2.3  initial POST /api/v1/process — validate, enqueue
                                run_pipeline as BackgroundTask, return 202
"""

from fastapi import APIRouter, BackgroundTasks, Depends

from app.auth import require_api_key
from app.pipeline.orchestrator import run_pipeline
from app.schemas import ProcessRequest

router = APIRouter()


# [T1.2.3] Auth (T1.2.1) is enforced via the require_api_key dependency before this body
# ever runs; a malformed body is rejected with 422 by FastAPI's own ProcessRequest
# validation before this function is even called. The pipeline itself is handed to
# BackgroundTasks (Starlette runs it after the response is sent) so this handler returns
# 202 immediately regardless of how long download/OCR/LLM extraction takes.
@router.post("/api/v1/process", status_code=202, dependencies=[Depends(require_api_key)])
async def process_document(req: ProcessRequest, background_tasks: BackgroundTasks) -> dict:
    background_tasks.add_task(run_pipeline, req)
    return {"status": "accepted", "case_id": req.case_id}
