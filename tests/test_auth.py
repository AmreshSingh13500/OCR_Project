"""
[MODULE]   tests/test_auth.py
[TASK]     T1.2 — Auth & API endpoints
[SUBTASKS] T1.2.1 Bearer token dependency, constant-time compare, 401 on failure
[SUMMARY]  Unit tests for the require_api_key() FastAPI dependency: a correct bearer
           token passes silently, a wrong or missing one raises HTTPException(401).
           Full request-level behavior (an actual 401 HTTP response through the mounted
           endpoint) is covered by T1.2.3's route tests once POST /api/v1/process exists.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.2.1
[HISTORY]  2026-07-17  T1.2.1  initial dependency unit tests
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import require_api_key
from app.config import settings


def test_valid_token_passes():
    """[T1.2.1] AC: the correct bearer token does not raise."""
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=settings.OCR_API_KEY)
    require_api_key(creds)


def test_wrong_token_raises_401():
    """[T1.2.1] AC: bad token -> 401."""
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token")
    with pytest.raises(HTTPException) as exc_info:
        require_api_key(creds)
    assert exc_info.value.status_code == 401


def test_missing_token_raises_401():
    """[T1.2.1] AC: missing bearer token -> 401."""
    with pytest.raises(HTTPException) as exc_info:
        require_api_key(None)
    assert exc_info.value.status_code == 401
