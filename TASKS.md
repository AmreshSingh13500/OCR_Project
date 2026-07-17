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
| Tasks done | 4 / 17 |
| Subtasks done | 17 / 68 |
| Current phase | 3 |
| Active tasks | — |
| Blocked tasks | — |

---

## 3. Task Board

| Task ID | Title | Phase | Depends On | Subtasks Done/Total | Status | AC ✔ | Started | Finished |
|---|---|---|---|---|---|---|---|---|
| T1.1 | Project scaffold | 1 | — | 4/4 | DONE | yes | 2026-07-16 | 2026-07-16 |
| T1.2 | Auth & API endpoints | 1 | T1.1 | 0/5 | PENDING | no | — | — |
| T1.3 | File downloader (Step 2a) | 1 | T1.1 | 3/3 | DONE | yes | 2026-07-16 | 2026-07-16 |
| T2.1 | Smart PDF detection (Step 2b) | 2 | T1.3 | 5/5 | DONE | yes | 2026-07-16 | 2026-07-17 |
| T2.2 | OpenCV pre-processing (Step 3) | 2 | T1.1 | 5/5 | DONE | yes | 2026-07-17 | 2026-07-17 |
| T3.1 | CLIP router (Step 4a) | 3 | T2.2 | 0/5 | IN_PROGRESS | no | 2026-07-17 | — |
| T3.2 | PaddleOCR engine (Step 4b) | 3 | T3.1 | 0/4 | PENDING | no | — | — |
| T4.1 | OpenAI structured extraction (Step 5) | 4 | T1.1 | 0/6 | PENDING | no | — | — |
| T4.2 | Laravel webhook return (Step 6) | 4 | T1.1 | 0/3 | PENDING | no | — | — |
| T4.3 | Pipeline orchestrator | 4 | T1.3, T2.1, T2.2, T3.1, T3.2, T4.1, T4.2 | 0/5 | PENDING | no | — | — |
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
| — | — | (empty — add one row per blocker, AC failure, or decision) |
