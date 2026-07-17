"""
[MODULE]   tests/test_security_hardening.py
[TASK]     T5.2 — Security hardening (app level)
[SUBTASKS] T5.2.1 constant-time token compare re-verification; no token in logs
           T5.2.2 privacy logging: field values DEBUG-only, presence booleans at INFO
           T5.2.3 request body size limit — reject bodies over MAX_REQUEST_BODY_BYTES
           T5.2.4 SSRF guard: ALLOWED_FILE_HOSTS allowlist + private/loopback IP rejection
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
           T5.2.3: confirms a request body over MAX_REQUEST_BODY_BYTES gets 413 through
           the real endpoint, and that enforce_body_size_limit()'s actual-body-length
           fallback still catches an oversized body even if Content-Length understates it.
           T5.2.4: confirms the always-on private/loopback/link-local IP guard rejects
           file_url hosts like 169.254.169.254 (cloud metadata), 127.0.0.1, and
           "localhost" — via `ssrf_client`, a fixture that (unlike `client`) does NOT
           bypass the real SSRF check — and that ALLOWED_FILE_HOSTS allowlist matching
           is exact/wildcard-prefix correct. Hostname-DNS-resolution cases are exercised
           by monkeypatching the event loop's getaddrinfo (no real network dependency,
           since a sandboxed test box may have no DNS access); IP-literal and
           OS-resolved-loopback cases ("127.0.0.1", "localhost") run for real since
           those never need an actual network round-trip.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T5.2.1, T5.2.2, T5.2.3, T5.2.4
[HISTORY]  2026-07-17  T5.2.1  initial no-token-in-logs regression tests
           2026-07-17  T5.2.2  add privacy-logging tests for orchestrator.py and
                                webhook_client.py
           2026-07-17  T5.2.3  add request-body-size-limit tests
           2026-07-17  T5.2.4  add SSRF guard tests (allowlist matching, IP-safety
                                checks, and end-to-end 400 rejection through the real
                                endpoint)
"""

import asyncio
import inspect
import json
import logging
import socket

import pytest
import respx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import Response

from app.api import routes
from app.api.routes import enforce_body_size_limit
from app.auth import require_api_key
from app.config import MAX_REQUEST_BODY_BYTES, settings
from app.pipeline.orchestrator import _log_extracted_data_privacy_safe
from app.pipeline.webhook_client import _redact_extracted_data, build_webhook_payload, send_webhook

AUTH_HEADERS = {"Authorization": f"Bearer {settings.OCR_API_KEY}"}
_WRONG_TOKEN = "wrong-token-should-never-appear-in-logs"


async def _bypass_ssrf_check(file_url: str) -> bool:
    return True


@pytest.fixture
def client(monkeypatch):
    scheduled = []
    monkeypatch.setattr(routes, "run_pipeline", lambda req: scheduled.append(req))
    # [T5.2.4] These T5.2.1-T5.2.3 tests aren't about the SSRF guard itself (its own
    # tests are below, using a separate fixture that keeps the real check) — bypassing
    # it here avoids a real DNS lookup for the placeholder "https://x/doc.pdf" host.
    monkeypatch.setattr(routes, "_is_safe_file_url", _bypass_ssrf_check)
    test_app = FastAPI()
    test_app.include_router(routes.router)
    test_app.state.scheduled = scheduled
    with TestClient(test_app) as c:
        yield c


@pytest.fixture
def ssrf_client(monkeypatch):
    """Same as `client`, but does NOT bypass the SSRF guard — for T5.2.4's own tests."""
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


# --- T5.2.3 — request body size limit (FastAPI level) ---


def test_oversized_request_body_returns_413(client):
    """[T5.2.3] AC: a request body over MAX_REQUEST_BODY_BYTES is rejected with 413."""
    oversized_blob = "x" * (MAX_REQUEST_BODY_BYTES + 1)
    response = client.post(
        "/api/v1/process",
        headers=AUTH_HEADERS,
        json={
            "case_id": "case-1",
            "message_id": "msg-1",
            "file_url": "https://x/doc.pdf",
            "file_name": oversized_blob,
        },
    )
    assert response.status_code == 413
    assert client.app.state.scheduled == []


def test_normal_sized_request_body_is_not_rejected(client):
    """[T5.2.3] AC: a normal small request body is unaffected by the size guard."""
    response = client.post(
        "/api/v1/process",
        headers=AUTH_HEADERS,
        json={"case_id": "case-1", "message_id": "msg-1", "file_url": "https://x/doc.pdf"},
    )
    assert response.status_code == 202


class _FakeRequestWithLyingContentLength:
    """Simulates a request whose Content-Length header understates the real body size."""

    def __init__(self, real_body: bytes, claimed_content_length: int):
        self.headers = {"content-length": str(claimed_content_length)}
        self._real_body = real_body

    async def body(self) -> bytes:
        return self._real_body


@pytest.mark.asyncio
async def test_enforce_body_size_limit_catches_understated_content_length():
    """[T5.2.3] AC: the actual buffered body length is still checked even when
    Content-Length lies about being small — a malicious client can't bypass the cap by
    sending a false header."""
    fake_request = _FakeRequestWithLyingContentLength(
        real_body=b"x" * (MAX_REQUEST_BODY_BYTES + 1), claimed_content_length=10
    )
    with pytest.raises(HTTPException) as exc_info:
        await enforce_body_size_limit(fake_request)
    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_enforce_body_size_limit_rejects_via_content_length_fast_path():
    """[T5.2.3] AC: an oversized Content-Length header is rejected before the body is
    even read (fast path)."""

    class _NeverReadBody:
        def __init__(self):
            self.headers = {"content-length": str(MAX_REQUEST_BODY_BYTES + 1)}

        async def body(self):
            raise AssertionError("body() should not be called when Content-Length already exceeds the limit")

    with pytest.raises(HTTPException) as exc_info:
        await enforce_body_size_limit(_NeverReadBody())
    assert exc_info.value.status_code == 413


# --- T5.2.4 — SSRF guard: ALLOWED_FILE_HOSTS allowlist + private/loopback IP rejection ---


def test_host_matches_allowlist_wildcard_and_exact():
    """[T5.2.4] Unit test: wildcard-prefix and exact-match allowlist patterns."""
    assert routes._host_matches_allowlist("media.amazonaws.com", ["*.amazonaws.com"]) is True
    assert routes._host_matches_allowlist("amazonaws.com", ["*.amazonaws.com"]) is True
    assert routes._host_matches_allowlist("evil.com", ["*.amazonaws.com"]) is False
    assert routes._host_matches_allowlist("media.ultramsg.com", ["media.ultramsg.com"]) is True
    assert routes._host_matches_allowlist("other.ultramsg.com", ["media.ultramsg.com"]) is False


def test_is_disallowed_ip_covers_private_loopback_link_local_and_public():
    """[T5.2.4] Unit test: _is_disallowed_ip() classifies each IP range correctly."""
    assert routes._is_disallowed_ip("169.254.169.254") is True  # cloud metadata (link-local)
    assert routes._is_disallowed_ip("127.0.0.1") is True  # loopback
    assert routes._is_disallowed_ip("10.0.0.5") is True  # private
    assert routes._is_disallowed_ip("::1") is True  # IPv6 loopback
    assert routes._is_disallowed_ip("8.8.8.8") is False  # public


@pytest.mark.asyncio
async def test_resolve_and_check_host_ip_literal_public_is_safe():
    """[T5.2.4] AC: an IP-literal host that's public is not rejected (no DNS involved)."""
    assert await routes._resolve_and_check_host("8.8.8.8") is True


@pytest.mark.asyncio
async def test_resolve_and_check_host_ip_literal_link_local_is_unsafe():
    """[T5.2.4] AC: file_url=...169.254.169.254... (cloud metadata) is rejected."""
    assert await routes._resolve_and_check_host("169.254.169.254") is False


@pytest.mark.asyncio
async def test_resolve_and_check_host_ip_literal_loopback_is_unsafe():
    """[T5.2.4] AC: a loopback IP literal is rejected."""
    assert await routes._resolve_and_check_host("127.0.0.1") is False


@pytest.mark.asyncio
async def test_resolve_and_check_host_localhost_is_unsafe():
    """[T5.2.4] AC: file_url=...localhost... is rejected — resolved via the OS's
    built-in loopback resolution, no external network dependency."""
    assert await routes._resolve_and_check_host("localhost") is False


@pytest.mark.asyncio
async def test_resolve_and_check_host_hostname_resolving_to_public_ip_is_safe(monkeypatch):
    """[T5.2.4] A hostname (not an IP literal) that resolves to a public IP is safe —
    DNS resolution mocked so this doesn't depend on real network access."""

    async def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    assert await routes._resolve_and_check_host("example.com") is True


@pytest.mark.asyncio
async def test_resolve_and_check_host_hostname_resolving_to_private_ip_is_unsafe(monkeypatch):
    """[T5.2.4] A hostname that resolves to a private IP (e.g. internal DNS rebinding
    target) is rejected."""

    async def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    assert await routes._resolve_and_check_host("internal.example.com") is False


@pytest.mark.asyncio
async def test_resolve_and_check_host_unresolvable_hostname_is_unsafe(monkeypatch):
    """[T5.2.4] An unresolvable host is treated as unsafe, not silently allowed through."""

    async def fake_getaddrinfo(host, port):
        raise socket.gaierror("mock: name or service not known")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    assert await routes._resolve_and_check_host("nonexistent.invalid") is False


@pytest.mark.asyncio
async def test_is_safe_file_url_rejects_missing_hostname():
    """[T5.2.4] A file_url with no parseable host is rejected outright."""
    assert await routes._is_safe_file_url("https:///doc.pdf") is False


@pytest.mark.asyncio
async def test_is_safe_file_url_allowlist_rejects_host_not_listed(monkeypatch):
    """[T5.2.4] AC: when ALLOWED_FILE_HOSTS is configured, a non-matching host is
    rejected even if its IP would otherwise be safe (IP check bypassed here to isolate
    the allowlist behavior specifically)."""
    monkeypatch.setattr(settings, "ALLOWED_FILE_HOSTS", "*.amazonaws.com")

    async def fake_safe(hostname):
        return True

    monkeypatch.setattr(routes, "_resolve_and_check_host", fake_safe)
    assert await routes._is_safe_file_url("https://evil.com/doc.pdf") is False


@pytest.mark.asyncio
async def test_is_safe_file_url_allowlist_allows_matching_host(monkeypatch):
    """[T5.2.4] AC: a host matching ALLOWED_FILE_HOSTS passes (given a safe IP)."""
    monkeypatch.setattr(settings, "ALLOWED_FILE_HOSTS", "*.amazonaws.com")

    async def fake_safe(hostname):
        return True

    monkeypatch.setattr(routes, "_resolve_and_check_host", fake_safe)
    assert await routes._is_safe_file_url("https://media.amazonaws.com/doc.pdf") is True


def test_link_local_metadata_file_url_returns_400_end_to_end(ssrf_client):
    """[T5.2.4] AC: file_url=https://169.254.169.254/... (cloud metadata endpoint,
    https since T1.2.5 requires it) is rejected with 400 through the real endpoint."""
    response = ssrf_client.post(
        "/api/v1/process",
        headers=AUTH_HEADERS,
        json={
            "case_id": "case-1",
            "message_id": "msg-1",
            "file_url": "https://169.254.169.254/latest/meta-data/",
        },
    )
    assert response.status_code == 400
    assert ssrf_client.app.state.scheduled == []


def test_localhost_file_url_returns_400_end_to_end(ssrf_client):
    """[T5.2.4] AC: file_url=https://localhost/... is rejected with 400 through the
    real endpoint."""
    response = ssrf_client.post(
        "/api/v1/process",
        headers=AUTH_HEADERS,
        json={"case_id": "case-1", "message_id": "msg-1", "file_url": "https://localhost/doc.pdf"},
    )
    assert response.status_code == 400
    assert ssrf_client.app.state.scheduled == []


def test_loopback_ip_file_url_returns_400_end_to_end(ssrf_client):
    """[T5.2.4] AC: file_url=https://127.0.0.1/... is rejected with 400 through the
    real endpoint."""
    response = ssrf_client.post(
        "/api/v1/process",
        headers=AUTH_HEADERS,
        json={"case_id": "case-1", "message_id": "msg-1", "file_url": "https://127.0.0.1/doc.pdf"},
    )
    assert response.status_code == 400
    assert ssrf_client.app.state.scheduled == []


def test_safe_public_ip_file_url_is_not_rejected_by_ssrf_guard(ssrf_client):
    """[T5.2.4] A file_url whose host is a public IP literal passes the SSRF guard
    (IP-literal, no DNS involved, so this is hermetic)."""
    response = ssrf_client.post(
        "/api/v1/process",
        headers=AUTH_HEADERS,
        json={"case_id": "case-1", "message_id": "msg-1", "file_url": "https://8.8.8.8/doc.pdf"},
    )
    assert response.status_code == 202
    assert len(ssrf_client.app.state.scheduled) == 1
