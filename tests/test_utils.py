"""
Tests for SwimSync utility modules:
  - utils/logger.py
  - utils/file_utils.py

Run with: pytest tests/test_utils.py -v
"""

import logging
import os
from pathlib import Path

import pytest

from swimsync.utils.logger import get_logger, get_log_file_path
from swimsync.utils.file_utils import (
    get_downloads_dir,
    get_exact_file_size,
    files_match,
    get_extension,
    is_supported_extension,
    is_known_audio_extension,
    safe_copy,
    safe_delete,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_file(path: Path, content: bytes = b"audio data") -> Path:
    """Write a temporary file with the given content and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

def test_get_logger_returns_logger():
    """get_logger returns a Logger instance."""
    log = get_logger("test.module")
    assert isinstance(log, logging.Logger)


def test_get_logger_name():
    """Logger name matches the name passed in."""
    log = get_logger("swimsync.test")
    assert log.name == "swimsync.test"


def test_log_file_path_is_absolute():
    """Log file path is an absolute path ending in swimsync.log."""
    path = get_log_file_path()
    assert path.is_absolute()
    assert path.name == "swimsync.log"


def test_log_dir_created_on_first_use():
    """Calling get_logger creates the log directory."""
    get_logger("swimsync.init_test")
    assert get_log_file_path().parent.exists()


# ---------------------------------------------------------------------------
# get_downloads_dir
# ---------------------------------------------------------------------------

def test_get_downloads_dir_returns_path():
    """get_downloads_dir returns a Path that exists."""
    downloads = get_downloads_dir()
    assert isinstance(downloads, Path)
    assert downloads.exists()


def test_get_downloads_dir_name():
    """Downloads directory is named 'downloads'."""
    assert get_downloads_dir().name == "downloads"


# ---------------------------------------------------------------------------
# get_exact_file_size
# ---------------------------------------------------------------------------

def test_exact_file_size_matches_content(tmp_path):
    """get_exact_file_size returns the correct byte count."""
    content = b"x" * 1234
    f = write_file(tmp_path / "test.mp3", content)
    assert get_exact_file_size(f) == 1234


def test_exact_file_size_missing_file(tmp_path):
    """get_exact_file_size returns None for a missing file."""
    assert get_exact_file_size(tmp_path / "nonexistent.mp3") is None


def test_exact_file_size_accepts_string(tmp_path):
    """get_exact_file_size accepts a string path as well as a Path."""
    f = write_file(tmp_path / "test.mp3", b"hello")
    assert get_exact_file_size(str(f)) == 5


# ---------------------------------------------------------------------------
# files_match
# ---------------------------------------------------------------------------

def test_files_match_identical_content(tmp_path):
    """files_match returns True when both files have the same name and size."""
    content = b"a" * 5000
    src = write_file(tmp_path / "episode.mp3", content)
    dst = write_file(tmp_path / "device" / "episode.mp3", content)
    assert files_match(src, dst) is True


def test_files_match_different_size(tmp_path):
    """files_match returns False when file sizes differ (e.g. truncation)."""
    src = write_file(tmp_path / "episode.mp3", b"a" * 5000)
    dst = write_file(tmp_path / "device" / "episode.mp3", b"a" * 4000)
    assert files_match(src, dst) is False


def test_files_match_missing_device_file(tmp_path):
    """files_match returns False when the device file does not exist."""
    src = write_file(tmp_path / "episode.mp3", b"a" * 1000)
    assert files_match(src, tmp_path / "device" / "episode.mp3") is False


def test_files_match_different_names(tmp_path):
    """files_match returns False when filenames differ."""
    content = b"a" * 1000
    src = write_file(tmp_path / "episode1.mp3", content)
    dst = write_file(tmp_path / "episode2.mp3", content)
    assert files_match(src, dst) is False


# ---------------------------------------------------------------------------
# get_extension
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected", [
    ("episode.mp3", "mp3"),
    ("track.FLAC", "flac"),
    ("audio.M4A", "m4a"),
    ("file.wav", "wav"),
    ("noextension", ""),
])
def test_get_extension(filename, expected):
    """get_extension returns lowercase extension without dot."""
    assert get_extension(filename) == expected


# ---------------------------------------------------------------------------
# is_supported_extension
# ---------------------------------------------------------------------------

def test_supported_extension_match():
    """is_supported_extension returns True for a supported type."""
    assert is_supported_extension("episode.mp3", ["mp3", "flac", "wav"]) is True


def test_supported_extension_no_match():
    """is_supported_extension returns False for an unsupported type."""
    assert is_supported_extension("episode.ape", ["mp3", "flac", "wav"]) is False


def test_supported_extension_case_insensitive():
    """is_supported_extension is case-insensitive."""
    assert is_supported_extension("episode.MP3", ["mp3"]) is True


# ---------------------------------------------------------------------------
# is_known_audio_extension
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "episode.mp3", "track.flac", "audio.wma",
    "file.wav", "podcast.aac", "song.m4a", "track.ape",
])
def test_known_extensions_recognised(filename):
    """All Shokz-supported extensions are recognised."""
    assert is_known_audio_extension(filename) is True


def test_unknown_extension_not_recognised():
    """An unknown extension is not recognised."""
    assert is_known_audio_extension("file.xyz") is False


# ---------------------------------------------------------------------------
# safe_copy
# ---------------------------------------------------------------------------

def test_safe_copy_creates_file(tmp_path):
    """safe_copy successfully copies a file to a new location."""
    src = write_file(tmp_path / "source.mp3", b"audio")
    dst = tmp_path / "dest" / "source.mp3"
    assert safe_copy(src, dst) is True
    assert dst.exists()
    assert dst.read_bytes() == b"audio"


def test_safe_copy_creates_parent_dirs(tmp_path):
    """safe_copy creates destination parent directories if needed."""
    src = write_file(tmp_path / "source.mp3", b"data")
    dst = tmp_path / "a" / "b" / "c" / "source.mp3"
    assert safe_copy(src, dst) is True
    assert dst.exists()


def test_safe_copy_missing_source(tmp_path):
    """safe_copy returns False if the source file does not exist."""
    result = safe_copy(tmp_path / "missing.mp3", tmp_path / "dest.mp3")
    assert result is False


# ---------------------------------------------------------------------------
# safe_delete
# ---------------------------------------------------------------------------

def test_safe_delete_removes_file(tmp_path):
    """safe_delete removes an existing file."""
    f = write_file(tmp_path / "file.mp3", b"data")
    assert safe_delete(f) is True
    assert not f.exists()


def test_safe_delete_missing_file_returns_true(tmp_path):
    """safe_delete returns True (gracefully) if file does not exist."""
    assert safe_delete(tmp_path / "nonexistent.mp3") is True
