"""
[MODULE]   app/pipeline/llm_extractor.py
[TASK]     T4.1 — OpenAI structured extraction (Step 5)
[SUBTASKS] T4.1.1 Structured Outputs JSON schema (strict) mirroring ExtractedData, incl. `cost`
[SUMMARY]  Defines the OpenAI Structured Outputs contract for Step 5: a strict JSON
           Schema mirroring the ExtractedData shape (patient_name, doctor_name,
           diagnosis, procedure, cost, medicines) so gpt-4o-mini can never return a
           malformed or partial payload. Every field is nullable — "not found in the
           document" is expressed as null, never a missing key or a guessed value.
           `cost` is a contract addition beyond the PRD §4.2 sample (PRD clarification
           #1, IMPLEMENTATION_PLAN.md §8-1); Laravel must tolerate the extra key. Both
           the text path (T4.1.2) and the vision path (T4.1.3) pass RESPONSE_FORMAT
           through unchanged.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T4.1.1
[HISTORY]  2026-07-17  T4.1.1  initial schema definition — first formal definition of
                                the ExtractedData shape (schemas.py/T1.2.2 not yet
                                implemented); additive-only, no existing contract to
                                break (Rule 7 n/a — nothing to compare against yet)
"""

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
