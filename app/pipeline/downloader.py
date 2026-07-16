"""
[MODULE]   app/pipeline/downloader.py
[TASK]     T1.3 — File downloader (Step 2a)
[SUBTASKS] T1.3.1 async streaming download into BytesIO with size cap
           T1.3.3 typed exceptions: DownloadError, FileTooLargeError, UnsupportedFileError
[SUMMARY]  Safely fetches the source file from file_url fully in memory. Streams via
           httpx with a hard MAX_FILE_SIZE_MB cap, aborting as soon as the running byte
           count exceeds it rather than buffering the whole oversized body first.
           Magic-byte content detection (T1.3.2) lands in this file too. Nothing is
           ever written to disk.
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.3.1, T1.3.3
[HISTORY]  2026-07-16  T1.3.3  initial typed exception classes
           2026-07-16  T1.3.1  async streaming download with mid-stream size cap
"""

import io

import httpx

from app.config import settings


# [T1.3.3] Raised when the source file cannot be fetched (network error, non-2xx, timeout).
class DownloadError(Exception):
    pass


# [T1.3.3] Raised when the streamed download exceeds MAX_FILE_SIZE_MB.
class FileTooLargeError(Exception):
    pass


# [T1.3.3] Raised when the downloaded content's magic bytes are neither PDF nor image.
class UnsupportedFileError(Exception):
    pass


# [T1.3.1] Streams the response body chunk by chunk, tracking the running size so the
# download aborts (and the connection closes) the moment it exceeds MAX_FILE_SIZE_MB,
# instead of fetching the entire oversized file before checking.
async def download_file(file_url: str) -> io.BytesIO:
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    buffer = io.BytesIO()
    size = 0
    try:
        async with httpx.AsyncClient(timeout=settings.DOWNLOAD_TIMEOUT_S) as client:
            async with client.stream("GET", file_url) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileTooLargeError(
                            f"Download exceeded {settings.MAX_FILE_SIZE_MB} MB limit"
                        )
                    buffer.write(chunk)
    except httpx.HTTPStatusError as exc:
        raise DownloadError(
            f"Download failed with HTTP {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise DownloadError(f"Download failed: {exc}") from exc

    buffer.seek(0)
    return buffer
