"""
[MODULE]   app/api/routes.py
[TASK]     T1.2 — Auth & API endpoints
[SUBTASKS] T1.2.3 POST /api/v1/process — validate -> BackgroundTask -> 202 immediately
           T1.2.4 GET /health — 200 with clip_loaded/paddle_loaded flags, unauthenticated
           T1.2.5 validate file_url scheme is https; reject invalid URLs with 400
[SUMMARY]  HTTP surface of the microservice. POST /api/v1/process is the Laravel-facing
           ingestion endpoint (Bearer-authenticated via T1.2.1's require_api_key
           dependency; the request body is validated against schemas.ProcessRequest,
           422 on a malformed body). `file_url` is additionally checked for an https
           scheme and a non-empty host (T1.2.5) — deliberately a manual check in the
           handler, not a pydantic field validator on ProcessRequest, since the plan
           requires this specific failure to be a 400, distinct from the 422 pydantic
           already returns for a structurally malformed body. Once both checks pass, the
           actual pipeline (download/clean/classify/OCR/LLM/webhook,
           app.pipeline.orchestrator.run_pipeline) is handed to FastAPI's BackgroundTasks
           so the handler returns 202 immediately — the pipeline's own duration never
           affects response latency, satisfying the "100% asynchronous / zero blocking"
           contract regardless of file size. GET /health is deliberately unauthenticated
           (monitoring probes don't carry the bearer token) and reports whether the
           CLIP/PaddleOCR models have finished loading, read from app.state — populated
           once at startup by main.py's lifespan (T3.1.1 CLIP, T3.2.1 PaddleOCR), never
           re-checked per request.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.2.3, T1.2.4, T1.2.5
[HISTORY]  2026-07-17  T1.2.3  initial POST /api/v1/process — validate, enqueue
                                run_pipeline as BackgroundTask, return 202
           2026-07-17  T1.2.4  add GET /health
           2026-07-17  T1.2.5  add _is_valid_https_url() + 400 check in process_document()
"""

from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.auth import require_api_key
from app.pipeline.orchestrator import run_pipeline
from app.schemas import ProcessRequest

router = APIRouter()


# [T1.2.5] "Obviously invalid" per plan T1.2.5: wrong scheme or no host. A manual check
# (not a pydantic field validator on ProcessRequest) so a bad file_url yields 400,
# distinct from the 422 pydantic already returns for a structurally malformed body.
def _is_valid_https_url(file_url: str) -> bool:
    parsed = urlparse(file_url)
    return parsed.scheme == "https" and bool(parsed.netloc)


# [T1.2.3] Auth (T1.2.1) is enforced via the require_api_key dependency before this body
# ever runs; a malformed body is rejected with 422 by FastAPI's own ProcessRequest
# validation before this function is even called. [T1.2.5] file_url is then checked for
# an https scheme and a real host, 400 if not. The pipeline itself is handed to
# BackgroundTasks (Starlette runs it after the response is sent) so this handler returns
# 202 immediately regardless of how long download/OCR/LLM extraction takes.
@router.post("/api/v1/process", status_code=202, dependencies=[Depends(require_api_key)])
async def process_document(req: ProcessRequest, background_tasks: BackgroundTasks) -> dict:
    if not _is_valid_https_url(req.file_url):
        raise HTTPException(status_code=400, detail="file_url must be a valid https URL")

    background_tasks.add_task(run_pipeline, req)
    return {"status": "accepted", "case_id": req.case_id}


# [T1.2.4] No auth dependency — monitoring probes (uptime checks, load balancers) don't
# carry Laravel's bearer token. Reads model-loaded flags from app.state rather than
# re-probing the models themselves, since main.py's lifespan already sets clip_model/
# paddle_ocr exactly once at startup (T3.1.1/T3.2.1) — getattr guards against a request
# arriving before lifespan has set them (or in a test app that never ran the real lifespan).
@router.get("/health")
async def health(request: Request) -> dict:
    return {
        "status": "ok",
        "clip_loaded": getattr(request.app.state, "clip_model", None) is not None,
        "paddle_loaded": getattr(request.app.state, "paddle_ocr", None) is not None,
    }
