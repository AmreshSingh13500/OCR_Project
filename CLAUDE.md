# OCR Microservice — Project Rules

AI-powered document ingestion & OCR microservice (Python/FastAPI) for Global Care ERP Phase 1.

## Document system (read before any implementation work)

1. **[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)** — single point of truth for ALL requirements. Every unit of work traces to a Task ID (`T<phase>.<task>.<subtask>`). Never implement anything not traceable to a Task ID.
2. **[TASKS.md](TASKS.md)** — task-level tracker. Follow its §1 Execution Protocol exactly: pick a dependency-eligible task → mark `IN_PROGRESS` → execute subtasks → verify AC → mark `DONE`.
3. **[SUBTASKS.md](SUBTASKS.md)** — subtask-level tracker. Subtasks are independent; mark each `DONE` with date + note as it finishes. When the last one finishes, roll the parent task up in TASKS.md.
4. **[CODING_RULES.md](CODING_RULES.md)** — mandatory for ALL generated code.

## Non-negotiable coding rules (full detail in CODING_RULES.md)

- Every source file starts with a tracking header: `[MODULE]`, `[TASK]`, `[SUBTASKS]`, `[SUMMARY]` (2–6 line plain-language description of what the file does), `[PLAN]` pointer, `[HISTORY]` (append-only).
- The function/class implementing a subtask carries its ID tag, e.g. `# [T1.3.2] ...` — searchable, one primary tag per subtask per file.
- Tests reference the subtask/AC they verify in their docstrings.
- A subtask is `DONE` only when: header lists it, code is tagged, tests (if AC requires) pass, and SUBTASKS.md row is updated. A task is `DONE` only when all its subtasks are `DONE` **and** the plan's AC is verified.
- Update both trackers in the same session as the code change — never leave them stale.
- **Backward compatibility (Rule 7):** the external contract is frozen — request schema, `WebhookPayload` keys, the 7 exact `error_message` strings, `processing_path` values, env var names. Updates to these are **additive only** (add optional fields, never rename/remove/retype). Internal code may be refactored freely as long as the full pytest suite is green. Breaking a contract surface requires endpoint versioning + Laravel sign-off recorded in TASKS.md §5.

## Key project constraints (from the plan)

- Files processed in memory (BytesIO) — never written to disk except `DEBUG_SAVE_IMAGES` mode.
- `POST /api/v1/process` returns 202 immediately; pipeline runs as BackgroundTask; results delivered via Laravel webhook (exactly one webhook per accepted request).
- Models (CLIP, PaddleOCR) load once at startup via lifespan — never per request.
- Error messages must match the plan's §T4.3.3 table strings exactly (e.g., `"Password protected document"`).
- Never log bearer tokens; medical field values at DEBUG only. No real patient data in fixtures.
