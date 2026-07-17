"""
[MODULE]   app/api/routes.py
[TASK]     T1.2 — Auth & API endpoints
           T5.2 — Security hardening (app level)
[SUBTASKS] T1.2.3 POST /api/v1/process — validate -> BackgroundTask -> 202 immediately
           T1.2.4 GET /health — 200 with clip_loaded/paddle_loaded flags, unauthenticated
           T1.2.5 validate file_url scheme is https; reject invalid URLs with 400
           T5.2.3 enforce_body_size_limit — reject request bodies over MAX_REQUEST_BODY_BYTES
           T5.2.4 SSRF guard — optional ALLOWED_FILE_HOSTS allowlist + reject
                  private/loopback/link-local IPs after DNS resolution
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
           re-checked per request. `enforce_body_size_limit` (T5.2.3) is a FastAPI
           dependency that rejects a request body over MAX_REQUEST_BODY_BYTES with 413 —
           app-level defense in depth ahead of Nginx's client_max_body_size (T6.2.2, not
           yet built). It checks Content-Length first for a fast rejection, then falls
           back to the actual buffered body length (Starlette caches `request.body()`,
           so this doesn't cause a second read) so a request with a missing or
           understated Content-Length can't bypass the cap either. [T5.2.4] After the
           https check, `file_url`'s host goes through an SSRF guard: an optional
           `ALLOWED_FILE_HOSTS` allowlist (comma-separated, `*.domain.com` wildcard
           prefixes supported) if configured, and an always-on check that every IP the
           host resolves to (via async DNS, `loop.getaddrinfo`, so this never blocks the
           event loop) is a public, routable address — private/loopback/link-local/
           reserved/multicast ranges are rejected with 400 regardless of the allowlist.
           An IP-literal `file_url` host (e.g. `169.254.169.254`) is checked directly,
           no DNS involved. This only guards the request-acceptance step; it does not
           protect against DNS rebinding between this check and the actual download
           (Step 2a's separate httpx call) — considered out of scope for this app-level
           hardening pass (see T5.2.4's SUBTASKS.md note for the full reasoning).
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.2.3, T1.2.4, T1.2.5, T5.2.3, T5.2.4
[HISTORY]  2026-07-17  T1.2.3  initial POST /api/v1/process — validate, enqueue
                                run_pipeline as BackgroundTask, return 202
           2026-07-17  T1.2.4  add GET /health
           2026-07-17  T1.2.5  add _is_valid_https_url() + 400 check in process_document()
           2026-07-17  T5.2.3  add enforce_body_size_limit() dependency + wire it into
                                POST /api/v1/process alongside require_api_key; new
                                MAX_REQUEST_BODY_BYTES constant added to config.py (Rule
                                7 gate n/a — new dependency only, ProcessRequest/
                                WebhookPayload/error strings untouched)
           2026-07-17  T5.2.4  add _host_matches_allowlist()/_is_disallowed_ip()/
                                _resolve_and_check_host()/_is_safe_file_url(), called
                                from process_document() right after the https check;
                                new ALLOWED_FILE_HOSTS setting added to config.py (Rule 7
                                gate n/a — new optional env var, additive; no
                                schemas.py/error-string changes)
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.auth import require_api_key
from app.config import MAX_REQUEST_BODY_BYTES, settings
from app.pipeline.orchestrator import run_pipeline
from app.schemas import ProcessRequest

router = APIRouter()


# [T1.2.5] "Obviously invalid" per plan T1.2.5: wrong scheme or no host. A manual check
# (not a pydantic field validator on ProcessRequest) so a bad file_url yields 400,
# distinct from the 422 pydantic already returns for a structurally malformed body.
def _is_valid_https_url(file_url: str) -> bool:
    parsed = urlparse(file_url)
    return parsed.scheme == "https" and bool(parsed.netloc)


# [T5.2.3] Content-Length is checked first for a fast rejection without reading the body
# at all; the actual buffered length is the robust fallback for a request with a
# missing/understated Content-Length header, since a malicious client can lie about it.
# `await request.body()` is safe to call here even though FastAPI will also parse the
# body into ProcessRequest afterwards — Starlette caches the raw bytes on the Request
# object the first time they're read, so this doesn't trigger a second stream read.
async def enforce_body_size_limit(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > MAX_REQUEST_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body exceeds 1 MB limit")
    body = await request.body()
    if len(body) > MAX_REQUEST_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body exceeds 1 MB limit")


# [T5.2.4] `ALLOWED_FILE_HOSTS` is comma-separated; a "*.domain.com" entry matches that
# domain itself or any subdomain, an entry with no leading "*." must match exactly.
def _host_matches_allowlist(host: str, patterns: list[str]) -> bool:
    host = host.lower()
    for pattern in patterns:
        pattern = pattern.strip().lower()
        if not pattern:
            continue
        if pattern.startswith("*."):
            suffix = pattern[2:]
            if host == suffix or host.endswith("." + suffix):
                return True
        elif host == pattern:
            return True
    return False


# [T5.2.4] The private/loopback/link-local/reserved/multicast ranges an SSRF attack
# targets (cloud metadata endpoints, localhost, internal networks) — checked against
# every IP a file_url host resolves to, regardless of whether ALLOWED_FILE_HOSTS is set.
def _is_disallowed_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


# [T5.2.4] Resolves `hostname` and returns True only if every resolved address is a
# public, routable IP. An IP-literal hostname (e.g. "169.254.169.254") is checked
# directly, no DNS involved. DNS resolution goes through the event loop's async
# getaddrinfo so a slow/hung resolver never blocks other requests (same "never block
# the event loop" principle as T3.2.3's PaddleOCR executor offload). An unresolvable
# host is treated as unsafe (rejected) rather than silently passed through.
async def _resolve_and_check_host(hostname: str) -> bool:
    try:
        return not _is_disallowed_ip(hostname)
    except ValueError:
        pass  # not an IP literal — resolve it below

    try:
        loop = asyncio.get_running_loop()
        addr_infos = await loop.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False

    resolved_ips = {info[4][0] for info in addr_infos}
    return bool(resolved_ips) and all(not _is_disallowed_ip(ip) for ip in resolved_ips)


# [T5.2.4] Combines the optional ALLOWED_FILE_HOSTS allowlist with the always-on
# private/loopback IP guard. A file_url with no parseable host is rejected outright.
async def _is_safe_file_url(file_url: str) -> bool:
    hostname = urlparse(file_url).hostname
    if not hostname:
        return False

    if settings.ALLOWED_FILE_HOSTS:
        patterns = [p for p in settings.ALLOWED_FILE_HOSTS.split(",") if p.strip()]
        if patterns and not _host_matches_allowlist(hostname, patterns):
            return False

    return await _resolve_and_check_host(hostname)


# [T1.2.3] Auth (T1.2.1) is enforced via the require_api_key dependency before this body
# ever runs; a malformed body is rejected with 422 by FastAPI's own ProcessRequest
# validation before this function is even called. [T1.2.5] file_url is then checked for
# an https scheme and a real host, 400 if not. [T5.2.4] file_url's host then goes
# through the SSRF guard (allowlist, if configured, plus the always-on private/loopback
# IP check), also 400 if it fails. [T5.2.3] enforce_body_size_limit rejects an oversized
# body with 413 before any of the above run. The pipeline itself is handed to
# BackgroundTasks (Starlette runs it after the response is sent) so this handler returns
# 202 immediately regardless of how long download/OCR/LLM extraction takes.
@router.post(
    "/api/v1/process",
    status_code=202,
    dependencies=[Depends(require_api_key), Depends(enforce_body_size_limit)],
)
async def process_document(req: ProcessRequest, background_tasks: BackgroundTasks) -> dict:
    if not _is_valid_https_url(req.file_url):
        raise HTTPException(status_code=400, detail="file_url must be a valid https URL")

    if not await _is_safe_file_url(req.file_url):
        raise HTTPException(status_code=400, detail="file_url host is not allowed")

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
