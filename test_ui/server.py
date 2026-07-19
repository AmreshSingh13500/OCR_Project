"""
[MODULE]   test_ui/server.py
[SCOPE]    Out-of-plan local dev tool — NOT traceable to a Task ID. This is a manual
           testing harness (same spirit as the plan's T5.1.4 accuracy harness / T6.3
           smoke test, which are "run manually, not in CI"), living outside the app/
           package so it never ships to production and never touches the frozen
           Laravel-facing contract.
[SUMMARY]  A tiny FastAPI app that lets you exercise the REAL pipeline from a browser and
           watch, in real time, which library/model each step uses. Production is
           asynchronous — POST /api/v1/process returns 202 and the result goes to Laravel
           via the Step-6 webhook — so this harness monkeypatches orchestrator.send_webhook
           to CAPTURE the WebhookPayload in-process, and additionally wraps each pipeline
           step function the orchestrator calls (download/httpx, PyMuPDF, pdf2image,
           OpenCV clean, CLIP classify, PaddleOCR, OpenAI) with a thin logging wrapper so
           every step announces itself. All log records (the narration plus the app's own
           logs — CLIP confidence, OpenAI token usage, etc.) are captured by a handler on
           the root logger and streamed to the browser over Server-Sent Events (SSE).

           Real-time streaming detail: CLIP and OpenAI calls are synchronous and would
           block the event loop, so the actual run_pipeline() is executed in a worker
           thread (its own asyncio loop). The main loop therefore stays free to flush log
           events to the browser as they happen; the log handler hands each record to the
           main loop via call_soon_threadsafe. Only one run executes at a time (a lock
           serializes them) so log routing to the active job is unambiguous.

           Two input modes: (1) upload an image/PDF — bytes held in memory and served at a
           local /_uploads/{id} URL so the real Step-2a downloader fetches them; (2) paste
           an image URL or a ProcessRequest-shaped JSON object. Because it drives
           run_pipeline directly, the SSRF/https guards in routes.py are intentionally
           bypassed (they only guard the public HTTP surface).

           REQUIREMENTS to run:
             * Run from the PROJECT ROOT with the project venv:
                   .venv\\Scripts\\python.exe -m test_ui.server
             * A .env (project root) with the four required vars from config.py. Only
               OPENAI_API_KEY needs to be real; OCR_API_KEY / LARAVEL_WEBHOOK_URL /
               LARAVEL_WEBHOOK_KEY may be dummy values (the webhook is captured, not sent,
               and the bearer token is never checked here).
"""

import os
import sys
import json
import time
import uuid
import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

# --- Make the sibling `app` package importable when run from anywhere -----------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# --- Import the real app modules; give a friendly message if the env isn't set up -----
try:
    from fastapi import FastAPI, File, Request, UploadFile
    from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

    # Keep classifier (torch) imported before ocr_engine (paddlepaddle) — same Windows
    # DLL load-order constraint documented in app/main.py and TASKS.md §5.
    from app.pipeline.classifier import load_clip, set_clip
    from app.pipeline.ocr_engine import load_paddleocr, set_paddleocr

    import app.pipeline.orchestrator as orchestrator
    from app.pipeline.orchestrator import run_pipeline
    from app.schemas import ProcessRequest
    from app.utils.logging import configure_logging
    from app.config import settings, CLIP_LABELS, BRANCH_A_PADDLEOCR
except Exception as exc:  # noqa: BLE001 - any startup failure should be friendly
    sys.stderr.write(
        "\n[test_ui] Could not import the OCR app.\n"
        "  * Run this from the PROJECT ROOT using the project venv, e.g.:\n"
        "        .venv\\Scripts\\python.exe -m test_ui.server\n"
        "  * Make sure a .env exists at the project root with the 4 required vars\n"
        "    (OCR_API_KEY, LARAVEL_WEBHOOK_URL, LARAVEL_WEBHOOK_KEY, OPENAI_API_KEY).\n"
        "    Copy .env.example to .env and fill in a real OPENAI_API_KEY.\n"
        f"\n  Underlying error: {exc!r}\n\n"
    )
    sys.exit(1)

logger = logging.getLogger("test_ui")
# Narration logger for the step wrappers below — captured by the same root handler.
_plog = logging.getLogger("test_ui.pipeline")

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_HOST = os.environ.get("TEST_UI_HOST", "127.0.0.1")
_PORT = int(os.environ.get("TEST_UI_PORT", "8500"))

# In-memory upload store (bytes held only for one run, never written to disk).
_UPLOADS: dict[str, tuple[bytes, str]] = {}
# Captured webhook payloads, keyed by case_id.
_CAPTURED: dict[str, dict] = {}


# ======================================================================================
# Live-log plumbing: per-run job + a root-logger handler that streams records to it.
# ======================================================================================
@dataclass
class Job:
    queue: "asyncio.Queue" = field(default_factory=asyncio.Queue)
    loop: object = None
    task: object = None


_JOBS: dict[str, Job] = {}
_ACTIVE_JOB: Job | None = None
_MAIN_LOOP: object = None
_RUN_LOCK = asyncio.Lock()  # one pipeline run at a time -> unambiguous log routing


# Maps a logger name to a short, friendly "source" tag shown in the UI, so it's obvious
# which library/model produced each line.
def _source_tag(logger_name: str) -> str:
    table = {
        "test_ui.pipeline": "STEP",
        "app.pipeline.classifier": "CLIP",
        "app.pipeline.ocr_engine": "PaddleOCR",
        "app.pipeline.image_cleaner": "OpenCV",
        "app.pipeline.llm_extractor": "OpenAI",
        "app.pipeline.downloader": "Download",
        "app.pipeline.pdf_handler": "PDF",
        "app.pipeline.webhook_client": "Webhook",
        "app.pipeline.orchestrator": "Pipeline",
    }
    if logger_name in table:
        return table[logger_name]
    return logger_name.split(".")[-1]


class _StreamLogHandler(logging.Handler):
    """Pushes every log record to the currently active job's queue, on the main loop."""

    def emit(self, record: logging.LogRecord) -> None:
        job = _ACTIVE_JOB
        loop = _MAIN_LOOP
        if job is None or loop is None:
            return
        try:
            msg = record.getMessage()
            if record.exc_info:
                msg += "\n" + logging.Formatter().formatException(record.exc_info)
            item = {
                "type": "log",
                "t": time.strftime("%H:%M:%S"),
                "level": record.levelname,
                "source": _source_tag(record.name),
                "logger": record.name,
                "message": msg,
            }
            loop.call_soon_threadsafe(job.queue.put_nowait, item)
        except Exception:
            pass  # logging must never raise


# ======================================================================================
# Step narration: wrap the functions orchestrator.py calls so each step announces which
# library/model it uses. orchestrator holds these as module globals (it did
# `from ... import name`), so replacing orchestrator.<name> is enough — same trick as the
# send_webhook capture. Originals are called unchanged; return values are passed through.
# ======================================================================================
_NARRATION_INSTALLED = False


def _install_step_narration() -> None:
    global _NARRATION_INSTALLED
    if _NARRATION_INSTALLED:
        return
    o = orchestrator

    _download_file = o.download_file

    async def download_file(file_url: str):
        _plog.info("Step 2a — Downloading source file via httpx (streaming, %d MB cap)", settings.MAX_FILE_SIZE_MB)
        buf = await _download_file(file_url)
        _plog.info("Downloaded %d bytes into memory (BytesIO) — nothing written to disk", buf.getbuffer().nbytes)
        return buf

    o.download_file = download_file

    _detect = o.detect_content_kind

    def detect_content_kind(data: bytes):
        kind = _detect(data)
        _plog.info("Detected content by magic bytes: %s", kind.value.upper())
        return kind

    o.detect_content_kind = detect_content_kind

    _open_pdf = o.open_pdf

    def open_pdf(data: bytes):
        _plog.info("Step 2b — Opening PDF with PyMuPDF (fitz)")
        return _open_pdf(data)

    o.open_pdf = open_pdf

    _native = o.extract_native_text

    def extract_native_text(doc):
        result = _native(doc)
        if result is not None:
            _plog.info("PyMuPDF found a real text layer (>100 chars) → NATIVE PDF, skipping OCR")
        else:
            _plog.info("PyMuPDF text layer too short → treating as SCANNED PDF (will rasterize)")
        return result

    o.extract_native_text = extract_native_text

    _convert = o.convert_scanned_pdf

    def convert_scanned_pdf(data, page_count):
        _plog.info("Rasterizing PDF pages with pdf2image + poppler at 200 DPI (max 5 pages, first 3 used)")
        return _convert(data, page_count)

    o.convert_scanned_pdf = convert_scanned_pdf

    _clean = o.clean_image

    def clean_image(image, case_id=None):
        _plog.info("Step 3 — OpenCV cleaning: grayscale → deskew → CLAHE → adaptive threshold")
        return _clean(image, case_id=case_id)

    o.clean_image = clean_image

    _classify = o.classify

    def classify(image):
        _plog.info("Step 4a — CLIP (openai/clip-vit-base-patch32) zero-shot classification…")
        label_index, confidence = _classify(image)
        label = CLIP_LABELS[label_index] if 0 <= label_index < len(CLIP_LABELS) else f"#{label_index}"
        _plog.info("CLIP best label: %r (confidence %.2f)", label, confidence)
        return label_index, confidence

    o.classify = classify

    _route = o.route_branch

    def route_branch(label_index, confidence):
        branch = _route(label_index, confidence)
        if branch == BRANCH_A_PADDLEOCR:
            _plog.info("Routing → Branch A (PaddleOCR, local CPU OCR)")
        else:
            _plog.info("Routing → Branch B (OpenAI Vision)")
        return branch

    o.route_branch = route_branch

    _extract_text_async = o.extract_text_async

    async def extract_text_async(image):
        _plog.info("Step 4b — PaddleOCR (CPU) reading printed text…")
        result = await _extract_text_async(image)
        _plog.info(
            "PaddleOCR extracted %d characters (mean confidence %.2f)",
            len(result.text or ""), result.mean_confidence,
        )
        return result

    o.extract_text_async = extract_text_async

    _should_reroute = o.should_reroute_to_vision

    def should_reroute_to_vision(text, mean_confidence=None):
        reroute = _should_reroute(text, mean_confidence)
        if reroute:
            _plog.info("OCR output too short / low-confidence / non-English → rerouting this page to OpenAI Vision")
        return reroute

    o.should_reroute_to_vision = should_reroute_to_vision

    _from_text = o.extract_from_text

    def extract_from_text(text):
        _plog.info("Step 5 — OpenAI %s structured extraction (TEXT path)…", settings.OPENAI_MODEL)
        return _from_text(text)

    o.extract_from_text = extract_from_text

    _from_images = o.extract_from_images

    def extract_from_images(images):
        vision_model = settings.OPENAI_VISION_MODEL or settings.OPENAI_MODEL
        _plog.info(
            "Step 5 — OpenAI %s structured extraction (VISION path, %d image(s), detail=high)…",
            vision_model, len(images),
        )
        return _from_images(images)

    o.extract_from_images = extract_from_images

    _NARRATION_INSTALLED = True


# Capture the webhook instead of POSTing it to Laravel.
async def _capture_webhook(payload: dict) -> None:
    case_id = payload.get("case_id")
    if case_id is not None:
        _CAPTURED[case_id] = payload


orchestrator.send_webhook = _capture_webhook


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _MAIN_LOOP
    configure_logging()

    # Capture everything at DEBUG (this is a debug UI) but tame the noisy libraries so the
    # log panel shows the pipeline's story, not HTTP/transport chatter.
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(_StreamLogHandler())
    for noisy in ("httpx", "httpcore", "openai", "urllib3", "PIL", "paddle", "ppocr",
                  "transformers", "matplotlib", "filelock", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _install_step_narration()
    _MAIN_LOOP = asyncio.get_running_loop()

    logger.info("Loading CLIP model (this can take a moment on first run)...")
    clip_model, clip_processor = load_clip()
    set_clip(clip_model, clip_processor)
    logger.info("CLIP loaded. Loading PaddleOCR engine...")
    set_paddleocr(load_paddleocr())
    logger.info("Models loaded. Test UI ready at http://%s:%d", _HOST, _PORT)
    yield


app = FastAPI(title="OCR Microservice — Local Test UI", lifespan=lifespan)


def _self_upload_url(upload_id: str) -> str:
    connect_host = "127.0.0.1" if _HOST in ("0.0.0.0", "", "::") else _HOST
    return f"http://{connect_host}:{_PORT}/_uploads/{upload_id}"


# Runs the whole pipeline in a worker thread (its own asyncio loop) so synchronous CLIP /
# OpenAI calls never block the main loop — the main loop stays free to stream log events.
async def _execute_job(job_id: str, file_url: str, file_type, file_name, cleanup=None) -> None:
    global _ACTIVE_JOB
    job = _JOBS[job_id]
    async with _RUN_LOCK:
        _ACTIVE_JOB = job
        case_id = f"testui-{uuid.uuid4().hex[:12]}"
        req = ProcessRequest(
            case_id=case_id,
            message_id=f"msg-{uuid.uuid4().hex[:12]}",
            file_url=file_url,
            file_type=file_type,
            file_name=file_name,
            source_channel="test_ui",
        )
        _plog.info("Accepted request — file=%s, starting pipeline", file_name or file_url)
        start = time.monotonic()
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: asyncio.run(run_pipeline(req))
            )
            elapsed_ms = round((time.monotonic() - start) * 1000, 1)
            payload = _CAPTURED.pop(case_id, None)
            job.queue.put_nowait({
                "type": "result",
                "ok": payload is not None,
                "elapsed_ms": elapsed_ms,
                "input": {"file_url": file_url, "file_name": file_name},
                "webhook_payload": payload,
                "error": None if payload is not None else "Pipeline produced no webhook payload (unexpected).",
            })
        except Exception as exc:  # harness-level failure (run_pipeline itself never raises)
            job.queue.put_nowait({"type": "result", "ok": False, "error": repr(exc)})
        finally:
            if cleanup:
                cleanup()
            _ACTIVE_JOB = None
            job.queue.put_nowait({"type": "done"})


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((_STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/_uploads/{upload_id}")
async def serve_upload(upload_id: str) -> Response:
    entry = _UPLOADS.get(upload_id)
    if entry is None:
        return Response(status_code=404)
    data, content_type = entry
    return Response(content=data, media_type=content_type)


@app.get("/stream/{job_id}")
async def stream(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        return Response(status_code=404)

    async def gen():
        try:
            while True:
                item = await job.queue.get()
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("type") == "done":
                    break
        finally:
            _JOBS.pop(job_id, None)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


def _start_job(file_url: str, file_type, file_name, cleanup=None) -> str:
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = Job()
    job = _JOBS[job_id]
    job.task = asyncio.create_task(_execute_job(job_id, file_url, file_type, file_name, cleanup))
    return job_id


@app.post("/run-upload")
async def run_upload(file: UploadFile = File(...)) -> JSONResponse:
    data = await file.read()
    if not data:
        return JSONResponse({"error": "Uploaded file is empty."}, status_code=400)
    upload_id = uuid.uuid4().hex
    _UPLOADS[upload_id] = (data, file.content_type or "application/octet-stream")
    job_id = _start_job(
        _self_upload_url(upload_id),
        file.content_type,
        file.filename,
        cleanup=lambda: _UPLOADS.pop(upload_id, None),
    )
    return JSONResponse({"job_id": job_id})


@app.post("/run-url")
async def run_url(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body is not valid JSON."}, status_code=400)

    if isinstance(body, str):
        file_url, file_type, file_name = body.strip(), None, None
    elif isinstance(body, dict):
        file_url = (body.get("file_url") or "").strip()
        file_type = body.get("file_type")
        file_name = body.get("file_name")
    else:
        return JSONResponse({"error": "JSON must be an object with a file_url, or a URL string."}, status_code=400)

    if not file_url:
        return JSONResponse({"error": "No file_url provided."}, status_code=400)

    job_id = _start_job(file_url, file_type, file_name)
    return JSONResponse({"job_id": job_id})


if __name__ == "__main__":
    import uvicorn

    print(f"[test_ui] Starting local test UI on http://{_HOST}:{_PORT}")
    print("[test_ui] Models load at startup — the first request may wait a few seconds.")
    uvicorn.run(app, host=_HOST, port=_PORT, log_level="warning")
