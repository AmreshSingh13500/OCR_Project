"""
[MODULE]   tests/conftest.py
[TASK]     T4.2 — Laravel webhook return (Step 6)
[SUBTASKS] T4.2.1 test env bootstrap so app.config.Settings() can instantiate under pytest
[SUMMARY]  `app/config.py:Settings` (T1.1.2) is instantiated at import time and fails fast
           when required env vars are missing — correct for production, but it also means
           any test importing anything that transitively imports app.config needs those 4
           vars set before collection. Pytest always imports a directory's conftest.py
           before its sibling test modules, so setting them here (fixed, obviously-fake
           values, never real secrets) covers every test module without relying on a
           developer's local `.env`. Assigned unconditionally (not `setdefault`) so tests
           never accidentally hit a real Laravel/OpenAI endpoint from a dev's own `.env`.
           This is a minimal bootstrap, not the full `conftest.py` (fixtures: sample
           files, mock OpenAI, mock Laravel webhook) the plan's §2 layout describes —
           T5.1.1 extends this file with fixtures per CODING_RULES.md Rule 3.
[PLAN]     IMPLEMENTATION_PLAN.md §2 (tests/conftest.py) → T4.2.1
[HISTORY]  2026-07-17  T4.2.1  initial required-env-var bootstrap for Settings()
"""

import os

os.environ["OCR_API_KEY"] = "test-ocr-api-key"
os.environ["LARAVEL_WEBHOOK_URL"] = "https://laravel.test/api/internal/ocr-webhook"
os.environ["LARAVEL_WEBHOOK_KEY"] = "test-laravel-webhook-key"
os.environ["OPENAI_API_KEY"] = "sk-test-openai-key"
