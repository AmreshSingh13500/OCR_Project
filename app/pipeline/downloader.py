"""
[MODULE]   app/pipeline/downloader.py
[TASK]     T1.3 — File downloader (Step 2a)
[SUBTASKS] T1.3.3 typed exceptions: DownloadError, FileTooLargeError, UnsupportedFileError
[SUMMARY]  Safely fetches the source file from file_url fully in memory (T1.3.1) and
           identifies its real content type from magic bytes, never trusting the
           extension (T1.3.2) — both land in this file when implemented. This subtask
           defines the typed exceptions raised by both. The orchestrator (T4.3.3) maps
           each to its exact webhook error_message string, so these three stay flat,
           independent Exception subclasses rather than a shared hierarchy — no
           except-order ambiguity when the orchestrator maps them one-to-one.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.3.3
[HISTORY]  2026-07-16  T1.3.3  initial typed exception classes
"""


# [T1.3.3] Raised when the source file cannot be fetched (network error, non-2xx, timeout).
class DownloadError(Exception):
    pass


# [T1.3.3] Raised when the streamed download exceeds MAX_FILE_SIZE_MB.
class FileTooLargeError(Exception):
    pass


# [T1.3.3] Raised when the downloaded content's magic bytes are neither PDF nor image.
class UnsupportedFileError(Exception):
    pass
