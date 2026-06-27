"""
Tests for SwimSync RSS client (core/rss_client.py).

Uses local XML fixture files instead of hitting the internet,
keeping tests fast, reliable, and network-independent.

Run with: pytest tests/test_rss_client.py -v
"""

from pathlib import Path

import pytest

from swimsync.core.rss_client import (
    fetch_feed,
    build_podcast_from_feed,
    _parse_duration,
    _check_stale,
    STALE_FEED_DAYS,
)
from swimsync.models.profile import Episode

# ---------------------------------------------------------------------------
# Paths to fixture files
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_FEED = FIXTURES_DIR / "sample_feed.xml"
STALE_FEED = FIXTURES_DIR / "stale_feed.xml"


# ---------------------------------------------------------------------------
# fetch_feed — happy path
# ---------------------------------------------------------------------------

def test_fetch_feed_ok():
    """fetch_feed returns ok=True for a valid local feed."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    assert result.ok is True


def test_fetch_feed_episode_count():
    """fetch_feed returns all three episodes from the sample feed."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    assert len(result.episodes) == 3


def test_fetch_feed_episode_titles():
    """fetch_feed parses episode titles correctly."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    titles = [ep.title for ep in result.episodes]
    assert "Episode 3 - Most Recent" in titles
    assert "Episode 2 - Middle" in titles
    assert "Episode 1 - Oldest" in titles


def test_fetch_feed_episode_urls():
    """fetch_feed parses audio URLs from enclosures."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    urls = [ep.url for ep in result.episodes]
    assert "https://example.com/ep3.mp3" in urls


def test_fetch_feed_episode_guids():
    """fetch_feed parses episode GUIDs correctly."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    guids = [ep.guid for ep in result.episodes]
    assert any("guid-003" in g for g in guids)
    assert any("guid-001" in g for g in guids)

def test_fetch_feed_episode_dates():
    """fetch_feed parses publish dates as ISO-8601 strings."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    dates = [ep.publish_date for ep in result.episodes]
    assert "2026-06-02" in dates
    assert "2026-05-05" in dates
    assert "2026-04-07" in dates


def test_fetch_feed_file_sizes():
    """fetch_feed parses file sizes from enclosure length attributes."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    sizes = [ep.file_size_bytes for ep in result.episodes]
    assert 50_000_000 in sizes
    assert 40_000_000 in sizes
    assert 30_000_000 in sizes


def test_fetch_feed_podcast_title():
    """fetch_feed extracts the podcast title from feed metadata."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    assert result.podcast_title == "Test Podcast"


def test_fetch_feed_podcast_author():
    """fetch_feed extracts the podcast author from feed metadata."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    assert result.podcast_author == "Test Author"


def test_fetch_feed_podcast_artwork():
    """fetch_feed extracts the artwork URL from feed metadata."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    assert result.podcast_artwork_url == "https://example.com/artwork.jpg"


def test_fetch_feed_not_stale():
    """fetch_feed marks a recent feed as not stale."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    assert result.is_stale is False


# ---------------------------------------------------------------------------
# fetch_feed — stale feed
# ---------------------------------------------------------------------------

def test_fetch_stale_feed_ok():
    """fetch_feed returns ok=True even for a stale feed."""
    result = fetch_feed(STALE_FEED.as_uri())
    assert result.ok is True


def test_fetch_stale_feed_is_stale():
    """fetch_feed marks a feed with old episodes as stale."""
    result = fetch_feed(STALE_FEED.as_uri())
    assert result.is_stale is True


# ---------------------------------------------------------------------------
# fetch_feed — error handling
# ---------------------------------------------------------------------------

def test_fetch_feed_bad_url():
    """fetch_feed returns ok=False for an unreachable URL."""
    result = fetch_feed("https://this.domain.does.not.exist.invalid/feed.xml")
    assert result.ok is False
    assert result.error is not None
    assert len(result.episodes) == 0


def test_fetch_feed_max_episodes():
    """fetch_feed respects the max_episodes limit."""
    result = fetch_feed(SAMPLE_FEED.as_uri(), max_episodes=2)
    assert len(result.episodes) <= 2


# ---------------------------------------------------------------------------
# _parse_duration
# ---------------------------------------------------------------------------

class FakeEntry:
    """Minimal feedparser entry stub for duration parsing tests."""
    def __init__(self, duration: str):
        self.itunes_duration = duration


@pytest.mark.parametrize("duration_str,expected_seconds", [
    ("01:00:00", 3600),
    ("00:45:30", 2730),
    ("30:00", 1800),
    ("1800", 1800),
    ("0", 0),
])
def test_parse_duration_formats(duration_str, expected_seconds):
    """_parse_duration handles HH:MM:SS, MM:SS, and plain seconds."""
    entry = FakeEntry(duration_str)
    assert _parse_duration(entry) == expected_seconds


def test_parse_duration_missing():
    """_parse_duration returns None when no duration is present."""
    class NoDuration:
        itunes_duration = None
    assert _parse_duration(NoDuration()) is None


def test_parse_duration_invalid():
    """_parse_duration returns None for an unparseable string."""
    assert _parse_duration(FakeEntry("not-a-duration")) is None


# ---------------------------------------------------------------------------
# _check_stale
# ---------------------------------------------------------------------------

def test_check_stale_empty_list():
    """_check_stale returns False for an empty episode list."""
    assert _check_stale([]) is False


def test_check_stale_recent_episode():
    """_check_stale returns False when the most recent episode is recent."""
    episode = Episode(
        title="Recent",
        url="https://example.com/ep.mp3",
        publish_date="2026-06-01",
        duration_seconds=None,
        file_size_bytes=None,
        guid="abc",
    )
    assert _check_stale([episode]) is False


def test_check_stale_old_episode():
    """_check_stale returns True when the most recent episode is very old."""
    episode = Episode(
        title="Old",
        url="https://example.com/ep.mp3",
        publish_date="2020-01-01",
        duration_seconds=None,
        file_size_bytes=None,
        guid="abc",
    )
    assert _check_stale([episode]) is True


def test_check_stale_missing_date():
    """_check_stale returns False when the episode has no publish date."""
    episode = Episode(
        title="No Date",
        url="https://example.com/ep.mp3",
        publish_date="",
        duration_seconds=None,
        file_size_bytes=None,
        guid="abc",
    )
    assert _check_stale([episode]) is False


# ---------------------------------------------------------------------------
# build_podcast_from_feed
# ---------------------------------------------------------------------------

def test_build_podcast_from_feed():
    """build_podcast_from_feed constructs a Podcast from a FeedResult."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    podcast = build_podcast_from_feed("https://example.com/feed.xml", result)

    assert podcast.rss_url == "https://example.com/feed.xml"
    assert podcast.title == "Test Podcast"
    assert podcast.author == "Test Author"
    assert podcast.artwork_url == "https://example.com/artwork.jpg"
    assert podcast.last_checked is not None


def test_build_podcast_last_checked_is_set():
    """build_podcast_from_feed always sets last_checked to a non-empty string."""
    result = fetch_feed(SAMPLE_FEED.as_uri())
    podcast = build_podcast_from_feed("https://example.com/feed.xml", result)
    assert podcast.last_checked != ""
