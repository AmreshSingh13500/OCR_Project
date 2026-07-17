"""
[MODULE]   tests/test_routes.py
[TASK]     T1.2 — Auth & API endpoints
[SUBTASKS] T1.2.3 POST /api/v1/process — validate -> BackgroundTask -> 202 immediately
[SUMMARY]  TestClient-level tests for app/api/routes.py, mounted on a minimal FastAPI app
           built here (not app.main:app) so these tests don't trigger main.py's lifespan
           (real CLIP/PaddleOCR model loads) just to exercise HTTP routing/validation/
           auth. `run_pipeline` is monkeypatched at the routes module level so a 202
           response never actually runs the pipeline; the fake records the ProcessRequest
           it was scheduled with so the "enqueued as a BackgroundTask" behavior itself is
           verifiable, not just the HTTP response shape.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.2.3
[HISTORY]  2026-07-17  T1.2.3  initial 202/401/422 endpoint tests
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
