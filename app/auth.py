"""
[MODULE]   app/auth.py
[TASK]     T1.2 — Auth & API endpoints
           T5.2 — Security hardening (app level)
[SUBTASKS] T1.2.1 Bearer token dependency, constant-time compare, 401 on failure
           T5.2.1 re-verify constant-time compare + no token in logs
[SUMMARY]  FastAPI dependency that authenticates incoming requests against the static
           OCR_API_KEY bearer token Laravel must send with every call. Uses
           secrets.compare_digest for the token comparison so response timing can't leak
           how many leading characters of a guessed token were correct. Raises
           HTTPException(401) directly (not a bare exception) so FastAPI returns exactly
           the AC-required status code; the token itself is never logged, matching
           CLAUDE.md's "never log bearer tokens" rule — this module has no logger at all,
           so neither the correct nor an attempted token can leak into a log line here.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.2.1; §4 → T5.2.1
[HISTORY]  2026-07-17  T1.2.1  initial bearer-token dependency
           2026-07-17  T5.2.1  re-verified secrets.compare_digest usage + confirmed no
                                logging statement exists in this module (no code change);
                                added regression tests locking in "no token in logs"
                                across the real HTTP request path
"""

import secrets
from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

# auto_error=False so a missing/malformed Authorization header reaches this dependency
# as `credentials=None` instead of HTTPBearer raising its own (differently-worded) 403.
_bearer_scheme = HTTPBearer(auto_error=False)


# [T1.2.1] Constant-time bearer-token check — a naive `==` comparison leaks timing
# information proportional to the number of matching leading bytes; compare_digest runs
# in time independent of where (or whether) the mismatch occurs.
# [T5.2.1] Re-verified 2026-07-17: still compare_digest (not `==`), and neither the
# expected token nor a caller-supplied one is ever passed to a logger anywhere in this
# function — see tests/test_security_hardening.py for the regression test.
def require_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
) -> None:
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, settings.OCR_API_KEY
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")
