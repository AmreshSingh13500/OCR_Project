"""
[MODULE]   app/schemas.py
[TASK]     T1.2 — Auth & API endpoints
           T8.1 — Generalized any-document extraction (additive contract update)
           T8.2 — Multi-language documents + extraction fidelity (additive)
[SUBTASKS] T1.2.2 ProcessRequest / ExtractedData / WebhookPayload per PRD §4.1-4.2
           T8.1.1 additive ExtractedData keys: document_type / document_summary /
                  additional_details (+ DocumentDetail item model)
           T8.2.1 additive ExtractedData key: original_language
[SUMMARY]  Canonical Pydantic contract models for the HTTP surface. `ProcessRequest` is
           the POST /api/v1/process request body (PRD §4.1); FastAPI validates incoming
           JSON against it automatically, returning 422 on a malformed body (T1.2.3's
           AC). `file_url` is a plain string here, not scheme-restricted — the https-only
           check is a distinct 400 response (T1.2.5), not a 422 pydantic validation
           error, so it deliberately lives in the route handler instead of a field
           validator. `ExtractedData` mirrors llm_extractor.py's
           `EXTRACTED_DATA_JSON_SCHEMA` (T4.1.1) field-for-field, including `cost` (PRD
           clarification #1, IMPLEMENTATION_PLAN.md §8-1) — that module keeps its own
           hand-built strict JSON Schema dict for OpenAI's Structured Outputs API (a
           different wire format with its own nullability/`additionalProperties`
           conventions), so the two are kept as separate definitions rather than one
           generating the other, but the field set must never drift apart. `WebhookPayload`
           mirrors webhook_client.py's `build_webhook_payload()` (T4.2.1) key-for-key;
           that function still returns a plain dict at the call site (unchanged here) —
           this model is the formal contract type schemas.py owns per the plan's §2
           repository layout, and is available for validation/documentation use going
           forward. `status`/`processing_path` use `Literal` types to make the frozen
           value sets (CODING_RULES.md Rule 7) explicit in code, not just in a comment.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.2.2, T8.1.1
[HISTORY]  2026-07-17  T1.2.2  initial ProcessRequest/ExtractedData/WebhookPayload models
           2026-07-18  T8.1.1  add document_type/document_summary/additional_details to
                                ExtractedData (+ new DocumentDetail item model) — Rule 7
                                gate checked: 3 new optional nullable keys, existing 6
                                fields untouched, no rename/remove/retype — additive,
                                contract-safe (same precedent as `cost`); mirrors
                                llm_extractor.py's EXTRACTED_DATA_JSON_SCHEMA which
                                gained the same keys in the same session
           2026-07-19  T8.2.1  add original_language — Rule 7 gate checked: 1 new
                                optional nullable key, existing 9 untouched — additive,
                                contract-safe; mirrors EXTRACTED_DATA_JSON_SCHEMA which
                                gained the same key in the same session
"""

from typing import Literal, Optional

from pydantic import BaseModel


# [T1.2.2] PRD §4.1 request body. Only case_id/message_id/file_url are required; the
# other three are carried through for contract completeness but unused by the pipeline
# itself (content kind is always re-derived from magic bytes, T1.3.2 — file_type is
# never trusted).
class ProcessRequest(BaseModel):
    case_id: str
    message_id: str
    file_url: str
    file_type: Optional[str] = None
    file_name: Optional[str] = None
    source_channel: Optional[str] = None


# [T8.1.1] One {field, value} entry of ExtractedData.additional_details — a list of
# these (not a free-form dict) because OpenAI strict mode can't express open objects;
# schemas.py mirrors that wire shape exactly.
class DocumentDetail(BaseModel):
    field: str
    value: str


# [T1.2.2] Mirrors llm_extractor.py's EXTRACTED_DATA_JSON_SCHEMA (T4.1.1) exactly: the
# original 6 fields plus T8.1.1's 3 general-document fields, all nullable. `cost` is a
# contract addition beyond the PRD §4.2 sample (PRD clarification #1) — Laravel must
# tolerate the extra key; document_type/document_summary/additional_details follow the
# same additive precedent (T8.1.1).
class ExtractedData(BaseModel):
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    diagnosis: Optional[str] = None
    procedure: Optional[str] = None
    cost: Optional[str] = None
    medicines: Optional[list[str]] = None
    # [T8.1.1] Additive general-document keys — what the document is, a properly written
    # summary, and every other readable detail as {field, value} pairs.
    document_type: Optional[str] = None
    document_summary: Optional[str] = None
    additional_details: Optional[list[DocumentDetail]] = None
    # [T8.2.1] Additive: the language(s) the original document is written in (e.g.
    # "Arabic", "Arabic and English"); all extracted values themselves are English.
    original_language: Optional[str] = None


# [T1.2.2] Mirrors webhook_client.py's build_webhook_payload() (T4.2.1) key set exactly.
# processing_path's Literal is the exact frozen `processing_path` contract (plan §1,
# CODING_RULES.md Rule 7) — a new value needs Laravel sign-off before it can be added
# here, same as in production.
class WebhookPayload(BaseModel):
    case_id: str
    message_id: str
    status: Literal["success", "error"]
    processing_path: Optional[Literal["native_pdf", "paddleocr", "vision_api"]] = None
    extracted_data: Optional[ExtractedData] = None
    error_message: Optional[str] = None
