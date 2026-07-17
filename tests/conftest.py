"""
[MODULE]   tests/conftest.py
[TASK]     T4.2 — Laravel webhook return (Step 6)
           T5.1 — Test suite completion
[SUBTASKS] T4.2.1 test env bootstrap so app.config.Settings() can instantiate under pytest
           T5.1.2 defensive classifier-before-ocr_engine import order, process-wide
[SUMMARY]  `app/config.py:Settings` (T1.1.2) is instantiated at import time and fails fast
           when required env vars are missing — correct for production, but it also means
           any test importing anything that transitively imports app.config needs those 4
           vars set before collection. Pytest always imports a directory's conftest.py
           before its sibling test modules, so setting them here (fixed, obviously-fake
           values, never real secrets) covers every test module without relying on a
           developer's local `.env`. Assigned unconditionally (not `setdefault`) so tests
           never accidentally hit a real Laravel/OpenAI endpoint from a dev's own `.env`.
           Also imports app.pipeline.classifier (torch) here, before anything else —
           the same Windows DLL conflict documented in main.py/orchestrator.py
           (paddlepaddle imported before torch in one process breaks torch's shm.dll
           load) applies across the whole pytest process, not just within one module;
           relying on test files happening to collect in an order where a
           classifier-importing module sorts before an ocr_engine-importing one is
           fragile, so it's pinned here instead, once, for every test run.
           This is a minimal bootstrap, not the full `conftest.py` (fixtures: sample
           files, mock OpenAI, mock Laravel webhook) the plan's §2 layout describes —
           T5.1.1 assembled the fixture files directly under tests/fixtures/ instead of
           adding fixture functions here, since every test module needs different real
           files, not a single shared shape (CODING_RULES.md Rule 3).
[PLAN]     IMPLEMENTATION_PLAN.md §2 (tests/conftest.py) → T4.2.1; §5 → T5.1.2
[HISTORY]  2026-07-17  T4.2.1  initial required-env-var bootstrap for Settings()
           2026-07-17  T5.1.2  pin classifier-before-ocr_engine import order process-wide
                                (dev-env note, no contract-surface change — Rule 7 n/a)
"""

import os

os.environ["OCR_API_KEY"] = "test-ocr-api-key"
os.environ["LARAVEL_WEBHOOK_URL"] = "https://laravel.test/api/internal/ocr-webhook"
os.environ["LARAVEL_WEBHOOK_KEY"] = "test-laravel-webhook-key"
os.environ["OPENAI_API_KEY"] = "sk-test-openai-key"

# [T5.1.2] Must come after the env vars above (app.config.settings needs them) and
# before any test module can import app.pipeline.ocr_engine (paddlepaddle) — see
# [SUMMARY]. Unused directly; the import side effect (loading torch first) is the point.
import app.pipeline.classifier  # noqa: E402,F401
