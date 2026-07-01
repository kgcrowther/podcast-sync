"""
SwimSync downloader.

Downloads audio files from URLs to the local temporary downloads directory.
Handles progress tracking, partial downloads, and cleanup.

This module is responsible for:
- Downloading files from podcast episode URLs
- Reporting download progress via a callback
- Verifying downloaded file size matches expected size
- Cleaning up the downloads directory after a successful sync
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Callable

import requests

from swimsync.models.sync_plan import SyncAction
from swimsync.utils.file_utils import get_downloads_dir, get_exact_file_size, safe_delete
from swimsync.utils.logger import get_logger

log = get_logger(__name__)

# Download chunk size — 1MB at a time
CHUNK_SIZE = 1024 * 1024

# Timeout for establishing a connection (seconds)
CONNECT_TIMEOUT = 15

# Timeout for reading data between chunks (seconds)
READ_TIMEOUT = 60

# Podcast hosts (e.g. Buzzsprout) reject the default python-requests UA with 403.
# Identifying as a podcast client gets through their filters.
_DOWNLOAD_HEADERS = {
    "User-Agent": "SwimSync/1.0 (Podcast sync; macOS)",
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

class DownloadResult:
    """
    The outcome of a single file download attempt.

    Attributes:
        ok: True if the file was downloaded successfully.
        local_path: Path to the downloaded file, or None on failure.
        file_size_bytes: Actual size of the downloaded file in bytes.
        error: Human-readable error message if ok is False, else None.
    """

    def __init__(
        self,
        ok: bool,
        local_path: Optional[Path] = None,
        file_size_bytes: Optional[int] = None,
        error: Optional[str] = None,
    ):
        self.ok = ok
        self.local_path = local_path
        self.file_size_bytes = file_size_bytes
        self.error = error


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def download_file(
    url: str,
    filename: str,
    expected_size_bytes: Optional[int] = None,
    progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
) -> DownloadResult:
    """
    Download a file from a URL to the SwimSync downloads directory.

    Args:
        url: The direct URL to the audio file.
        filename: The filename to save the file as locally.
        expected_size_bytes: If provided, the downloaded file's size will be
                             verified against this value after download.
        progress_callback: Optional callable receiving (bytes_downloaded, total_bytes).
                           total_bytes may be None if Content-Length is unavailable.
                           Called after each chunk is written.

    Returns:
        A DownloadResult describing the outcome.
    """
    downloads_dir = get_downloads_dir()
    local_path = downloads_dir / filename

    log.info(f"Downloading: {filename} from {url}")

    try:
        response = requests.get(
            url,
            stream=True,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            headers=_DOWNLOAD_HEADERS,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        msg = f"Download timed out: {filename}"
        log.error(msg)
        return DownloadResult(ok=False, error=msg)
    except requests.exceptions.ConnectionError:
        msg = f"Connection error while downloading: {filename}"
        log.error(msg)
        return DownloadResult(ok=False, error=msg)
    except requests.exceptions.HTTPError as exc:
        msg = f"HTTP error downloading {filename}: {exc}"
        log.error(msg)
        return DownloadResult(ok=False, error=msg)

    # Get total size from Content-Length header if available
    total_bytes: Optional[int] = None
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            total_bytes = int(content_length)
        except ValueError:
            pass

    # Stream the file to disk
    bytes_downloaded = 0
    try:
        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(bytes_downloaded, total_bytes)
    except OSError as exc:
        msg = f"Failed to write {filename} to disk: {exc}"
        log.error(msg)
        safe_delete(local_path)
        return DownloadResult(ok=False, error=msg)

    # Verify file size if expected size was provided
    actual_size = get_exact_file_size(local_path)

    if expected_size_bytes is not None and actual_size != expected_size_bytes:
        log.warning(
            f"Size mismatch for {filename}: "
            f"expected {expected_size_bytes} bytes, got {actual_size} bytes"
        )
        # We keep the file — size mismatches can occur when RSS feed metadata
        # is inaccurate. The sync engine will use the actual downloaded size.

    log.info(
        f"Downloaded {filename}: {actual_size} bytes "
        f"({_fmt_bytes(actual_size) if actual_size else 'unknown size'})"
    )

    return DownloadResult(
        ok=True,
        local_path=local_path,
        file_size_bytes=actual_size,
    )


def download_action(
    action: SyncAction,
    progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
) -> DownloadResult:
    """
    Download the file described by a SyncAction.

    Handles both remote URLs (podcast episodes) and local file paths
    (drag-and-dropped files, which just need to be copied to downloads).

    Args:
        action: The SyncAction describing the file to download.
        progress_callback: Optional progress callback (see download_file).

    Returns:
        A DownloadResult describing the outcome.
    """
    # Local file — copy to downloads directory instead of downloading
    if action.local_file_path:
        return _copy_local_file(action)

    if not action.source_url:
        msg = f"SyncAction has no source URL or local path: {action.filename}"
        log.error(msg)
        return DownloadResult(ok=False, error=msg)

    return download_file(
        url=action.source_url,
        filename=action.filename,
        expected_size_bytes=action.file_size_bytes,
        progress_callback=progress_callback,
    )


def _copy_local_file(action: SyncAction) -> DownloadResult:
    """
    Copy a local file into the downloads directory.

    Used for drag-and-dropped audio files that don't need to be
    downloaded from the internet.

    Args:
        action: The SyncAction with a local_file_path set.

    Returns:
        A DownloadResult describing the outcome.
    """
    import shutil

    src = Path(action.local_file_path)
    dst = get_downloads_dir() / action.filename

    if not src.exists():
        msg = f"Local file not found: {src}"
        log.error(msg)
        return DownloadResult(ok=False, error=msg)

    try:
        shutil.copy2(str(src), str(dst))
        size = get_exact_file_size(dst)
        log.info(f"Copied local file {src.name} to downloads directory")
        return DownloadResult(ok=True, local_path=dst, file_size_bytes=size)
    except OSError as exc:
        msg = f"Failed to copy local file {src}: {exc}"
        log.error(msg)
        return DownloadResult(ok=False, error=msg)


def cleanup_downloads() -> None:
    """
    Delete all files in the downloads directory.

    Called after a successful sync to free up disk space.
    Logs each deletion and any errors encountered.
    """
    downloads_dir = get_downloads_dir()
    deleted = 0
    errors = 0

    for path in downloads_dir.iterdir():
        if path.is_file():
            if safe_delete(path):
                deleted += 1
            else:
                errors += 1

    log.info(
        f"Downloads cleanup: {deleted} files deleted"
        + (f", {errors} errors" if errors else "")
    )


def get_downloaded_file_path(filename: str) -> Optional[Path]:
    """
    Return the path to a file in the downloads directory if it exists.

    Args:
        filename: The filename to look for.

    Returns:
        Path to the file if it exists, None otherwise.
    """
    path = get_downloads_dir() / filename
    return path if path.exists() else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    """Format a byte count as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"
