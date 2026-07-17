"""
[MODULE]   tests/test_accuracy_harness.py
[TASK]     T5.1 — Test suite completion
[SUBTASKS] T5.1.4 accuracy validation harness — field-level accuracy report script
[SUMMARY]  Unit tests for scripts/accuracy_harness.py's pure scoring/reporting logic
           (score_extraction, build_report) plus an end-to-end run_all_fixtures() pass
           with the real per-fixture extraction step monkeypatched out — this proves
           the harness produces a correct report (the plan's literal AC: "accuracy
           harness produces a report") without needing real CLIP/PaddleOCR/OpenAI
           calls or a real OPENAI_API_KEY. A real, uncommitted run of
           `python -m scripts.accuracy_harness` (real models + a real API key) is the
           actual pre-release accuracy check — not something this pytest suite runs.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T5.1.4
[HISTORY]  2026-07-17  T5.1.4  initial test file
"""

import pytest

from scripts import accuracy_harness
from scripts.accuracy_harness import (
    FixtureResult,
    build_report,
    score_extraction,
)
from tests.fixtures.ground_truth import GROUND_TRUTH

_ALL_NULL = {
    "patient_name": None, "doctor_name": None, "diagnosis": None,
    "procedure": None, "cost": None, "medicines": None,
}

_PATH_BY_FIXTURE = {
    "native.pdf": "native_pdf",
    "scanned.pdf": "paddleocr",
    "printed_report.jpg": "paddleocr",
    "handwritten.jpg": "vision_api",
    "medicine_box.jpg": "vision_api",
}


def test_field_matches_case_and_whitespace_insensitive():
    assert accuracy_harness._field_matches("Dr. Alice Johnson", "  dr. alice   johnson ") is True


def test_field_matches_medicines_list_is_order_independent():
    assert accuracy_harness._field_matches(
        ["Metformin 500mg", "Glimepiride 2mg"], ["Glimepiride 2mg", "Metformin 500mg"],
    ) is True


def test_field_matches_none_vs_none_matches():
    assert accuracy_harness._field_matches(None, None) is True


def test_score_extraction_all_fields_match():
    expected = GROUND_TRUTH["native.pdf"]
    scores = score_extraction(expected, dict(expected))
    assert all(scores.values())


def test_score_extraction_flags_a_wrong_field():
    expected = GROUND_TRUTH["native.pdf"]
    actual = dict(expected, diagnosis="something completely different")
    scores = score_extraction(expected, actual)
    assert scores["diagnosis"] is False
    assert scores["patient_name"] is True


def test_build_report_perfect_scores_pass_both_buckets():
    results = [
        FixtureResult(name=name, processing_path=_PATH_BY_FIXTURE[name], field_matches={f: True for f in accuracy_harness.FIELD_NAMES})
        for name in GROUND_TRUTH
    ]
    report = build_report(results)

    assert "printed: 100.0% (PASS vs target 95%)" in report
    assert "handwritten: 100.0% (PASS vs target 85%)" in report


def test_build_report_flags_fail_when_below_target():
    results = [
        FixtureResult(name=name, processing_path=_PATH_BY_FIXTURE[name], field_matches={f: True for f in accuracy_harness.FIELD_NAMES})
        for name in GROUND_TRUTH
    ]
    # Fail every field for handwritten.jpg -> handwritten bucket accuracy drops below 85%.
    for result in results:
        if result.name == "handwritten.jpg":
            result.field_matches = {f: False for f in accuracy_harness.FIELD_NAMES}

    report = build_report(results)
    assert "FAIL vs target 85%" in report
    assert "PASS vs target 95%" in report  # printed bucket unaffected


def test_build_report_includes_special_case_lines():
    results = [
        FixtureResult(name="password.pdf", processing_path=None, special_case="password_protected_ok"),
        FixtureResult(name="blurry.jpg", processing_path="vision_api", special_case="all_null_ok"),
    ]
    report = build_report(results)
    assert "password.pdf: password_protected_ok" in report
    assert "blurry.jpg: all_null_ok" in report


@pytest.mark.asyncio
async def test_run_all_fixtures_produces_a_report_with_extraction_stubbed(monkeypatch):
    """[T5.1.4] AC: the harness produces a report — end-to-end with the real per-fixture extraction stubbed to a perfect match, no real models/API calls needed."""

    async def fake_extract_for_fixture(path):
        if path.name == "blurry.jpg":
            return dict(_ALL_NULL), "vision_api"
        return dict(GROUND_TRUTH[path.name]), _PATH_BY_FIXTURE[path.name]

    monkeypatch.setattr(accuracy_harness, "_extract_for_fixture", fake_extract_for_fixture)

    results = await accuracy_harness.run_all_fixtures()
    report = build_report(results)

    assert len(results) == len(GROUND_TRUTH) + 2  # + password.pdf and blurry.jpg special cases
    assert "printed: 100.0% (PASS vs target 95%)" in report
    # password.pdf is a real committed fixture (T5.1.1) — open_pdf() runs for real here
    # and genuinely raises PasswordProtectedError, no stubbing needed.
    assert "password.pdf: password_protected_ok" in report
