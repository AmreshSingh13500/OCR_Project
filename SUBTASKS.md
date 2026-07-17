# SUBTASKS — Execution Tracker (Subtask Level)

**Source of truth:** [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — descriptions below are one-line summaries only; read the plan section for full detail before implementing.
**Task tracker:** [TASKS.md](TASKS.md)
**Last updated:** 2026-07-17

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
| T2.2.2 | Deskew via minAreaRect + confidence gate (skip if \|angle\| < 0.5°) | DONE | 2026-07-17 | `app/pipeline/image_cleaner.py` — `deskew()` + estimators. Found/fixed two bugs vs. the classic reference snippet: (x,y) vs (row,col) coordinate order, and OpenCV ≥4.5's changed minAreaRect angle convention. Empirically validated correction formula against known rotation angles; verified 5° full-page skew → 0.0° residual, already-straight passthrough, blank-image passthrough, dtype/shape, and <2s/image performance (0.14s on A4-sized image). |
| T2.2.3 | CLAHE (clipLimit=2.0, 8×8) on grayscale before thresholding | DONE | 2026-07-17 | `app/pipeline/image_cleaner.py` — `apply_clahe()`. Verified: shape/dtype preserved, contrast (std dev) increases on a synthetic low-contrast image (8.04→21.23), high-contrast image processed without error. |
| T2.2.4 | Adaptive threshold; return both `ocr_ready` (binary) and `vision_ready` (CLAHE) | DONE | 2026-07-17 | `app/pipeline/image_cleaner.py` — `CleanedImage` + `clean_image()` (full grayscale→deskew→CLAHE→threshold pipeline). Verified on an A4-sized synthetic BGR image: shape/dtype valid, ocr_ready strictly binary (0/255), vision_ready retains grayscale detail (130 unique values, not thresholded), runs in 0.09s (<2s AC). |
| T2.2.5 | `DEBUG_SAVE_IMAGES=true` → dump each stage with case_id prefix | DONE | 2026-07-17 | `app/pipeline/image_cleaner.py` — `_debug_save_stage()` + `clean_image(image, case_id=None)`. Writes grayscale/deskewed/CLAHE/threshold stages to gitignored `debug_images/` as `{case_id}_{stage}.png`; no-op when the flag is off (verified no dir created). `case_id` param is new and optional — additive, no existing caller (orchestrator T4.3 not built yet), contract-safe per Rule 7. Verified: flag off → no dir; flag on → 4 readable PNGs with correct shape; `case_id=None` falls back to `unknown_` prefix; `CleanedImage` output unchanged. |

## T3.1 — CLIP router, Step 4a (Phase 3)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T3.1.1 | Load clip-vit-base-patch32 at startup (lifespan), CPU, no_grad | DONE | 2026-07-17 | `app/pipeline/classifier.py` — `load_clip()` called in `app/main.py` lifespan with `torch.no_grad()`. Model/processor stored in `app.state` and module-level globals via `set_clip()`. |
| T3.1.2 | Candidate labels for 4 document classes (tunable in T7.2) | DONE | 2026-07-17 | `app/config.py` — `CLIP_LABELS` list, 4 exact strings per plan §4 T3.1.2. Index 0 is the printed-document label T3.1.3 will route to Branch A; order is load-bearing for that routing check. |
| T3.1.3 | Routing rule: printed → Branch A; else Branch B; score <0.4 → Branch B fallback | DONE | 2026-07-17 | `app/pipeline/classifier.py` — `route_branch()` + `_ROUTING_CONFIDENCE_THRESHOLD=0.4`. Verified: label 0 + high confidence → Branch A; label 0 + confidence just under 0.4 → Branch B; confidence exactly 0.4 → Branch A (>=); labels 1-3 → Branch B regardless of confidence. **Update (2026-07-17, T3.2.4):** `BRANCH_A_PADDLEOCR`/`BRANCH_B_VISION` constants moved from this file to `app/config.py` — ocr_engine.py needed `BRANCH_B_VISION` and importing classifier.py (torch) triggered a real torch/paddlepaddle Windows DLL conflict; see T3.2.4's note. `route_branch()`'s behavior is unchanged, re-verified after the move. |
| T3.1.4 | Classify on `vision_ready` image (CLAHE grayscale → RGB) | DONE | 2026-07-17 | `app/pipeline/classifier.py` — `classify()`: `cv2.cvtColor(GRAY2RGB)` then CLIP zero-shot scoring against `CLIP_LABELS`, returns `(top_label_index, confidence)`. Verified end-to-end with the real downloaded model: synthetic noise image → valid index/confidence range, 0.29s (<1.5s AC); synthetic printed-text image → correctly scores label 0 (printed) at high confidence, routes to `paddleocr` via `route_branch()`. |
| T3.1.5 | Log label + confidence per page with case_id | DONE | 2026-07-17 | `app/pipeline/classifier.py` — `classify()` logs `label=... confidence=...` at INFO on every call. case_id/message_id are picked up automatically from the T1.1.3 logging contextvar, not passed as a parameter. Verified: log line shows `case_id: null` before `bind_case_context()`, and the bound values after. |

## T3.2 — PaddleOCR engine, Step 4b (Phase 3)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T3.2.1 | Init PaddleOCR (angle_cls, en, CPU) once at startup | DONE | 2026-07-17 | `app/pipeline/ocr_engine.py` — `load_paddleocr()` calls `PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False)` exactly per plan; wired into `app/main.py` lifespan after CLIP loading, mirroring the `set_clip`/`get_clip` pattern. paddleocr/paddlepaddle aren't safely installable in the shared global Python env (a first attempt force-downgraded `protobuf`, breaking unrelated tooling — reverted); created an isolated project `.venv` (already gitignored) and verified for real there instead: constructor accepted the plan's exact kwargs with no deprecation errors (confirmed via ppocr's own debug namespace dump), and the full `main.py` lifespan loads both CLIP and PaddleOCR correctly in one run. |
| T3.2.2 | `extract_text(image) -> str` — reading-order line join, debug confidences | DONE | 2026-07-17 | `app/pipeline/ocr_engine.py` — `extract_text()`: runs `ocr.ocr(image, cls=True)`, sorts detected lines by box top-y explicitly (doesn't rely on PaddleOCR's internal order), joins with `\n`, logs each line's text+confidence at DEBUG. Verified in `.venv` with real PaddleOCR: text drawn in scrambled vertical order comes back correctly top-to-bottom; blank image → `""` (PaddleOCR returns `[None]` for no detections, handled explicitly). |
| T3.2.3 | Thread-safety: asyncio.Lock + run_in_executor (never block event loop) | DONE | 2026-07-17 | `app/pipeline/ocr_engine.py` — `extract_text_async()`: module-level `asyncio.Lock` serializes access to the shared PaddleOCR instance, `run_in_executor` offloads the blocking call to a thread. Verified in `.venv` with real PaddleOCR: 4 concurrent calls on 4 distinct images all returned correctly matched, non-interleaved results (`DOC 1`..`DOC 4`); a concurrent 20ms-interval heartbeat coroutine ticked 8 times during the 0.55s run, confirming the event loop was not blocked by the synchronous OCR calls. |
| T3.2.4 | Fallback: <20 chars OCR output → reroute page to vision, log reroute | DONE | 2026-07-17 | `app/pipeline/ocr_engine.py` — `should_reroute_to_vision(text)`: `_MIN_OCR_CHARS=20` threshold, logs a WARNING with char count when rerouting. Verified boundary cases (0, 1, 19, 20, long text). While implementing, found importing `classifier.py` (torch) from `ocr_engine.py` (paddlepaddle) hits a real Windows DLL conflict (paddle-before-torch import breaks torch's shm.dll load, WinError 127) — fixed by moving `BRANCH_A_PADDLEOCR`/`BRANCH_B_VISION` out of classifier.py into `app/config.py` (no ML deps), which both modules now import from instead of each other. Confirmed the underlying native conflict persists even after decoupling (paddle-loaded-anywhere-before-torch still breaks torch), but `main.py`'s existing import order (classifier before ocr_engine) avoids it — added a defensive comment there; likely Windows-only since deploy target is Ubuntu (T6.1). Re-verified full lifespan + all T3.2.1-3 functions post-refactor, no regressions. |

## T4.1 — OpenAI structured extraction, Step 5 (Phase 4)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T4.1.1 | Strict Structured Outputs JSON schema incl. `cost` (PRD clarification #1) | DONE | 2026-07-17 | `app/pipeline/llm_extractor.py` — `EXTRACTED_DATA_JSON_SCHEMA` + `RESPONSE_FORMAT`. Mirrors the ExtractedData shape (patient_name, doctor_name, diagnosis, procedure, cost, medicines), all nullable via `type: [T, "null"]` since OpenAI strict mode requires every key in `required` (no optional keys). `schemas.py` (T1.2.2) doesn't exist yet, so this is the first formal definition of the contract shape — T1.2.2 must mirror it when built. Verified structurally: property set == required set, `additionalProperties: false`, JSON-serializable, field order matches plan. `RESPONSE_FORMAT` is ready to pass unchanged to both T4.1.2 (text) and T4.1.3 (vision). |
| T4.1.2 | Text path: gpt-4o-mini chat completion with extraction system prompt | DONE | 2026-07-17 | `app/pipeline/llm_extractor.py` — `extract_from_text()` + module-level `_client`/`_EXTRACTION_SYSTEM_PROMPT`. Verified in `.venv` (pinned `openai==1.58.1`) with a mocked `chat.completions.create`: correct `model`/`response_format`/messages (exact plan system prompt + input text as user message) passed, JSON response body parsed back into the expected dict. No retry/error handling yet (T4.1.4) and no all-nulls flag (T4.1.5) — bare call by design. |
| T4.1.3 | Vision path: ≤3 base64 JPEGs (quality 85, longest side 1536 px) | DONE | 2026-07-17 | `app/pipeline/llm_extractor.py` — `extract_from_images()` + `_encode_image_base64_jpeg()`. Downscales only when the longest side exceeds 1536px (never upscales), JPEG quality 85, grayscale `vision_ready` images encoded directly (no RGB conversion needed). Truncates defensively to `MAX_PDF_PAGES_OCR` (3). Reuses T4.1.1's `RESPONSE_FORMAT` and T4.1.2's system prompt unchanged. Verified in `.venv`: 2000×1000 image → downscaled to 1536×768 (aspect preserved); 400×300 image → unchanged (no upscale); mocked `chat.completions.create` shows correct model/response_format/messages, 5 input images truncated to 3 `image_url` content items, response parsed correctly. |
| T4.1.4 | Tenacity retries: 3 attempts, exp backoff 2–30 s, retryable errors only | DONE | 2026-07-17 | `app/pipeline/llm_extractor.py` — `LLMError` + `_call_chat_completion()`/`_create_chat_completion()` (tenacity-decorated), reusing `OPENAI_MAX_RETRIES` from `app/config.py`. Retries only `APITimeoutError`/`APIConnectionError`/`RateLimitError`/`InternalServerError` with `wait_exponential(multiplier=1, min=2, max=30)`, `stop_after_attempt(3)`; 401/400 are excluded from the retry set so they propagate unwrapped immediately. `extract_from_text()`/`extract_from_images()` refactored to build a `messages` list and delegate here (T4.1.2/T4.1.3 tags kept, same primary functions). Verified in `.venv` with mocked errors: 500 ×3 → `LLMError` after exactly 3 calls; 401 → propagates as `AuthenticationError` unwrapped after exactly 1 call (no retry); 500 then success → retried once, correct parsed result. Reran T4.1.1–T4.1.3 checks — no regressions. |
| T4.1.5 | All-fields-null flag → success + informative error_message (clarification #2) | DONE | 2026-07-17 | `app/pipeline/llm_extractor.py` — `is_all_fields_null()` + `ALL_FIELDS_NULL_MESSAGE = "All fields empty - possible unreadable document"`. Rule 7 gate checked: this is a *new* frozen error string (PRD clarification #2), not an edit to the existing 7 in T4.3.3's table, so it's additive — exact wording locked from this commit on. Detection only; T4.3 (not built yet) owns pairing this with `status:"success"` in the actual webhook payload. Verified: all-null dict → True; one field filled → False; `medicines: []` (empty list, not None) → False, confirmed not conflated with null; keys match the T4.1.1 schema's 6 properties exactly. |
| T4.1.6 | Log prompt/completion token usage per call | DONE | 2026-07-17 | `app/pipeline/llm_extractor.py` — `_call_chat_completion()` logs `prompt`/`completion`/`total` token counts at INFO on every successful call, right after a call succeeds and before JSON parsing; a raised exception (retries exhausted or non-retryable) carries no `response.usage`, so nothing is logged for failed calls. Verified with a real `openai.types.completion_usage.CompletionUsage` object attached to a mocked response: exact log line `"OpenAI extraction token usage: prompt=123 completion=45 total=168"` emitted on success; confirmed no usage line is logged when a 500 exhausts retries and raises `LLMError`. This was T4.1's last subtask — all 6/6 done. |

## T4.2 — Laravel webhook return, Step 6 (Phase 4)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T4.2.1 | `webhook_client.py` — async POST with Bearer key, WebhookPayload body | DONE | 2026-07-17 | `app/pipeline/webhook_client.py` — `build_webhook_payload()` (exact WebhookPayload key set, first formal definition since schemas.py/T1.2.2 doesn't exist yet, same precedent as T4.1.1) + `send_webhook()` (bare async httpx POST, Bearer `LARAVEL_WEBHOOK_KEY` header, no retry/error handling yet — T4.2.2/T4.2.3). Also added `tests/conftest.py` (new, minimal — sets the 4 required env vars so `Settings()` can instantiate under pytest; not the full plan-§2 conftest.py with sample-file/mock fixtures, which is T5.1.1's deliverable and will extend this file per Rule 3). Verified via committed respx test `tests/test_webhook_client.py`: payload key-set exact match, POST hits `LARAVEL_WEBHOOK_URL` with correct Bearer header and JSON body — both tests green in `.venv`. |
| T4.2.2 | Retries on 5xx/connection only (3×, exp backoff); 4xx = no retry, CRITICAL log | DONE | 2026-07-17 | `app/pipeline/webhook_client.py` — `_RetryableWebhookError` + `_post_webhook_with_retry()` (tenacity: retries only 5xx/connection failures, 3 attempts, exp backoff 2-30s, mirrors T4.1.4's shape) + `send_webhook()` now catches the unwrapped 4xx `HTTPStatusError` and logs CRITICAL immediately (no retry). Verified via `tests/test_webhook_client.py`: 503 then 200 → 2 calls, no CRITICAL log; 401 → exactly 1 call + 1 CRITICAL log mentioning the status code — both green in `.venv` (4/4 tests passing, real exponential backoff elapsed ~2s). |
| T4.2.3 | Retries exhausted → CRITICAL log with full replayable payload JSON | DONE | 2026-07-17 | `app/pipeline/webhook_client.py` — `send_webhook()` now also catches `_RetryableWebhookError` (retries exhausted) and logs CRITICAL with the full payload JSON (`json.dumps(payload)`) for manual replay; delivery failure is fully terminal here (no persistence/dead-letter queue in Phase 1, plan §8-3) and `send_webhook()` never raises to its caller either way. Verified via `tests/test_webhook_client.py::test_send_webhook_5xx_retries_exhausted_logs_critical_with_payload`: 4 queued 503/502/500/500 responses, only 3 consumed (stop_after_attempt=3), exactly 1 CRITICAL log containing the exact payload JSON. T4.2 AC fully covered: all 4 respx scenarios (success, 5xx→retry→success, 5xx×4→CRITICAL+payload, 401→single attempt+CRITICAL) green — 5/5 tests passing in `.venv`. |

## T4.3 — Pipeline orchestrator (Phase 4)

| ID | Summary | Status | Done on | Notes |
|---|---|---|---|---|
| T4.3.1 | `run_pipeline()` wiring Steps 2→6; direct images skip Step 2b | DONE | 2026-07-17 | `app/pipeline/orchestrator.py` — `ProcessRequest` (first formal PRD §4.1 definition, schemas.py/T1.2.2 doesn't exist yet, same precedent as T4.1.1/T4.2.1) + `run_pipeline()` + `_extract_from_pages()` helper. Wires download→detect kind→native-PDF text (skips straight to Step 5) / scanned-PDF pages / direct-image passthrough (skips Step 2b)→clean→classify→OCR-or-vision→LLM→webhook. Mixed-page rule implemented pragmatically (any page needing vision → whole call uses vision with every page's image) since extract_from_text/extract_from_images can't be combined in one call; T4.3.2 owns formally verifying/tagging that rule. No error mapping (T4.3.3) or guaranteed-one-webhook try/except (T4.3.4) yet — bare wiring, same "error handling comes later" pattern as T4.1.2/T4.2.1. Imports classifier (torch) before ocr_engine (paddlepaddle) — same defensive order as main.py (T3.2.4 DLL note). Verified via new `tests/test_pipeline_e2e.py` (4 tests, all collaborators monkeypatched): native PDF → `native_pdf` + extract_from_text, no cleaning/classify called; scanned printed page → `paddleocr` + extract_from_text on OCR output; direct image (handwritten) → `vision_api` + extract_from_images, Step 2b skipped; unsupported content → `UnsupportedFileError` raised. Full suite green in `.venv` (9/9, no regressions, no torch/paddle DLL conflict).
| T4.3.2 | Set processing_path (native_pdf / paddleocr / vision_api; vision wins mixed) | DONE | 2026-07-17 | `app/pipeline/orchestrator.py` — tagged the processing_path decision inside `_extract_from_pages()` (already built as part of T4.3.1's necessary wiring): `paddleocr` only when every page's OCR output was trusted, `vision_api` wins the instant any single page needs vision (originally routed there, or rerouted via T3.2.4's low-yield check) — all pages' images sent together in that case since extract_from_text/extract_from_images can't be combined in one call. No behavior change, formal tagging + verification only. Verified via 3 new tests in `tests/test_pipeline_e2e.py`: mixed pages (one paddleocr + one vision-routed) → `vision_api`, both pages' images sent, extract_from_text never called; mixed via low-OCR-yield reroute (page 2 <20 chars) → `vision_api`; all-paddleocr 2-page set → stays `paddleocr` with concatenated text. Full suite green in `.venv` (12/12, no regressions).
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
