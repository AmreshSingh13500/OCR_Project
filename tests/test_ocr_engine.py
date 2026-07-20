"""
[MODULE]   tests/test_ocr_engine.py
[TASK]     T3.2 — PaddleOCR engine (Step 4b, Branch A)
           T5.1 — Test suite completion
           T8.2 — Multi-language documents + extraction fidelity (additive)
           T8.4 — Non-English field values + explicit OCR non-English detection
[SUBTASKS] T3.2.2 AC: printed_report.jpg -> non-empty text containing known fixture keywords
           T3.2.3 AC: concurrent calls don't crash or interleave results
           T3.2.4 AC: <20-char boundary cases for the vision-reroute rule
           T8.2.2 AC: OcrResult carries mean confidence; <0.80 confidence boundary cases
                  for the reroute quality gate (incl. None -> char rule only)
           T8.4.2 AC: non-Latin OCR text reroutes to vision; clean English (incl.
                  numbers/punctuation) does not; _non_latin_letter_ratio boundaries
           T8.5.3 AC: >20%-lines-below-0.60 cluster gate boundaries (0.50/0.21/0.20/
                  0.00/None); OcrResult.low_confidence_ratio defaults to 0.0
           T5.1.2 backfilled committed pytest coverage for T3.2 using T5.1.1's real
                  printed_report.jpg fixture (previously verified ad hoc, per SUBTASKS.md)
[SUMMARY]  Loads the real PaddleOCR engine (cached locally from earlier manual
           verification — no network call needed) and runs it against the real
           printed_report.jpg fixture's ocr_ready (Step 3 cleaned) image, matching
           plan §4 T3.2's AC. Also exercises extract_text_async()'s concurrency guard
           with distinct concurrent inputs and should_reroute_to_vision()'s exact
           character-count boundary.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T3.2.2, T3.2.3, T3.2.4; §5 → T5.1.2
[HISTORY]  2026-07-17  T5.1.2  initial committed test file using the real
                                printed_report.jpg fixture (backfills T3.2's ad hoc
                                verification)
           2026-07-19  T8.2.2  adapt to OcrResult return shape; add confidence-gate
                                boundary tests (0.10/0.79/0.80/0.95/None)
           2026-07-19  T8.4.2  add non-Latin-script reroute tests (Arabic -> reroute;
                                clean English incl. numbers/punctuation -> no reroute) +
                                _non_latin_letter_ratio boundary tests
           2026-07-19  T8.5.3  add low-confidence-cluster gate boundary tests + the
                                OcrResult backward-compat default test
"""

import asyncio
from pathlib import Path

import cv2
import pytest

from app.pipeline.image_cleaner import clean_image
from app.pipeline.ocr_engine import (
    extract_text,
    extract_text_async,
    load_paddleocr,
    set_paddleocr,
    should_reroute_to_vision,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module", autouse=True)
def _paddleocr_loaded():
    """Loads the real PaddleOCR engine once for this test module (T3.2.1) — cached locally."""
    set_paddleocr(load_paddleocr())


def _ocr_ready(name: str):
    bgr = cv2.imread(str(FIXTURES_DIR / name), cv2.IMREAD_COLOR)
    return clean_image(bgr).ocr_ready


def test_extract_text_printed_report_contains_known_keywords():
    """[T3.2.2] AC: printed_report.jpg -> non-empty text containing known fixture keywords.
    [T8.2.2] extract_text now returns OcrResult; a clean printed fixture scores high mean confidence."""
    result = extract_text(_ocr_ready("printed_report.jpg"))

    assert result.text != ""
    assert "LAB REPORT" in result.text
    assert "John Smith" in result.text
    assert result.mean_confidence > 0.8  # clean synthetic print -> confidently read


@pytest.mark.asyncio
async def test_extract_text_async_concurrent_calls_do_not_interleave():
    """[T3.2.3] AC: concurrent calls through the asyncio.Lock guard don't crash or mix up results between requests."""
    printed = _ocr_ready("printed_report.jpg")
    medicine_box_gray = cv2.cvtColor(
        cv2.imread(str(FIXTURES_DIR / "medicine_box.jpg"), cv2.IMREAD_COLOR), cv2.COLOR_BGR2GRAY
    )

    results = await asyncio.gather(
        extract_text_async(printed),
        extract_text_async(medicine_box_gray),
        extract_text_async(printed),
        extract_text_async(medicine_box_gray),
    )

    assert "LAB REPORT" in results[0].text
    assert "PARACETAMOL" in results[1].text or "ParaCure" in results[1].text
    assert "LAB REPORT" in results[2].text
    assert "PARACETAMOL" in results[3].text or "ParaCure" in results[3].text


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", True),
        ("x", True),
        ("x" * 19, True),
        ("x" * 20, False),  # exactly at the threshold -> trusted, no reroute
        ("a fully readable line of extracted text", False),
    ],
)
def test_should_reroute_to_vision_boundary(text, expected):
    """[T3.2.4] AC: <20 characters reroutes to vision; >=20 is trusted as-is (confidence omitted -> char rule only)."""
    assert should_reroute_to_vision(text) == expected


@pytest.mark.parametrize(
    "mean_confidence, expected",
    [
        (0.10, True),   # garbled — e.g. Arabic script read by the en-only engine
        (0.79, True),   # just under the threshold -> reroute
        (0.80, False),  # exactly at the threshold -> trusted
        (0.95, False),  # clean print -> trusted
        (None, False),  # confidence unknown -> char rule alone decides
    ],
)
def test_should_reroute_to_vision_confidence_gate(mean_confidence, expected):
    """[T8.2.2] AC: >=20 chars but mean confidence <0.80 reroutes to vision; >=0.80 or None is trusted."""
    long_enough_text = "plenty of extracted characters here"
    assert should_reroute_to_vision(long_enough_text, mean_confidence) == expected


def test_should_reroute_to_vision_on_non_latin_script():
    """[T8.4.2] AC: OCR text that is substantially non-Latin (e.g. Arabic) reroutes to vision even at high confidence."""
    arabic = "سروة إبراهيم حمادة اسم المريض الطبيب"
    assert should_reroute_to_vision(arabic, 0.99) is True


def test_should_not_reroute_clean_english_with_high_confidence():
    """[T8.4.2] AC: a clean English line (no non-Latin script, high confidence) is trusted — no false reroute."""
    english = "Patient Name John Smith Diagnosis influenza"
    assert should_reroute_to_vision(english, 0.95) is False


def test_should_not_reroute_english_with_numbers_and_punctuation():
    """[T8.4.2] AC: digits/punctuation are ignored by the non-Latin ratio — a numbers-heavy English page isn't misjudged."""
    text = "IVSd 1.2 cm  EF 51 %  LVIDd 6.6 cm  date 15/04/2026"
    assert should_reroute_to_vision(text, 0.95) is False


@pytest.mark.parametrize(
    "ratio_input, expected",
    [
        ("English only words here", 0.0),
        ("سروة إبراهيم", 1.0),
        ("12345 %/.- ", 0.0),  # no letters at all
    ],
)
def test_non_latin_letter_ratio(ratio_input, expected):
    """[T8.4.2] _non_latin_letter_ratio ignores non-letters and measures only alphabetic script."""
    from app.pipeline.ocr_engine import _non_latin_letter_ratio

    assert _non_latin_letter_ratio(ratio_input) == pytest.approx(expected)


@pytest.mark.parametrize(
    "low_confidence_ratio, expected",
    [
        (0.50, True),   # half the page unreadable -> reroute (mixed-language page)
        (0.21, True),   # just over the threshold -> reroute
        (0.20, False),  # exactly at the threshold -> trusted
        (0.00, False),  # every line readable -> trusted
        (None, False),  # ratio unknown -> other gates alone decide
    ],
)
def test_should_reroute_to_vision_low_confidence_cluster_gate(low_confidence_ratio, expected):
    """[T8.5.3] AC: >20% of lines below 0.60 confidence reroutes to vision even when the MEAN confidence is high (English body masking an unreadable Arabic region)."""
    long_english = "Patient scan report with plenty of readable English body text"
    assert should_reroute_to_vision(long_english, 0.95, low_confidence_ratio) == expected


def test_ocr_result_low_confidence_ratio_defaults_to_zero():
    """[T8.5.3] OcrResult stays backward compatible — pre-T8.5 constructor calls (text + mean only) still work."""
    from app.pipeline.ocr_engine import OcrResult

    result = OcrResult(text="abc", mean_confidence=0.9)
    assert result.low_confidence_ratio == 0.0
