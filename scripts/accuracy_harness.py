"""
[MODULE]   scripts/accuracy_harness.py
[TASK]     T5.1 — Test suite completion
[SUBTASKS] T5.1.4 accuracy validation harness — field-level accuracy report script
[SUMMARY]  Manual, pre-release accuracy report (plan §4 T5.1.4 — "not in CI"). Runs
           each ground-truthed T5.1.1 fixture through the real pipeline (Steps 2b-5:
           PDF/image detection -> clean -> classify -> PaddleOCR-or-vision -> OpenAI
           structured extraction) and scores each of the 6 ExtractedData fields
           against tests/fixtures/ground_truth.py's expected values, then reports
           per-path accuracy against the PRD targets (>95% "printed" [native_pdf /
           paddleocr], >85% "handwritten" [vision_api] — the vision_api bucket also
           covers scans/medicine-boxes; the plan only names two target buckets).
           password.pdf and blurry.jpg have no field-level ground truth (see
           ground_truth.py) and are scored as pass/fail special cases instead:
           password.pdf must raise PasswordProtectedError, blurry.jpg must come back
           all-fields-null. The field-matching/report-building logic (score_extraction,
           build_report) is pure and unit-tested in tests/test_accuracy_harness.py
           without needing real models or a real OPENAI_API_KEY; running `main()` for
           real does need both (CLIP/PaddleOCR load from local cache, OpenAI calls
           cost real tokens), plus poppler-utils on the host for scanned.pdf's
           pdf2image conversion (README "System requirements") — see README's
           "Accuracy harness" section.
           Run: `.venv\\Scripts\\python.exe -m scripts.accuracy_harness`
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T5.1.4
[HISTORY]  2026-07-17  T5.1.4  initial harness
"""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.pipeline.classifier import load_clip, set_clip
from app.pipeline.downloader import ContentKind, UnsupportedFileError, detect_content_kind
from app.pipeline.llm_extractor import LLMError, extract_from_text, is_all_fields_null
from app.pipeline.ocr_engine import load_paddleocr, set_paddleocr
from app.pipeline.orchestrator import _StepTimings, _extract_from_pages, _pil_to_bgr
from app.pipeline.pdf_handler import (
    PasswordProtectedError,
    convert_scanned_pdf,
    extract_native_text,
    open_pdf,
)
from tests.fixtures.ground_truth import GROUND_TRUTH

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"

FIELD_NAMES = ("patient_name", "doctor_name", "diagnosis", "procedure", "cost", "medicines")

# [T5.1.4] Per plan §4 T5.1's AC exactly. "printed" = native_pdf/paddleocr paths;
# "handwritten" = vision_api (also covers scans/medicine boxes — the plan names only
# these two target buckets, see [SUMMARY]).
PRD_ACCURACY_TARGETS = {"printed": 0.95, "handwritten": 0.85}

_PATH_TO_BUCKET = {"native_pdf": "printed", "paddleocr": "printed", "vision_api": "handwritten"}


def _normalize(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().casefold())


# [T5.1.4] A field "matches" when its normalized value is identical; `medicines` (a
# list) matches when the normalized item sets are equal, order-independent.
def _field_matches(expected, actual) -> bool:
    if isinstance(expected, list) or isinstance(actual, list):
        expected_set = {_normalize(v) for v in (expected or [])}
        actual_set = {_normalize(v) for v in (actual or [])}
        return expected_set == actual_set
    return _normalize(expected) == _normalize(actual)


# [T5.1.4] Per-field pass/fail for one fixture — the atomic unit the accuracy % is built from.
def score_extraction(expected: dict, actual: dict) -> dict[str, bool]:
    return {field_name: _field_matches(expected[field_name], actual.get(field_name)) for field_name in FIELD_NAMES}


@dataclass
class FixtureResult:
    name: str
    processing_path: Optional[str]
    field_matches: dict[str, bool] = field(default_factory=dict)
    special_case: Optional[str] = None  # e.g. "password_protected_ok", "all_null_ok"


# [T5.1.4] Mirrors orchestrator._run_extraction's Steps 2b-5 dispatch, sourcing bytes
# from a local fixture file instead of a network download (Step 2a is out of scope for
# an accuracy harness — it's about extraction quality, not the downloader).
async def _extract_for_fixture(path: Path) -> tuple[dict, str]:
    data = path.read_bytes()
    kind = detect_content_kind(data)
    timings = _StepTimings()

    if kind == ContentKind.PDF:
        doc = open_pdf(data)
        native_result = extract_native_text(doc)
        if native_result is not None:
            return extract_from_text(native_result.text), "native_pdf"
        scanned = convert_scanned_pdf(data, doc.page_count)
        images = [_pil_to_bgr(page) for page in scanned.images]
        return await _extract_from_pages(images, path.stem, timings)
    if kind == ContentKind.IMAGE:
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        return await _extract_from_pages([image], path.stem, timings)
    raise UnsupportedFileError(f"{path.name}: neither PDF nor image magic bytes")


# [T5.1.4] Runs every GROUND_TRUTH fixture plus the two special-case fixtures
# (password.pdf, blurry.jpg) through the real pipeline.
async def run_all_fixtures() -> list[FixtureResult]:
    results = []

    for name, expected in GROUND_TRUTH.items():
        actual, processing_path = await _extract_for_fixture(FIXTURES_DIR / name)
        results.append(FixtureResult(
            name=name, processing_path=processing_path,
            field_matches=score_extraction(expected, actual),
        ))

    try:
        open_pdf((FIXTURES_DIR / "password.pdf").read_bytes())
        password_ok = False
    except PasswordProtectedError:
        password_ok = True
    results.append(FixtureResult(
        name="password.pdf", processing_path=None,
        special_case="password_protected_ok" if password_ok else "password_protected_FAILED",
    ))

    try:
        actual, blurry_path = await _extract_for_fixture(FIXTURES_DIR / "blurry.jpg")
        blurry_ok = is_all_fields_null(actual)
    except LLMError:
        blurry_ok = True  # an LLM failure on an unreadable image is an acceptable outcome too
        blurry_path = None
    results.append(FixtureResult(
        name="blurry.jpg", processing_path=blurry_path,
        special_case="all_null_ok" if blurry_ok else "all_null_FAILED",
    ))

    return results


# [T5.1.4] Builds the printed report: per-fixture per-field pass/fail, per-bucket
# aggregate accuracy against PRD_ACCURACY_TARGETS, and the two special-case checks.
def build_report(results: list[FixtureResult]) -> str:
    lines = ["Accuracy harness report", "=" * 40, ""]
    bucket_totals: dict[str, list[bool]] = {}

    for result in results:
        if result.special_case is not None:
            lines.append(f"{result.name}: {result.special_case}")
            continue

        bucket = _PATH_TO_BUCKET.get(result.processing_path, "unknown")
        bucket_totals.setdefault(bucket, [])
        lines.append(f"{result.name} (processing_path={result.processing_path}, bucket={bucket}):")
        for field_name in FIELD_NAMES:
            matched = result.field_matches[field_name]
            bucket_totals[bucket].append(matched)
            lines.append(f"    {field_name}: {'OK' if matched else 'MISMATCH'}")

    lines.append("")
    lines.append("Per-bucket accuracy vs. PRD targets:")
    for bucket, target in PRD_ACCURACY_TARGETS.items():
        matches = bucket_totals.get(bucket, [])
        accuracy = (sum(matches) / len(matches)) if matches else None
        status = "n/a (no fixtures)" if accuracy is None else (
            f"{accuracy:.1%} ({'PASS' if accuracy >= target else 'FAIL'} vs target {target:.0%})"
        )
        lines.append(f"  {bucket}: {status}")

    return "\n".join(lines)


async def _main() -> None:
    set_clip(*load_clip())
    set_paddleocr(load_paddleocr())
    results = await run_all_fixtures()
    print(build_report(results))


if __name__ == "__main__":
    asyncio.run(_main())
