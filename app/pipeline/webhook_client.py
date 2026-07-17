"""
[MODULE]   app/pipeline/webhook_client.py
[TASK]     T4.2 — Laravel webhook return (Step 6)
[SUBTASKS] T4.2.1 async httpx POST with Bearer key, WebhookPayload body
[SUMMARY]  Delivers the pipeline's final result to Laravel via the Step-6 webhook.
           `build_webhook_payload()` defines the exact WebhookPayload key set
           (case_id, message_id, status, processing_path, extracted_data,
           error_message) — schemas.py (T1.2.2) doesn't exist yet, so this is the
           first formal definition of that contract shape, mirroring the precedent
           set by llm_extractor.py's EXTRACTED_DATA_JSON_SCHEMA (T4.1.1). `send_webhook()`
           POSTs the payload to LARAVEL_WEBHOOK_URL with a Bearer LARAVEL_WEBHOOK_KEY
           header. No retry or failure handling yet (T4.2.2/T4.2.3 add those) — a
           non-2xx or transport error simply propagates, same "bare call by design"
           as T4.1.2's first cut of extract_from_text().
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T4.2.1
[HISTORY]  2026-07-17  T4.2.1  initial build_webhook_payload() + send_webhook() bare POST —
                                additive-only new module, no existing contract surface
                                touched (Rule 7 gate n/a)
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_WEBHOOK_TIMEOUT_S = 30


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
# A non-2xx response or transport error is left to propagate to the caller unwrapped;
# T4.2.2 adds the retry policy and T4.2.3 adds the terminal-failure CRITICAL log.
async def send_webhook(payload: dict) -> None:
    async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT_S) as client:
        response = await client.post(
            settings.LARAVEL_WEBHOOK_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.LARAVEL_WEBHOOK_KEY}"},
        )
        response.raise_for_status()
