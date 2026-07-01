"""
Tests for SwimSync downloader (core/downloader.py).

Network-dependent tests are marked @pytest.mark.network and skipped by default.
All other tests use mocking or local files.

Run without network:  pytest tests/test_downloader.py -v -m "not network"
Run all tests:        pytest tests/test_downloader.py -v
"""

from pathlib import Path
from unittest.mock import patch, MagicMock, call
import shutil

import pytest

import swimsync.core.downloader as dl
from swimsync.core.downloader import (
    download_file,
    download_action,
    cleanup_downloads,
    get_downloaded_file_path,
    DownloadResult,
)
from swimsync.models.sync_plan import SyncAction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_downloads(tmp_path, monkeypatch):
    """
    Redirect all downloader file I/O to a temporary directory.
    Runs automatically for every test in this file.
    """
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()

    # Patch get_downloads_dir wherever it is used inside the downloader module
    monkeypatch.setattr(dl, "get_downloads_dir", lambda: downloads_dir)

    # Also patch it in file_utils as imported inside downloader
    import swimsync.utils.file_utils as fu
    monkeypatch.setattr(fu, "DOWNLOADS_DIR", downloads_dir)

    return downloads_dir


def make_mock_response(
    content: bytes = b"audio data",
    status_code: int = 200,
    content_length: bool = True,
) -> MagicMock:
    """Create a mock requests.Response that streams content in chunks."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.raise_for_status.return_value = None

    if content_length:
        mock.headers = {"Content-Length": str(len(content))}
    else:
        mock.headers = {}

    # iter_content yields the whole content as one chunk
    mock.iter_content.return_value = iter([content])
    return mock


def make_action(
    filename: str = "ep1.mp3",
    source_url: str = "https://example.com/ep1.mp3",
    file_size_bytes: int = None,
    local_file_path: str = None,
) -> SyncAction:
    return SyncAction(
        filename=filename,
        title="Test Episode",
        source_label="Test Podcast",
        source_url=source_url,
        file_size_bytes=file_size_bytes,
        local_file_path=local_file_path,
    )


# ---------------------------------------------------------------------------
# download_file — success
# ---------------------------------------------------------------------------

@patch("swimsync.core.downloader.requests.get")
def test_download_file_success(mock_get, tmp_path):
    """download_file returns ok=True and a valid path on success."""
    content = b"x" * 1000
    mock_get.return_value = make_mock_response(content)

    result = download_file("https://example.com/ep.mp3", "ep.mp3")

    assert result.ok is True
    assert result.local_path is not None
    assert result.local_path.exists()
    assert result.file_size_bytes == len(content)


@patch("swimsync.core.downloader.requests.get")
def test_download_file_content_correct(mock_get, tmp_path):
    """download_file writes the correct bytes to disk."""
    content = b"podcast audio content"
    mock_get.return_value = make_mock_response(content)

    result = download_file("https://example.com/ep.mp3", "ep.mp3")

    assert result.local_path.read_bytes() == content


@patch("swimsync.core.downloader.requests.get")
def test_download_file_progress_callback(mock_get, tmp_path):
    """download_file calls the progress callback with bytes downloaded."""
    content = b"x" * 500
    mock_get.return_value = make_mock_response(content)

    progress_calls = []
    def on_progress(downloaded, total):
        progress_calls.append((downloaded, total))

    download_file("https://example.com/ep.mp3", "ep.mp3", progress_callback=on_progress)

    assert len(progress_calls) > 0
    assert progress_calls[-1][0] == len(content)


@patch("swimsync.core.downloader.requests.get")
def test_download_file_no_content_length(mock_get, tmp_path):
    """download_file handles missing Content-Length header gracefully."""
    content = b"audio"
    mock_get.return_value = make_mock_response(content, content_length=False)

    result = download_file("https://example.com/ep.mp3", "ep.mp3")

    assert result.ok is True
    assert result.file_size_bytes == len(content)


@patch("swimsync.core.downloader.requests.get")
def test_download_file_size_mismatch_still_succeeds(mock_get, tmp_path):
    """download_file returns ok=True even when actual size differs from expected."""
    content = b"x" * 1000
    mock_get.return_value = make_mock_response(content)

    # Pass wrong expected size — should warn but not fail
    result = download_file(
        "https://example.com/ep.mp3",
        "ep.mp3",
        expected_size_bytes=9999,
    )

    assert result.ok is True
    assert result.file_size_bytes == 1000


# ---------------------------------------------------------------------------
# download_file — errors
# ---------------------------------------------------------------------------

@patch("swimsync.core.downloader.requests.get")
def test_download_file_timeout(mock_get):
    """download_file returns ok=False on timeout."""
    import requests as req
    mock_get.side_effect = req.exceptions.Timeout()

    result = download_file("https://example.com/ep.mp3", "ep.mp3")

    assert result.ok is False
    assert "timed out" in result.error.lower()


@patch("swimsync.core.downloader.requests.get")
def test_download_file_connection_error(mock_get):
    """download_file returns ok=False on connection error."""
    import requests as req
    mock_get.side_effect = req.exceptions.ConnectionError()

    result = download_file("https://example.com/ep.mp3", "ep.mp3")

    assert result.ok is False
    assert result.error is not None


@patch("swimsync.core.downloader.requests.get")
def test_download_file_http_error(mock_get):
    """download_file returns ok=False on HTTP error."""
    import requests as req
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = req.exceptions.HTTPError("404")
    mock_get.return_value = mock_response

    result = download_file("https://example.com/ep.mp3", "ep.mp3")

    assert result.ok is False
    assert "404" in result.error


@patch("swimsync.core.downloader.requests.get")
def test_download_file_http_403_forbidden(mock_get):
    """download_file returns ok=False with clear message on 403 (e.g. Buzzsprout)."""
    import requests as req
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = req.exceptions.HTTPError(
        "403 Client Error: Forbidden"
    )
    mock_get.return_value = mock_response

    result = download_file("https://www.buzzsprout.com/episode.mp3", "episode.mp3")

    assert result.ok is False
    assert "403" in result.error


@patch("swimsync.core.downloader.requests.get")
def test_download_file_sends_user_agent(mock_get):
    """download_file sends a SwimSync User-Agent so podcast hosts don't reject it."""
    mock_get.return_value = make_mock_response(b"audio data")

    download_file("https://example.com/ep.mp3", "ep.mp3")

    _, kwargs = mock_get.call_args
    user_agent = kwargs.get("headers", {}).get("User-Agent", "")
    assert "SwimSync" in user_agent


# ---------------------------------------------------------------------------
# download_action — URL-based
# ---------------------------------------------------------------------------

@patch("swimsync.core.downloader.requests.get")
def test_download_action_url(mock_get, tmp_path):
    """download_action downloads from source_url when no local path is set."""
    content = b"episode audio"
    mock_get.return_value = make_mock_response(content)

    action = make_action(filename="ep1.mp3", source_url="https://example.com/ep1.mp3")
    result = download_action(action)

    assert result.ok is True
    assert result.local_path.name == "ep1.mp3"


def test_download_action_no_source():
    """download_action returns ok=False when action has neither URL nor local path."""
    action = SyncAction(
        filename="ep.mp3",
        title="Test",
        source_label="Podcast",
        source_url=None,
        local_file_path=None,
    )
    result = download_action(action)
    assert result.ok is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# download_action — local file
# ---------------------------------------------------------------------------

def test_download_action_local_file(tmp_path):
    """download_action copies a local file into downloads directory."""
    src = tmp_path / "myfile.mp3"
    src.write_bytes(b"local audio content")

    action = make_action(
        filename="myfile.mp3",
        source_url=None,
        local_file_path=str(src),
    )
    result = download_action(action)

    assert result.ok is True
    assert result.local_path is not None
    assert result.local_path.read_bytes() == b"local audio content"


def test_download_action_local_file_missing(tmp_path):
    """download_action returns ok=False if the local file does not exist."""
    action = make_action(
        filename="missing.mp3",
        source_url=None,
        local_file_path=str(tmp_path / "nonexistent.mp3"),
    )
    result = download_action(action)
    assert result.ok is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# cleanup_downloads
# ---------------------------------------------------------------------------

def test_cleanup_downloads_removes_files(tmp_path):
    """cleanup_downloads deletes all files in the downloads directory."""
    downloads = dl.get_downloads_dir()
    (downloads / "ep1.mp3").write_bytes(b"audio1")
    (downloads / "ep2.mp3").write_bytes(b"audio2")

    cleanup_downloads()

    remaining = list(downloads.iterdir())
    assert remaining == []


def test_cleanup_downloads_empty_dir(tmp_path):
    """cleanup_downloads handles an already-empty directory without error."""
    cleanup_downloads()  # Should not raise


# ---------------------------------------------------------------------------
# get_downloaded_file_path
# ---------------------------------------------------------------------------

def test_get_downloaded_file_path_exists(tmp_path):
    """get_downloaded_file_path returns path when file exists."""
    downloads = dl.get_downloads_dir()
    (downloads / "ep1.mp3").write_bytes(b"audio")

    path = get_downloaded_file_path("ep1.mp3")
    assert path is not None
    assert path.name == "ep1.mp3"


def test_get_downloaded_file_path_missing(tmp_path):
    """get_downloaded_file_path returns None when file does not exist."""
    assert get_downloaded_file_path("nonexistent.mp3") is None


# ---------------------------------------------------------------------------
# Network test
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_download_real_file(tmp_path):
    """NETWORK: download_file downloads a real small audio file."""
    # This is a tiny public domain audio file used for testing
    url = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"
    result = download_file(url, "test_real.mp3")
    assert result.ok is True
    assert result.file_size_bytes > 0
