"""
[MODULE]   app/pipeline/webhook_client.py
[TASK]     T4.2 — Laravel webhook return (Step 6)
           T5.2 — Security hardening (app level)
[SUBTASKS] T4.2.1 async httpx POST with Bearer key, WebhookPayload body
           T4.2.2 tenacity retries on 5xx/connection only; 4xx = no retry, CRITICAL log
           T4.2.3 retries exhausted -> CRITICAL log with full replayable payload JSON
           T5.2.2 redact extracted_data field values from the CRITICAL failure logs;
                  full payload (for replay) moved to a DEBUG-only log line
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
           immediately. If the 5xx/connection retries are exhausted instead, `send_webhook()`
           logs CRITICAL with the full payload JSON so a human can replay the delivery
           manually (no persistence layer/dead-letter queue in Phase 1 — plan §8
           clarification #3) — this call never raises to its caller either way; delivery
           failure is fully terminal and self-contained here. [T5.2.2] The CRITICAL logs
           (both the 4xx and retries-exhausted paths) now log a *redacted* payload —
           `extracted_data` replaced with per-field presence booleans, same convention
           as orchestrator.py's `_log_extracted_data_privacy_safe()` — so a delivery
           failure alert visible at the default INFO-and-above log level never contains
           patient field values. The full, unredacted payload (needed for an actual
           manual replay) is logged separately at DEBUG immediately after.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T4.2.1, T4.2.2, T4.2.3; T5.2.2
[HISTORY]  2026-07-17  T4.2.1  initial build_webhook_payload() + send_webhook() bare POST —
                                additive-only new module, no existing contract surface
                                touched (Rule 7 gate n/a)
           2026-07-17  T4.2.2  add _RetryableWebhookError + _post_webhook_with_retry()
                                tenacity wrapper (5xx/connection only, 3 attempts,
                                2-30s backoff); send_webhook() now catches the
                                unwrapped 4xx HTTPStatusError and logs CRITICAL —
                                no schemas.py/routes.py/error-string changes (Rule 7
                                gate n/a), webhook_client.py is internal-only
           2026-07-17  T4.2.3  send_webhook() now also catches _RetryableWebhookError
                                (retries exhausted) and logs CRITICAL with the full
                                payload JSON; T4.2 is feature-complete — no
                                schemas.py/routes.py/error-string changes (Rule 7 n/a)
           2026-07-17  T5.2.2  add _redact_extracted_data(); both CRITICAL log calls now
                                use a redacted payload (presence booleans only), and the
                                full payload moved to a new DEBUG log line right after —
                                Rule 7 gate checked: this changes only local log output,
                                not the WebhookPayload dict actually POSTed to Laravel
                                (send_webhook still sends the original, unredacted
                                `payload` over the wire) and not any frozen error string,
                                so it's contract-safe; full suite re-verified green
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


# [T5.2.2] Same presence-boolean convention as orchestrator.py's
# _log_extracted_data_privacy_safe() — used to keep field values out of the CRITICAL
# failure logs below, which run at a level visible in production by default.
def _redact_extracted_data(extracted_data: dict | None) -> dict | None:
    if extracted_data is None:
        return None
    return {field: value is not None for field, value in extracted_data.items()}


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


# [T4.2.2] A 4xx fails on the first attempt (see _post_webhook_with_retry) and is logged
# CRITICAL here as a contract/config bug — no automatic recovery is possible, a human
# needs to fix the URL/key/payload shape.
# [T4.2.3] If the 5xx/connection retries are exhausted instead, _post_webhook_with_retry
# reraises _RetryableWebhookError; caught here and logged CRITICAL so a human is alerted
# that delivery failed and needs to replay it manually (plan §8 clarification #3 — no
# dead-letter queue in Phase 1). Either failure path is terminal: send_webhook() never
# raises to its caller, since the CRITICAL log is itself the only recovery mechanism.
# [T5.2.2] The CRITICAL log itself carries a *redacted* payload (extracted_data replaced
# with presence booleans) since CRITICAL is visible at the default log level; the full,
# unredacted payload needed to actually replay the delivery is logged separately at
# DEBUG right after.
async def send_webhook(payload: dict) -> None:
    redacted_payload = {**payload, "extracted_data": _redact_extracted_data(payload.get("extracted_data"))}
    try:
        await _post_webhook_with_retry(payload)
    except httpx.HTTPStatusError as exc:
        logger.critical(
            "Webhook delivery failed with non-retryable HTTP %d (contract/config bug); "
            "payload=%s",
            exc.response.status_code,
            json.dumps(redacted_payload),
        )
        logger.debug("Webhook delivery failure — full payload for manual replay: %s", json.dumps(payload))
    except _RetryableWebhookError:
        logger.critical(
            "Webhook delivery failed after %d attempts (retries exhausted); payload=%s",
            _WEBHOOK_MAX_RETRIES,
            json.dumps(redacted_payload),
        )
        logger.debug("Webhook delivery failure — full payload for manual replay: %s", json.dumps(payload))
