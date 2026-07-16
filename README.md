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

Deployment (Ubuntu dedicated server) steps and operational notes land in this README as
Phase 6 (`deploy/`) tasks complete — see IMPLEMENTATION_PLAN.md §4 Phase 6.
