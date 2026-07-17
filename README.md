# OCR Microservice

AI-powered document ingestion & OCR microservice (Python/FastAPI) for Global Care ERP Phase 1.

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full architecture, requirements,
and task plan — this is the single source of truth for scope. See [TASKS.md](TASKS.md) and
[SUBTASKS.md](SUBTASKS.md) for current execution status, and [CODING_RULES.md](CODING_RULES.md)
for the traceability standard all code in this repo follows.

## System requirements

- **poppler-utils** — required by `pdf2image` (`app/pipeline/pdf_handler.py`) to rasterize
  scanned PDFs; `pdf2image` shells out to poppler's `pdftoppm` binary, which isn't bundled
  with the Python package. Install via `apt-get install poppler-utils` on Ubuntu (see
  `deploy/setup_server.sh`), or via your OS's package manager for local dev. Without it,
  `convert_scanned_pdf()` raises at the first scanned-PDF page.

## Run (local dev)

```bash
python -m venv .venv
source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env        # fill in required values
uvicorn app.main:app --reload
```

## Deployment

The service runs on a dedicated **AlmaLinux 9** server (this recorded project decision
supersedes the plan's "Ubuntu" wording — see TASKS.md §5, 2026-07-17). Deploy artifacts
live in `deploy/`:

- **`deploy/setup_server.sh`** (T6.1) — one-shot provisioning as root on a fresh VM:
  system deps, the `ocrsvc` service user, the project venv, firewalld (22 + 443 only),
  certbot renewal hooks, and model warmup.
- **`deploy/ocr-service.service`** (T6.2.1) — systemd unit running the app under gunicorn
  with 4 uvicorn workers on `127.0.0.1:8000`. Install to `/etc/systemd/system/`, then
  `systemctl enable --now ocr-service`.
- **`deploy/nginx.conf`** (T6.2.2) — 443 TLS reverse proxy to gunicorn. Install to
  `/etc/nginx/conf.d/ocr-service.conf` (replace the `example.com` placeholders first).

Config and secrets are read from `/etc/ocr-service/env` (a systemd `EnvironmentFile`),
created at deploy time from `.env.example` — never committed.

### Worker memory budget (T6.2.3)

Each gunicorn worker loads its own copy of the CLIP router and PaddleOCR engine at startup
(models load once per worker via the lifespan, never per request). Budget roughly
**~1–1.5 GB per worker**, so the default **4 workers use ≈ 4–6 GB RAM** — fits the 8 GB
minimum and is comfortable at 16 GB:

| Server RAM | Recommended `--workers` | Notes |
|---|---|---|
| 8 GB (minimum) | `2` | 2-worker fallback — leaves headroom for the OS + peak request buffers. |
| 16 GB (recommended) | `4` (default) | The value shipped in `deploy/ocr-service.service`. |

**8 GB box → use the 2-worker fallback.** Either change `--workers 4` to `--workers 2` in
`deploy/ocr-service.service`'s `ExecStart` before installing it, or override the shipped unit
with a systemd drop-in (no edit to the packaged file):

```bash
sudo systemctl edit ocr-service
# then set (the empty ExecStart= first is required — systemd replaces rather than appends):
#   [Service]
#   ExecStart=
#   ExecStart=/opt/ocr-service/.venv/bin/gunicorn app.main:app --workers 2 \
#       --worker-class uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000 --timeout 300
sudo systemctl daemon-reload && sudo systemctl restart ocr-service
```

Further deployment validation (external smoke test, load test, log rotation) is Phase 6
T6.3 — see IMPLEMENTATION_PLAN.md §4 Phase 6.

## Accuracy harness

`scripts/accuracy_harness.py` (T5.1.4) runs the `tests/fixtures/` documents through the
real pipeline and reports field-level extraction accuracy against
`tests/fixtures/ground_truth.py`, per IMPLEMENTATION_PLAN.md §4 T5.1.4. It's a manual,
pre-release check — not part of `pytest`/CI — and needs a real `OPENAI_API_KEY` (it makes
real, billed OpenAI calls) and poppler-utils installed (for `scanned.pdf`'s conversion):

```bash
.venv/Scripts/python.exe -m scripts.accuracy_harness
```

T7.2.1 re-runs this same harness against ≥30 real anonymized documents for the accuracy
tuning pass.
