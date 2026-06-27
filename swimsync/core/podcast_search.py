"""
SwimSync podcast search.

Searches the iTunes Search API for podcasts by name or keyword.
Also validates RSS feed URLs pasted directly by the user.

iTunes Search API docs: https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/
No API key required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests

from swimsync.utils.logger import get_logger

log = get_logger(__name__)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
REQUEST_TIMEOUT = 10  # seconds


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PodcastSearchResult:
    """
    A single result returned from a podcast search.

    Attributes:
        title: The podcast title.
        author: The podcast author or publisher.
        artwork_url: URL to the podcast artwork image (300x300 or larger).
        rss_url: The RSS feed URL for this podcast.
        itunes_id: The iTunes collection ID (useful for deduplication).
        genre: Primary genre label, e.g. "Technology".
        episode_count: Total episode count reported by iTunes, or None.
    """
    title: str
    author: str
    artwork_url: Optional[str]
    rss_url: str
    itunes_id: int
    genre: Optional[str]
    episode_count: Optional[int]


@dataclass
class SearchOutcome:
    """
    The outcome of a search or RSS validation operation.

    Attributes:
        ok: True if the operation succeeded.
        results: List of PodcastSearchResult objects (empty on failure).
        error: Human-readable error message if ok is False, else None.
    """
    ok: bool
    results: list[PodcastSearchResult]
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# iTunes Search API
# ---------------------------------------------------------------------------

def search_podcasts(query: str, limit: int = 20) -> SearchOutcome:
    """
    Search the iTunes Search API for podcasts matching a query string.

    Args:
        query: The search term (podcast name, topic, or keyword).
        limit: Maximum number of results to return (default 20, max 200).

    Returns:
        A SearchOutcome with ok=True and a list of results on success,
        or ok=False with an error message on failure.
    """
    if not query.strip():
        return SearchOutcome(ok=False, results=[], error="Search query cannot be empty.")

    params = {
        "term": query.strip(),
        "media": "podcast",
        "entity": "podcast",
        "limit": min(limit, 200),
    }

    log.info(f"Searching iTunes for podcasts: '{query}'")

    try:
        response = requests.get(ITUNES_SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        msg = "Search request timed out. Please check your internet connection."
        log.warning(msg)
        return SearchOutcome(ok=False, results=[], error=msg)
    except requests.exceptions.ConnectionError:
        msg = "Could not connect to the iTunes Search API. Please check your internet connection."
        log.warning(msg)
        return SearchOutcome(ok=False, results=[], error=msg)
    except requests.exceptions.HTTPError as exc:
        msg = f"iTunes Search API returned an error: {exc}"
        log.warning(msg)
        return SearchOutcome(ok=False, results=[], error=msg)

    try:
        data = response.json()
    except ValueError:
        msg = "Received an unexpected response from the iTunes Search API."
        log.error(msg)
        return SearchOutcome(ok=False, results=[], error=msg)

    results = _parse_itunes_results(data.get("results", []))
    log.info(f"iTunes search returned {len(results)} results for '{query}'")
    return SearchOutcome(ok=True, results=results)


def _parse_itunes_results(raw_results: list[dict]) -> list[PodcastSearchResult]:
    """
    Convert raw iTunes API result dicts into PodcastSearchResult objects.

    Skips entries that are missing a feed URL or collection ID.

    Args:
        raw_results: List of result dicts from the iTunes API response.

    Returns:
        List of PodcastSearchResult objects.
    """
    results = []
    for item in raw_results:
        rss_url = item.get("feedUrl")
        itunes_id = item.get("collectionId")

        if not rss_url or not itunes_id:
            continue

        # Prefer high-resolution artwork
        artwork = (
            item.get("artworkUrl600")
            or item.get("artworkUrl100")
            or item.get("artworkUrl60")
        )

        genres = item.get("genres", [])
        genre = genres[0] if genres else None

        results.append(PodcastSearchResult(
            title=item.get("collectionName", "Unknown Title"),
            author=item.get("artistName", "Unknown Author"),
            artwork_url=artwork,
            rss_url=rss_url,
            itunes_id=itunes_id,
            genre=genre,
            episode_count=item.get("trackCount"),
        ))

    return results


# ---------------------------------------------------------------------------
# RSS URL validation
# ---------------------------------------------------------------------------

@dataclass
class FeedValidationResult:
    """
    The outcome of validating a user-supplied RSS feed URL.

    Attributes:
        ok: True if the URL points to a reachable, parseable podcast feed.
        title: The podcast title from the feed, or None.
        author: The podcast author from the feed, or None.
        episode_count: Number of episodes found in the feed, or None.
        most_recent_episode: Title of the most recent episode, or None.
        error: Human-readable error message if ok is False, else None.
    """
    ok: bool
    title: Optional[str] = None
    author: Optional[str] = None
    episode_count: Optional[int] = None
    most_recent_episode: Optional[str] = None
    error: Optional[str] = None


def validate_rss_url(rss_url: str) -> FeedValidationResult:
    """
    Validate a user-supplied RSS feed URL and return basic feed metadata.

    This is used when a user pastes an RSS URL directly rather than
    searching. It fetches the feed and returns enough information to
    confirm to the user that the URL is correct and working.

    Args:
        rss_url: The RSS feed URL to validate.

    Returns:
        A FeedValidationResult describing whether the feed is valid
        and providing basic metadata for user confirmation.
    """
    from swimsync.core.rss_client import fetch_feed

    if not rss_url.strip():
        return FeedValidationResult(ok=False, error="RSS URL cannot be empty.")

    if not rss_url.startswith(("http://", "https://", "file://")):
        return FeedValidationResult(
            ok=False,
            error="RSS URL must start with http://, https://, or file://",
        )

    log.info(f"Validating RSS URL: {rss_url}")
    result = fetch_feed(rss_url, max_episodes=20)

    if not result.ok:
        msg = result.error or "Could not fetch the RSS feed."
        log.warning(f"RSS validation failed for {rss_url}: {msg}")
        return FeedValidationResult(ok=False, error=msg)

    if not result.episodes:
        return FeedValidationResult(
            ok=False,
            error="The feed was reachable but contained no audio episodes.",
        )

    most_recent = result.episodes[0].title if result.episodes else None

    log.info(
        f"RSS URL valid: '{result.podcast_title}' "
        f"({len(result.episodes)} episodes) — {rss_url}"
    )

    return FeedValidationResult(
        ok=True,
        title=result.podcast_title,
        author=result.podcast_author,
        episode_count=len(result.episodes),
        most_recent_episode=most_recent,
    )
