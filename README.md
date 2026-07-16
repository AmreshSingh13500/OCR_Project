# OCR Microservice

AI-powered document ingestion & OCR microservice (Python/FastAPI) for Global Care ERP Phase 1.

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full architecture, requirements,
and task plan — this is the single source of truth for scope. See [TASKS.md](TASKS.md) and
[SUBTASKS.md](SUBTASKS.md) for current execution status, and [CODING_RULES.md](CODING_RULES.md)
for the traceability standard all code in this repo follows.

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
