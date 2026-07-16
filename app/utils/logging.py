"""
[MODULE]   app/utils/logging.py
[TASK]     T1.1 — Project scaffold
[SUBTASKS] T1.1.3 JSON logs with case_id/message_id correlation on every pipeline log line
[SUMMARY]  Structured JSON logging. `configure_logging()` installs a JSON formatter on the
           root logger. `case_id`/`message_id` are carried via contextvars rather than
           passed into every log call: `bind_case_context()` sets them once per pipeline
           run, and every log line emitted during that run picks them up automatically —
           including across the FastAPI BackgroundTask boundary, since each background
           task runs as its own asyncio Task with an independently copied context (no
           cross-request bleed, required by T5.1.3). Never log bearer tokens; medical
           field values are DEBUG-only per CLAUDE.md — enforced by callers, not here.
[PLAN]     IMPLEMENTATION_PLAN.md §2, §4 T1.1 → T1.1.3
[HISTORY]  2026-07-16  T1.1.3  initial JSON formatter + case/message correlation context
"""

import json
import logging
from contextvars import ContextVar
from typing import Optional

from app.config import settings

_case_id_var: ContextVar[Optional[str]] = ContextVar("case_id", default=None)
_message_id_var: ContextVar[Optional[str]] = ContextVar("message_id", default=None)


# [T1.1.3] Every log line is one JSON object; case_id/message_id come from contextvars
# (null outside a bound pipeline run, e.g. startup logs) rather than log call arguments.
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "case_id": _case_id_var.get(),
            "message_id": _message_id_var.get(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


# [T1.1.3] Installs the JSON formatter on the root logger; called once at app startup.
def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]


# [T1.1.3] Binds correlation IDs for the current asyncio task's contextvar scope.
def bind_case_context(case_id: Optional[str], message_id: Optional[str]) -> None:
    _case_id_var.set(case_id)
    _message_id_var.set(message_id)
