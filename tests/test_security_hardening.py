"""
[MODULE]   tests/test_security_hardening.py
[TASK]     T5.2 — Security hardening (app level)
[SUBTASKS] T5.2.1 constant-time token compare re-verification; no token in logs
           T5.2.2 privacy logging: field values DEBUG-only, presence booleans at INFO
[SUMMARY]  Cross-cutting security tests for Phase 5's app-level hardening pass. Each
           T5.2 subtask gets its own section here rather than being folded into the
           module it touches, since these are properties of the whole request path
           (auth + routing + logging together), not of a single pipeline module.
           T5.2.1: confirms require_api_key() still uses secrets.compare_digest (not a
           naive `==`) and that neither the correct OCR_API_KEY nor a wrong attempted
           token ever appears in captured logs, exercised through the real mounted
           /api/v1/process endpoint (not just the bare dependency function) so the
           guarantee holds for the actual HTTP path Laravel calls.
           T5.2.2: confirms orchestrator.py's _log_extracted_data_privacy_safe() logs
           field presence booleans at INFO and the actual values only at DEBUG, and that
           webhook_client.py's send_webhook() CRITICAL failure logs never carry a raw
           field value (only the DEBUG-level full-payload log does).
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T5.2.1, T5.2.2
[HISTORY]  2026-07-17  T5.2.1  initial no-token-in-logs regression tests
           2026-07-17  T5.2.2  add privacy-logging tests for orchestrator.py and
                                webhook_client.py
"""

import inspect
import json
import logging

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from app.api import routes
from app.auth import require_api_key
from app.config import settings
from app.pipeline.orchestrator import _log_extracted_data_privacy_safe
from app.pipeline.webhook_client import _redact_extracted_data, build_webhook_payload, send_webhook

AUTH_HEADERS = {"Authorization": f"Bearer {settings.OCR_API_KEY}"}
_WRONG_TOKEN = "wrong-token-should-never-appear-in-logs"


@pytest.fixture
def client(monkeypatch):
    scheduled = []
    monkeypatch.setattr(routes, "run_pipeline", lambda req: scheduled.append(req))
    test_app = FastAPI()
    test_app.include_router(routes.router)
    test_app.state.scheduled = scheduled
    with TestClient(test_app) as c:
        yield c


def test_wrong_token_returns_401_and_never_logs_either_token(client, caplog):
    """[T5.2.1] AC: a failed auth attempt (through the real endpoint) never leaks the
    correct OCR_API_KEY or the caller-supplied wrong token into any log record."""
    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/api/v1/process",
            headers={"Authorization": f"Bearer {_WRONG_TOKEN}"},
            json={"case_id": "case-1", "message_id": "msg-1", "file_url": "https://x/doc.pdf"},
        )

    assert response.status_code == 401
    all_log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert settings.OCR_API_KEY not in all_log_text
    assert _WRONG_TOKEN not in all_log_text


def test_missing_token_returns_401_and_never_logs_real_token(client, caplog):
    """[T5.2.1] AC: a missing bearer token also never leaks the real OCR_API_KEY."""
    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/api/v1/process",
            json={"case_id": "case-1", "message_id": "msg-1", "file_url": "https://x/doc.pdf"},
        )

    assert response.status_code == 401
    all_log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert settings.OCR_API_KEY not in all_log_text


def test_valid_token_request_never_logs_the_token(client, caplog):
    """[T5.2.1] AC: a successful auth attempt doesn't echo the token into logs either."""
    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/api/v1/process",
            headers=AUTH_HEADERS,
            json={"case_id": "case-1", "message_id": "msg-1", "file_url": "https://x/doc.pdf"},
        )

    assert response.status_code == 202
    all_log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert settings.OCR_API_KEY not in all_log_text


def test_require_api_key_uses_constant_time_compare():
    """[T5.2.1] AC: re-verify require_api_key is implemented with secrets.compare_digest,
    not a naive `==`, by inspecting the function source (a regression guard against a
    future refactor silently swapping it back to a timing-unsafe comparison)."""
    assert "compare_digest" in inspect.getsource(require_api_key)


# --- T5.2.2 — privacy logging: field values DEBUG-only, presence booleans at INFO ---

_SENSITIVE_VALUE = "Jane Doe (should never appear above DEBUG)"


def test_extracted_data_logging_splits_presence_at_info_values_at_debug(caplog):
    """[T5.2.2] AC: presence booleans logged at INFO; actual field values only at DEBUG."""
    extracted_data = {
        "patient_name": _SENSITIVE_VALUE,
        "doctor_name": None,
        "diagnosis": "flu",
        "procedure": None,
        "cost": None,
        "medicines": None,
    }

    with caplog.at_level(logging.INFO):
        _log_extracted_data_privacy_safe(extracted_data)

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    assert _SENSITIVE_VALUE not in info_records[0].getMessage()
    assert "flu" not in info_records[0].getMessage()
    assert "'patient_name': True" in info_records[0].getMessage()
    assert "'doctor_name': False" in info_records[0].getMessage()

    # At INFO level, the DEBUG-level value log should not even be emitted.
    assert not any(r.levelno == logging.DEBUG for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        _log_extracted_data_privacy_safe(extracted_data)

    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(debug_records) == 1
    assert _SENSITIVE_VALUE in debug_records[0].getMessage()


def test_redact_extracted_data_replaces_values_with_presence_booleans():
    """[T5.2.2] Unit test: _redact_extracted_data() never carries a raw field value."""
    assert _redact_extracted_data(None) is None
    redacted = _redact_extracted_data({"patient_name": _SENSITIVE_VALUE, "cost": None})
    assert redacted == {"patient_name": True, "cost": False}


@pytest.mark.asyncio
async def test_send_webhook_critical_log_redacted_debug_log_has_full_payload(caplog):
    """[T5.2.2] AC: a webhook-delivery-failure CRITICAL log never carries a raw
    extracted_data value (only presence booleans); the full payload for manual replay
    is logged separately, only at DEBUG."""
    payload = build_webhook_payload(
        case_id="case-5",
        message_id="msg-5",
        status="success",
        processing_path="native_pdf",
        extracted_data={"patient_name": _SENSITIVE_VALUE},
        error_message=None,
    )

    with caplog.at_level(logging.DEBUG):
        with respx.mock:
            respx.post(settings.LARAVEL_WEBHOOK_URL).mock(
                return_value=Response(401, json={"error": "unauthorized"})
            )
            await send_webhook(payload)

    critical_records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]

    assert len(critical_records) == 1
    assert _SENSITIVE_VALUE not in critical_records[0].getMessage()
    assert '"patient_name": true' in critical_records[0].getMessage()

    assert any(_SENSITIVE_VALUE in r.getMessage() for r in debug_records)
    assert any(json.dumps(payload) in r.getMessage() for r in debug_records)
