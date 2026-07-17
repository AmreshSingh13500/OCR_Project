"""
[MODULE]   tests/test_webhook_client.py
[TASK]     T4.2 — Laravel webhook return (Step 6)
[SUBTASKS] T4.2.1 async httpx POST with Bearer key, WebhookPayload body
           T4.2.2 tenacity retries on 5xx/connection only; 4xx = no retry, CRITICAL log
[SUMMARY]  respx-mocked tests for webhook_client.py. No file fixtures needed — the
           webhook only ever sends a plain dict payload, so this doesn't depend on
           T5.1.1's fixture assembly. Verifies the exact WebhookPayload key set, that
           the POST carries the Bearer LARAVEL_WEBHOOK_KEY header and JSON body, that a
           5xx is retried until it succeeds, and that a 4xx fails on the first attempt
           with a CRITICAL log (no retry).
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T4.2.1, T4.2.2
[HISTORY]  2026-07-17  T4.2.1  initial success-path tests
           2026-07-17  T4.2.2  add 5xx-retries-then-succeeds and 4xx-no-retry-CRITICAL tests
"""

import json
import logging

import pytest
import respx
from httpx import Response

from app.config import settings
from app.pipeline.webhook_client import build_webhook_payload, send_webhook


def test_build_webhook_payload_has_exact_key_set():
    """[T4.2.1] WebhookPayload has exactly the 6 contract keys, no more, no less."""
    payload = build_webhook_payload(
        case_id="case-1",
        message_id="msg-1",
        status="success",
        processing_path="native_pdf",
        extracted_data={"patient_name": "Jane Doe"},
        error_message=None,
    )
    assert set(payload.keys()) == {
        "case_id",
        "message_id",
        "status",
        "processing_path",
        "extracted_data",
        "error_message",
    }
    assert payload["case_id"] == "case-1"
    assert payload["message_id"] == "msg-1"
    assert payload["status"] == "success"
    assert payload["processing_path"] == "native_pdf"
    assert payload["extracted_data"] == {"patient_name": "Jane Doe"}
    assert payload["error_message"] is None


@pytest.mark.asyncio
async def test_send_webhook_success_posts_bearer_and_json_body():
    """[T4.2.1] AC: success — POST hits LARAVEL_WEBHOOK_URL with Bearer auth and the payload as JSON."""
    payload = build_webhook_payload(
        case_id="case-1",
        message_id="msg-1",
        status="success",
        processing_path="paddleocr",
        extracted_data={"patient_name": "Jane Doe"},
        error_message=None,
    )

    with respx.mock:
        route = respx.post(settings.LARAVEL_WEBHOOK_URL).mock(
            return_value=Response(200, json={"ok": True})
        )

        await send_webhook(payload)

        assert route.called
        request = route.calls.last.request
        assert request.headers["Authorization"] == f"Bearer {settings.LARAVEL_WEBHOOK_KEY}"
        assert json.loads(request.content) == payload


@pytest.mark.asyncio
async def test_send_webhook_retries_5xx_then_succeeds(caplog):
    """[T4.2.2] AC: 5xx -> retry -> success — second attempt succeeds, no CRITICAL log."""
    payload = build_webhook_payload(
        case_id="case-2",
        message_id="msg-2",
        status="success",
        processing_path="vision_api",
        extracted_data={},
        error_message=None,
    )

    with caplog.at_level(logging.CRITICAL):
        with respx.mock:
            route = respx.post(settings.LARAVEL_WEBHOOK_URL).mock(
                side_effect=[Response(503), Response(200, json={"ok": True})]
            )

            await send_webhook(payload)

            assert route.call_count == 2

    assert not any(r.levelno == logging.CRITICAL for r in caplog.records)


@pytest.mark.asyncio
async def test_send_webhook_4xx_fails_immediately_and_logs_critical(caplog):
    """[T4.2.2] AC: 401 -> single attempt + CRITICAL log, never retried."""
    payload = build_webhook_payload(
        case_id="case-3",
        message_id="msg-3",
        status="error",
        processing_path=None,
        extracted_data=None,
        error_message="Some error",
    )

    with caplog.at_level(logging.CRITICAL):
        with respx.mock:
            route = respx.post(settings.LARAVEL_WEBHOOK_URL).mock(
                return_value=Response(401, json={"error": "unauthorized"})
            )

            await send_webhook(payload)

            assert route.call_count == 1

    critical_records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(critical_records) == 1
    assert "401" in critical_records[0].getMessage()
