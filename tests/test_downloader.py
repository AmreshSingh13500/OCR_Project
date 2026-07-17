"""
[MODULE]   tests/test_downloader.py
[TASK]     T1.3 — File downloader (Step 2a)
           T5.1 — Test suite completion
[SUBTASKS] T1.3.1 AC: happy path, 404, timeout, oversize (via respx)
           T1.3.2 AC: magic-byte content_kind detection (pdf/image/unsupported)
           T5.1.2 backfilled committed pytest coverage for T1.3 (previously verified
                  ad hoc against httpx.MockTransport per SUBTASKS.md, respx wasn't
                  installed locally at the time)
[SUMMARY]  respx-mocked tests for downloader.py's download_file()/detect_content_kind().
           Covers the plan's exact T1.3 AC list: happy path, 404, timeout, oversize
           (via a monkeypatched MAX_FILE_SIZE_MB so the test doesn't need to transfer
           real megabytes), and content-kind detection for every magic-byte case
           (PDF, JPEG, PNG, and unsupported: GIF/plain-text/empty).
[PLAN]     IMPLEMENTATION_PLAN.md §4 → T1.3.1, T1.3.2; §5 → T5.1.2
[HISTORY]  2026-07-17  T5.1.2  initial committed test file (backfills T1.3's ad hoc
                                verification with real respx-mocked tests)
"""

import httpx
import pytest
import respx

from app.config import settings
from app.pipeline.downloader import (
    ContentKind,
    DownloadError,
    FileTooLargeError,
    detect_content_kind,
    download_file,
)

_URL = "https://files.test/doc.pdf"


@pytest.mark.asyncio
async def test_download_file_happy_path():
    """[T1.3.1] AC: happy path — a normal 200 response is fully read into a BytesIO."""
    content = b"%PDF-1.4 fake pdf body"
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, content=content))
        buffer = await download_file(_URL)
        assert buffer.read() == content


@pytest.mark.asyncio
async def test_download_file_404_raises_download_error():
    """[T1.3.1] AC: a 404 response raises DownloadError."""
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(404))
        with pytest.raises(DownloadError):
            await download_file(_URL)


@pytest.mark.asyncio
async def test_download_file_timeout_raises_download_error():
    """[T1.3.1] AC: a transport timeout raises DownloadError."""
    with respx.mock:
        respx.get(_URL).mock(side_effect=httpx.TimeoutException("timed out"))
        with pytest.raises(DownloadError):
            await download_file(_URL)


@pytest.mark.asyncio
async def test_download_file_oversize_raises_file_too_large_error(monkeypatch):
    """[T1.3.1] AC: streamed content exceeding MAX_FILE_SIZE_MB raises FileTooLargeError."""
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
    oversized_content = b"x" * (2 * 1024 * 1024)
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, content=oversized_content))
        with pytest.raises(FileTooLargeError):
            await download_file(_URL)


@pytest.mark.parametrize(
    "data, expected",
    [
        (b"%PDF-1.7 rest of a real pdf", ContentKind.PDF),
        (b"\xff\xd8\xff\xe0 jpeg bytes", ContentKind.IMAGE),
        (b"\x89PNG\r\n\x1a\n rest of png", ContentKind.IMAGE),
        (b"GIF89a not a supported type", ContentKind.UNSUPPORTED),
        (b"plain text file, not a document", ContentKind.UNSUPPORTED),
        (b"", ContentKind.UNSUPPORTED),
    ],
)
def test_detect_content_kind(data, expected):
    """[T1.3.2] AC: magic bytes decide content kind — extension/file_type is never trusted."""
    assert detect_content_kind(data) == expected
