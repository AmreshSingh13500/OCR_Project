"""
[MODULE]   tests/test_routes.py
[TASK]     T1.2 — Auth & API endpoints
[SUBTASKS] T1.2.3 POST /api/v1/process — validate -> BackgroundTask -> 202 immediately
           T1.2.4 GET /health — 200 with clip_loaded/paddle_loaded flags, unauthenticated
[SUMMARY]  TestClient-level tests for app/api/routes.py, mounted on a minimal FastAPI app
           built here (not app.main:app) so these tests don't trigger main.py's lifespan
           (real CLIP/PaddleOCR model loads) just to exercise HTTP routing/validation/
           auth. `run_pipeline` is monkeypatched at the routes module level so a 202
           response never actually runs the pipeline; the fake records the ProcessRequest
           it was scheduled with so the "enqueued as a BackgroundTask" behavior itself is
           verifiable, not just the HTTP response shape. /health tests set app.state
           directly (no lifespan run) to exercise both the "not loaded yet" and "loaded"
           flag states, and confirm no auth header is required.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.2.3, T1.2.4
[HISTORY]  2026-07-17  T1.2.3  initial 202/401/422 endpoint tests
           2026-07-17  T1.2.4  add /health tests (model-loaded flags false/true, no auth)
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.config import settings

AUTH_HEADERS = {"Authorization": f"Bearer {settings.OCR_API_KEY}"}


@pytest.fixture
def client(monkeypatch):
    scheduled = []
    monkeypatch.setattr(routes, "run_pipeline", lambda req: scheduled.append(req))
    test_app = FastAPI()
    test_app.include_router(routes.router)
    test_app.state.scheduled = scheduled
    with TestClient(test_app) as c:
        yield c


def test_valid_request_returns_202_and_enqueues_pipeline(client):
    """[T1.2.3] AC: valid request -> 202 with {"status": "accepted", "case_id": ...}, run_pipeline scheduled."""
    response = client.post(
        "/api/v1/process",
        headers=AUTH_HEADERS,
        json={"case_id": "case-1", "message_id": "msg-1", "file_url": "https://x/doc.pdf"},
    )
    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "case_id": "case-1"}
    assert len(client.app.state.scheduled) == 1
    assert client.app.state.scheduled[0].case_id == "case-1"


def test_missing_bearer_token_returns_401(client):
    """[T1.2.1/T1.2.3] AC: no bearer token -> 401."""
    response = client.post(
        "/api/v1/process",
        json={"case_id": "case-1", "message_id": "msg-1", "file_url": "https://x/doc.pdf"},
    )
    assert response.status_code == 401
    assert client.app.state.scheduled == []


def test_wrong_bearer_token_returns_401(client):
    """[T1.2.1/T1.2.3] AC: bad bearer token -> 401."""
    response = client.post(
        "/api/v1/process",
        headers={"Authorization": "Bearer wrong-token"},
        json={"case_id": "case-1", "message_id": "msg-1", "file_url": "https://x/doc.pdf"},
    )
    assert response.status_code == 401
    assert client.app.state.scheduled == []


def test_malformed_body_returns_422(client):
    """[T1.2.3] AC: malformed body (missing required fields) -> 422."""
    response = client.post(
        "/api/v1/process",
        headers=AUTH_HEADERS,
        json={"case_id": "case-1"},
    )
    assert response.status_code == 422
    assert client.app.state.scheduled == []


def test_health_no_auth_reports_models_not_loaded():
    """[T1.2.4] AC: /health is unauthenticated and returns 200 with clip_loaded/paddle_loaded flags."""
    test_app = FastAPI()
    test_app.include_router(routes.router)
    with TestClient(test_app) as c:
        response = c.get("/health")  # deliberately no Authorization header
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "clip_loaded": False, "paddle_loaded": False}


def test_health_reports_models_loaded_when_state_set():
    """[T1.2.4] AC: /health reflects app.state.clip_model/paddle_ocr once lifespan has set them."""
    test_app = FastAPI()
    test_app.include_router(routes.router)
    test_app.state.clip_model = object()
    test_app.state.paddle_ocr = object()
    with TestClient(test_app) as c:
        response = c.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["clip_loaded"] is True
    assert body["paddle_loaded"] is True
