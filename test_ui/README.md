# Local Test UI

A small browser UI to exercise the OCR pipeline **locally**, watch a **real-time log** of
which library/model each step uses, and see the extracted result — all on one screen.
This is an out-of-plan developer tool: it is **not** part of the traced implementation
plan, never ships to production, lives outside `app/`, and does not touch the frozen
Laravel-facing contract.

## What it does

Production is asynchronous: `POST /api/v1/process` returns `202` and the result is
delivered to Laravel via the Step-6 webhook — nothing comes back inline. To show output
in the browser, this harness:

1. Loads CLIP + PaddleOCR once at startup (like [app/main.py](../app/main.py)'s lifespan).
2. Monkeypatches `orchestrator.send_webhook` to **capture** the `WebhookPayload` in-process.
3. Wraps each pipeline step the orchestrator calls with a logging wrapper, so every step
   announces which library/model it's using (httpx download → PyMuPDF / pdf2image →
   OpenCV cleaning → CLIP classification → PaddleOCR / OpenAI extraction).
4. Captures **all** logs (the narration plus the app's own logs — CLIP confidence, OpenAI
   token usage, PaddleOCR reroute, timings) and **streams them to the browser in real
   time** via Server-Sent Events.

To keep the stream truly live, the actual `run_pipeline` runs in a worker thread (the
synchronous CLIP and OpenAI calls would otherwise freeze the event loop), so log lines
appear as each step happens rather than in one burst at the end.

Two input modes:

- **Upload image / PDF** — the bytes are held in memory and served at a local
  `/_uploads/{id}` URL, so the real Step-2a downloader fetches them (same code path as
  production). Nothing is written to disk.
- **Image URL / JSON** — paste an image URL, or a JSON object shaped like the real
  `/api/v1/process` body (only `file_url` is required).

Because it drives `run_pipeline` directly, the SSRF/https guards in
[app/api/routes.py](../app/api/routes.py) are intentionally bypassed (those only guard the
public HTTP surface) — that's what lets the local upload URL work.

## Prerequisites

- The project virtualenv with all deps installed (`torch`, `paddleocr`, etc.).
- A `.env` at the **project root** with the four required vars from
  [app/config.py](../app/config.py). Only `OPENAI_API_KEY` needs to be **real** — the LLM
  extraction actually calls it. `OCR_API_KEY`, `LARAVEL_WEBHOOK_URL`, and
  `LARAVEL_WEBHOOK_KEY` can be dummy values, since the webhook is captured (not sent) and
  the bearer token is never checked here.

  ```
  copy .env.example .env      # then edit .env and set a real OPENAI_API_KEY
  ```

## Run it

From the **project root**, using the project venv:

```powershell
.venv\Scripts\python.exe -m test_ui.server
```

Then open <http://127.0.0.1:8500>.

- Models load at startup, so the server takes a few seconds to become ready.
- Change host/port with the `TEST_UI_HOST` / `TEST_UI_PORT` env vars.

## Reading the screen

- **Live pipeline log** — colored tags show the source of each line: `Download`, `PDF`,
  `OpenCV`, `CLIP`, `PaddleOCR`, `OpenAI`, `Pipeline`, `Webhook`. Runs at DEBUG level so
  you see full detail (this is a debug tool; noisy third-party HTTP logs are suppressed).
- **status: success** (green) — pipeline completed; the extracted fields are shown.
- **status: error** (red) — the pipeline produced an error payload; `error_message` shows
  which mapped failure occurred (e.g. `"Password protected document"`). This is a correct
  run of the error path, not a harness bug.
- **Harness error** — the request never reached the pipeline (bad JSON, empty upload, etc.).

`processing_path` will be one of `native_pdf`, `paddleocr`, or `vision_api`.
