"""
SwimSync RSS client.

Fetches and parses podcast RSS feeds using the feedparser library.
Returns Episode objects and handles feed unavailability gracefully.

Responsibilities:
- Fetch a feed by URL and return a list of Episode objects
- Detect whether a feed has been inactive for more than 45 days
- Handle network errors and malformed feeds without crashing
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import feedparser

from swimsync.models.profile import Episode, Podcast
from swimsync.utils.logger import get_logger

log = get_logger(__name__)

# A feed is considered stale if its most recent episode is older than this
STALE_FEED_DAYS = 45


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_date(entry) -> str:
    """
    Extract a publish date from a feed entry as an ISO-8601 date string.

    feedparser provides published_parsed as a time.struct_time in UTC.
    Falls back to an empty string if no date is available.

    Args:
        entry: A feedparser entry object.

    Returns:
        ISO-8601 date string e.g. "2026-06-01", or "" if unavailable.
    """
    parsed = getattr(entry, "published_parsed", None)
    if parsed is None:
        parsed = getattr(entry, "updated_parsed", None)
    if parsed is None:
        return ""
    try:
        dt = datetime(*parsed[:6], tzinfo=timezone.utc)
        return dt.date().isoformat()
    except (TypeError, ValueError):
        return ""


def _parse_duration(entry) -> Optional[int]:
    """
    Extract episode duration in seconds from a feed entry.

    Handles formats: "HH:MM:SS", "MM:SS", or plain seconds as a string.

    Args:
        entry: A feedparser entry object.

    Returns:
        Duration in seconds as an integer, or None if unavailable.
    """
    duration_str = getattr(entry, "itunes_duration", None)
    if not duration_str:
        return None

    duration_str = str(duration_str).strip()
    parts = duration_str.split(":")

    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        else:
            return int(duration_str)
    except (ValueError, TypeError):
        return None


def _parse_file_size(entry) -> Optional[int]:
    """
    Extract the audio file size in bytes from a feed entry's enclosure.

    Args:
        entry: A feedparser entry object.

    Returns:
        File size in bytes as an integer, or None if unavailable.
    """
    enclosures = getattr(entry, "enclosures", [])
    for enclosure in enclosures:
        length = getattr(enclosure, "length", None)
        if length:
            try:
                return int(length)
            except (ValueError, TypeError):
                pass
    return None


def _get_audio_url(entry) -> Optional[str]:
    """
    Extract the direct audio file URL from a feed entry's enclosure.

    Args:
        entry: A feedparser entry object.

    Returns:
        URL string, or None if no audio enclosure is found.
    """
    enclosures = getattr(entry, "enclosures", [])
    for enclosure in enclosures:
        url = getattr(enclosure, "href", None)
        mime = getattr(enclosure, "type", "")
        if url and ("audio" in mime or any(
            url.lower().endswith(f".{ext}")
            for ext in ["mp3", "flac", "wav", "aac", "m4a", "wma", "ape"]
        )):
            return url
    return None


def _get_guid(entry) -> str:
    """
    Extract a unique identifier for a feed entry.

    Falls back to the entry's link or title if no explicit guid is provided.

    Args:
        entry: A feedparser entry object.

    Returns:
        A non-empty string that uniquely identifies this episode.
    """
    guid = getattr(entry, "id", None)
    if guid:
        return str(guid)
    return getattr(entry, "link", None) or getattr(entry, "title", "unknown")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class FeedResult:
    """
    The result of fetching and parsing a podcast RSS feed.

    Attributes:
        ok: True if the feed was reachable and parseable.
        episodes: List of Episode objects parsed from the feed (may be empty).
        podcast_title: Title from the feed, or None if unavailable.
        podcast_author: Author from the feed, or None if unavailable.
        podcast_description: Description from the feed, or None.
        podcast_artwork_url: Artwork URL from the feed, or None.
        error: Human-readable error message if ok is False, else None.
        is_stale: True if the most recent episode is older than STALE_FEED_DAYS.
    """

    def __init__(
        self,
        ok: bool,
        episodes: list[Episode],
        podcast_title: Optional[str] = None,
        podcast_author: Optional[str] = None,
        podcast_description: Optional[str] = None,
        podcast_artwork_url: Optional[str] = None,
        error: Optional[str] = None,
        is_stale: bool = False,
    ):
        self.ok = ok
        self.episodes = episodes
        self.podcast_title = podcast_title
        self.podcast_author = podcast_author
        self.podcast_description = podcast_description
        self.podcast_artwork_url = podcast_artwork_url
        self.error = error
        self.is_stale = is_stale


def fetch_feed(rss_url: str, max_episodes: int = 100) -> FeedResult:
    """
    Fetch and parse a podcast RSS feed.

    Retrieves the feed at the given URL and converts its entries into
    Episode objects. Handles network failures and malformed feeds
    gracefully by returning a FeedResult with ok=False rather than raising.

    Args:
        rss_url: The URL of the podcast RSS feed.
        max_episodes: Maximum number of episodes to return (most recent first).

    Returns:
        A FeedResult instance describing the outcome.
    """
    log.info(f"Fetching feed: {rss_url}")

    try:
        parsed = feedparser.parse(rss_url)
    except Exception as exc:
        log.error(f"Unexpected error fetching feed {rss_url}: {exc}")
        return FeedResult(ok=False, episodes=[], error=str(exc))

    # feedparser does not raise on network errors — check bozo and status
    if parsed.get("bozo") and not parsed.get("entries"):
        bozo_exc = parsed.get("bozo_exception", "Unknown error")
        msg = f"Feed unavailable or malformed: {bozo_exc}"
        log.warning(f"{msg} — {rss_url}")
        return FeedResult(ok=False, episodes=[], error=msg)

    status = parsed.get("status", 200)
    if status >= 400:
        msg = f"HTTP {status} when fetching feed"
        log.warning(f"{msg}: {rss_url}")
        return FeedResult(ok=False, episodes=[], error=msg)

    # Extract feed-level metadata
    feed_meta = parsed.get("feed", {})
    podcast_title = feed_meta.get("title") or None
    podcast_author = feed_meta.get("author") or feed_meta.get("itunes_author") or None
    podcast_description = feed_meta.get("summary") or feed_meta.get("description") or None

    artwork_url = None
    image = feed_meta.get("image", {})
    if isinstance(image, dict):
        artwork_url = image.get("href") or image.get("url")
    if not artwork_url:
        artwork_url = feed_meta.get("itunes_image", {}).get("href")

    # Parse entries into Episode objects
    episodes: list[Episode] = []
    for entry in parsed.entries[:max_episodes]:
        audio_url = _get_audio_url(entry)
        if not audio_url:
            continue  # Skip entries with no audio enclosure

        episode = Episode(
            title=getattr(entry, "title", "Untitled Episode"),
            url=audio_url,
            publish_date=_parse_date(entry),
            duration_seconds=_parse_duration(entry),
            file_size_bytes=_parse_file_size(entry),
            guid=_get_guid(entry),
        )
        episodes.append(episode)

    # Check for stale feed
    is_stale = _check_stale(episodes)
    if is_stale:
        log.warning(f"Feed is stale (no new episodes in {STALE_FEED_DAYS}+ days): {rss_url}")

    log.info(f"Feed fetched: {len(episodes)} episodes found — {rss_url}")

    return FeedResult(
        ok=True,
        episodes=episodes,
        podcast_title=podcast_title,
        podcast_author=podcast_author,
        podcast_description=podcast_description,
        podcast_artwork_url=artwork_url,
        is_stale=is_stale,
    )


def _check_stale(episodes: list[Episode]) -> bool:
    """
    Return True if the most recent episode is older than STALE_FEED_DAYS.

    Args:
        episodes: List of Episode objects (assumed most-recent-first).

    Returns:
        True if the feed should be marked stale, False otherwise.
    """
    if not episodes:
        return False

    most_recent_date_str = episodes[0].publish_date
    if not most_recent_date_str:
        return False

    try:
        most_recent = datetime.fromisoformat(most_recent_date_str).replace(
            tzinfo=timezone.utc
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_FEED_DAYS)
        return most_recent < cutoff
    except ValueError:
        return False


def build_podcast_from_feed(rss_url: str, result: FeedResult) -> Podcast:
    """
    Construct a Podcast model from an RSS URL and a successful FeedResult.

    Args:
        rss_url: The RSS feed URL.
        result: A FeedResult with ok=True.

    Returns:
        A Podcast instance populated with feed metadata.
    """
    now = datetime.now(timezone.utc).isoformat()
    return Podcast(
        title=result.podcast_title or rss_url,
        rss_url=rss_url,
        author=result.podcast_author or "",
        description=result.podcast_description or "",
        artwork_url=result.podcast_artwork_url,
        last_checked=now,
    )
