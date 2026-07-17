"""
[MODULE]   tests/test_webhook_client.py
[TASK]     T4.2 — Laravel webhook return (Step 6)
[SUBTASKS] T4.2.1 async httpx POST with Bearer key, WebhookPayload body
[SUMMARY]  respx-mocked tests for webhook_client.py. No file fixtures needed — the
           webhook only ever sends a plain dict payload, so this doesn't depend on
           T5.1.1's fixture assembly. Verifies the exact WebhookPayload key set and
           that the POST carries the Bearer LARAVEL_WEBHOOK_KEY header and JSON body.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T4.2.1
[HISTORY]  2026-07-17  T4.2.1  initial success-path tests
"""

import json

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
