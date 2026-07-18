"""
[MODULE]   tests/test_llm_extractor.py
[TASK]     T4.1 — OpenAI structured extraction (Step 5)
           T5.1 — Test suite completion
           T8.1 — Generalized any-document extraction (additive contract update)
           T8.2 — Multi-language documents + extraction fidelity (additive)
[SUBTASKS] T8.2.1 AC: original_language nullable + required (strict), 10-key shape;
                  prompt carries the language/English-output/transliteration rules
           T8.2.3 AC: prompt carries verbatim-transcription rules; vision items send
                  detail:"high"
           T8.1.1 AC: 3 new nullable keys additive (legacy 6 byte-identical); nested
                  additional_details item strict-compliant; general-document-only
                  result not flagged unreadable
           T8.1.2 AC: text + vision paths share the generalized prompt (incl. the
                  unreadable->all-null instruction)
           T4.1.1 AC: strict JSON schema mirrors ExtractedData
           T4.1.2 AC: text path sends the frozen system prompt + correct response_format
           T4.1.3 AC: vision path downscales >1536px images, never upscales, truncates
                  to MAX_PDF_PAGES_OCR
           T4.1.4 AC: retry fires exactly OPENAI_MAX_RETRIES times on 500s then raises
                  LLMError; non-retryable 401 propagates unwrapped on the first attempt
           T4.1.5 AC: is_all_fields_null() detects an all-null result, doesn't conflate
                  an empty list with null
           T4.1.6 AC: token usage logged on success, not logged on a failed call
           T5.1.2 backfilled committed pytest coverage for T4.1 (previously verified ad
                  hoc via a mocked openai.OpenAI client, per SUBTASKS.md); the plan's
                  "live smoke test extracts correct fields from native.pdf" AC item
                  stays gated behind OPENAI_LIVE_SMOKE_TEST=1 + a real OPENAI_API_KEY,
                  neither of which is available in this dev environment (TASKS.md §5,
                  2026-07-17 T4.1 AC note)
[SUMMARY]  Mocks openai.OpenAI's chat.completions.create (module-level `_client` in
           llm_extractor.py) to test the schema/retry/logging contract without any
           network call. test_extract_from_text_live_smoke_against_native_pdf is
           written and wired correctly but skipped unless OPENAI_LIVE_SMOKE_TEST=1 is
           set with a real OPENAI_API_KEY, per the still-open T4.1 AC blocker note.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T4.1.1, T4.1.2, T4.1.3, T4.1.4, T4.1.5, T4.1.6; §5 → T5.1.2
[HISTORY]  2026-07-17  T5.1.2  initial committed test file (backfills T4.1's ad hoc
                                verification with real mocked-client tests)
           2026-07-18  T8.1.1  _ALL_NULL_RESULT extended to the 9-key shape; new
                                additive-schema + strict-nested-object + non-medical
                                is_all_fields_null tests; _LEGACY_SCHEMA_PROPERTIES
                                locks the Rule 7 frozen surface
           2026-07-18  T8.1.2  new shared-generalized-prompt test (text + vision)
           2026-07-19  T8.2.1  _ALL_NULL_RESULT extended to 10 keys; original_language
                                schema test + language/verbatim prompt-rule test
           2026-07-19  T8.2.3  vision detail:"high" test
"""

import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import cv2
import httpx
import numpy as np
import openai
import pytest

from app.config import MAX_PDF_PAGES_OCR, OPENAI_MAX_RETRIES, settings
from app.pipeline import llm_extractor
from app.pipeline.llm_extractor import (
    EXTRACTED_DATA_JSON_SCHEMA,
    LLMError,
    RESPONSE_FORMAT,
    _encode_image_base64_jpeg,
    extract_from_images,
    extract_from_text,
    is_all_fields_null,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_ALL_NULL_RESULT = {
    "patient_name": None, "doctor_name": None, "diagnosis": None,
    "procedure": None, "cost": None, "medicines": None,
    "document_type": None, "document_summary": None, "additional_details": None,
    "original_language": None,
}

# [T8.1.1] The 6 pre-T8.1 keys with their exact schema entries — the Rule 7 frozen
# surface an additive change must never touch.
_LEGACY_SCHEMA_PROPERTIES = {
    "patient_name": {"type": ["string", "null"]},
    "doctor_name": {"type": ["string", "null"]},
    "diagnosis": {"type": ["string", "null"]},
    "procedure": {"type": ["string", "null"]},
    "cost": {"type": ["string", "null"]},
    "medicines": {"type": ["array", "null"], "items": {"type": "string"}},
}


def _fake_response(content: dict, usage=(100, 20, 120)):
    prompt, completion, total = usage
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(content)))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total),
    )


def _dummy_httpx_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://api.openai.test/v1/chat/completions")
    return httpx.Response(status_code, request=request)


def test_extract_from_text_sends_frozen_prompt_and_schema(monkeypatch):
    """[T4.1.2] AC: text path sends the exact frozen system prompt, the raw text as the user turn, and RESPONSE_FORMAT."""
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_response(_ALL_NULL_RESULT)

    monkeypatch.setattr(llm_extractor._client.chat.completions, "create", fake_create)

    result = extract_from_text("some document text")

    assert captured["model"] == settings.OPENAI_MODEL
    assert captured["response_format"] == RESPONSE_FORMAT
    assert captured["messages"] == [
        {"role": "system", "content": llm_extractor._EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": "some document text"},
    ]
    assert result == _ALL_NULL_RESULT


def test_extract_from_images_truncates_to_max_pages_and_uses_image_url_content(monkeypatch):
    """[T4.1.3] AC: vision path sends at most MAX_PDF_PAGES_OCR images as image_url content, even given more input images."""
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_response(_ALL_NULL_RESULT)

    monkeypatch.setattr(llm_extractor._client.chat.completions, "create", fake_create)

    images = [np.zeros((50, 50), dtype=np.uint8) for _ in range(MAX_PDF_PAGES_OCR + 2)]
    extract_from_images(images)

    user_content = captured["messages"][1]["content"]
    assert len(user_content) == MAX_PDF_PAGES_OCR
    assert all(item["type"] == "image_url" for item in user_content)
    assert all(item["image_url"]["url"].startswith("data:image/jpeg;base64,") for item in user_content)


def test_encode_image_downscales_when_over_max_longest_side():
    """[T4.1.3] AC: an image wider than 1536px on its longest side is downscaled to fit, aspect preserved."""
    image = np.zeros((1000, 2000), dtype=np.uint8)  # width 2000 is the longest side
    data_url = _encode_image_base64_jpeg(image)
    assert data_url.startswith("data:image/jpeg;base64,")

    import base64
    jpeg_bytes = base64.b64decode(data_url.split(",", 1)[1])
    decoded = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert max(decoded.shape) == 1536
    assert decoded.shape[0] / decoded.shape[1] == pytest.approx(1000 / 2000, rel=0.01)


def test_encode_image_never_upscales_small_image():
    """[T4.1.3] AC: an image already under 1536px is encoded unchanged, never upscaled."""
    image = np.zeros((300, 400), dtype=np.uint8)
    data_url = _encode_image_base64_jpeg(image)

    import base64
    jpeg_bytes = base64.b64decode(data_url.split(",", 1)[1])
    decoded = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert decoded.shape == (300, 400)


def test_retry_exhausted_after_max_retries_raises_llm_error(monkeypatch):
    """[T4.1.4] AC: 3 consecutive 500s (InternalServerError) -> LLMError raised after exactly OPENAI_MAX_RETRIES attempts."""
    call_count = {"n": 0}
    response = _dummy_httpx_response(500)

    def fake_create(**kwargs):
        call_count["n"] += 1
        raise openai.InternalServerError("server error", response=response, body=None)

    monkeypatch.setattr(llm_extractor._client.chat.completions, "create", fake_create)

    with pytest.raises(LLMError):
        extract_from_text("some text")

    assert call_count["n"] == OPENAI_MAX_RETRIES


def test_non_retryable_401_propagates_immediately_without_retry(monkeypatch):
    """[T4.1.4] AC: a 401 (AuthenticationError) is not retried — propagates unwrapped on the first attempt."""
    call_count = {"n": 0}
    response = _dummy_httpx_response(401)

    def fake_create(**kwargs):
        call_count["n"] += 1
        raise openai.AuthenticationError("invalid api key", response=response, body=None)

    monkeypatch.setattr(llm_extractor._client.chat.completions, "create", fake_create)

    with pytest.raises(openai.AuthenticationError):
        extract_from_text("some text")

    assert call_count["n"] == 1


def test_token_usage_logged_on_success(monkeypatch, caplog):
    """[T4.1.6] AC: a successful call logs prompt/completion/total token usage at INFO."""
    monkeypatch.setattr(
        llm_extractor._client.chat.completions, "create",
        lambda **kwargs: _fake_response(_ALL_NULL_RESULT, usage=(123, 45, 168)),
    )

    with caplog.at_level(logging.INFO):
        extract_from_text("some text")

    assert any("prompt=123 completion=45 total=168" in r.getMessage() for r in caplog.records)


def test_token_usage_not_logged_when_retries_exhausted(monkeypatch, caplog):
    """[T4.1.6] AC: a failed call (retries exhausted) carries no usage data, so nothing is logged for it."""
    response = _dummy_httpx_response(500)
    monkeypatch.setattr(
        llm_extractor._client.chat.completions, "create",
        lambda **kwargs: (_ for _ in ()).throw(
            openai.InternalServerError("server error", response=response, body=None)
        ),
    )

    with caplog.at_level(logging.INFO):
        with pytest.raises(LLMError):
            extract_from_text("some text")

    assert not any("token usage" in r.getMessage() for r in caplog.records)


def test_is_all_fields_null_true_when_every_field_is_none():
    """[T4.1.5] AC: every field null -> True (the blurry/unreadable-document signal)."""
    assert is_all_fields_null(_ALL_NULL_RESULT) is True


def test_is_all_fields_null_false_when_one_field_present():
    """[T4.1.5] AC: any single non-null field -> False."""
    data = dict(_ALL_NULL_RESULT, patient_name="Jane Doe")
    assert is_all_fields_null(data) is False


def test_is_all_fields_null_does_not_conflate_empty_list_with_null():
    """[T4.1.5] AC: medicines=[] (empty list, not None) is not treated as null."""
    data = dict(_ALL_NULL_RESULT, medicines=[])
    assert is_all_fields_null(data) is False


def test_is_all_fields_null_false_when_only_general_document_fields_present():
    """[T8.1.1] AC: a non-medical document (6 medical fields null, new fields filled) is NOT flagged unreadable."""
    data = dict(
        _ALL_NULL_RESULT,
        document_type="passport",
        document_summary="This is a passport belonging to Jane Doe.",
        additional_details=[{"field": "Passport Number", "value": "N1234567"}],
    )
    assert is_all_fields_null(data) is False


def test_json_schema_property_and_required_sets_match():
    """[T4.1.1] AC: strict-mode schema — property set equals required set, additionalProperties is False."""
    schema = EXTRACTED_DATA_JSON_SCHEMA
    assert set(schema["properties"].keys()) == set(schema["required"])
    assert schema["additionalProperties"] is False


def test_schema_gains_general_document_keys_without_touching_legacy_keys():
    """[T8.1.1] AC: 3 new nullable keys present; the 6 legacy key definitions are byte-identical (Rule 7 additive)."""
    props = EXTRACTED_DATA_JSON_SCHEMA["properties"]
    for key, expected in _LEGACY_SCHEMA_PROPERTIES.items():
        assert props[key] == expected
    assert props["document_type"] == {"type": ["string", "null"]}
    assert props["document_summary"] == {"type": ["string", "null"]}
    assert props["additional_details"]["type"] == ["array", "null"]


def test_additional_details_item_object_is_strict_mode_compliant():
    """[T8.1.1] AC: nested additional_details item object — properties == required == {field, value}, additionalProperties False."""
    item = EXTRACTED_DATA_JSON_SCHEMA["properties"]["additional_details"]["items"]
    assert item["type"] == "object"
    assert set(item["properties"].keys()) == {"field", "value"} == set(item["required"])
    assert item["additionalProperties"] is False


def test_text_and_vision_paths_share_the_generalized_prompt(monkeypatch):
    """[T8.1.2] AC: extract_from_text and extract_from_images send the same generalized system prompt."""
    prompts = []

    def fake_create(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        return _fake_response(_ALL_NULL_RESULT)

    monkeypatch.setattr(llm_extractor._client.chat.completions, "create", fake_create)

    extract_from_text("some text")
    extract_from_images([np.zeros((50, 50), dtype=np.uint8)])

    assert prompts[0] == prompts[1] == llm_extractor._EXTRACTION_SYSTEM_PROMPT
    assert "document_type" in prompts[0]
    assert "additional_details" in prompts[0]
    assert "unreadable" in prompts[0]  # the all-null instruction T4.1.5 depends on


def test_schema_gains_original_language_key():
    """[T8.2.1] AC: original_language present, nullable, in required (strict mode); 10-key shape."""
    props = EXTRACTED_DATA_JSON_SCHEMA["properties"]
    assert props["original_language"] == {"type": ["string", "null"]}
    assert "original_language" in EXTRACTED_DATA_JSON_SCHEMA["required"]
    assert len(props) == 10


def test_prompt_contains_language_and_verbatim_accuracy_rules():
    """[T8.2.1][T8.2.3] AC: prompt carries the language rules (English output, transliteration, original_language) and the verbatim-transcription rules."""
    prompt = llm_extractor._EXTRACTION_SYSTEM_PROMPT
    assert "original_language" in prompt
    assert "English" in prompt
    assert "transliterated" in prompt
    assert "EXACTLY" in prompt  # verbatim transcription rule
    assert "Never guess or fabricate" in prompt


def test_vision_images_are_sent_with_high_detail(monkeypatch):
    """[T8.2.3] AC: every vision image_url item requests detail='high' for document-text fidelity."""
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_response(_ALL_NULL_RESULT)

    monkeypatch.setattr(llm_extractor._client.chat.completions, "create", fake_create)

    extract_from_images([np.zeros((50, 50), dtype=np.uint8) for _ in range(2)])

    user_content = captured["messages"][1]["content"]
    assert all(item["image_url"]["detail"] == "high" for item in user_content)


@pytest.mark.skipif(
    not os.getenv("OPENAI_LIVE_SMOKE_TEST"),
    reason="requires a real OPENAI_API_KEY and network access; set OPENAI_LIVE_SMOKE_TEST=1 to opt in",
)
def test_extract_from_text_live_smoke_against_native_pdf():
    """[T4.1 AC] Live smoke test: native.pdf's real text layer -> correct fields via the real OpenAI API."""
    import fitz

    from tests.fixtures.ground_truth import GROUND_TRUTH

    doc = fitz.open(str(FIXTURES_DIR / "native.pdf"))
    text = doc[0].get_text()

    result = extract_from_text(text)

    expected = GROUND_TRUTH["native.pdf"]
    assert result["patient_name"] == expected["patient_name"]
    assert result["doctor_name"] == expected["doctor_name"]
