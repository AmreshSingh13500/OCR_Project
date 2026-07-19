"""
[MODULE]   app/config.py
[TASK]     T1.1 — Project scaffold
           T3.1 — CLIP router (Step 4a)
           T3.2 — PaddleOCR engine (Step 4b)
           T5.2 — Security hardening (app level)
           T8.3 — Vision-path accuracy (optional per-path model)
[SUBTASKS] T1.1.2 pydantic-settings Settings; fail fast on missing required env vars
           T8.3.3 OPENAI_VISION_MODEL — optional stronger model for the vision path only
           T3.1.2 CLIP_LABELS candidate labels for zero-shot document classification
           T3.1.3 / T3.2.4 BRANCH_A_PADDLEOCR / BRANCH_B_VISION frozen branch constants
           T5.2.3 MAX_REQUEST_BODY_BYTES — FastAPI-level request body size cap
           T5.2.4 ALLOWED_FILE_HOSTS — optional file_url host allowlist (SSRF guard)
[SUMMARY]  Central configuration for the OCR microservice. `Settings` (pydantic-settings
           BaseSettings) loads every env var from IMPLEMENTATION_PLAN.md §3 and is
           instantiated at import time, so a missing required var raises immediately and
           aborts app startup (T1.1 AC) rather than failing later mid-request. Secrets and
           URLs with no safe default (OCR_API_KEY, LARAVEL_WEBHOOK_URL, LARAVEL_WEBHOOK_KEY,
           OPENAI_API_KEY) are required; operational tuning knobs keep the plan's example
           values as defaults. Also holds fixed pipeline constants that are not
           environment-driven, including `CLIP_LABELS` — the candidate label strings CLIP
           scores each document image against; index 0 is the "printed" label that routes
           to Branch A, the rest fall through to Branch B (T3.1.3 owns the routing rule
           itself). Labels are tunable during the T7.2 accuracy pass. `BRANCH_A_PADDLEOCR`
           / `BRANCH_B_VISION` reuse the exact frozen `processing_path` contract strings
           (CODING_RULES.md Rule 7) and live here — not in classifier.py or ocr_engine.py —
           specifically so neither module needs to import the other's heavy ML dependency
           (torch vs paddlepaddle) just to reference a branch name; see T3.2.4's history
           note for the concrete bug this avoids. `MAX_REQUEST_BODY_BYTES` (T5.2.3) is the
           FastAPI-level request body size cap enforced by routes.py's
           `enforce_body_size_limit` dependency — a fixed constant (not env-driven) since
           it must stay in lockstep with Nginx's `client_max_body_size 1m` (T6.2.2).
           `ALLOWED_FILE_HOSTS` (T5.2.4) is an optional comma-separated `file_url` host
           allowlist for routes.py's SSRF guard; `None`/unset means "no allowlist
           restriction" — the private/loopback IP check still always applies regardless
           of whether this is configured.
[PLAN]     IMPLEMENTATION_PLAN.md §3 → T1.1.2, T5.2.4; §4 → T3.1.2, T3.1.3, T3.2.4, T5.2.3
[HISTORY]  2026-07-16  T1.1.2  initial Settings class + fixed pipeline constants
           2026-07-17  T3.1.2  add CLIP_LABELS constant
           2026-07-17  T3.2.4  move BRANCH_A_PADDLEOCR/BRANCH_B_VISION here from
                                classifier.py (see classifier.py [HISTORY] for why)
           2026-07-17  T5.2.3  add MAX_REQUEST_BODY_BYTES (1 MB) — fixed constant, not
                                env-driven, mirrors Nginx's future client_max_body_size
                                1m (deploy/nginx.conf, T6.2.2, not yet built)
           2026-07-17  T5.2.4  add ALLOWED_FILE_HOSTS (optional, default None/unset) —
                                new env var per plan §4 T5.2.4's own wording; additive
                                (Rule 7: new optional env var, no rename), also added to
                                IMPLEMENTATION_PLAN.md §3's env var table and
                                .env.example for consistency
           2026-07-19  T8.3.3  add OPENAI_VISION_MODEL (optional, default None -> falls
                                back to OPENAI_MODEL) — additive new optional env var
                                (Rule 7-safe, same precedent as ALLOWED_FILE_HOSTS);
                                also added to plan §3 + .env.example
"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


# [T1.1.2] Instantiating `Settings()` at import time is the fail-fast mechanism: a
# missing required field raises pydantic.ValidationError immediately on `uvicorn
# app.main:app` startup, before any request can be served.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Required — no safe default (secrets / endpoints)
    OCR_API_KEY: str
    LARAVEL_WEBHOOK_URL: str
    LARAVEL_WEBHOOK_KEY: str
    OPENAI_API_KEY: str

    # Operational knobs — default to the plan's example values
    OPENAI_MODEL: str = "gpt-4o-mini"
    # [T8.3.3] Optional stronger model for the VISION path only (photos/scans/handwriting/
    # non-Latin script — where reading accuracy, not cost, is the bottleneck). Unset ->
    # falls back to OPENAI_MODEL, so behavior is unchanged unless explicitly set. Lets a
    # deployment spend gpt-4o on hard image documents while keeping the cheap model for
    # the text path (native PDF / clean OCR), instead of paying gpt-4o prices on every doc.
    OPENAI_VISION_MODEL: Optional[str] = None
    MAX_FILE_SIZE_MB: int = 25
    DOWNLOAD_TIMEOUT_S: int = 30
    LOG_LEVEL: str = "INFO"
    DEBUG_SAVE_IMAGES: bool = False

    # [T5.2.4] Optional SSRF-guard allowlist — comma-separated file_url hosts (e.g.
    # "*.amazonaws.com,media.ultramsg.com"). Unset/empty means no allowlist restriction;
    # the private/loopback IP check in routes.py always applies either way.
    ALLOWED_FILE_HOSTS: Optional[str] = None


settings = Settings()

# --- Fixed pipeline constants (not environment-driven) — IMPLEMENTATION_PLAN.md §3 ---
NATIVE_PDF_MIN_CHARS = 100      # T2.1.2 native-vs-scanned text length threshold
MAX_PDF_PAGES_CONVERT = 5       # T2.1.3 hard cap on pages rasterized from a PDF
MAX_PDF_PAGES_OCR = 3           # T2.1.2 / T2.1.3 pages actually sent through OCR/LLM
PDF2IMAGE_DPI = 200             # T2.1.3 rasterization DPI
OPENAI_MAX_RETRIES = 3          # T4.1.4 tenacity stop_after_attempt

# [T5.2.3] FastAPI-level request body size cap (defense in depth ahead of Nginx's
# client_max_body_size 1m, T6.2.2 — not yet built). The JSON body Laravel sends to
# POST /api/v1/process is inherently small (case_id/message_id/file_url/etc., never the
# file content itself, which is downloaded separately in Step 2a) — 1 MB is a generous
# ceiling against abuse/oversized payloads, matching the plan's exact Nginx figure.
MAX_REQUEST_BODY_BYTES = 1 * 1024 * 1024  # 1 MB

# [T3.1.2] Candidate labels CLIP scores each document image against (zero-shot).
# Index 0 is the sole "printed" label (Branch A / paddleocr); indices 1-3 are the
# handwritten/scan/photo labels that fall through to Branch B (vision_api) per T3.1.3's
# routing rule. Wording is tunable during the T7.2 accuracy pass — order must not change
# without updating T3.1.3's index-based routing check.
CLIP_LABELS = [
    "a printed medical lab report document",
    "a handwritten doctor prescription note",
    "an ultrasound or radiology scan image",
    "a photo of a medicine box or blister pack",
]

# [T3.1.3] Reuses the exact processing_path contract strings (IMPLEMENTATION_PLAN.md §1,
# CODING_RULES.md Rule 7) rather than inventing separate branch names — T4.3.2 sets
# processing_path directly from these values. Deliberately kept in this lightweight
# config module (no torch/paddle deps) rather than classifier.py or ocr_engine.py, so
# neither of those needs to import the other's heavy ML dependency — see T3.2.4.
BRANCH_A_PADDLEOCR = "paddleocr"
BRANCH_B_VISION = "vision_api"
