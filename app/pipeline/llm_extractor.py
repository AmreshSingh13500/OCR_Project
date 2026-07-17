"""
[MODULE]   app/pipeline/llm_extractor.py
[TASK]     T4.1 — OpenAI structured extraction (Step 5)
[SUBTASKS] T4.1.1 Structured Outputs JSON schema (strict) mirroring ExtractedData, incl. `cost`
           T4.1.2 Text path: gpt-4o-mini chat completion with extraction system prompt
           T4.1.3 Vision path: <=3 base64 JPEGs (quality 85, longest side 1536px)
           T4.1.4 Tenacity retries: 3 attempts, exp backoff 2-30s, retryable errors only
[SUMMARY]  Defines the OpenAI Structured Outputs contract for Step 5 and both extraction
           call paths. `EXTRACTED_DATA_JSON_SCHEMA`/`RESPONSE_FORMAT` mirror the
           ExtractedData shape (patient_name, doctor_name, diagnosis, procedure, cost,
           medicines) so gpt-4o-mini can never return a malformed or partial payload —
           every field is nullable, so "not found in the document" is expressed as
           null, never a missing key or a guessed value. `cost` is a contract addition
           beyond the PRD §4.2 sample (PRD clarification #1, IMPLEMENTATION_PLAN.md
           §8-1); Laravel must tolerate the extra key. `extract_from_text()` sends
           native-PDF text (T2.1) or PaddleOCR output (T3.2) through a single chat
           completion using the frozen system prompt; `extract_from_images()` sends up
           to MAX_PDF_PAGES_OCR `vision_ready` images (T2.2), each downscaled to a 1536px
           longest side and JPEG-encoded at quality 85 to control token cost, through the
           same schema and system prompt. Both paths funnel through `_call_chat_completion()`,
           which retries transient OpenAI failures (timeout, connection, rate limit, 5xx)
           up to `OPENAI_MAX_RETRIES` times with exponential backoff (2-30s) and raises
           `LLMError` once retries are exhausted; non-retryable errors (401, 400) are not
           in the retry set and propagate immediately on the first attempt. The all-nulls
           flag (T4.1.5) is not set yet.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T4.1.1, T4.1.2, T4.1.3, T4.1.4
[HISTORY]  2026-07-17  T4.1.1  initial schema definition — first formal definition of
                                the ExtractedData shape (schemas.py/T1.2.2 not yet
                                implemented); additive-only, no existing contract to
                                break (Rule 7 n/a — nothing to compare against yet)
           2026-07-17  T4.1.2  add extract_from_text() — module-level OpenAI client +
                                exact plan system prompt; no schemas.py/routes.py/
                                webhook_client.py/error-string changes (Rule 7 gate n/a)
           2026-07-17  T4.1.3  add extract_from_images() + JPEG encode/downscale helper;
                                reuses RESPONSE_FORMAT/system prompt unchanged from
                                T4.1.2 — no contract-surface changes (Rule 7 gate n/a)
           2026-07-17  T4.1.4  add LLMError + _call_chat_completion() retry wrapper;
                                extract_from_text()/extract_from_images() now build a
                                `messages` list and delegate to it instead of calling
                                the OpenAI client directly (T4.1.2/T4.1.3 tags kept —
                                same primary functions, bodies refactored to share retry
                                logic); no schemas.py/routes.py/webhook_client.py/
                                error-string changes (Rule 7 gate n/a) — LLMError is a
                                new internal exception, T4.3.3 will map it later
"""

import base64
import json
import logging

import cv2
import numpy as np
import openai
from openai import OpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import MAX_PDF_PAGES_OCR, OPENAI_MAX_RETRIES, settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """[T4.1.4] Raised when OpenAI extraction fails after all retries are exhausted."""


# [T4.1.2] Constructing the client does not make a network call — safe to build once
# at import time, same "load once, reuse" spirit as the CLIP/PaddleOCR startup loads,
# without needing a lifespan hook since there's no model weights to warm up.
_client = OpenAI(api_key=settings.OPENAI_API_KEY)

# [T4.1.2] Exact wording from IMPLEMENTATION_PLAN.md §4 T4.1.2 — frozen for this subtask;
# tuning happens in T7.2, not here.
_EXTRACTION_SYSTEM_PROMPT = (
    "Extract Patient Name, Doctor Name, Diagnosis, Procedure, and Cost from this "
    "medical document. Return null for any field not present. Do not guess or "
    "fabricate values."
)

# [T4.1.3] Per plan §4 T4.1.3 exactly — bounds vision token cost/latency.
_VISION_MAX_LONGEST_SIDE_PX = 1536
_VISION_JPEG_QUALITY = 85

# [T4.1.4] Per plan §4 T4.1.4 exactly — only transient/server-side failures are retried.
# AuthenticationError (401) / BadRequestError (400) are config/contract bugs, not
# transient faults, so they're deliberately excluded here and propagate on the first
# attempt ("fail immediately" per the plan).
_RETRYABLE_OPENAI_ERRORS = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)

EXTRACTED_DATA_SCHEMA_NAME = "extracted_medical_data"

# [T4.1.1] Strict JSON Schema for OpenAI Structured Outputs, mirroring the ExtractedData
# model that schemas.py (T1.2.2) will define. OpenAI's strict mode has no concept of an
# "optional" key — every property must be listed in `required`; nullability is instead
# expressed via `"type": [<type>, "null"]`. `additionalProperties: False` is mandatory
# for strict mode at every object level (root and any nested object).
EXTRACTED_DATA_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "patient_name": {"type": ["string", "null"]},
        "doctor_name": {"type": ["string", "null"]},
        "diagnosis": {"type": ["string", "null"]},
        "procedure": {"type": ["string", "null"]},
        "cost": {"type": ["string", "null"]},
        "medicines": {
            "type": ["array", "null"],
            "items": {"type": "string"},
        },
    },
    "required": [
        "patient_name",
        "doctor_name",
        "diagnosis",
        "procedure",
        "cost",
        "medicines",
    ],
    "additionalProperties": False,
}

# [T4.1.1] Ready to pass straight through as `response_format=` to
# `client.chat.completions.create(...)` — used unchanged by both the text path
# (T4.1.2) and the vision path (T4.1.3).
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": EXTRACTED_DATA_SCHEMA_NAME,
        "strict": True,
        "schema": EXTRACTED_DATA_JSON_SCHEMA,
    },
}


# [T4.1.2] Text path (native PDF text or PaddleOCR output) — a single chat completion
# with the frozen system prompt and the strict schema from T4.1.1. The all-nulls flag
# (T4.1.5) is not set yet; retries/LLMError translation happen in _call_chat_completion.
def extract_from_text(text: str) -> dict:
    messages = [
        {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    return _call_chat_completion(messages)


# Downscales only when needed (never upscales a smaller image) and re-encodes as JPEG —
# grayscale is a valid single-component JPEG, no RGB conversion needed for the vision API.
def _encode_image_base64_jpeg(image: np.ndarray) -> str:
    h, w = image.shape[:2]
    longest_side = max(h, w)
    if longest_side > _VISION_MAX_LONGEST_SIDE_PX:
        scale = _VISION_MAX_LONGEST_SIDE_PX / longest_side
        image = cv2.resize(
            image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA
        )

    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, _VISION_JPEG_QUALITY])
    if not ok:
        raise ValueError("Failed to JPEG-encode image for vision extraction")

    encoded = base64.b64encode(buffer).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


# [T4.1.3] Vision path (Branch B / handwritten, scans, medicine boxes) — same schema and
# system prompt as the text path, but the user turn carries up to MAX_PDF_PAGES_OCR
# `vision_ready` images instead of raw text. Truncates defensively to MAX_PDF_PAGES_OCR
# even though the orchestrator (T4.3) is expected to already cap page count upstream.
def extract_from_images(images: list[np.ndarray]) -> dict:
    content = [
        {"type": "image_url", "image_url": {"url": _encode_image_base64_jpeg(image)}}
        for image in images[:MAX_PDF_PAGES_OCR]
    ]
    messages = [
        {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]
    return _call_chat_completion(messages)


# [T4.1.4] Shared call path for both extraction functions: retries transient OpenAI
# failures with exponential backoff, then raises LLMError once attempts are exhausted.
# Non-retryable errors (401/400) are not in _RETRYABLE_OPENAI_ERRORS so they propagate
# unwrapped on the first attempt, per the plan's "fail immediately" rule.
def _call_chat_completion(messages: list) -> dict:
    try:
        response = _create_chat_completion(messages)
    except _RETRYABLE_OPENAI_ERRORS as exc:
        raise LLMError(
            f"OpenAI extraction failed after {OPENAI_MAX_RETRIES} attempts: {exc}"
        ) from exc
    return json.loads(response.choices[0].message.content)


@retry(
    retry=retry_if_exception_type(_RETRYABLE_OPENAI_ERRORS),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(OPENAI_MAX_RETRIES),
    reraise=True,
)
def _create_chat_completion(messages: list):
    return _client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        response_format=RESPONSE_FORMAT,
    )
