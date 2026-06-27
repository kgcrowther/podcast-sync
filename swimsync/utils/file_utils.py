"""
SwimSync file utilities.

Shared helpers for file operations used across the app:
- Exact byte-size comparison (for sync decisions)
- Supported extension checking (for file type warnings)
- Safe file copy with error handling
- Download directory path resolution
"""

import os
import shutil
from pathlib import Path
from typing import Optional

from swimsync.utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "SwimSync"
DOWNLOADS_DIR = APP_SUPPORT_DIR / "downloads"


def get_downloads_dir() -> Path:
    """
    Return the path to the temporary downloads directory, creating it if needed.

    Returns:
        Path to ~/Library/Application Support/SwimSync/downloads/
    """
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    return DOWNLOADS_DIR


# ---------------------------------------------------------------------------
# File size
# ---------------------------------------------------------------------------

def get_exact_file_size(path: Path | str) -> Optional[int]:
    """
    Return the exact size of a file in bytes, or None if the file does not exist.

    Uses os.path.getsize() which returns exact bytes, not size-on-disk.
    This is the correct value to use for sync comparisons across filesystems.

    Args:
        path: Path to the file.

    Returns:
        Integer byte count, or None if the file is missing.
    """
    try:
        return os.path.getsize(str(path))
    except (FileNotFoundError, OSError):
        return None


def files_match(local_path: Path | str, device_path: Path | str) -> bool:
    """
    Return True if two files are considered identical for sync purposes.

    Comparison is based on filename and exact byte size. If the device file
    has a different byte count (e.g. truncated from a prior interrupted sync),
    it is considered a mismatch and will be re-downloaded and overwritten.

    Args:
        local_path: Path to the reference file (e.g. downloaded copy).
        device_path: Path to the file on the mounted device.

    Returns:
        True if filenames match and byte sizes are identical, False otherwise.
    """
    local_size = get_exact_file_size(local_path)
    device_size = get_exact_file_size(device_path)

    if local_size is None or device_size is None:
        return False

    return (
        Path(local_path).name == Path(device_path).name
        and local_size == device_size
    )


# ---------------------------------------------------------------------------
# Extension checking
# ---------------------------------------------------------------------------

# All extensions that are supported by at least one known Shokz device
ALL_KNOWN_EXTENSIONS = {"mp3", "flac", "wma", "wav", "aac", "m4a", "ape"}


def get_extension(path: Path | str) -> str:
    """
    Return the lowercase file extension without the leading dot.

    Args:
        path: File path or filename.

    Returns:
        Lowercase extension string, e.g. "mp3", "flac", "wav".
    """
    return Path(path).suffix.lstrip(".").lower()


def is_supported_extension(path: Path | str, supported: list[str]) -> bool:
    """
    Return True if the file's extension is in the given supported list.

    Args:
        path: File path or filename to check.
        supported: List of supported extensions for the target device
                   (e.g. ["mp3", "flac", "wav"]).

    Returns:
        True if the extension is supported, False otherwise.
    """
    return get_extension(path) in {ext.lower() for ext in supported}


def is_known_audio_extension(path: Path | str) -> bool:
    """
    Return True if the file extension is recognised by any known Shokz device.

    Use this to show the generic file-type warning when a user adds a file
    whose type is outside all known device support lists.

    Args:
        path: File path or filename to check.

    Returns:
        True if at least one Shokz model supports this extension.
    """
    return get_extension(path) in ALL_KNOWN_EXTENSIONS


# ---------------------------------------------------------------------------
# Safe file copy
# ---------------------------------------------------------------------------

def safe_copy(src: Path | str, dst: Path | str) -> bool:
    """
    Copy a file from src to dst, creating parent directories as needed.

    Logs the operation and any errors. Does not raise on failure — returns
    False instead so the caller can decide how to handle it.

    Args:
        src: Source file path.
        dst: Destination file path.

    Returns:
        True if the copy succeeded, False if an error occurred.
    """
    src = Path(src)
    dst = Path(dst)

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        log.info(f"Copied {src.name} → {dst}")
        return True
    except (OSError, shutil.Error) as exc:
        log.error(f"Failed to copy {src} to {dst}: {exc}")
        return False


def safe_delete(path: Path | str) -> bool:
    """
    Delete a file, logging the operation and any errors.

    Does not raise on failure — returns False instead.

    Args:
        path: Path to the file to delete.

    Returns:
        True if deletion succeeded or file did not exist, False on error.
    """
    path = Path(path)

    if not path.exists():
        log.warning(f"Tried to delete non-existent file: {path}")
        return True

    try:
        path.unlink()
        log.info(f"Deleted {path}")
        return True
    except OSError as exc:
        log.error(f"Failed to delete {path}: {exc}")
        return False
