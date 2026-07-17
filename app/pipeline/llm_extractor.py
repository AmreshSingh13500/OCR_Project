"""
[MODULE]   app/pipeline/llm_extractor.py
[TASK]     T4.1 — OpenAI structured extraction (Step 5)
[SUBTASKS] T4.1.1 Structured Outputs JSON schema (strict) mirroring ExtractedData, incl. `cost`
           T4.1.2 Text path: gpt-4o-mini chat completion with extraction system prompt
[SUMMARY]  Defines the OpenAI Structured Outputs contract for Step 5 and the text-path
           extraction call. `EXTRACTED_DATA_JSON_SCHEMA`/`RESPONSE_FORMAT` mirror the
           ExtractedData shape (patient_name, doctor_name, diagnosis, procedure, cost,
           medicines) so gpt-4o-mini can never return a malformed or partial payload —
           every field is nullable, so "not found in the document" is expressed as
           null, never a missing key or a guessed value. `cost` is a contract addition
           beyond the PRD §4.2 sample (PRD clarification #1, IMPLEMENTATION_PLAN.md
           §8-1); Laravel must tolerate the extra key. `extract_from_text()` sends
           native-PDF text (T2.1) or PaddleOCR output (T3.2) through a single chat
           completion using the frozen system prompt and returns the parsed JSON dict;
           it does not yet retry or catch API errors (T4.1.4). The vision path (T4.1.3)
           will reuse RESPONSE_FORMAT and the same system prompt unchanged.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T4.1.1, T4.1.2
[HISTORY]  2026-07-17  T4.1.1  initial schema definition — first formal definition of
                                the ExtractedData shape (schemas.py/T1.2.2 not yet
                                implemented); additive-only, no existing contract to
                                break (Rule 7 n/a — nothing to compare against yet)
           2026-07-17  T4.1.2  add extract_from_text() — module-level OpenAI client +
                                exact plan system prompt; no schemas.py/routes.py/
                                webhook_client.py/error-string changes (Rule 7 gate n/a)
"""

import json
import logging

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

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
# with the frozen system prompt and the strict schema from T4.1.1. Retries/error typing
# (T4.1.4) and the all-nulls flag (T4.1.5) wrap this later; this call is bare on purpose.
def extract_from_text(text: str) -> dict:
    response = _client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format=RESPONSE_FORMAT,
    )
    return json.loads(response.choices[0].message.content)
