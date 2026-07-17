"""
[MODULE]   app/pipeline/webhook_client.py
[TASK]     T4.2 — Laravel webhook return (Step 6)
[SUBTASKS] T4.2.1 async httpx POST with Bearer key, WebhookPayload body
           T4.2.2 tenacity retries on 5xx/connection only; 4xx = no retry, CRITICAL log
[SUMMARY]  Delivers the pipeline's final result to Laravel via the Step-6 webhook.
           `build_webhook_payload()` defines the exact WebhookPayload key set
           (case_id, message_id, status, processing_path, extracted_data,
           error_message) — schemas.py (T1.2.2) doesn't exist yet, so this is the
           first formal definition of that contract shape, mirroring the precedent
           set by llm_extractor.py's EXTRACTED_DATA_JSON_SCHEMA (T4.1.1). `send_webhook()`
           POSTs the payload to LARAVEL_WEBHOOK_URL with a Bearer LARAVEL_WEBHOOK_KEY
           header, retrying only 5xx responses and transport-level failures (3 attempts,
           exponential backoff 2-30s, same tenacity shape as T4.1.4's OpenAI retry) via
           `_post_webhook_with_retry()`. A 4xx is a contract/config bug a retry can never
           fix, so it deliberately fails on the first attempt and is logged CRITICAL
           immediately here. Retries-exhausted (5xx/connection) is not yet handled — that
           terminal case is T4.2.3.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T4.2.1, T4.2.2
[HISTORY]  2026-07-17  T4.2.1  initial build_webhook_payload() + send_webhook() bare POST —
                                additive-only new module, no existing contract surface
                                touched (Rule 7 gate n/a)
           2026-07-17  T4.2.2  add _RetryableWebhookError + _post_webhook_with_retry()
                                tenacity wrapper (5xx/connection only, 3 attempts,
                                2-30s backoff); send_webhook() now catches the
                                unwrapped 4xx HTTPStatusError and logs CRITICAL —
                                no schemas.py/routes.py/error-string changes (Rule 7
                                gate n/a), webhook_client.py is internal-only
"""

import json
import logging

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)

_WEBHOOK_TIMEOUT_S = 30
_WEBHOOK_MAX_RETRIES = 3


# [T4.2.2] Wraps only a 5xx response or a transport-level failure (connection error,
# timeout) so tenacity's retry predicate targets exactly these — a 4xx httpx.HTTPStatusError
# is deliberately left unwrapped so it is never retried (see _post_webhook_with_retry).
class _RetryableWebhookError(Exception):
    pass


# [T4.2.1] Defines the exact WebhookPayload key set per IMPLEMENTATION_PLAN.md §4 T4.2.1 —
# schemas.py (T1.2.2) must mirror this shape when it's built. Callers (T4.3, not built yet)
# pass every field explicitly rather than relying on defaults, so a forgotten field is a
# TypeError at the call site, not a silently-missing key in the JSON sent to Laravel.
def build_webhook_payload(
    case_id: str,
    message_id: str,
    status: str,
    processing_path: str | None,
    extracted_data: dict | None,
    error_message: str | None,
) -> dict:
    return {
        "case_id": case_id,
        "message_id": message_id,
        "status": status,
        "processing_path": processing_path,
        "extracted_data": extracted_data,
        "error_message": error_message,
    }


# [T4.2.1] Bare async POST — Bearer-authenticated, JSON body = the WebhookPayload dict.
# Raises httpx.HTTPStatusError (4xx/5xx) or another httpx.HTTPError (transport failure)
# unwrapped; _post_webhook_with_retry (T4.2.2) is what decides which of those get retried.
async def _post_webhook(payload: dict) -> None:
    async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT_S) as client:
        response = await client.post(
            settings.LARAVEL_WEBHOOK_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.LARAVEL_WEBHOOK_KEY}"},
        )
        response.raise_for_status()


# [T4.2.2] Per IMPLEMENTATION_PLAN.md §4 T4.2.2 exactly: retries only 5xx / connection
# failures, 3 attempts, exponential backoff 2-30s. A 4xx is re-raised unwrapped (not
# _RetryableWebhookError), so tenacity's retry_if_exception_type predicate doesn't match
# it and it propagates on the very first attempt — "no retry" for a contract/config bug.
@retry(
    retry=retry_if_exception_type(_RetryableWebhookError),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(_WEBHOOK_MAX_RETRIES),
    reraise=True,
)
async def _post_webhook_with_retry(payload: dict) -> None:
    try:
        await _post_webhook(payload)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code >= 500:
            raise _RetryableWebhookError(str(exc)) from exc
        raise
    except httpx.HTTPError as exc:
        raise _RetryableWebhookError(str(exc)) from exc


# [T4.2.2] Entry point. A 4xx fails on the first attempt (see above) and is logged
# CRITICAL here as a contract/config bug — no automatic recovery is possible, a human
# needs to fix the URL/key/payload shape. Retries-exhausted (5xx/connection) is not yet
# caught here; that terminal case is T4.2.3.
async def send_webhook(payload: dict) -> None:
    try:
        await _post_webhook_with_retry(payload)
    except httpx.HTTPStatusError as exc:
        logger.critical(
            "Webhook delivery failed with non-retryable HTTP %d (contract/config bug); "
            "payload=%s",
            exc.response.status_code,
            json.dumps(payload),
        )
