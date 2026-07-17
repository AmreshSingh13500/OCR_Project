"""
[MODULE]   tests/test_schemas.py
[TASK]     T1.2 — Auth & API endpoints
[SUBTASKS] T1.2.2 ProcessRequest / ExtractedData / WebhookPayload per PRD §4.1-4.2
[SUMMARY]  Unit tests for app/schemas.py's three contract models: field sets, required
           vs. optional split, and that a missing required field raises pydantic
           ValidationError (the mechanism FastAPI turns into a 422 at the route level,
           verified end-to-end in test_routes.py once T1.2.3 exists). Also asserts
           ExtractedData mirrors llm_extractor.py's EXTRACTED_DATA_JSON_SCHEMA (T4.1.1)
           field-for-field, since the two are intentionally separate definitions that
           must not drift apart.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.2.2
[HISTORY]  2026-07-17  T1.2.2  initial schema shape/validation tests
"""

import pytest
from pydantic import ValidationError

from app.pipeline.llm_extractor import EXTRACTED_DATA_JSON_SCHEMA
from app.schemas import ExtractedData, ProcessRequest, WebhookPayload


def test_process_request_requires_case_id_message_id_file_url():
    """[T1.2.2] AC: case_id/message_id/file_url required; the rest default to None."""
    req = ProcessRequest(case_id="c-1", message_id="m-1", file_url="https://x/doc.pdf")
    assert req.file_type is None
    assert req.file_name is None
    assert req.source_channel is None


def test_process_request_missing_required_field_raises_validation_error():
    """[T1.2.2] AC: a missing required field raises ValidationError (-> 422 at the route)."""
    with pytest.raises(ValidationError):
        ProcessRequest(case_id="c-1", file_url="https://x/doc.pdf")


def test_process_request_accepts_all_optional_fields():
    """[T1.2.2] AC: file_type/file_name/source_channel are accepted when present."""
    req = ProcessRequest(
        case_id="c-1",
        message_id="m-1",
        file_url="https://x/doc.pdf",
        file_type="pdf",
        file_name="doc.pdf",
        source_channel="whatsapp",
    )
    assert req.file_type == "pdf"
    assert req.file_name == "doc.pdf"
    assert req.source_channel == "whatsapp"


def test_extracted_data_all_fields_default_to_none():
    """[T1.2.2] AC: every ExtractedData field is nullable/optional."""
    data = ExtractedData()
    assert data.patient_name is None
    assert data.doctor_name is None
    assert data.diagnosis is None
    assert data.procedure is None
    assert data.cost is None
    assert data.medicines is None


def test_extracted_data_field_set_matches_openai_structured_output_schema():
    """[T1.2.2] ExtractedData mirrors llm_extractor.py's EXTRACTED_DATA_JSON_SCHEMA (T4.1.1) exactly."""
    assert set(ExtractedData.model_fields.keys()) == set(
        EXTRACTED_DATA_JSON_SCHEMA["properties"].keys()
    )


def test_webhook_payload_requires_status():
    """[T1.2.2] AC: status is required; processing_path/extracted_data/error_message default to None."""
    payload = WebhookPayload(case_id="c-1", message_id="m-1", status="success")
    assert payload.processing_path is None
    assert payload.extracted_data is None
    assert payload.error_message is None


def test_webhook_payload_rejects_unknown_status():
    """[T1.2.2] status is a frozen Literal["success", "error"] (CODING_RULES.md Rule 7)."""
    with pytest.raises(ValidationError):
        WebhookPayload(case_id="c-1", message_id="m-1", status="pending")


def test_webhook_payload_rejects_unknown_processing_path():
    """[T1.2.2] processing_path is a frozen Literal per plan §1 (Rule 7)."""
    with pytest.raises(ValidationError):
        WebhookPayload(
            case_id="c-1", message_id="m-1", status="success", processing_path="ocr_v2"
        )


def test_webhook_payload_key_set_matches_build_webhook_payload():
    """[T1.2.2] WebhookPayload mirrors webhook_client.py's build_webhook_payload() (T4.2.1) key set exactly."""
    from app.pipeline.webhook_client import build_webhook_payload

    built = build_webhook_payload(
        case_id="c-1",
        message_id="m-1",
        status="success",
        processing_path="native_pdf",
        extracted_data={"patient_name": "Jane Doe"},
        error_message=None,
    )
    assert set(built.keys()) == set(WebhookPayload.model_fields.keys())
