"""
[MODULE]   app/config.py
[TASK]     T1.1 — Project scaffold
[SUBTASKS] T1.1.2 pydantic-settings Settings; fail fast on missing required env vars
[SUMMARY]  Central configuration for the OCR microservice. `Settings` (pydantic-settings
           BaseSettings) loads every env var from IMPLEMENTATION_PLAN.md §3 and is
           instantiated at import time, so a missing required var raises immediately and
           aborts app startup (T1.1 AC) rather than failing later mid-request. Secrets and
           URLs with no safe default (OCR_API_KEY, LARAVEL_WEBHOOK_URL, LARAVEL_WEBHOOK_KEY,
           OPENAI_API_KEY) are required; operational tuning knobs keep the plan's example
           values as defaults. Also holds fixed pipeline constants that are not
           environment-driven. CLIP_LABELS is intentionally NOT defined here yet — its
           content is owned by T3.1.2 and will be appended to this file when that subtask
           runs (CODING_RULES.md Rule 3).
[PLAN]     IMPLEMENTATION_PLAN.md §3 → T1.1.2
[HISTORY]  2026-07-16  T1.1.2  initial Settings class + fixed pipeline constants
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
