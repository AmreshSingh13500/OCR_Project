# Implementation Plan: AI-Powered Document Ingestion & OCR Microservice (Python)

**Project:** Global Care ERP — Phase 1 (Lead Management & Patient Journey)
**Scope:** Python/FastAPI OCR Microservice only (Laravel side is out of scope except for contract compliance)
**Source PRD:** v1.0, dated July 16, 2026
**Status:** SINGLE POINT OF KNOWLEDGE — all implementation work must trace back to a Task ID in this document.

---

## 0. How to Use This Document

- Every unit of work has an ID: `T<phase>.<task>` (e.g., `T3.2`). Subtasks are `T3.2.1`, etc.
- Each task lists: **Goal, Subtasks, Dependencies, Acceptance Criteria (AC)**.
- Work phases in order; tasks inside a phase can be parallelized unless a dependency says otherwise.
- Definitions of Done (DoD) for the whole project are in §9.

---

## 1. Architecture Summary (Authoritative)

```
WhatsApp (Ultramsg) / Email
        │ webhook
        ▼
Laravel ERP ──(200 OK immediately)──► Redis/Horizon Job: ProcessMedicalDocumentJob
        │
        │ POST /api/v1/process  (Bearer token, JSON: case_id, file_url, ...)
        ▼
┌──────────────────────── Python Microservice (Dedicated Ubuntu Server) ───────────────────────┐
│  FastAPI (Uvicorn workers under Gunicorn, behind Nginx + SSL)                                 │
│                                                                                               │
│  [Step 2] Download file → PDF? ── PyMuPDF text extraction                                     │
│              │                        │ >100 chars → NATIVE PDF → skip to Step 5              │
│              │                        │ <100 chars → SCANNED → pdf2image (max 5 pages,        │
│              │                                                  first 3 converted to JPEG)    │
│              ▼                                                                                │
│  [Step 3] OpenCV cleaning: Grayscale → Deskew → Adaptive Threshold → CLAHE                    │
│              ▼                                                                                │
│  [Step 4] CLIP classifier (local, HuggingFace)                                                │
│              ├── Branch A: Printed report → PaddleOCR (CPU) → raw text                        │
│              └── Branch B: Handwritten / scan / medicine box → Base64 image                   │
│              ▼                                                                                │
│  [Step 5] OpenAI gpt-4o-mini, Structured Outputs                                              │
│              ├── text path: chat completion with raw text                                     │
│              └── image path: Vision endpoint with Base64                                      │
│              ▼                                                                                │
│  [Step 6] POST result → Laravel /api/internal/ocr-webhook (Bearer token)                      │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Key design decisions (locked):**
1. `POST /api/v1/process` returns `202 Accepted` immediately; the pipeline runs as a FastAPI `BackgroundTask` (or internal task queue) and delivers results via the Step-6 webhook. This satisfies the "100% asynchronous / zero blocking" metric on both sides.
2. Files are processed **in memory** (BytesIO) — never written to disk except optional debug mode.
3. CLIP and PaddleOCR models are loaded **once per worker at startup** (lifespan event), not per request.
4. `processing_path` is always one of: `native_pdf` | `paddleocr` | `vision_api`.
5. Page limits: hard cap of 5 pages converted for any PDF (PRD §6.4); of those, the first 3 pages are used for OCR (PRD Step 2). Implement as constants `MAX_PDF_PAGES_CONVERT = 5`, `MAX_PDF_PAGES_OCR = 3`.
6. Multi-page results: run the pipeline per page, concatenate PaddleOCR text before the single LLM call; for the vision path, send up to 3 images in one Vision request.

---

## 2. Repository Layout (Target)

```
OCR_Project/
├── IMPLEMENTATION_PLAN.md          # this file
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app factory, lifespan (model loading), router mount
│   ├── config.py                   # pydantic-settings: env vars, constants
│   ├── auth.py                     # Bearer token dependency
│   ├── schemas.py                  # Pydantic models: ProcessRequest, WebhookPayload, ExtractedData
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py               # POST /api/v1/process, GET /health
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── orchestrator.py         # run_pipeline(): steps 2→6, error handling, processing_path
│   │   ├── downloader.py           # Step 2a: fetch file_url into BytesIO (size/type limits)
│   │   ├── pdf_handler.py          # Step 2b: PyMuPDF text check, pdf2image conversion
│   │   ├── image_cleaner.py        # Step 3: grayscale, deskew, adaptive threshold, CLAHE
│   │   ├── classifier.py           # Step 4a: CLIP zero-shot routing
│   │   ├── ocr_engine.py           # Step 4b: PaddleOCR wrapper
│   │   ├── llm_extractor.py        # Step 5: OpenAI structured outputs (text + vision)
│   │   └── webhook_client.py       # Step 6: POST back to Laravel with retries
│   └── utils/
│       ├── __init__.py
│       └── logging.py              # structured JSON logging, request-id correlation
├── tests/
│   ├── conftest.py                 # fixtures: sample files, mock OpenAI, mock Laravel webhook
│   ├── fixtures/                   # native.pdf, scanned.pdf, printed_report.jpg,
│   │                               # handwritten.jpg, medicine_box.jpg, password.pdf, blurry.jpg
│   ├── test_auth.py
│   ├── test_pdf_handler.py
│   ├── test_image_cleaner.py
│   ├── test_classifier.py
│   ├── test_ocr_engine.py
│   ├── test_llm_extractor.py
│   ├── test_webhook_client.py
│   └── test_pipeline_e2e.py
├── deploy/
│   ├── nginx.conf                  # reverse proxy + SSL template
│   ├── ocr-service.service         # systemd unit for gunicorn
│   └── setup_server.sh             # Ubuntu bootstrap: deps, ufw, certbot
├── .env.example
├── requirements.txt
├── pyproject.toml                  # optional; requirements.txt is authoritative
└── README.md                       # run/deploy quickstart (points here for detail)
```

---

## 3. Configuration & Environment Variables

| Variable | Purpose | Example |
|---|---|---|
| `OCR_API_KEY` | Static bearer token Laravel must send to us | `long-random-hex` |
| `LARAVEL_WEBHOOK_URL` | Step 6 target | `https://erp.yourdomain.com/api/internal/ocr-webhook` |
| `LARAVEL_WEBHOOK_KEY` | Bearer token we send to Laravel | `long-random-hex` |
| `OPENAI_API_KEY` | OpenAI auth | `sk-...` |
| `OPENAI_MODEL` | LLM model (text path; default for both) | `gpt-4o-mini` |
| `OPENAI_VISION_MODEL` | optional stronger model for the vision path only (T8.3.3); unset → uses `OPENAI_MODEL` | `gpt-4o` |
| `MAX_FILE_SIZE_MB` | Download guard | `25` |
| `DOWNLOAD_TIMEOUT_S` | httpx timeout for file fetch | `30` |
| `LOG_LEVEL` | logging | `INFO` |
| `DEBUG_SAVE_IMAGES` | save intermediate images to /tmp for debugging | `false` |
| `ALLOWED_FILE_HOSTS` | optional SSRF-guard allowlist for `file_url` hosts (T5.2.4) | `*.amazonaws.com,media.ultramsg.com` |

Constants in `config.py` (not env): `NATIVE_PDF_MIN_CHARS = 100`, `MAX_PDF_PAGES_CONVERT = 5`, `MAX_PDF_PAGES_OCR = 3`, `PDF2IMAGE_DPI = 200`, `CLIP_LABELS`, `OPENAI_MAX_RETRIES = 3`.

---

## 4. Task Plan

### PHASE 1 — Project Scaffold & Core Service

#### T1.1 — Project scaffold
**Goal:** Runnable empty FastAPI service with config and logging.
**Subtasks:**
- T1.1.1 Create repo layout per §2; `requirements.txt` with pinned versions: `fastapi`, `uvicorn[standard]`, `gunicorn`, `pydantic`, `pydantic-settings`, `httpx`, `PyMuPDF`, `pdf2image`, `opencv-python-headless`, `numpy`, `paddleocr`, `paddlepaddle` (CPU), `transformers`, `torch` (CPU), `pillow`, `openai`, `tenacity`, `pytest`, `pytest-asyncio`, `respx`.
- T1.1.2 `config.py` using `pydantic-settings`; fail fast on missing required env vars at startup.
- T1.1.3 `utils/logging.py`: JSON logs with `case_id` / `message_id` correlation fields on every pipeline log line.
- T1.1.4 `.env.example` with every var from §3.
**Dependencies:** none.
**AC:** `uvicorn app.main:app` starts; missing `OCR_API_KEY` aborts startup with a clear error.

#### T1.2 — Auth & API endpoints
**Goal:** Contract-compliant ingestion endpoint.
**Subtasks:**
- T1.2.1 `auth.py`: FastAPI dependency validating `Authorization: Bearer <OCR_API_KEY>` with constant-time comparison (`secrets.compare_digest`); 401 on failure.
- T1.2.2 `schemas.py`: `ProcessRequest` exactly matching PRD §4.1 (`case_id`, `message_id`, `file_url`, `file_type`, `file_name`, `source_channel`); `ExtractedData` (`patient_name`, `doctor_name`, `diagnosis`, `procedure`, `medicines` — all nullable strings, `medicines` nullable list of strings); `WebhookPayload` exactly matching PRD §4.2.
- T1.2.3 `POST /api/v1/process`: validate → enqueue `run_pipeline` as BackgroundTask → return `202 {"status": "accepted", "case_id": ...}` immediately.
- T1.2.4 `GET /health`: returns 200 with model-loaded flags (`clip_loaded`, `paddle_loaded`) — unauthenticated, for monitoring.
- T1.2.5 Validate `file_url` scheme is https and reject obviously invalid URLs (400).
**Dependencies:** T1.1.
**AC:** Valid request → 202 in <200 ms regardless of file size; bad token → 401; malformed body → 422.

#### T1.3 — File downloader (Step 2a)
**Goal:** Safe in-memory download of the source file.
**Subtasks:**
- T1.3.1 `downloader.py`: async httpx GET with `DOWNLOAD_TIMEOUT_S`, streaming into BytesIO with `MAX_FILE_SIZE_MB` cap (abort mid-stream if exceeded).
- T1.3.2 Detect content kind by magic bytes (`%PDF`, JPEG/PNG signatures) — do not trust `file_type`/extension; classify as `pdf` | `image` | `unsupported`.
- T1.3.3 Raise typed exceptions: `DownloadError`, `FileTooLargeError`, `UnsupportedFileError` (orchestrator maps these to webhook error payloads, see T5.1).
**Dependencies:** T1.1.
**AC:** Unit tests with `respx` mock: happy path, 404, timeout, oversize, wrong type.

---

### PHASE 2 — PDF Handling & Image Cleaning

#### T2.1 — Smart PDF detection (Step 2b)
**Goal:** Native-vs-scanned branch exactly per PRD.
**Subtasks:**
- T2.1.1 `pdf_handler.py`: open BytesIO with PyMuPDF; catch `fitz.FileDataError` (and `fitz` password indicators — check `doc.needs_pass`) → raise `PasswordProtectedError` with message `"Password protected document"`.
- T2.1.2 Extract text from up to first `MAX_PDF_PAGES_OCR` pages; strip whitespace; if total length **> 100 chars** → return `NativePdfResult(text=...)`.
- T2.1.3 Else scanned: convert with `pdf2image` at `PDF2IMAGE_DPI`, `first_page=1`, `last_page=min(page_count, MAX_PDF_PAGES_CONVERT)`; keep the first `MAX_PDF_PAGES_OCR` images for the pipeline → return `ScannedPdfResult(images=[...])`.
- T2.1.4 System dependency note: `pdf2image` requires `poppler-utils` — added to `deploy/setup_server.sh` (T6.1) and README.
- T2.1.5 Handle zero-page/corrupt PDFs → `CorruptFileError`.
**Dependencies:** T1.3.
**AC:** Fixtures: native.pdf → text path; scanned.pdf → ≤3 images; password.pdf → `PasswordProtectedError`; 60-page PDF → exactly 5 pages converted, 3 used.

#### T2.2 — OpenCV pre-processing (Step 3)
**Goal:** Deterministic cleaning function `clean_image(np.ndarray) -> np.ndarray`.
**Subtasks:**
- T2.2.1 Grayscale conversion (`cv2.cvtColor` BGR→GRAY).
- T2.2.2 Deskew: estimate angle via `cv2.minAreaRect` on thresholded foreground pixels (fallback: Hough lines); rotate with `cv2.warpAffine`, border replicate; skip rotation if |angle| < 0.5° or estimation is low-confidence (avoid making good images worse).
- T2.2.3 CLAHE (`cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))`) applied on grayscale **before** thresholding (glare/lighting fix for medicine blister packs).
- T2.2.4 Adaptive thresholding (`cv2.adaptiveThreshold`, Gaussian, blockSize=31, C=15) → binarized output for OCR. Keep the **pre-threshold CLAHE grayscale** version too: the vision path (Branch B) sends the CLAHE image, not the binarized one (binarization destroys detail LLM vision needs). Return both: `CleanedImage(ocr_ready, vision_ready)`.
- T2.2.5 `DEBUG_SAVE_IMAGES=true` → write each stage to scratch dir with case_id prefix.
**Dependencies:** T1.1 (parallel with T2.1).
**AC:** Unit tests: skewed fixture becomes ~horizontal (angle within ±1°); output dtype/shape valid; runs <2 s per image on 4-core CPU.

---

### PHASE 3 — Classification & OCR

#### T3.1 — CLIP router (Step 4a)
**Goal:** Local zero-shot classification into Branch A vs Branch B.
**Subtasks:**
- T3.1.1 `classifier.py`: load `openai/clip-vit-base-patch32` via HuggingFace Transformers at app startup (lifespan), CPU, `torch.no_grad()`.
- T3.1.2 Candidate labels (tune during T7.2): `"a printed medical lab report document"`, `"a handwritten doctor prescription note"`, `"an ultrasound or radiology scan image"`, `"a photo of a medicine box or blister pack"`.
- T3.1.3 Routing rule: label 1 → Branch A (`paddleocr`); labels 2–4 → Branch B (`vision_api`). If top score < 0.4 confidence → Branch B (vision is the safe fallback).
- T3.1.4 Classification runs on the `vision_ready` (CLAHE grayscale converted to RGB) image.
- T3.1.5 Log label + confidence per page with case_id.
**Dependencies:** T2.2.
**AC:** printed_report.jpg → Branch A; handwritten.jpg, medicine_box.jpg → Branch B; inference <1.5 s/image on CPU; model loads once (verified via startup log, not per-request).

#### T3.2 — PaddleOCR engine (Step 4b, Branch A)
**Goal:** Local CPU text extraction for printed documents.
**Subtasks:**
- T3.2.1 `ocr_engine.py`: initialize `PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False)` once at startup.
- T3.2.2 `extract_text(image) -> str`: run OCR on `ocr_ready` image, join detected lines top-to-bottom preserving reading order; include per-line confidence in debug logs.
- T3.2.3 Guard: PaddleOCR is not thread-safe under concurrent calls in one process — serialize access with an `asyncio.Lock` per worker (Gunicorn's 4 processes still give 4-way parallelism), and run inference via `run_in_executor` so the event loop never blocks.
- T3.2.4 Fallback rule: if OCR yields < 20 characters total on a Branch-A image, reroute that page to Branch B (vision) and log the reroute.
**Dependencies:** T3.1.
**AC:** printed_report.jpg → non-empty text containing known fixture keywords; concurrent test (4 parallel requests) does not crash or interleave results.

---

### PHASE 4 — LLM Structuring & Webhook Return

#### T4.1 — OpenAI structured extraction (Step 5)
**Goal:** Guaranteed-schema JSON from text or images.
**Subtasks:**
- T4.1.1 `llm_extractor.py`: define the Structured Outputs JSON schema (strict) mirroring `ExtractedData`: `patient_name`, `doctor_name`, `diagnosis`, `procedure`, `cost`, `medicines` — nullable. *(Note: PRD prompt mentions `Cost` while the §4.2 sample omits it; include `cost` in the schema AND in `ExtractedData` so nothing is lost — flagged as PRD clarification #1 in §8.)*
- T4.1.2 Text path: `chat.completions` (or `responses` API) with `gpt-4o-mini`, `response_format={"type": "json_schema", ...}`, system prompt: *"Extract Patient Name, Doctor Name, Diagnosis, Procedure, and Cost from this medical document. Return null for any field not present. Do not guess or fabricate values."*
- T4.1.3 Vision path: same schema; content = prompt + up to `MAX_PDF_PAGES_OCR` images as `data:image/jpeg;base64,...` (encode `vision_ready` images as JPEG quality 85, downscale longest side to 1536 px to control tokens/cost).
- T4.1.4 Retries: `tenacity` — `retry=retry_if_exception_type((APITimeoutError, APIConnectionError, RateLimitError, InternalServerError))`, `wait_exponential(multiplier=1, min=2, max=30)`, `stop_after_attempt(3)`. Non-retryable errors (401, 400) fail immediately.
- T4.1.5 Blurry/unreadable detection: if **all** extracted fields are null → set pipeline flag `all_fields_null=True`; orchestrator returns `status: "success"` but Laravel-facing payload includes `extracted_data` of all nulls (Laravel flags Manual Review per PRD §6.2 — our contract addition: also set `error_message: "All fields empty - possible unreadable document"` while keeping `status: "success"`; flagged as PRD clarification #2 in §8).
- T4.1.6 Log token usage per call (prompt/completion tokens) for cost monitoring.
**Dependencies:** T1.1; integrates with T2.1 (native text), T3.2 (OCR text), T3.1 (vision images).
**AC:** Mocked-OpenAI unit tests: schema enforced, nulls handled, retry fires exactly 3 times on 500s then raises `LLMError`; live smoke test extracts correct fields from native.pdf fixture.

#### T4.2 — Laravel webhook return (Step 6)
**Goal:** Reliable result delivery matching PRD §4.2.
**Subtasks:**
- T4.2.1 `webhook_client.py`: async httpx POST to `LARAVEL_WEBHOOK_URL` with `Authorization: Bearer <LARAVEL_WEBHOOK_KEY>`; payload = `WebhookPayload` (case_id, message_id, status, processing_path, extracted_data, error_message).
- T4.2.2 Tenacity retries on connection errors / 5xx: 3 attempts, exponential backoff (2s→30s). 4xx = no retry (log CRITICAL — contract/config bug).
- T4.2.3 If all retries exhausted: log CRITICAL with full payload JSON so a human can replay manually. (Persistent dead-letter queue is a Phase-2 candidate — see §8 clarification #3.)
**Dependencies:** T1.1.
**AC:** respx tests: success, 5xx→retry→success, 5xx×4→CRITICAL log with payload, 401→single attempt + CRITICAL.

#### T4.3 — Pipeline orchestrator
**Goal:** Wire Steps 2–6 with correct branching and error mapping.
**Subtasks:**
- T4.3.1 `orchestrator.py` `run_pipeline(req: ProcessRequest)`: download → detect kind → PDF logic / direct image path → clean → classify → OCR-or-vision → LLM → webhook. Images sent directly (not in a PDF) skip Step 2b and go straight to cleaning.
- T4.3.2 Set `processing_path`: `native_pdf` (Step-2 text branch), `paddleocr` (Branch A), `vision_api` (Branch B or reroute). Mixed multi-page case (some pages A, some B): `vision_api` wins if any page used vision.
- T4.3.3 Error mapping table (exception → webhook payload with `status:"error"`, `extracted_data:null`):
  | Exception | error_message |
  |---|---|
  | `PasswordProtectedError` | `"Password protected document"` (exact PRD string) |
  | `DownloadError` | `"Failed to download source file"` |
  | `FileTooLargeError` | `"File exceeds size limit"` |
  | `UnsupportedFileError` | `"Unsupported file type"` |
  | `CorruptFileError` | `"Corrupt or unreadable file"` |
  | `LLMError` (retries exhausted) | `"AI extraction service unavailable"` |
  | any uncaught `Exception` | `"Internal processing error"` (+ full traceback in logs) |
- T4.3.4 Top-level try/except ensures **every** accepted request produces exactly one webhook call (success or error) — no silent drops.
- T4.3.5 Per-request timing log: total ms + per-step ms.
**Dependencies:** T1.3, T2.1, T2.2, T3.1, T3.2, T4.1, T4.2.
**AC:** E2E tests (mock OpenAI + mock Laravel): native PDF → `native_pdf` webhook; scanned printed → `paddleocr`; handwritten image → `vision_api`; password PDF → exact error string; every test asserts exactly one webhook call.

---

### PHASE 5 — Testing & Hardening

#### T5.1 — Test suite completion
**Subtasks:**
- T5.1.1 Assemble `tests/fixtures/` (7 files per §2 layout). Handwritten/medicine-box fixtures can be synthetic or anonymized samples — **no real patient data in the repo**.
- T5.1.2 Coverage target ≥80% on `app/pipeline/`; all AC tests from Phases 1–4 green.
- T5.1.3 Concurrency test: 8 simultaneous `/api/v1/process` calls → 8 webhook deliveries, no cross-request data bleed (verify case_ids match).
- T5.1.4 Accuracy validation harness (supports PRD success metrics): script that runs N labeled fixtures and reports field-level accuracy — target >95% printed, >85% handwritten. Run manually pre-release; not in CI.
**Dependencies:** Phases 1–4.
**AC:** `pytest` green; coverage report ≥80% pipeline; accuracy harness produces a report.

#### T5.2 — Security hardening (app level)
**Subtasks:**
- T5.2.1 Constant-time token compare (verify T1.2.1), no token in logs.
- T5.2.2 Never log extracted medical data at INFO — field values only at DEBUG; log field *presence* booleans at INFO (privacy).
- T5.2.3 Request body size limit at Nginx (1 MB — JSON only) and FastAPI level.
- T5.2.4 Optional allowlist for `file_url` hosts (e.g., `*.amazonaws.com`, Ultramsg media hosts) via env `ALLOWED_FILE_HOSTS`; SSRF guard — reject private/loopback IPs after DNS resolution.
**Dependencies:** T1.2, T1.3.
**AC:** SSRF test: `file_url=http://169.254.169.254/...` and `http://localhost/...` rejected; logs contain no bearer tokens or patient field values at INFO.

---

### PHASE 6 — Deployment (Ubuntu Dedicated Server)

#### T6.1 — Server provisioning script
**Subtasks:**
- T6.1.1 `deploy/setup_server.sh`: apt install `python3.11+`, `python3-venv`, `poppler-utils`, `nginx`, `libgl1` (OpenCV), `certbot python3-certbot-nginx`; create service user `ocrsvc`; venv + `pip install -r requirements.txt`.
- T6.1.2 UFW: `default deny incoming`, allow 22/tcp and 443/tcp only, enable. (Port 80 open only transiently for certbot HTTP-01, then closed — or use certbot's nginx plugin with 80→443 redirect kept; PRD says only 22+443, so close 80 after issuance and use standalone renewals with a pre/post hook.)
- T6.1.3 Model pre-download step: run a warmup script that pulls CLIP + PaddleOCR weights into the service user's cache so first request isn't slow.
**Dependencies:** none (can be written in parallel; validated in T6.3).
**AC:** Fresh Ubuntu 22.04 VM: script runs unattended to completion; `ufw status` shows only 22, 443.

#### T6.2 — Process & proxy configuration
**Subtasks:**
- T6.2.1 `deploy/ocr-service.service` (systemd): `ExecStart=gunicorn app.main:app -k uvicorn.workers.UvicornWorker --workers 4 --bind 127.0.0.1:8000 --timeout 300`; `Restart=always`; env via `EnvironmentFile=/etc/ocr-service/env`.
- T6.2.2 `deploy/nginx.conf`: 443 SSL (Let's Encrypt), proxy_pass to 127.0.0.1:8000, `client_max_body_size 1m`, `proxy_read_timeout 300s`, security headers.
- T6.2.3 Worker memory note: 4 workers × (CLIP + PaddleOCR) ≈ 4–6 GB RAM — fits 8 GB minimum, comfortable at 16 GB. Document in README; if 8 GB box, set `--workers 2` fallback documented.
**Dependencies:** T6.1.
**AC:** `systemctl status ocr-service` active; service survives reboot; `curl -k https://host/health` → 200 with models loaded.

#### T6.3 — End-to-end deployment validation
**Subtasks:**
- T6.3.1 Smoke test from an external machine: POST real sample docs through the public HTTPS endpoint → webhook received by a request-bin/mock Laravel.
- T6.3.2 Load test: 10 concurrent documents; confirm 202s < 500 ms, all webhooks delivered, RAM stable.
- T6.3.3 Log rotation (`journald` limits or logrotate) configured.
**Dependencies:** T6.1, T6.2, Phases 1–5.
**AC:** All three subtasks pass on the production server; results recorded in README deployment log.

---

### PHASE 7 — Integration & Tuning (with Laravel team)

#### T7.1 — Contract integration test with Laravel
**Subtasks:**
- T7.1.1 Exchange final bearer tokens (both directions) via secure channel.
- T7.1.2 Joint test: real Ultramsg WhatsApp message with attachment → Laravel job → Python → webhook → Case History fields populated (AP LC-2.0 / AP LC-7.0).
- T7.1.3 Verify Laravel handles all 7 error_message strings from T4.3.3 (esp. password-protected → Ops Exec notification path).
**Dependencies:** Phase 6; Laravel side ready.
**AC:** One document of each type (native PDF, scanned PDF, printed photo, handwritten, medicine box, password PDF) round-trips correctly in staging.

#### T7.2 — Accuracy tuning pass
**Subtasks:**
- T7.2.1 Run T5.1.4 harness on ≥30 real (anonymized) documents; measure per-path accuracy.
- T7.2.2 Tune: CLIP labels/threshold, adaptive-threshold params, deskew confidence gate, LLM prompt wording — re-run harness after each change.
- T7.2.3 Record final accuracy vs PRD targets (>95% printed, >85% handwritten) in README; if unmet, escalate options (e.g., route more traffic to vision path) before go-live.
**Dependencies:** T7.1.
**AC:** Documented accuracy report meets targets or has a signed-off mitigation plan.

---

### PHASE 8 — Additive Enhancements (post-Phase-4, user-directed)

#### T8.1 — Generalized any-document extraction (additive contract update)
**Goal:** Step 5 must handle ANY document kind — not only medical documents but also passports, ID cards, invoices, certificates, medicine boxes, ultrasounds, etc. For every document the service must additionally report *what kind of document it is*, *a properly written summary* ("this is X; it carries Y"), and *every other detail visible on the document* — all as **new optional keys on `extracted_data`** (CODING_RULES.md Rule 7: additive only; the 6 existing keys are untouched). Requirement recorded from product owner instruction, 2026-07-18 (see TASKS.md §5).
**Subtasks:**
- T8.1.1 Extend `EXTRACTED_DATA_JSON_SCHEMA` (llm_extractor.py) and `ExtractedData` (schemas.py) with three additive nullable keys: `document_type` (string — short label, e.g. "passport", "lab report", "medicine box"), `document_summary` (string — 2–4 properly written sentences describing the document and the information it carries), `additional_details` (array of `{"field": str, "value": str}` objects — every other readable detail: IDs, dates, numbers, addresses, results, issuing authority, …). Strict-mode compliant at every level (all keys `required`, `additionalProperties: false` on every object).
- T8.1.2 Generalize the extraction system prompt (shared by the text and vision paths): identify the document kind, write the summary, fill the 6 legacy medical fields when present (null when absent), capture all other visible details as field/value pairs, never guess or fabricate; an unreadable document returns null for **every** field including the new three (preserves T4.1.5's all-null unreadable signal).
- T8.1.3 Wire T4.1.5's unreadable signal into the orchestrator's success path: `error_message = ALL_FIELDS_NULL_MESSAGE` when `is_all_fields_null(extracted_data)`, else `None` — `status` stays `"success"` per PRD clarification #2. (Closes a discovered gap: T4.1.5 defined the flag + frozen message but T4.3 never wired them, so success payloads always carried `error_message: null` even for all-null results.)
**Dependencies:** T4.1, T4.3 (both DONE).
**AC:** Mocked-OpenAI tests: strict-mode structural checks pass with the 9-key schema (properties == required, `additionalProperties: false` incl. the nested `additional_details` item object); the 6 legacy keys are byte-identical (additive verified); text + vision paths share the new prompt; all-null across all 9 keys → success webhook carries `ALL_FIELDS_NULL_MESSAGE`, any non-null field → `error_message: null`; `ExtractedData` field set still mirrors the JSON schema exactly; full pytest suite green.

#### T8.2 — Multi-language documents + extraction fidelity (additive contract update)
**Goal:** Documents may be in ANY language (Arabic, Kurdish, mixed Arabic+English, …). The service must report the document's *original language* as a new `extracted_data` key and return **every extracted value in English** (faithful translation; proper names transliterated, never substituted). Separately, extracted values must match the document *verbatim* — observed failure: doctor name printed "DR. Abdulrahman Dabagh Clinic" was returned as "Dr. Abdul Imran Dabbagh" (a plausible-looking fabrication). Root causes addressed: (a) PaddleOCR runs `lang='en'` only, so non-Latin/garbled pages yield mangled text that the LLM then "plausibilizes" — a low-confidence OCR result must reroute to vision (which reads Arabic natively); (b) the vision call used default image detail — document text needs `detail: "high"`; (c) the prompt lacked verbatim-transcription rules. Requirement recorded from product owner instruction, 2026-07-19 (see TASKS.md §5).
**Subtasks:**
- T8.2.1 Add additive nullable key `original_language` (string, e.g. `"Arabic"`, `"English"`, `"Arabic and English"`) to `EXTRACTED_DATA_JSON_SCHEMA` + `ExtractedData`; prompt language rules: detect language(s), report them in `original_language`, output every value in English (translate content; transliterate proper names into Latin script exactly — never replace with a similar-sounding name); unreadable documents return null for every field including `original_language` (preserves T4.1.5).
- T8.2.2 OCR quality gate: `extract_text()` returns `OcrResult(text, mean_confidence)` (mean of PaddleOCR per-line recognition confidences; 0.0 when nothing detected); `should_reroute_to_vision(text, mean_confidence=None)` reroutes when text < 20 chars (T3.2.4 rule unchanged) **or** mean confidence < `_MIN_OCR_MEAN_CONFIDENCE = 0.80` — garbled-but-long OCR output (foreign script read as `en`, blurry print) no longer reaches the LLM as trusted text. Internal refactor (Rule 7B); orchestrator threads the result through.
- T8.2.3 Fidelity hardening: prompt gains explicit verbatim-transcription rules (copy names/numbers/IDs character-for-character; never correct, expand, or infer; unclear → null or only the legible part — never a plausible guess); vision `image_url` items gain `"detail": "high"` (better small-text reading; token cost bounded by T4.1.3's existing 1536 px downscale — cost tradeoff recorded in TASKS.md §5).
**Dependencies:** T8.1 (DONE).
**AC:** Schema/mirror tests cover the 10-key shape (legacy 6 still byte-identical); prompt contains the language + verbatim rules and is still shared by both paths; `should_reroute_to_vision` boundary tests: <20 chars → reroute regardless of confidence, ≥20 chars + conf <0.80 → reroute, ≥20 chars + conf ≥0.80 → trusted, confidence omitted → char rule only; vision content items carry `detail: "high"`; full pytest suite green.

#### T8.3 — Vision-path accuracy (original-image passthrough, resolution, MRZ/completeness, per-path model)
**Goal:** Maximize extraction accuracy on real photographed/scanned documents (observed failures: wrong doctor name off a photographed ultrasound header; incomplete passport fields). The vision path was being fed a deliberately degraded image and a weak model. Four levers, all additive/internal:
**Subtasks:**
- T8.3.1 Send the **original color image** to the vision LLM, not `cleaned.vision_ready`. OpenCV cleaning (grayscale + CLAHE + text-based deskew) exists for PaddleOCR; it degrades GPT-4o vision (loses color; the deskew can mis-rotate a photo whose dominant dark pixels aren't text, e.g. an ultrasound cone, smearing small header text). Classification and the PaddleOCR path keep using the cleaned images. Internal (Rule 7B).
- T8.3.2 Raise the vision downscale cap 1536→2048 px (GPT-4o high-detail tiling sweet spot; small text like a clinic header / MRZ line survives) and JPEG quality 85→90. Prompt gains: (a) an **MRZ-authoritative** rule — for passports/IDs, read the machine-readable zone and treat it as the source of truth for name/number/nationality/DOB/sex/expiry; (b) an explicit **completeness** rule — extract every labeled field, anything unmapped goes to `additional_details`. Cost tradeoff (more image tokens/call) recorded in TASKS.md §5.
- T8.3.3 Add optional `OPENAI_VISION_MODEL` env var: a stronger model for the vision path only (unset → falls back to `OPENAI_MODEL`, so default behavior is unchanged). Lets a deployment spend gpt-4o on hard image documents while keeping the cheap model for the text path. Additive optional env var (Rule 7-safe).
**Dependencies:** T8.2 (DONE).
**AC:** `_extract_from_pages` sends the original image to `extract_from_images` (not `vision_ready`) — verified by the existing e2e vision tests staying green after the swap; encode downscale test updated to 2048 px; prompt-rule tests for MRZ + completeness; per-path model tests (vision uses `OPENAI_VISION_MODEL` when set, falls back when unset; text path always `OPENAI_MODEL`); full pytest suite green. *Real-accuracy validation (the actual "reads the ultrasound name / all passport fields correctly" check) belongs to T7.2.1's live run with a real key — this task ships the mechanism; measuring the accuracy gain needs live API calls not available in the dev env.*

#### T8.4 — Non-English field values forced to English + explicit OCR non-English detection (additive)
**Goal:** Fix a reported bug on a bilingual (Arabic+English) PET-CT report: `document_summary` came back in English but `patient_name` came back in **Arabic script**. Every extracted value must be English/Latin (transliterated names, translated words) — consistently, for all fields, not just the summary. Separately, make the "if OCR sees non-English text, route to vision for accurate translation" behavior explicit (user request). Backward-compatible — no schema/key changes; T8.1–T8.3 behavior preserved. Requirement recorded 2026-07-19 (see TASKS.md §5).
**Subtasks:**
- T8.4.1 Prompt fix (root cause): the T8.2.1 "output in English/transliterate names" rule and the T8.2.3 "transcribe EXACTLY as they appear, character by character" rule contradicted each other for a non-Latin name; the model satisfied them inconsistently (Arabic in `patient_name`, English in the summary). Reword so the English/Latin-output rule explicitly applies to EVERY field (patient_name/doctor_name/… included) with a worked transliteration example, and the fidelity rule is scoped to a value's CONTENT (never invent/change), not its script. No schema change.
- T8.4.2 `should_reroute_to_vision()` gains a third trigger: OCR text that is >10% non-Latin alphabetic characters reroutes to vision (`_non_latin_letter_ratio()` ignores digits/punctuation). This is the user's explicit "OCR detects non-English → use vision" signal, complementing T8.2.2's confidence gate (which remains the practical trigger for this en-only PaddleOCR, since it emits garbled low-confidence Latin rather than actual non-Latin script for a foreign page). Signature unchanged → backward compatible.
**Dependencies:** T8.2, T8.3 (both DONE).
**AC:** Prompt-rule test: English/Latin applies to EVERY field incl. `patient_name`, has the transliteration example, accuracy scoped to CONTENT; `should_reroute_to_vision` reroutes substantially-non-Latin text (even at high confidence) but not clean English (incl. numbers/punctuation); `_non_latin_letter_ratio` boundary tests; existing T8.1–T8.3 tests unchanged and green; full pytest suite green. *Real-accuracy validation is T7.2.1's live-key job.*

#### T8.5 — Complex documents: transcription-grounded extraction, RTL tables, mixed-language reroute (additive)
**Goal:** Fix the reported failure class on a bilingual RTL-table report (Arabic header table on an English PET-CT body): doctor name missed entirely, patient name wrong. Two mechanisms: (a) the page is mostly English print, so CLIP can legitimately route it to en-only PaddleOCR, which reads the English body at high mean confidence — no existing gate fires, and the Arabic table (where the names live) never reaches the LLM; (b) on the vision path the model jumps straight to field values, reading RTL cells in the wrong direction and skipping rows. Requirement recorded 2026-07-19 (see TASKS.md §5).
**Subtasks:**
- T8.5.1 **Transcription-grounded extraction** (the "out-of-the-box" technique): new additive nullable key `full_text` as the **FIRST** schema property — OpenAI strict mode generates keys in schema order, so a single call becomes transcribe-then-extract: the model must write out every piece of text on the document (in its ORIGINAL script — the one field exempt from the T8.4.1 Latin-only rule; every table row as a `label: value` line) before filling any extraction field, and is instructed that all other fields must come FROM that transcription. Null on the text path (input text already known). Grounding of this kind is how dedicated document-AI pipelines work, in one LLM call.
- T8.5.2 **RTL rules in the prompt:** Arabic tables read right-to-left — the label is the RIGHTMOST cell, its value the cell to its left; match each value to its own row's label (never swap/drop a row, e.g. اسم الطبيب vs اسم المريض); honorifics (المحترم, السيد, الدكتور) are not part of names; when a name appears in both scripts on one document, cross-check and prefer the Latin spelling.
- T8.5.3 **Mixed-language reroute gate:** `OcrResult` gains `low_confidence_ratio` (fraction of lines below 0.60 confidence; defaulted, backward compatible); `should_reroute_to_vision()` gains a fourth trigger — >20% unreadable lines → vision. Catches the mostly-English-page case the mean-confidence gate structurally misses (many good English lines mask the unreadable Arabic cluster).
**Dependencies:** T8.3, T8.4 (both DONE).
**AC:** `full_text` is nullable and the first property/required entry; prompt carries the transcribe-first + RTL rules; cluster-gate boundary tests (0.50/0.21/0.20/0.00/None); `OcrResult(text, mean)` old constructor shape still valid; all prior T8.x tests unchanged and green; full pytest suite green. *Real-accuracy validation is T7.2.1's live-key job; if this document class still falls short there, the recorded escalation options are a layout-aware document-AI service (Azure Document Intelligence / Google Document AI — native RTL table cell structure) or a second Arabic PaddleOCR engine (see TASKS.md §5).*

#### T8.6 — Role-based patient/subject vs doctor name assignment (prompt, contract-safe)
**Goal:** The name that goes into `patient_name` must be chosen by the *role* a name plays on the document, not by its label or position: the person the document is ABOUT — the patient, subject, or **passport/ID holder** — is the `patient_name`, and the physician/referrer/signer is the `doctor_name`, with the two **never confused**. A passport therefore populates `patient_name` with the holder (previously non-medical documents were told these fields would "usually all be null"). Requirement recorded from product owner instruction, 2026-07-20 (see TASKS.md §5). The product owner asked to also rename the key to `Name`; that would break the frozen `extracted_data` contract (Rule 7), so per the recorded decision only the contract-safe extraction-intelligence half ("Option A") is implemented — the key stays `patient_name`; a rename/mirror-key remains an open, Laravel-sign-off-gated option (TASKS.md §5).
**Subtasks:**
- T8.6.1 Add a **"Name roles"** section to the shared extraction system prompt: `patient_name` = the document's subject/holder (holder's name on a passport or ID; any field labeled "Patient Name"/"Name"/"Patient"/الاسم/اسم المريض; the sole named person on a non-medical document); `doctor_name` = the medical professional (marked "Dr."/الطبيب/اسم الطبيب/"Consultant"/"Referred by", or a physician's signature/stamp); decide by ROLE, never cross the two, and leave a genuinely ambiguous name's field null rather than guess the wrong role. Update field-list item 3 so non-medical documents populate `patient_name` with the holder. Prompt wording only — no schema/key change (Rule 7-safe, additive-by-omission).
**Dependencies:** T8.4, T8.5 (both DONE).
**AC:** Prompt-rule test: the "Name roles" section is present and states the subject/holder (incl. a passport holder) → `patient_name`, the physician → `doctor_name`, and never cross them; no schema/key/signature change (all T8.1–T8.5 tests unchanged and green); full pytest suite green. *Real-accuracy validation (does it actually route a real passport holder to `patient_name` and never mistake a doctor for a patient) is T7.2.1's live-key job — this task ships the prompt mechanism.*

---

## 5. Dependency Graph (Critical Path)

```
T1.1 ──► T1.2 ─────────────────────────────┐
  ├────► T1.3 ──► T2.1 ────────────┐        │
  ├────► T2.2 ──► T3.1 ──► T3.2 ───┤        ▼
  ├────► T4.1 ─────────────────────┼──► T4.3 ──► T5.1 ──► T6.3 ──► T7.1 ──► T7.2
  └────► T4.2 ─────────────────────┘        ▲
T6.1 ──► T6.2 ──────────────────────────────┘ (deploy track, parallel)
T5.2 (parallel with Phase 3–4)
```

**Parallelizable tracks:** (a) T2.2→T3.x, (b) T4.1/T4.2, (c) T6.1/T6.2 deploy scripts, (d) T5.1.1 fixture collection — can all proceed simultaneously after T1.1.

---

## 6. Estimates

| Phase | Tasks | Est. effort |
|---|---|---|
| 1 Scaffold & API | T1.1–T1.3 | 1.5 days |
| 2 PDF & cleaning | T2.1–T2.2 | 2 days |
| 3 CLIP & PaddleOCR | T3.1–T3.2 | 2 days |
| 4 LLM & orchestration | T4.1–T4.3 | 2.5 days |
| 5 Tests & hardening | T5.1–T5.2 | 2 days |
| 6 Deployment | T6.1–T6.3 | 1.5 days |
| 7 Integration & tuning | T7.1–T7.2 | 2 days (elapsed; depends on Laravel team) |
| **Total** | | **~13.5 dev-days** (≈2.5–3 weeks calendar with one developer) |

---

## 7. Risks & Mitigations

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | PaddleOCR + CLIP + 4 workers exceed 8 GB RAM | Service OOM | T6.2.3 memory budget; 2-worker fallback; recommend 16 GB |
| R2 | CLIP misroutes printed↔handwritten | Wrong OCR path, accuracy drop | T3.2.4 low-text reroute to vision; T3.1.3 confidence fallback to vision; T7.2 label tuning |
| R3 | Deskew worsens already-straight images | OCR accuracy drop | T2.2.2 angle/confidence gate before rotating |
| R4 | Laravel webhook down when result ready | Lost result | T4.2.2 retries + T4.2.3 CRITICAL replayable log; Phase-2 dead-letter queue |
| R5 | WhatsApp media URLs expire before processing | Download failure | Laravel should dispatch promptly; `DownloadError` webhook lets Laravel re-trigger |
| R6 | OpenAI cost creep on vision path | Budget | T4.1.3 image downscaling; T4.1.6 token logging; gpt-4o-mini already chosen for cost |
| R7 | Real patient data in test fixtures | Privacy/compliance | T5.1.1 synthetic/anonymized only; T5.2.2 log redaction |
| R8 | Port-80 closure vs certbot renewal | Cert expiry outage | T6.1.2 renewal hook opens/closes 80 transiently |

---

## 8. PRD Clarifications Needed (assumptions made; confirm with product owner)

1. **`cost` field:** Step-5 prompt extracts Cost, but the §4.2 response sample omits it. **Assumed:** include `cost` in `extracted_data`. Laravel must tolerate/consume the extra key.
2. **Blurry-document signaling:** PRD says Laravel flags "Manual Review Required" when all fields are empty. **Assumed:** Python still returns `status:"success"` with all-null fields plus an informative `error_message`; the flagging logic lives in Laravel.
3. **Webhook delivery guarantee:** No persistence layer is specified for the Python side. **Assumed:** retry + CRITICAL replay log is acceptable for Phase 1; a Redis-backed dead-letter queue is deferred.
4. **Page limits:** Step 2 says convert first 3 pages; §6.4 says max 5. **Assumed:** convert ≤5, OCR/analyze first 3 (both constraints honored, constants adjustable).
5. **`medicines` shape:** Sample shows `null`; for medicine boxes a list of `{name, dosage?}` strings is more useful. **Assumed:** nullable array of strings.
6. **Email channel ingestion:** PRD covers WhatsApp webhook detail only. **Assumed:** Laravel normalizes email attachments to the same §4.1 contract — no Python changes needed.

---

## 9. Definition of Done (Project)

- [ ] All Phase 1–6 acceptance criteria pass.
- [ ] `pytest` suite green, ≥80% coverage on `app/pipeline/`.
- [ ] Deployed on the dedicated Ubuntu server: HTTPS, UFW (22/443 only), systemd auto-restart, 4 Gunicorn Uvicorn workers.
- [ ] `/api/v1/process` returns 202 <500 ms under 10-document concurrent load.
- [ ] Every accepted request produces exactly one webhook callback (success or error) — verified by load test.
- [ ] All 7 error paths (§T4.3.3) verified end-to-end with Laravel (T7.1.3).
- [ ] Accuracy report from T7.2 meets PRD targets or has signed-off mitigation.
- [ ] §8 clarifications resolved and this document updated accordingly.
