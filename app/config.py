"""
[MODULE]   app/config.py
[TASK]     T1.1 — Project scaffold
           T3.1 — CLIP router (Step 4a)
[SUBTASKS] T1.1.2 pydantic-settings Settings; fail fast on missing required env vars
           T3.1.2 CLIP_LABELS candidate labels for zero-shot document classification
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
           itself). Labels are tunable during the T7.2 accuracy pass.
[PLAN]     IMPLEMENTATION_PLAN.md §3 → T1.1.2; §4 → T3.1.2
[HISTORY]  2026-07-16  T1.1.2  initial Settings class + fixed pipeline constants
           2026-07-17  T3.1.2  add CLIP_LABELS constant
"""

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
    MAX_FILE_SIZE_MB: int = 25
    DOWNLOAD_TIMEOUT_S: int = 30
    LOG_LEVEL: str = "INFO"
    DEBUG_SAVE_IMAGES: bool = False


settings = Settings()

# --- Fixed pipeline constants (not environment-driven) — IMPLEMENTATION_PLAN.md §3 ---
NATIVE_PDF_MIN_CHARS = 100      # T2.1.2 native-vs-scanned text length threshold
MAX_PDF_PAGES_CONVERT = 5       # T2.1.3 hard cap on pages rasterized from a PDF
MAX_PDF_PAGES_OCR = 3           # T2.1.2 / T2.1.3 pages actually sent through OCR/LLM
PDF2IMAGE_DPI = 200             # T2.1.3 rasterization DPI
OPENAI_MAX_RETRIES = 3          # T4.1.4 tenacity stop_after_attempt

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
