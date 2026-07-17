"""
[MODULE]   tests/test_warmup_models.py
[TASK]     T6.1 — Server provisioning script (Phase 6)
[SUBTASKS] T6.1.3 model warmup — pre-download CLIP + PaddleOCR weights
[SUMMARY]  Unit test for scripts/warmup_models.py's warmup() orchestration. With both model
           loaders monkeypatched (no real ~600 MB download, no network), asserts warmup()
           invokes load_clip AND load_paddleocr exactly once each, in that order, and
           reports 2 model sets warmed — guarding the "both models, CLIP/torch before
           PaddleOCR/paddle" contract (TASKS.md §5 / T3.2.4). The actual weight-caching and
           first-request speedup are verified on the deploy server (T6.3), the same
           deferral precedent used for the other Phase 6 deploy artifacts.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T6.1.3
[HISTORY]  2026-07-18  T6.1.3  initial test file
"""

from scripts import warmup_models


def test_warmup_loads_both_models_once_in_order(monkeypatch):
    """[T6.1.3] warmup() pulls both model sets — load_clip then load_paddleocr, once each."""
    calls = []
    monkeypatch.setattr(warmup_models, "load_clip", lambda: calls.append("clip"))
    monkeypatch.setattr(warmup_models, "load_paddleocr", lambda: calls.append("paddle"))

    warmed = warmup_models.warmup()

    assert warmed == 2
    # CLIP (torch) must load before PaddleOCR (paddle) — see TASKS.md §5 T3.2.4 DLL note.
    assert calls == ["clip", "paddle"]
