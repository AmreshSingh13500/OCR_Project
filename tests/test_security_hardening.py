"""
[MODULE]   tests/test_security_hardening.py
[TASK]     T5.2 — Security hardening (app level)
[SUBTASKS] T5.2.1 constant-time token compare re-verification; no token in logs
[SUMMARY]  Cross-cutting security tests for Phase 5's app-level hardening pass. Each
           T5.2 subtask gets its own section here rather than being folded into the
           module it touches, since these are properties of the whole request path
           (auth + routing + logging together), not of a single pipeline module.
           T5.2.1: confirms require_api_key() still uses secrets.compare_digest (not a
           naive `==`) and that neither the correct OCR_API_KEY nor a wrong attempted
           token ever appears in captured logs, exercised through the real mounted
           /api/v1/process endpoint (not just the bare dependency function) so the
           guarantee holds for the actual HTTP path Laravel calls.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T5.2.1
[HISTORY]  2026-07-17  T5.2.1  initial no-token-in-logs regression tests
"""

import inspect
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.auth import require_api_key
from app.config import settings

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
