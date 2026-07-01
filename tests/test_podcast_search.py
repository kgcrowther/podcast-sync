"""
Tests for SwimSync podcast search (core/podcast_search.py).

Network-dependent tests are separated from pure logic tests.
Tests that hit the real iTunes API are marked with @pytest.mark.network
and can be skipped with: pytest -m "not network"

Run all tests:        pytest tests/test_podcast_search.py -v
Run without network:  pytest tests/test_podcast_search.py -v -m "not network"
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from swimsync.core.podcast_search import (
    search_podcasts,
    validate_rss_url,
    _parse_itunes_results,
    PodcastSearchResult,
    SearchOutcome,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_FEED = FIXTURES_DIR / "sample_feed.xml"


# ---------------------------------------------------------------------------
# Fake iTunes API response data
# ---------------------------------------------------------------------------

FAKE_ITUNES_RESULT = {
    "collectionId": 123456,
    "collectionName": "Test Podcast",
    "artistName": "Test Author",
    "feedUrl": "https://example.com/feed.xml",
    "artworkUrl600": "https://example.com/art600.jpg",
    "artworkUrl100": "https://example.com/art100.jpg",
    "genres": ["Technology"],
    "trackCount": 42,
}

FAKE_ITUNES_RESPONSE = {
    "resultCount": 1,
    "results": [FAKE_ITUNES_RESULT],
}


# ---------------------------------------------------------------------------
# _parse_itunes_results (pure logic — no network)
# ---------------------------------------------------------------------------

def test_parse_itunes_results_basic():
    """_parse_itunes_results converts a valid result dict correctly."""
    results = _parse_itunes_results([FAKE_ITUNES_RESULT])
    assert len(results) == 1
    r = results[0]
    assert r.title == "Test Podcast"
    assert r.author == "Test Author"
    assert r.rss_url == "https://example.com/feed.xml"
    assert r.itunes_id == 123456
    assert r.genre == "Technology"
    assert r.episode_count == 42
    assert r.artwork_url == "https://example.com/art600.jpg"


def test_parse_itunes_results_prefers_high_res_artwork():
    """_parse_itunes_results prefers artworkUrl600 over lower resolutions."""
    result = _parse_itunes_results([FAKE_ITUNES_RESULT])
    assert result[0].artwork_url == "https://example.com/art600.jpg"


def test_parse_itunes_results_falls_back_artwork():
    """_parse_itunes_results falls back to artworkUrl100 if 600 is absent."""
    item = {**FAKE_ITUNES_RESULT}
    del item["artworkUrl600"]
    result = _parse_itunes_results([item])
    assert result[0].artwork_url == "https://example.com/art100.jpg"


def test_parse_itunes_results_skips_missing_feed_url():
    """_parse_itunes_results skips entries with no feedUrl."""
    item = {**FAKE_ITUNES_RESULT}
    del item["feedUrl"]
    results = _parse_itunes_results([item])
    assert len(results) == 0


def test_parse_itunes_results_skips_missing_collection_id():
    """_parse_itunes_results skips entries with no collectionId."""
    item = {**FAKE_ITUNES_RESULT}
    del item["collectionId"]
    results = _parse_itunes_results([item])
    assert len(results) == 0


def test_parse_itunes_results_empty_input():
    """_parse_itunes_results returns an empty list for empty input."""
    assert _parse_itunes_results([]) == []


def test_parse_itunes_results_no_genres():
    """_parse_itunes_results handles missing genres gracefully."""
    item = {**FAKE_ITUNES_RESULT, "genres": []}
    result = _parse_itunes_results([item])
    assert result[0].genre is None


def test_parse_itunes_results_multiple():
    """_parse_itunes_results handles multiple results."""
    item2 = {**FAKE_ITUNES_RESULT, "collectionId": 999, "collectionName": "Second Podcast"}
    results = _parse_itunes_results([FAKE_ITUNES_RESULT, item2])
    assert len(results) == 2
    titles = [r.title for r in results]
    assert "Test Podcast" in titles
    assert "Second Podcast" in titles


# ---------------------------------------------------------------------------
# search_podcasts — mocked network
# ---------------------------------------------------------------------------

def make_mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock requests.Response object."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status.return_value = None
    return mock


@patch("swimsync.core.podcast_search.requests.get")
def test_search_podcasts_success(mock_get):
    """search_podcasts returns ok=True and results on a successful API call."""
    mock_get.return_value = make_mock_response(FAKE_ITUNES_RESPONSE)
    outcome = search_podcasts("test podcast")
    assert outcome.ok is True
    assert len(outcome.results) == 1
    assert outcome.results[0].title == "Test Podcast"


@patch("swimsync.core.podcast_search.requests.get")
def test_search_podcasts_empty_query(mock_get):
    """search_podcasts returns ok=False for an empty query without calling API."""
    outcome = search_podcasts("   ")
    assert outcome.ok is False
    assert outcome.error is not None
    mock_get.assert_not_called()


@patch("swimsync.core.podcast_search.requests.get")
def test_search_podcasts_connection_error(mock_get):
    """search_podcasts returns ok=False on a connection error."""
    import requests as req
    mock_get.side_effect = req.exceptions.ConnectionError()
    outcome = search_podcasts("test")
    assert outcome.ok is False
    assert outcome.error is not None


@patch("swimsync.core.podcast_search.requests.get")
def test_search_podcasts_timeout(mock_get):
    """search_podcasts returns ok=False on a timeout."""
    import requests as req
    mock_get.side_effect = req.exceptions.Timeout()
    outcome = search_podcasts("test")
    assert outcome.ok is False
    assert "timed out" in outcome.error.lower()


@patch("swimsync.core.podcast_search.requests.get")
def test_search_podcasts_empty_results(mock_get):
    """search_podcasts returns ok=True with empty list when API finds nothing."""
    mock_get.return_value = make_mock_response({"resultCount": 0, "results": []})
    outcome = search_podcasts("xyzzy nothing matches this")
    assert outcome.ok is True
    assert outcome.results == []


@patch("swimsync.core.podcast_search.requests.get")
def test_search_podcasts_respects_limit(mock_get):
    """search_podcasts passes the limit parameter to the API."""
    mock_get.return_value = make_mock_response(FAKE_ITUNES_RESPONSE)
    search_podcasts("test", limit=5)
    call_params = mock_get.call_args[1]["params"]
    assert call_params["limit"] == 5


@patch("swimsync.core.podcast_search.requests.get")
def test_search_podcasts_caps_limit_at_200(mock_get):
    """search_podcasts caps the limit at 200 regardless of input."""
    mock_get.return_value = make_mock_response(FAKE_ITUNES_RESPONSE)
    search_podcasts("test", limit=500)
    call_params = mock_get.call_args[1]["params"]
    assert call_params["limit"] == 200


# ---------------------------------------------------------------------------
# validate_rss_url
# ---------------------------------------------------------------------------

def _make_feed_result(title="Test Podcast", n_episodes=3):
    """Return a successful FeedResult stub with n_episodes fake episodes."""
    from swimsync.core.rss_client import FeedResult
    from swimsync.models.profile import Episode
    episodes = [
        Episode(
            title=f"Episode {i}",
            url=f"https://example.com/ep{i}.mp3",
            publish_date="2026-01-01",
            duration_seconds=None,
            file_size_bytes=None,
            guid=f"guid-{i}",
        )
        for i in range(1, n_episodes + 1)
    ]
    return FeedResult(ok=True, episodes=episodes, podcast_title=title)


@patch("swimsync.core.rss_client.fetch_feed")
def test_validate_rss_url_valid(mock_fetch):
    """validate_rss_url returns ok=True when fetch_feed succeeds."""
    mock_fetch.return_value = _make_feed_result()

    result = validate_rss_url("https://example.com/feed.xml")

    assert result.ok is True
    assert result.title == "Test Podcast"
    assert result.episode_count == 3
    assert result.most_recent_episode is not None


def test_validate_rss_url_empty():
    """validate_rss_url returns ok=False for an empty URL."""
    result = validate_rss_url("")
    assert result.ok is False
    assert result.error is not None


def test_validate_rss_url_no_scheme():
    """validate_rss_url returns ok=False if URL lacks http/https scheme."""
    result = validate_rss_url("example.com/feed.xml")
    assert result.ok is False
    assert "http" in result.error.lower()


def test_validate_rss_url_rejects_file_scheme():
    """validate_rss_url rejects file:// to prevent local file reads."""
    result = validate_rss_url("file:///etc/passwd")
    assert result.ok is False
    assert "http" in result.error.lower()


def test_validate_rss_url_rejects_ftp_scheme():
    """validate_rss_url rejects ftp:// and other non-http schemes."""
    result = validate_rss_url("ftp://example.com/feed.xml")
    assert result.ok is False
    assert "http" in result.error.lower()


def test_validate_rss_url_rejects_data_scheme():
    """validate_rss_url rejects data: URIs."""
    result = validate_rss_url("data:text/xml,<rss/>")
    assert result.ok is False
    assert "http" in result.error.lower()


def test_validate_rss_url_unreachable():
    """validate_rss_url returns ok=False for an unreachable URL."""
    result = validate_rss_url("https://this.does.not.exist.invalid/feed.xml")
    assert result.ok is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# Network tests (skipped by default in CI)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_search_podcasts_real_api():
    """NETWORK: search_podcasts returns real results from iTunes API."""
    outcome = search_podcasts("serial podcast", limit=5)
    assert outcome.ok is True
    assert len(outcome.results) > 0
    assert all(isinstance(r, PodcastSearchResult) for r in outcome.results)
    assert all(r.rss_url.startswith("http") for r in outcome.results)
