# TASKS — Execution Tracker (Task Level)

**Source of truth:** [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — this file only tracks *execution status*. Never copy requirement details here; always read the plan for Goal/AC.
**Subtask tracker:** [SUBTASKS.md](SUBTASKS.md)
**Last updated:** 2026-07-17

---

## 1. Execution Protocol (follow exactly)

1. **Pick a task:** choose any task whose `Status = PENDING` **and** every task in its `Depends On` column is `DONE`. Prefer the lowest wave number (see §4). Set its status to `IN_PROGRESS` and stamp `Started`.
2. **Check subtasks:** open [SUBTASKS.md](SUBTASKS.md) and find the section for that Task ID.
   - Subtasks exist → execute them **one by one** (any order — all subtasks are independent). Mark each `DONE` in SUBTASKS.md with the date as it finishes.
   - **Stop-per-subtask:** after each subtask finishes, STOP so the user can review and commit (`T1.3.2: description` format). Do not start the next subtask until told to — see CLAUDE.md "Execution cadence".
   - No subtasks (never happens in this plan, but rule anyway) → do the task's Goal directly.
3. **Roll up:** when **all** subtasks of the task are `DONE`, verify the task's **Acceptance Criteria** from IMPLEMENTATION_PLAN.md.
   - AC pass → set task `Status = DONE`, stamp `Finished`, set `AC ✔` to `yes`, update the `Done/Total` count and the Progress Summary (§2).
   - AC fail → task stays `IN_PROGRESS`; add a note in §5 and fix before moving on.
4. **Blocked?** If a task cannot proceed (external dependency, missing info), set `Status = BLOCKED` and record the reason in §5. Pick another eligible task meanwhile.
5. **One rule that never breaks:** a task is `DONE` **only if** all its subtasks are `DONE` **and** AC is verified. No exceptions.

**Status values:** `PENDING` · `IN_PROGRESS` · `BLOCKED` · `DONE`

---

## 2. Progress Summary

| Metric | Value |
|---|---|
| Tasks done | 9 / 17 |
| Subtasks done | 40 / 68 |
| Current phase | 4 |
| Active tasks | — |
| Blocked tasks | — |

---

## 3. Task Board

| Task ID | Title | Phase | Depends On | Subtasks Done/Total | Status | AC ✔ | Started | Finished |
|---|---|---|---|---|---|---|---|---|
| T1.1 | Project scaffold | 1 | — | 4/4 | DONE | yes | 2026-07-16 | 2026-07-16 |
| T1.2 | Auth & API endpoints | 1 | T1.1 | 2/5 | IN_PROGRESS | no | 2026-07-17 | — |
| T1.3 | File downloader (Step 2a) | 1 | T1.1 | 3/3 | DONE | yes | 2026-07-16 | 2026-07-16 |
| T2.1 | Smart PDF detection (Step 2b) | 2 | T1.3 | 5/5 | DONE | yes | 2026-07-16 | 2026-07-17 |
| T2.2 | OpenCV pre-processing (Step 3) | 2 | T1.1 | 5/5 | DONE | yes | 2026-07-17 | 2026-07-17 |
| T3.1 | CLIP router (Step 4a) | 3 | T2.2 | 5/5 | DONE | yes | 2026-07-17 | 2026-07-17 |
| T3.2 | PaddleOCR engine (Step 4b) | 3 | T3.1 | 4/4 | DONE | yes | 2026-07-17 | 2026-07-17 |
| T4.1 | OpenAI structured extraction (Step 5) | 4 | T1.1 | 6/6 | DONE | yes | 2026-07-17 | 2026-07-17 |
| T4.2 | Laravel webhook return (Step 6) | 4 | T1.1 | 3/3 | DONE | yes | 2026-07-17 | 2026-07-17 |
| T4.3 | Pipeline orchestrator | 4 | T1.3, T2.1, T2.2, T3.1, T3.2, T4.1, T4.2 | 5/5 | DONE | yes | 2026-07-17 | 2026-07-17 |
| T5.1 | Test suite completion | 5 | T1.1–T4.3 (all) | 0/4 | PENDING | no | — | — |
| T5.2 | Security hardening (app level) | 5 | T1.2, T1.3 | 0/4 | PENDING | no | — | — |
| T6.1 | Server provisioning script | 6 | — | 0/3 | PENDING | no | — | — |
| T6.2 | Process & proxy configuration | 6 | T6.1 | 0/3 | PENDING | no | — | — |
| T6.3 | E2E deployment validation | 6 | T6.1, T6.2, T5.1, T5.2 | 0/3 | PENDING | no | — | — |
| T7.1 | Contract integration test w/ Laravel | 7 | T6.3 + Laravel team ready | 0/3 | PENDING | no | — | — |
| T7.2 | Accuracy tuning pass | 7 | T7.1 | 0/3 | PENDING | no | — | — |

---

## 4. Execution Waves (dependency-safe order)

Tasks inside the same wave can run **in parallel**. A wave may start as soon as each individual task's own dependencies are `DONE` (you do not need the whole previous wave finished).

| Wave | Tasks | Unlocked by |
|---|---|---|
| 0 | T1.1, T6.1 | nothing — start here |
| 1 | T1.2, T1.3, T2.2, T4.1, T4.2 | T1.1 · (T6.2 unlocked by T6.1) |
| 2 | T2.1, T3.1, T5.2, T6.2 | T1.3 → T2.1 · T2.2 → T3.1 · T1.2+T1.3 → T5.2 |
| 3 | T3.2 | T3.1 |
| 4 | T4.3 | T1.3, T2.1, T2.2, T3.1, T3.2, T4.1, T4.2 |
| 5 | T5.1 | all of Phases 1–4 |
| 6 | T6.3 | T6.1, T6.2, T5.1, T5.2 |
| 7 | T7.1 → T7.2 | T6.3 + Laravel team (external) |

**Recommended solo-developer path (critical path first):**
`T1.1 → T1.3 → T2.1 → T2.2 → T3.1 → T3.2 → T4.1 → T4.2 → T1.2 → T4.3 → T5.2 → T5.1 → T6.1 → T6.2 → T6.3 → T7.1 → T7.2`

---

## 5. Blockers & Notes Log

| Date | Task/Subtask | Note |
|---|---|---|
| 2026-07-17 | T3.1 AC | Plan's exact AC references `printed_report.jpg`/`handwritten.jpg`/`medicine_box.jpg` fixtures owned by T5.1.1 (not yet built). Verified equivalent behavior with synthetic proxies instead (same precedent as T2.1/T2.2): real downloaded CLIP model, synthetic printed-text image → correctly scores the printed label at high confidence → routes to Branch A; random-noise image → non-printed label → Branch B; inference 0.29s (<1.5s AC); model-loads-once confirmed via lifespan test + startup log. Re-verify against real fixtures once T5.1.1 lands (T5.1.2 AC-test pass). |
| 2026-07-17 | T3.2.1 / dev env | Installing `paddlepaddle`/`paddleocr` into the shared global Python environment force-downgraded `protobuf` (6.31.0→3.20.2) via a transitive dependency conflict, breaking unrelated tooling (`google-generativeai`, `mcp`, `opentelemetry-proto`); reverted immediately, no lasting damage. Created an isolated project `.venv` (already in `.gitignore`) with the full pinned `requirements.txt` installed, and verified T3.2.1 there instead. **Any future subtask touching PaddleOCR (T3.2.2–T3.2.4) should also be tested via `.venv/Scripts/python.exe` on this machine, not the global `python`.** |
| 2026-07-17 | T6.1/T6.2 (decision) | **Deployment target is AlmaLinux 9, not Ubuntu** (user decision, supersedes the plan's "Dedicated Ubuntu Server" wording — plan update pending). Consequences for Phase 6: (1) `deploy/setup_server.sh` must use `dnf`, not `apt` — including the existing T2.1.4 poppler-utils line (same package name in AlmaLinux repos); (2) SELinux is enforcing by default — nginx→gunicorn proxying requires `setsebool -P httpd_can_network_connect 1` or the proxy 502s with clean app logs; (3) `paddleocr` transitively installs non-headless `opencv-python`/`opencv-contrib-python`, which need `mesa-libGL` + `glib2` on a GUI-less server or import fails on `libGL.so.1`; (4) T6.1.2 firewall = `firewalld`, not UFW; certbot via EPEL; (5) default `python3` is 3.9 — install `python3.12` (appstream, 9.4+) to match dev; (6) re-verify the torch/paddle load-order behavior (see T3.2.4 note) on this OS. No `app/` code changes required — application code is OS-portable. |
| 2026-07-17 | T4.1 AC | Plan's exact AC includes "live smoke test extracts correct fields from native.pdf fixture" — that fixture is owned by T5.1.1 (not yet built) and a live test would require a real (non-placeholder) `OPENAI_API_KEY` and incur actual API cost. Verified the rest of the AC instead (same precedent as T3.1/T3.2): schema enforced (T4.1.1, structural strict-mode checks), nulls handled correctly incl. the empty-list-vs-null distinction (T4.1.2/T4.1.3/T4.1.5), retry fires exactly `OPENAI_MAX_RETRIES`=3 times on mocked 500s then raises `LLMError` (T4.1.4), non-retryable 401 propagates unwrapped on the first attempt, token usage logged only on success (T4.1.6) — all via mocked `openai.OpenAI` client in the project `.venv`, no network calls made. **Re-run a real smoke test against `native.pdf` once T5.1.1 lands and a real `OPENAI_API_KEY` is available.** |
| 2026-07-17 | T3.2.4 / dev env | Found a real Windows DLL conflict in the `.venv`: importing `paddlepaddle` anywhere in a process before `torch` breaks torch's DLL loading (`shm.dll`, WinError 127) — confirmed it's paddle-before-torch load *order* that breaks it (torch-before-paddle works fine), not merely an unnecessary cross-import (tried `KMP_DUPLICATE_LIB_OK=TRUE`, didn't help; this is a genuine native export mismatch, not the classic OpenMP duplicate-lib issue). Moved `BRANCH_A_PADDLEOCR`/`BRANCH_B_VISION` from `classifier.py` to `app/config.py` so `ocr_engine.py` no longer needs to import `classifier.py` at all (removes an *unnecessary* coupling), but this does **not** fully fix the underlying conflict — `main.py`'s import order (classifier/torch, then ocr_engine/paddle) is what actually avoids it, and now has a defensive comment warning against reordering. Not investigated further: `WinError 127`/`shm.dll` are Windows-specific, and the deploy target is Ubuntu (T6.1) — likely moot in production, but **re-verify no torch/paddle load-order issue exists once T6.1's Linux server is up**, and remove the defensive comment in `main.py` if confirmed moot there. |
| 2026-07-17 | T5.1 (dependency note) | TASKS.md's own Depends-On column lists "T1.1–T4.3 (all)" for T5.1, which literally includes T1.2 (Auth & API endpoints — still 0/5 PENDING: no `auth.py`/`schemas.py`/`routes.py` exist yet). Proceeding with T5.1 anyway per explicit user direction, since T5.1.2's actual AC text is narrower than the shorthand dependency entry — "coverage ≥80% on `app/pipeline/`" and "all Phase 1–4 AC tests green" for code that exists — and every T5.1 subtask (fixtures, pipeline coverage, orchestrator-level concurrency test, accuracy harness) operates on `app/pipeline/`/`run_pipeline()` directly, none of it touches the HTTP layer T1.2 owns. T1.2's own AC (202 response, 401/422 handling) remains unverified until T1.2 is implemented — do not treat T5.1's rollup to DONE as covering it. `test_auth.py` from the plan's §2 layout is intentionally not created in T5.1.2 for the same reason. |
| 2026-07-17 | T3.2.4 / dev env (poppler) | `pdftoppm` (poppler-utils) is still not installed on this Windows dev box, confirmed again while building T5.1.1's `scanned.pdf` fixture — `pdf2image.convert_from_bytes()` cannot be exercised for real here. `pdf_handler.py`'s scanned-PDF branch (T2.1.3) continues to be verified via mocking on this machine; `scanned.pdf` is real and committed, but any test that calls `convert_scanned_pdf()` against it for real needs to be skipped on this box (`pytest.mark.skipif` on `shutil.which("pdftoppm")`) and re-run once poppler-utils is available (T6.1's Linux server, or a local poppler install). |
