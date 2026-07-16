# SUBTASKS — Execution Tracker (Subtask Level)

**Source of truth:** [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — descriptions below are one-line summaries only; read the plan section for full detail before implementing.
**Task tracker:** [TASKS.md](TASKS.md)
**Last updated:** 2026-07-16

## Update Rules

1. All subtasks under one task are **independent** — execute in any order, or in parallel.
2. When you start a subtask, set `Status = IN_PROGRESS`. When finished **and verified**, set `Status = DONE` and stamp the `Done on` date.
3. When the **last** subtask of a task turns `DONE`, go to [TASKS.md](TASKS.md), verify the task's AC, and roll the task status up (protocol §1 there).
4. Use `Notes` for anything the next session needs to know (deviations from plan, files touched, follow-ups). Keep it to one line; longer notes go to the Blockers & Notes Log in TASKS.md.
5. Never delete a row. Never mark `DONE` without the deliverable actually existing in the repo.

**Status values:** `PENDING` · `IN_PROGRESS` · `BLOCKED` · `DONE`

---

## T1.1 — Project scaffold (Phase 1)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T1.1.1 | Create repo layout per plan §2 + `requirements.txt` with pinned deps | DONE | 2026-07-16 | `app/__init__.py`, `app/main.py`, `app/api/__init__.py`, `app/pipeline/__init__.py`, `app/utils/__init__.py`, `requirements.txt`, `README.md`. `main.py` has no dedicated subtask owner elsewhere so its skeleton (FastAPI app + empty lifespan) lives here; T1.2.3/T1.2.4 mount routers, T3.1.1/T3.2.1 populate lifespan model loading later per Rule 3. |
| T1.1.2 | `config.py` via pydantic-settings; fail fast on missing env vars | DONE | 2026-07-16 | `app/config.py`. Required: OCR_API_KEY, LARAVEL_WEBHOOK_URL, LARAVEL_WEBHOOK_KEY, OPENAI_API_KEY (no default — verified ValidationError on missing). Others default to plan's example values. CLIP_LABELS deliberately deferred to T3.1.2. |
| T1.1.3 | `utils/logging.py` — JSON logs with case_id/message_id correlation | DONE | 2026-07-16 | `app/utils/logging.py` (JSON formatter + contextvar-based `bind_case_context`); wired into `app/main.py` lifespan via `configure_logging()`. Verified: JSON output, and no cross-task bleed under concurrent asyncio tasks. |
| T1.1.4 | `.env.example` with every var from plan §3 | DONE | 2026-07-16 | `.env.example`. Verified all 9 var names match `Settings` fields in `app/config.py` exactly (Rule 7 contract check). |

## T1.2 — Auth & API endpoints (Phase 1)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T1.2.1 | `auth.py` — Bearer token dependency, constant-time compare, 401 | PENDING | — | — |
| T1.2.2 | `schemas.py` — ProcessRequest / ExtractedData / WebhookPayload per PRD §4.1–4.2 | PENDING | — | — |
| T1.2.3 | `POST /api/v1/process` — validate → BackgroundTask → 202 immediately | PENDING | — | — |
| T1.2.4 | `GET /health` — 200 with clip_loaded/paddle_loaded flags, unauthenticated | PENDING | — | — |
| T1.2.5 | Validate `file_url` is https; reject invalid URLs with 400 | PENDING | — | — |

## T1.3 — File downloader, Step 2a (Phase 1)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T1.3.1 | `downloader.py` — async httpx GET, streaming into BytesIO, size cap mid-stream | DONE | 2026-07-16 | `app/pipeline/downloader.py` — `download_file()`. Verified with httpx.MockTransport (respx not installed locally): happy path, 404, timeout, oversize all raise/return correctly. |
| T1.3.2 | Magic-byte content detection (pdf / image / unsupported) — never trust extension | DONE | 2026-07-16 | `app/pipeline/downloader.py` — `ContentKind` enum + `detect_content_kind()`. Verified: PDF/JPEG/PNG magic bytes, GIF/text/empty → UNSUPPORTED. |
| T1.3.3 | Typed exceptions: DownloadError, FileTooLargeError, UnsupportedFileError | DONE | 2026-07-16 | `app/pipeline/downloader.py`. Done out of numeric order (before T1.3.1/T1.3.2) since both need to raise these; kept as 3 flat Exception subclasses, no shared hierarchy, to avoid except-order ambiguity in T4.3.3's mapping. |

## T2.1 — Smart PDF detection, Step 2b (Phase 2)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T2.1.1 | PyMuPDF open; password detection → PasswordProtectedError (exact PRD string) | DONE | 2026-07-16 | `app/pipeline/pdf_handler.py` — `open_pdf()`. Verified with real PyMuPDF-generated PDFs: plain PDF opens normally; AES-256-encrypted PDF raises PasswordProtectedError("Password protected document"). |
| T2.1.2 | Text extraction from first 3 pages; >100 chars → NativePdfResult | DONE | 2026-07-16 | `app/pipeline/pdf_handler.py` — `NativePdfResult` + `extract_native_text()`. Verified with real PyMuPDF PDFs: long text (170 chars) → NativePdfResult; short text and blank page → None. |
| T2.1.3 | Scanned branch: pdf2image @200 DPI, convert ≤5 pages, keep first 3 | DONE | 2026-07-16 | `app/pipeline/pdf_handler.py` — `ScannedPdfResult` + `convert_scanned_pdf()`. poppler-utils not available on this Windows dev box (Linux server dep, T2.1.4/T6.1.1) — verified page-limit logic (last_page clamp to 5, truncate to 3) via a mocked `convert_from_bytes`, matching the plan's 60-page AC exactly; module imports cleanly without poppler installed. |
| T2.1.4 | Document poppler-utils system dep in setup script + README | DONE | 2026-07-17 | `deploy/setup_server.sh` (new, minimal — just the poppler-utils install step; `deploy/setup_server.sh` is T6.1.1's primary deliverable and will extend this file per Rule 3, same pattern as `main.py` in T1.1.1) + `README.md` System requirements section. |
| T2.1.5 | Zero-page / corrupt PDFs → CorruptFileError | DONE | 2026-07-17 | `app/pipeline/pdf_handler.py` — `CorruptFileError` + zero-page check in `open_pdf()`. PyMuPDF itself refuses to save a real zero-page PDF (ValueError), so verified the page_count==0 branch via a mocked `fitz.open`; confirmed no regression on a normal 1-page PDF. |

## T2.2 — OpenCV pre-processing, Step 3 (Phase 2)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T2.2.1 | Grayscale conversion (BGR→GRAY) | DONE | 2026-07-17 | `app/pipeline/image_cleaner.py` — `to_grayscale()`. Verified shape (H,W), dtype uint8. |
| T2.2.2 | Deskew via minAreaRect + confidence gate (skip if \|angle\| < 0.5°) | PENDING | — | — |
| T2.2.3 | CLAHE (clipLimit=2.0, 8×8) on grayscale before thresholding | PENDING | — | — |
| T2.2.4 | Adaptive threshold; return both `ocr_ready` (binary) and `vision_ready` (CLAHE) | PENDING | — | — |
| T2.2.5 | `DEBUG_SAVE_IMAGES=true` → dump each stage with case_id prefix | PENDING | — | — |

## T3.1 — CLIP router, Step 4a (Phase 3)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T3.1.1 | Load clip-vit-base-patch32 at startup (lifespan), CPU, no_grad | PENDING | — | — |
| T3.1.2 | Candidate labels for 4 document classes (tunable in T7.2) | PENDING | — | — |
| T3.1.3 | Routing rule: printed → Branch A; else Branch B; score <0.4 → Branch B fallback | PENDING | — | — |
| T3.1.4 | Classify on `vision_ready` image (CLAHE grayscale → RGB) | PENDING | — | — |
| T3.1.5 | Log label + confidence per page with case_id | PENDING | — | — |

## T3.2 — PaddleOCR engine, Step 4b (Phase 3)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T3.2.1 | Init PaddleOCR (angle_cls, en, CPU) once at startup | PENDING | — | — |
| T3.2.2 | `extract_text(image) -> str` — reading-order line join, debug confidences | PENDING | — | — |
| T3.2.3 | Thread-safety: asyncio.Lock + run_in_executor (never block event loop) | PENDING | — | — |
| T3.2.4 | Fallback: <20 chars OCR output → reroute page to vision, log reroute | PENDING | — | — |

## T4.1 — OpenAI structured extraction, Step 5 (Phase 4)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T4.1.1 | Strict Structured Outputs JSON schema incl. `cost` (PRD clarification #1) | PENDING | — | — |
| T4.1.2 | Text path: gpt-4o-mini chat completion with extraction system prompt | PENDING | — | — |
| T4.1.3 | Vision path: ≤3 base64 JPEGs (quality 85, longest side 1536 px) | PENDING | — | — |
| T4.1.4 | Tenacity retries: 3 attempts, exp backoff 2–30 s, retryable errors only | PENDING | — | — |
| T4.1.5 | All-fields-null flag → success + informative error_message (clarification #2) | PENDING | — | — |
| T4.1.6 | Log prompt/completion token usage per call | PENDING | — | — |

## T4.2 — Laravel webhook return, Step 6 (Phase 4)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T4.2.1 | `webhook_client.py` — async POST with Bearer key, WebhookPayload body | PENDING | — | — |
| T4.2.2 | Retries on 5xx/connection only (3×, exp backoff); 4xx = no retry, CRITICAL log | PENDING | — | — |
| T4.2.3 | Retries exhausted → CRITICAL log with full replayable payload JSON | PENDING | — | — |

## T4.3 — Pipeline orchestrator (Phase 4)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T4.3.1 | `run_pipeline()` wiring Steps 2→6; direct images skip Step 2b | PENDING | — | — |
| T4.3.2 | Set processing_path (native_pdf / paddleocr / vision_api; vision wins mixed) | PENDING | — | — |
| T4.3.3 | Error mapping table — 7 exception → error_message strings exactly per plan | PENDING | — | — |
| T4.3.4 | Top-level try/except: every accepted request → exactly one webhook call | PENDING | — | — |
| T4.3.5 | Per-request timing log: total + per-step milliseconds | PENDING | — | — |

## T5.1 — Test suite completion (Phase 5)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T5.1.1 | Assemble 7 test fixtures — synthetic/anonymized only, no real patient data | PENDING | — | — |
| T5.1.2 | Coverage ≥80% on app/pipeline/; all Phase 1–4 AC tests green | PENDING | — | — |
| T5.1.3 | Concurrency test: 8 parallel requests → 8 webhooks, no data bleed | PENDING | — | — |
| T5.1.4 | Accuracy validation harness (field-level accuracy report script) | PENDING | — | — |

## T5.2 — Security hardening (Phase 5)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T5.2.1 | Verify constant-time token compare; no tokens in logs | PENDING | — | — |
| T5.2.2 | Privacy logging: field values DEBUG-only; presence booleans at INFO | PENDING | — | — |
| T5.2.3 | Request body size limit (Nginx 1 MB + FastAPI level) | PENDING | — | — |
| T5.2.4 | SSRF guard: host allowlist env + reject private/loopback IPs post-DNS | PENDING | — | — |

## T6.1 — Server provisioning script (Phase 6)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T6.1.1 | `setup_server.sh` — apt deps, service user, venv, pip install | PENDING | — | — |
| T6.1.2 | UFW: deny incoming, allow 22+443 only; certbot port-80 renewal hooks | PENDING | — | — |
| T6.1.3 | Model warmup script — pre-download CLIP + PaddleOCR weights | PENDING | — | — |

## T6.2 — Process & proxy configuration (Phase 6)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T6.2.1 | systemd unit: gunicorn 4 uvicorn workers, Restart=always, EnvironmentFile | PENDING | — | — |
| T6.2.2 | nginx.conf: 443 SSL, proxy_pass, 1 MB body, 300 s read timeout, headers | PENDING | — | — |
| T6.2.3 | Document 4–6 GB RAM budget + 2-worker fallback for 8 GB boxes in README | PENDING | — | — |

## T6.3 — E2E deployment validation (Phase 6)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T6.3.1 | External smoke test: real docs via public HTTPS → mock-Laravel webhook | PENDING | — | — |
| T6.3.2 | Load test: 10 concurrent docs; 202 <500 ms, all webhooks, RAM stable | PENDING | — | — |
| T6.3.3 | Log rotation configured (journald limits or logrotate) | PENDING | — | — |

## T7.1 — Contract integration test with Laravel (Phase 7)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T7.1.1 | Exchange final bearer tokens both directions (secure channel) | PENDING | — | — |
| T7.1.2 | Joint test: WhatsApp → Laravel → Python → webhook → Case History | PENDING | — | — |
| T7.1.3 | Verify Laravel handles all 7 error_message strings | PENDING | — | — |

## T7.2 — Accuracy tuning pass (Phase 7)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T7.2.1 | Run accuracy harness on ≥30 real anonymized docs; measure per path | PENDING | — | — |
| T7.2.2 | Tune CLIP labels/threshold, threshold params, deskew gate, LLM prompt | PENDING | — | — |
| T7.2.3 | Record final accuracy vs PRD targets in README (or mitigation plan) | PENDING | — | — |
