"""
[MODULE]   app/pipeline/llm_extractor.py
[TASK]     T4.1 — OpenAI structured extraction (Step 5)
           T8.1 — Generalized any-document extraction (additive contract update)
           T8.2 — Multi-language documents + extraction fidelity (additive)
           T8.3 — Vision-path accuracy (resolution + completeness/MRZ prompt)
           T8.4 — Non-English field values forced to English (prompt fix)
           T8.5 — Complex documents: transcription-grounded extraction + RTL rules
           T8.6 — Role-based patient/subject vs doctor name assignment (prompt)
           T8.7 — Language-mix percentage in original_language (prompt)
[SUBTASKS] T4.1.1 Structured Outputs JSON schema (strict) mirroring ExtractedData, incl. `cost`
           T4.1.2 Text path: gpt-4o-mini chat completion with extraction system prompt
           T4.1.3 Vision path: <=3 base64 JPEGs (downscale cap + quality now per T8.3.2)
           T4.1.4 Tenacity retries: 3 attempts, exp backoff 2-30s, retryable errors only
           T4.1.5 All-fields-null flag -> success + informative error_message (PRD clarification #2)
           T4.1.6 Log prompt/completion token usage per call
           T8.1.1 additive schema keys: document_type / document_summary / additional_details
           T8.1.2 generalized any-document extraction prompt (text + vision share it)
           T8.2.1 additive original_language key + English-output/transliteration prompt rules
           T8.2.3 verbatim-transcription prompt rules + vision detail:"high"
           T8.3.2 vision resolution 2048px/quality 90 + MRZ-authoritative & completeness prompt rules
           T8.3.3 optional OPENAI_VISION_MODEL — stronger model for the vision path only
           T8.4.1 prompt: ALL field values forced to English/Latin (fixes Arabic patient_name)
           T8.5.1 full_text transcription-first schema field (additive; strict-mode key
                  order = generation order -> transcribe-then-extract in one call)
           T8.5.2 RTL table/honorific/cross-script prompt rules
           T8.6.1 role-based name assignment — subject/holder (incl. passport holder)
                  -> patient_name; physician/referrer/signer -> doctor_name; never crossed
           T8.7.1 original_language reports each language's approximate % share for
                  mixed-language documents (single language -> just named)
[SUMMARY]  Defines the OpenAI Structured Outputs contract for Step 5 and both extraction
           call paths. `EXTRACTED_DATA_JSON_SCHEMA`/`RESPONSE_FORMAT` mirror the
           ExtractedData shape — the 6 original medical keys (patient_name, doctor_name,
           diagnosis, procedure, cost, medicines) plus the additive T8.1.1 keys
           (document_type, document_summary, additional_details) and T8.2.1's
           original_language, which together let the service handle ANY document kind
           (passport, invoice, medicine box, ...) in ANY language (Arabic, mixed, ...):
           what the document is, its original language, a properly written English
           summary, and every other readable detail as {field, value} pairs — all
           values output in English (content translated; proper names transliterated
           exactly, per the T8.2.1/T8.2.3 prompt rules that also forbid correcting or
           inferring names/numbers). Every field is nullable, so "not found in the
           document" is expressed as null, never a missing key or a guessed value; an
           unreadable document returns null for every field including the additive
           ones, preserving T4.1.5's all-null unreadable signal. `cost` is a contract addition
           beyond the PRD §4.2 sample (PRD clarification #1, IMPLEMENTATION_PLAN.md
           §8-1); Laravel must tolerate the extra key. `extract_from_text()` sends
           native-PDF text (T2.1) or PaddleOCR output (T3.2) through a single chat
           completion using the frozen system prompt; `extract_from_images()` sends up
           to MAX_PDF_PAGES_OCR page images — since T8.3.1 the orchestrator hands over
           the ORIGINAL color photos, not the cleaned grayscale — each downscaled to a
           2048px longest side and JPEG-encoded at quality 90 (T8.3.2), through the
           same schema and system prompt. Both paths funnel through `_call_chat_completion()`,
           which retries transient OpenAI failures (timeout, connection, rate limit, 5xx)
           up to `OPENAI_MAX_RETRIES` times with exponential backoff (2-30s) and raises
           `LLMError` once retries are exhausted; non-retryable errors (401, 400) are not
           in the retry set and propagate immediately on the first attempt.
           `is_all_fields_null()` + `ALL_FIELDS_NULL_MESSAGE` let the orchestrator (T4.3,
           not built yet) detect a blurry/unreadable document: when every extracted field
           is null, Laravel still gets `status:"success"` (Manual Review is Laravel's
           call per PRD §6.2) but with the frozen `error_message` below set alongside it
           (PRD clarification #2, IMPLEMENTATION_PLAN.md §8-2) — this module only exposes
           the detection + message; T4.3 owns building the actual webhook payload.
           `_call_chat_completion()` also logs prompt/completion/total token usage at
           INFO on every successful call (not per failed retry attempt, since a raised
           exception carries no usage data) — routing-decision-adjacent cost telemetry,
           not medical field data, so it isn't subject to CLAUDE.md's DEBUG-only rule.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T4.1.1, T4.1.2, T4.1.3, T4.1.4, T4.1.5, T4.1.6
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
           2026-07-17  T4.1.5  add is_all_fields_null() + ALL_FIELDS_NULL_MESSAGE;
                                Rule 7 gate checked — this is a NEW frozen error string
                                (PRD clarification #2), not an edit to an existing one,
                                so it's additive; exact wording locked from this commit on
           2026-07-17  T4.1.6  add token-usage logging in _call_chat_completion(); no
                                schemas.py/routes.py/webhook_client.py/error-string
                                changes (Rule 7 gate n/a) — logging-only addition
           2026-07-18  T8.1.1  add document_type/document_summary/additional_details to
                                EXTRACTED_DATA_JSON_SCHEMA — Rule 7 gate checked: 3 new
                                nullable keys, existing 6 keys byte-identical, no rename/
                                remove/retype — additive, contract-safe (same precedent
                                as `cost`); schema name constant renamed to
                                "extracted_document_data" (OpenAI-internal label only,
                                never seen by Laravel)
           2026-07-18  T8.1.2  replace _EXTRACTION_SYSTEM_PROMPT with the generalized
                                any-document prompt (both paths share it unchanged);
                                prompt wording is internal (plan T7.2.2 explicitly
                                allows tuning) — no contract surface touched; unreadable
                                documents instructed to return all-null incl. the new
                                keys so T4.1.5's signal keeps working
           2026-07-19  T8.2.1  add original_language to EXTRACTED_DATA_JSON_SCHEMA —
                                Rule 7 gate checked: 1 new nullable key, existing 9
                                byte-identical, additive/contract-safe (same precedent
                                as cost/T8.1.1); prompt gains language rules (detect,
                                report, output English, transliterate names exactly)
           2026-07-19  T8.2.3  prompt gains verbatim-transcription accuracy rules
                                (never correct/expand/infer names; unclear ->
                                null, not a guess); vision image_url items now send
                                detail:"high" (cost bounded by T4.1.3's 1536px
                                downscale) — internal request param, no contract surface
           2026-07-19  T8.3.2  vision downscale cap 1536->2048px + JPEG quality 85->90;
                                prompt gains MRZ-authoritative rule (passports/IDs) and
                                an explicit completeness rule (extract every labeled
                                field). Prompt/encoding tuning only (plan T7.2.2 allows) —
                                no contract surface touched (Rule 7 gate n/a)
           2026-07-19  T8.3.3  _call_chat_completion()/_create_chat_completion() now take
                                an explicit `model`; text path passes OPENAI_MODEL, vision
                                path passes _vision_model() (OPENAI_VISION_MODEL or the
                                default). Internal signature change (Rule 7B); the new env
                                var is additive/optional (Rule 7 gate n/a)
           2026-07-19  T8.5.1  add full_text as the FIRST schema property (strict mode
                                generates keys in schema order -> the model transcribes
                                the whole document before extracting; grounding fixes
                                skipped-row/RTL errors) — Rule 7 gate checked: 1 new
                                nullable key, prior 10 byte-identical, additive; the only
                                field allowed to carry the original (non-Latin) script;
                                null on the text path
           2026-07-19  T8.5.2  prompt gains RTL rules: table labels are the RIGHTMOST
                                cell (value to its left, never swap/drop rows), honorifics
                                (المحترم etc.) are not part of names, cross-check
                                dual-script names and prefer the Latin spelling. Prompt
                                tuning only (T7.2.2 allows), no contract surface
           2026-07-20  T8.6.1  prompt gains a "Name roles" section: assign patient_name
                                (the document's subject/holder — incl. a passport/ID
                                holder, or a "Patient Name"/الاسم/اسم المريض label) vs
                                doctor_name (physician/referrer/signer) by ROLE, never
                                crossing them; field-list item 3 updated so non-medical
                                documents populate patient_name with the holder. Prompt
                                tuning only (T7.2.2 allows); no schema/key change — this
                                is the contract-safe "Option A" the user chose over
                                renaming patient_name -> "Name" (Rule 7 gate n/a)
           2026-07-20  T8.7.1  original_language prompt rule extended: mixed-language
                                documents report each language's approximate percentage
                                share (adding up to 100), e.g. "75% Arabic, 25% English";
                                single-language documents just name the language.
                                document_type/original_language already have dedicated
                                keys, so nothing was duplicated into additional_details
                                (which is by-design for details NOT already in a named
                                field). Prompt wording only, no schema change (Rule 7 n/a)
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

# [T8.1.2] Generalized any-document prompt, replacing T4.1.2's medical-only wording
# (prompt text is internal — plan T7.2.2 explicitly allows tuning it; the schema is the
# contract, not the prompt). The final paragraph is load-bearing: instructing all-null
# for unreadable documents (INCLUDING the new T8.1.1 keys) is what keeps T4.1.5's
# all-fields-null unreadable signal working now that a summary would otherwise almost
# always be non-null.
# [T8.2.1] Language rules: any-language documents, original_language reported, every
# value output in English (translate content, transliterate proper names exactly).
# [T8.2.3] Fidelity rules: verbatim transcription of names/numbers/IDs, no correcting/
# expanding/inferring, unclear -> null (or only the legible part) — never a plausible
# guess. Directly targets the observed wrong-doctor-name fabrication.
# [T8.4.1] The language rules and the accuracy rules were reworded to resolve a conflict
# that made the model return e.g. an Arabic patient_name while writing the summary in
# English: "output in English/Latin" now explicitly applies to EVERY field, and the
# "transcribe exactly" fidelity rule is scoped to CONTENT (don't invent/change), not to
# the script — names/words are always transliterated/translated into Latin/English.
# [T8.6.1] Name-roles section: assign patient_name vs doctor_name by the ROLE each name
# plays, not its position — the subject/holder (incl. a passport or ID holder, or any
# "Patient Name"/الاسم/اسم المريض label) is the patient_name; the physician/referrer/
# signer is the doctor_name; never cross them, and leave a genuinely ambiguous name's
# field null. Contract-safe (Rule 7): prompt wording only, no schema/key change — this
# is "Option A", chosen by the user over renaming the frozen patient_name key to "Name".
# [T8.7.1] original_language now reports a percentage split for mixed-language documents
# (e.g. "75% Arabic, 25% English"); single-language docs just name the language. Prompt
# wording only — original_language is already a string key (T8.2.1), so no schema change.
# document_type/original_language keep their dedicated top-level keys and are NOT copied
# into additional_details (which is reserved for details not already in a named field).
_EXTRACTION_SYSTEM_PROMPT = (
    "You are a document information extraction system. The document may be of ANY kind: "
    "medical (lab report, prescription, medicine box, ultrasound or radiology scan, "
    "bill) or non-medical (passport, ID card, invoice, certificate, letter, form, etc.), "
    "and may be written in ANY language (English, Arabic, Kurdish, mixed, ...).\n"
    "\n"
    "STEP 1 — full_text (do this FIRST, before any other field):\n"
    "Transcribe EVERY piece of text visible on the document into full_text, top to "
    "bottom, exactly as written — keep the original language and script here (full_text "
    "is the ONLY field where non-Latin script is allowed). Include every table row as "
    "one 'label: value' line, every header, every caption inside embedded images, every "
    "stamp and footnote. Miss nothing: a row you skip here is data lost forever. All "
    "other fields must then be filled FROM this transcription (plus the image), so a "
    "name or value that is not in full_text must not appear in any other field. If the "
    "document content was given to you as plain text rather than an image, set "
    "full_text to null — the text is already known.\n"
    "\n"
    "Right-to-left (RTL) documents — Arabic, Kurdish, etc.:\n"
    "- Arabic text and tables read RIGHT to LEFT: in a table row, the field label is "
    "usually the RIGHTMOST cell and its value is the cell to its LEFT. Match each value "
    "to the label of its own row — e.g. a row labeled اسم الطبيب (doctor name) vs "
    "اسم المريض (patient name): read each label carefully and never swap or drop one.\n"
    "- Honorific titles such as المحترم (the respected), السيد (Mr.), or "
    "الدكتور (Dr.) are NOT part of a person's name — do not include them in name "
    "fields.\n"
    "- The same name often appears in BOTH scripts on one document (e.g. an Arabic "
    "table plus a Latin caption inside a scan image): cross-check them, and use the "
    "Latin spelling for the name fields.\n"
    "\n"
    "Language rules (these apply to EVERY field below — patient_name, doctor_name, "
    "diagnosis, additional_details, all of them — not only document_summary):\n"
    "- original_language: name the language(s) the document is written in. If it is in a "
    "SINGLE language, just name it, e.g. \"English\" or \"Arabic\". If it MIXES "
    "languages, list each language with its approximate percentage share of the text — "
    "estimate the share from how much of the transcription is in each script, round to "
    "sensible whole numbers that add up to 100 — e.g. \"75% Arabic, 25% English\" or "
    '"60% English, 40% Kurdish".\n'
    "- ALWAYS write every value in English using the Latin alphabet. NEVER output "
    "Arabic, Kurdish, or any other non-Latin script in any field except full_text. "
    "Translate non-English words and phrases into English.\n"
    "- Transliterate proper names (people, doctors, clinics, brands, places) into the "
    "Latin alphabet — e.g. the Arabic name “محمد عبد "
    "الله” must be written “Mohammed Abdullah”, never "
    "left in Arabic. Do not translate a name's meaning and do not replace it with a "
    "different or more common name; transliterate the actual name. If the document also "
    "prints the same name in the Latin alphabet somewhere (an embedded image caption, a "
    "signature, or an MRZ), use that exact spelling.\n"
    "\n"
    "Accuracy rules (critical) — these govern a value's CONTENT, not which script it is "
    "written in (every value is always English/Latin, per the language rules above):\n"
    "- Transcribe numbers, dates, and identifiers EXACTLY, digit by digit. For names "
    "and words, render the true content faithfully — never invent, correct, expand, "
    "reorder, or \"improve\" what the document actually says.\n"
    "- Never guess or fabricate a value. If a value is unclear or only partially "
    "legible, return null for that field, or only the clearly legible part — never a "
    "plausible-looking guess.\n"
    "- If the document is a passport, ID card, or any document with a machine-readable "
    "zone (MRZ — the one or two lines of monospaced characters filled with '<'), read "
    "the MRZ and use it as the AUTHORITATIVE source for the holder's name, document "
    "number, nationality, date of birth, sex, and expiry date: it is machine-encoded "
    "and more reliable than the printed labels. In the MRZ, '<' is a separator/filler; "
    "the surname comes before '<<' and the given names after it.\n"
    "\n"
    "Completeness rule:\n"
    "- Extract EVERY labeled field and value visible on the document — do not skip any. "
    "For an ID, passport, form, or report, that means every field (e.g. document/serial "
    "number, type, country, date of issue, date of expiry, place of birth, nationality, "
    "sex, mother's/father's name, issuing authority, every measurement row, every result "
    "line). Anything not mapped to a named field below goes into additional_details.\n"
    "\n"
    "Name roles — decide which name is the PATIENT and which is the DOCTOR by the ROLE "
    "each name plays on the document, not by where it sits:\n"
    "- patient_name is the person the document is ABOUT — the patient, the subject, or "
    "the holder. Use it for the holder's name on a passport or ID card, and for any name "
    "labeled \"Patient Name\", \"Name\", \"Patient\", الاسم, or اسم المريض. If the "
    "document names only one person and gives no medical role (e.g. a passport, an ID "
    "card, a personal certificate), that single name IS the patient_name.\n"
    "- doctor_name is the medical professional — the doctor, physician, consultant, "
    "radiologist, or the clinician who referred, treated, or signed the report. Use it "
    "for a name marked \"Dr.\", الطبيب, اسم الطبيب, \"Consultant\", \"Referred by\", or a "
    "physician's signature or stamp.\n"
    "- NEVER put the doctor's name into patient_name, and never put the patient's name "
    "into doctor_name. If a name's role is genuinely unclear, leave the field you are "
    "unsure about null rather than assign the name to the wrong role.\n"
    "\n"
    "After full_text, fill the remaining fields as follows:\n"
    "1. document_type: a short label naming what kind of document this is, e.g. "
    '"lab report", "handwritten prescription", "medicine box", "ultrasound scan", '
    '"passport", "invoice".\n'
    "2. document_summary: 2-4 complete, properly written English sentences: state what "
    "the document is and the key information it carries, e.g. \"This is a passport "
    'issued by ... belonging to ... It carries ..."\n'
    "3. patient_name, doctor_name, diagnosis, procedure, cost, medicines: fill each one "
    "when that information is present on the document; return null for any that are "
    "absent. Assign patient_name and doctor_name strictly by the Name-roles rule above — "
    "on a passport, ID, or other non-medical document, patient_name is the holder's/"
    "subject's name (diagnosis, procedure, cost, and medicines are usually null there).\n"
    "4. additional_details: every other piece of information readable on the document "
    "that is not already captured in the fields above, as {\"field\": <label>, "
    "\"value\": <value>} pairs — identification numbers, dates, names, addresses, "
    "nationalities, test results, dosages, amounts, issuing authorities, etc. Return "
    "null if there is nothing beyond the fields above.\n"
    "5. original_language: as described in the language rules.\n"
    "\n"
    "Never guess or fabricate values; report only what is actually readable. If the "
    "document is unreadable (blurry, blank, or too degraded), return null for EVERY "
    "field, including full_text, document_type, document_summary, additional_details, "
    "and original_language."
)

# [T4.1.3] Bounds vision token cost/latency. [T8.3.2] Raised 1536->2048 (GPT-4o's
# high-detail tiling sweet spot — 2048px longest side maps to a full 6-tile grid, so
# small text like a clinic-name header or an MRZ line survives) and quality 85->90
# (sharper text edges). Cost tradeoff (more image tokens/call) recorded in TASKS.md §5;
# still bounded — every image is capped at this longest side before encoding.
_VISION_MAX_LONGEST_SIDE_PX = 2048
_VISION_JPEG_QUALITY = 90

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

EXTRACTED_DATA_SCHEMA_NAME = "extracted_document_data"

# [T4.1.1] Strict JSON Schema for OpenAI Structured Outputs, mirroring the ExtractedData
# model that schemas.py (T1.2.2) will define. OpenAI's strict mode has no concept of an
# "optional" key — every property must be listed in `required`; nullability is instead
# expressed via `"type": [<type>, "null"]`. `additionalProperties: False` is mandatory
# for strict mode at every object level (root and any nested object).
EXTRACTED_DATA_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        # [T8.5.1] MUST stay the FIRST property: OpenAI strict mode generates keys in
        # schema order, so the model is forced to transcribe the whole document before
        # filling any extraction field — transcription-grounded extraction (the
        # "transcribe, then extract from your own transcription" decomposition). This is
        # what makes RTL tables and mixed-language pages read completely instead of the
        # model jumping straight to (wrong) field values. Nullable + additive (Rule 7).
        "full_text": {"type": ["string", "null"]},
        "patient_name": {"type": ["string", "null"]},
        "doctor_name": {"type": ["string", "null"]},
        "diagnosis": {"type": ["string", "null"]},
        "procedure": {"type": ["string", "null"]},
        "cost": {"type": ["string", "null"]},
        "medicines": {
            "type": ["array", "null"],
            "items": {"type": "string"},
        },
        # [T8.1.1] Additive general-document keys (Rule 7: the 6 keys above are frozen
        # and byte-identical; these 3 are new optional/nullable keys, same precedent as
        # `cost`). additional_details is an array of {field, value} string pairs rather
        # than a free-form object because strict mode forbids open objects
        # (additionalProperties must be False, so arbitrary keys can't be expressed).
        "document_type": {"type": ["string", "null"]},
        "document_summary": {"type": ["string", "null"]},
        "additional_details": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["field", "value"],
                "additionalProperties": False,
            },
        },
        # [T8.2.1] Additive (Rule 7, same precedent): the language(s) the original
        # document is written in; extracted values themselves are always English.
        "original_language": {"type": ["string", "null"]},
    },
    "required": [
        "full_text",
        "patient_name",
        "doctor_name",
        "diagnosis",
        "procedure",
        "cost",
        "medicines",
        "document_type",
        "document_summary",
        "additional_details",
        "original_language",
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
    return _call_chat_completion(messages, model=settings.OPENAI_MODEL)


# [T8.3.3] The vision path optionally uses a stronger model than the text path — image
# reading accuracy (small/photographed/non-Latin text) is where the cheap model falls
# down, and the text path (already-extracted characters) doesn't need the upgrade. Unset
# OPENAI_VISION_MODEL -> same model as the text path, so behavior is unchanged by default.
def _vision_model() -> str:
    return settings.OPENAI_VISION_MODEL or settings.OPENAI_MODEL


# Downscales only when needed (never upscales a smaller image) and re-encodes as JPEG.
# Handles both the original BGR color images the orchestrator sends since T8.3.1 (cv2
# encodes 3-channel BGR as a standard color JPEG) and single-channel grayscale (a valid
# single-component JPEG) — no conversion needed for the vision API in either case.
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
# page images instead of raw text (since T8.3.1 the orchestrator passes the original
# color images, not the cleaned grayscale). Truncates defensively to MAX_PDF_PAGES_OCR
# even though the orchestrator (T4.3) is expected to already cap page count upstream.
def extract_from_images(images: list[np.ndarray]) -> dict:
    # [T8.2.3] detail:"high" — document text (names, dosages, IDs) is exactly what the
    # default/low detail modes misread; token cost stays bounded because every image is
    # downscaled to a 2048px longest side (T8.3.2) before encoding.
    content = [
        {
            "type": "image_url",
            "image_url": {"url": _encode_image_base64_jpeg(image), "detail": "high"},
        }
        for image in images[:MAX_PDF_PAGES_OCR]
    ]
    messages = [
        {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]
    return _call_chat_completion(messages, model=_vision_model())


# [T4.1.4] Shared call path for both extraction functions: retries transient OpenAI
# failures with exponential backoff, then raises LLMError once attempts are exhausted.
# Non-retryable errors (401/400) are not in _RETRYABLE_OPENAI_ERRORS so they propagate
# unwrapped on the first attempt, per the plan's "fail immediately" rule.
def _call_chat_completion(messages: list, model: str) -> dict:
    try:
        response = _create_chat_completion(messages, model)
    except _RETRYABLE_OPENAI_ERRORS as exc:
        raise LLMError(
            f"OpenAI extraction failed after {OPENAI_MAX_RETRIES} attempts: {exc}"
        ) from exc

    # [T4.1.6] Only reachable on a successful call — a raised exception above carries no
    # usage data, so there is nothing to log for exhausted-retry/non-retryable failures.
    usage = response.usage
    logger.info(
        "OpenAI extraction token usage: prompt=%d completion=%d total=%d",
        usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
    )

    return json.loads(response.choices[0].message.content)


@retry(
    retry=retry_if_exception_type(_RETRYABLE_OPENAI_ERRORS),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(OPENAI_MAX_RETRIES),
    reraise=True,
)
def _create_chat_completion(messages: list, model: str):
    return _client.chat.completions.create(
        model=model,
        messages=messages,
        response_format=RESPONSE_FORMAT,
    )


# [T4.1.5] Frozen exact string (PRD clarification #2, IMPLEMENTATION_PLAN.md §8-2) — set
# alongside status:"success" (never status:"error") when every extracted field is null.
# Never edit this wording once shipped; CODING_RULES.md Rule 7 treats error_message
# strings as frozen. Laravel does the actual Manual Review flagging (PRD §6.2); this
# service only signals the condition.
ALL_FIELDS_NULL_MESSAGE = "All fields empty - possible unreadable document"


# [T4.1.5] extracted_data is the dict returned by extract_from_text()/extract_from_images(),
# always exactly the ExtractedData key set (strict schema, T4.1.1 + T8.1.1's additions —
# this iterates whatever keys are present, so it covers the 9-key shape automatically) —
# "all null" means the model found nothing at all, the signal for a blurry/unreadable
# document. The T8.1.2 prompt explicitly instructs all-null (including document_summary)
# for unreadable documents, so this signal stays meaningful for any document kind.
def is_all_fields_null(extracted_data: dict) -> bool:
    return all(value is None for value in extracted_data.values())
