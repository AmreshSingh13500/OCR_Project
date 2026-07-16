# CODING RULES — Traceability & Documentation Standard

**Applies to:** every source file generated in this project (Python, shell, config, tests).
**Companion docs:** [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) (requirements) · [TASKS.md](TASKS.md) · [SUBTASKS.md](SUBTASKS.md) (status).
**Core principle:** every line of code must be traceable back to a Task/Subtask ID, and every ID must be findable in code via a plain-text search.

---

## Rule 1 — Mandatory file header (every new file)

Every source file starts with a **tracking header** in that file type's comment syntax. Template (Python docstring shown):

```python
"""
[MODULE]   app/pipeline/downloader.py
[TASK]     T1.3 — File downloader (Step 2a)
[SUBTASKS] T1.3.1 async streaming download into BytesIO with size cap
           T1.3.2 magic-byte content detection (pdf | image | unsupported)
           T1.3.3 typed exceptions: DownloadError, FileTooLargeError, UnsupportedFileError
[SUMMARY]  Safely fetches the source file from file_url fully in memory.
           Streams via httpx with a hard MAX_FILE_SIZE_MB cap (aborts mid-stream),
           identifies the real content type from magic bytes (never trusts the
           extension), and raises typed errors the orchestrator maps to webhook
           error payloads. Nothing is ever written to disk.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.3
[HISTORY]  2026-07-16  T1.3.1–T1.3.3  initial implementation
"""
```

**Field rules:**
- `[TASK]` — the parent task ID + title from TASKS.md. If a file serves multiple tasks, list each on its own line.
- `[SUBTASKS]` — every subtask ID implemented **in this file**, one per line, with a short phrase. Only list subtasks whose code actually lives here.
- `[SUMMARY]` — 2–6 lines, plain language: **what the file does and why it exists**, its role in the pipeline, and any hard constraints (limits, exact strings, ordering). Not a line-by-line narration.
- `[PLAN]` — pointer to the plan section. Never copy requirements into code; link to them.
- `[HISTORY]` — one line per work session that changed the file: `date  subtask-IDs  short description`. Append, never rewrite.

**Comment syntax by file type:**
| File type | Header style |
|---|---|
| `.py` | module docstring `""" ... """` at line 1 (after shebang if any) |
| `.sh` | `#` block after `#!/bin/bash` |
| `.conf`, `.service`, `.env.example` | `#` block at top |
| test files | same as `.py`, but see Rule 4 |

---

## Rule 2 — Subtask tags in code (`[Tx.y.z]`)

The specific function/class/block implementing a subtask carries its ID as a tag, so a text search for the ID lands exactly on the implementation:

```python
# [T1.3.2] Detect real content kind by magic bytes — extension is untrusted input.
def detect_content_kind(data: bytes) -> ContentKind:
    ...
```

- Tag format is always square brackets: `[T1.3.2]` — one consistent, searchable pattern.
- Place the tag on the `def`/`class` (or block) that is the subtask's primary implementation — **one primary tag per subtask per file**. Don't scatter the same tag over every helper line.
- Helpers that only support a tagged function don't need tags.
- Beyond the tag line, follow normal commenting discipline: comment **constraints and non-obvious decisions** (why blockSize=31, why the lock exists), not what the next line does.

## Rule 3 — Files touched by later tasks

When a later task modifies an existing file (e.g., T5.2 SSRF hardening edits `downloader.py`):
1. Add the new task/subtask lines to `[TASK]` / `[SUBTASKS]` in the header.
2. Tag the new code block with its ID (`# [T5.2.4] SSRF guard ...`).
3. Append a `[HISTORY]` line with the date and IDs.
4. Never remove existing IDs — history is append-only.

## Rule 4 — Tests carry the same traceability

- Test file header follows Rule 1, with `[TASK]` = the task under test.
- Each test function's docstring names the subtask or AC it verifies:

```python
def test_oversize_download_aborts_mid_stream():
    """[T1.3.1] AC: download exceeding MAX_FILE_SIZE_MB raises FileTooLargeError."""
```

- AC-level tests (from the plan's **AC:** lines) reference the parent task: `"""[T1.3 AC] happy path, 404, timeout, oversize, wrong type."""`

## Rule 5 — Code completion checklist (gates the tracker)

A subtask may be marked `DONE` in [SUBTASKS.md](SUBTASKS.md) **only when all of these hold**:

- [ ] File header exists and lists the subtask ID (Rule 1)
- [ ] Implementation carries the `[Tx.y.z]` tag (Rule 2)
- [ ] `[SUMMARY]` still accurately describes the file after the change
- [ ] `[HISTORY]` line appended
- [ ] Related test (if the plan's AC demands one) is tagged and passing
- [ ] SUBTASKS.md row updated: status `DONE`, date, note naming the file(s) touched

## Rule 6 — Traceability check (run anytime)

Any subtask ID must be findable in **three places** with one search — e.g. searching `T1.3.2` across the repo must hit:
1. **IMPLEMENTATION_PLAN.md** — the requirement
2. **SUBTASKS.md** — the status row
3. **Source code** — the header line and/or the `[T1.3.2]` tag

If a `DONE` subtask's ID doesn't appear in any source file, the tracker is lying — fix it before continuing.

---

## Quick example — full life of one subtask

1. Start T1.3 → mark `IN_PROGRESS` in TASKS.md.
2. Create `app/pipeline/downloader.py` with the Rule-1 header listing T1.3.1–T1.3.3.
3. Implement `detect_content_kind()` with `# [T1.3.2]` tag.
4. Write `tests/test_downloader.py` — header per Rule 4, test docstrings tagged.
5. Tests pass → run Rule-5 checklist → mark T1.3.2 `DONE` in SUBTASKS.md with date + note `downloader.py`.
6. All three subtasks done → verify T1.3 AC → mark T1.3 `DONE` in TASKS.md, update counters.
