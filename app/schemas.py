"""
[MODULE]   app/schemas.py
[TASK]     T1.2 — Auth & API endpoints
[SUBTASKS] T1.2.2 ProcessRequest / ExtractedData / WebhookPayload per PRD §4.1-4.2
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
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.2.2
[HISTORY]  2026-07-17  T1.2.2  initial ProcessRequest/ExtractedData/WebhookPayload models
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


# [T1.2.2] Mirrors llm_extractor.py's EXTRACTED_DATA_JSON_SCHEMA (T4.1.1) exactly: same
# 6 fields, all nullable. `cost` is a contract addition beyond the PRD §4.2 sample (PRD
# clarification #1) — Laravel must tolerate the extra key.
class ExtractedData(BaseModel):
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    diagnosis: Optional[str] = None
    procedure: Optional[str] = None
    cost: Optional[str] = None
    medicines: Optional[list[str]] = None


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
