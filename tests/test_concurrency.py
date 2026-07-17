"""
[MODULE]   tests/test_concurrency.py
[TASK]     T5.1 — Test suite completion
[SUBTASKS] T5.1.3 concurrency test: 8 parallel requests -> 8 webhooks, no data bleed
[SUMMARY]  Runs 8 concurrent run_pipeline() calls (T1.2's POST /api/v1/process ->
           BackgroundTask -> run_pipeline() isn't built yet — T1.2 is still PENDING,
           see TASKS.md §5 T5.1 dependency note — so this exercises run_pipeline()
           directly, exactly the unit T1.2.3's endpoint will dispatch as a
           BackgroundTask once it exists). Collaborators are monkeypatched with
           per-request-index behavior and a staggered async sleep in the fake
           download step, so the 8 tasks genuinely interleave rather than happening
           to complete in submission order. Asserts exactly 8 webhook calls, each
           with its own case_id (no duplicates, none dropped), and that the
           case-context contextvar (app/utils/logging.py, T1.1.3) bound inside each
           task never leaks into another concurrent task's extracted_data — the
           literal "no cross-request data bleed" AC.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T5.1.3
[HISTORY]  2026-07-17  T5.1.3  initial concurrency test
"""

import asyncio
import io
from dataclasses import dataclass

import pytest

from app.pipeline import orchestrator
from app.pipeline.downloader import ContentKind
from app.pipeline.orchestrator import ProcessRequest, run_pipeline
from app.utils.logging import _case_id_var

_NUM_CONCURRENT_REQUESTS = 8


@dataclass
class _FakeDoc:
    page_count: int = 1


@dataclass
class _NativeResult:
    text: str


@pytest.mark.asyncio
async def test_concurrent_requests_produce_one_webhook_each_with_no_data_bleed(monkeypatch):
    """[T5.1.3] AC: 8 concurrent requests -> 8 webhook deliveries; each payload's case_id and extracted_data belong to that same request, never another's."""
    sent_payloads = []

    async def fake_download(file_url):
        # Stagger completion order (last-submitted finishes first) so the 8 tasks
        # actually interleave through run_pipeline() rather than running start-to-
        # finish one at a time.
        index = int(file_url.rsplit("/", 1)[-1])
        await asyncio.sleep((_NUM_CONCURRENT_REQUESTS - index) * 0.01)
        return io.BytesIO(f"%PDF-fake-{index}".encode())

    def fake_extract_from_text(text):
        # Tags the result with whatever case_id is currently bound in *this* task's
        # context — a context leak between concurrent tasks would surface as this
        # value not matching the payload's own case_id, asserted below.
        return {
            "patient_name": _case_id_var.get(), "doctor_name": None, "diagnosis": None,
            "procedure": None, "cost": None, "medicines": None,
        }

    async def fake_send_webhook(payload):
        sent_payloads.append(payload)

    monkeypatch.setattr(orchestrator, "download_file", fake_download)
    monkeypatch.setattr(orchestrator, "detect_content_kind", lambda data: ContentKind.PDF)
    monkeypatch.setattr(orchestrator, "open_pdf", lambda data: _FakeDoc(page_count=1))
    monkeypatch.setattr(
        orchestrator, "extract_native_text",
        lambda doc: _NativeResult(text="a native pdf text layer long enough to pass" * 3),
    )
    monkeypatch.setattr(orchestrator, "extract_from_text", fake_extract_from_text)
    monkeypatch.setattr(orchestrator, "send_webhook", fake_send_webhook)

    requests = [
        ProcessRequest(case_id=f"case-{i}", message_id=f"msg-{i}", file_url=f"https://x/doc/{i}")
        for i in range(_NUM_CONCURRENT_REQUESTS)
    ]

    await asyncio.gather(*(run_pipeline(req) for req in requests))

    assert len(sent_payloads) == _NUM_CONCURRENT_REQUESTS

    case_ids_seen = [p["case_id"] for p in sent_payloads]
    assert sorted(case_ids_seen) == sorted(r.case_id for r in requests)
    assert len(set(case_ids_seen)) == _NUM_CONCURRENT_REQUESTS  # no duplicates/dropped requests

    for payload in sent_payloads:
        assert payload["status"] == "success"
        assert payload["extracted_data"]["patient_name"] == payload["case_id"]
