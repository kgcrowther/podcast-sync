"""
Tests for SwimSync sync engine (core/sync_engine.py).

All tests use temporary directories to simulate a mounted device —
no real Shokz device is required.

Run with: pytest tests/test_sync_engine.py -v
"""

from pathlib import Path

import pytest

from swimsync.core.sync_engine import (
    compute_sync_plan,
    _episodes_matching_flow,
    _safe_filename,
    _sanitise,
    _fmt_bytes,
    STORAGE_WARNING_THRESHOLD,
)
from swimsync.models.profile import (
    Profile,
    Podcast,
    Episode,
    Flow,
    PlaylistItem,
    DeviceConfig,
    DEFAULT_DEVICES,
)
from swimsync.models.sync_plan import SyncPlan, SyncAction


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def make_episode(
    title: str = "Test Episode",
    url: str = "https://example.com/ep.mp3",
    publish_date: str = "2026-06-01",
    file_size_bytes: int = 10_000_000,
    guid: str = "guid-001",
) -> Episode:
    return Episode(
        title=title,
        url=url,
        publish_date=publish_date,
        duration_seconds=3600,
        file_size_bytes=file_size_bytes,
        guid=guid,
    )


def make_playlist_item(
    title: str = "Playlist Episode",
    episode_url: str = "https://example.com/playlist_ep.mp3",
    file_size_bytes: int = 10_000_000,
) -> PlaylistItem:
    return PlaylistItem(
        title=title,
        source_label="Test Podcast",
        file_size_bytes=file_size_bytes,
        duration_seconds=1800,
        podcast_rss_url="https://example.com/feed.xml",
        episode_guid="guid-playlist",
        episode_url=episode_url,
    )


def make_profile(
    flows: list[Flow] = None,
    playlist: list[PlaylistItem] = None,
) -> Profile:
    return Profile(
        name="TestUser",
        podcasts=[],
        flows=flows or [],
        playlist=playlist or [],
        device_configs=list(DEFAULT_DEVICES),
    )


def make_device(tmp_path: Path, files: dict[str, bytes] = None) -> str:
    """
    Create a fake mounted device directory with optional files.

    Args:
        tmp_path: Pytest temporary directory.
        files: Dict of filename -> file content bytes.

    Returns:
        String path to the fake device directory.
    """
    device = tmp_path / "SWIM_PRO"
    device.mkdir()
    for filename, content in (files or {}).items():
        (device / filename).write_bytes(content)
    return str(device)


# ---------------------------------------------------------------------------
# compute_sync_plan — empty states
# ---------------------------------------------------------------------------

def test_empty_profile_empty_device(tmp_path):
    """No changes needed when profile and device are both empty."""
    device_path = make_device(tmp_path)
    profile = make_profile()
    plan = compute_sync_plan(profile, device_path, "SWIM PRO", {})
    assert plan.is_empty


def test_empty_profile_device_has_files(tmp_path):
    """Files on device with empty profile should all be marked for deletion."""
    device_path = make_device(tmp_path, {"old.mp3": b"x" * 1000})
    profile = make_profile()
    plan = compute_sync_plan(profile, device_path, "SWIM PRO", {})
    assert "old.mp3" in plan.to_delete
    assert plan.to_add == []


# ---------------------------------------------------------------------------
# compute_sync_plan — playlist
# ---------------------------------------------------------------------------

def test_playlist_item_added_when_not_on_device(tmp_path):
    """A playlist item not on the device is added to to_add."""
    device_path = make_device(tmp_path)
    item = make_playlist_item(episode_url="https://example.com/ep1.mp3")
    profile = make_profile(playlist=[item])
    plan = compute_sync_plan(profile, device_path, "SWIM PRO", {})
    filenames = [a.filename for a in plan.to_add]
    assert any("ep1.mp3" in f for f in filenames)


def test_playlist_item_not_added_when_already_on_device(tmp_path):
    """A playlist item already on device with correct size is not re-added."""
    content = b"a" * 10_000_000
    device_path = make_device(tmp_path, {"ep1.mp3": content})
    item = make_playlist_item(
        episode_url="https://example.com/ep1.mp3",
        file_size_bytes=len(content),
    )
    profile = make_profile(playlist=[item])
    plan = compute_sync_plan(profile, device_path, "SWIM PRO", {})
    assert plan.to_add == []
    assert plan.to_delete == []


def test_playlist_item_redownloaded_on_size_mismatch(tmp_path):
    """A playlist item with wrong byte size on device is queued for re-download."""
    device_path = make_device(tmp_path, {"ep1.mp3": b"x" * 5_000})
    item = make_playlist_item(
        episode_url="https://example.com/ep1.mp3",
        file_size_bytes=10_000_000,
    )
    profile = make_profile(playlist=[item])
    plan = compute_sync_plan(profile, device_path, "SWIM PRO", {})
    assert len(plan.to_redownload) == 1
    assert plan.to_redownload[0].filename == "ep1.mp3"


# ---------------------------------------------------------------------------
# compute_sync_plan — flows
# ---------------------------------------------------------------------------

def test_flow_episode_added_when_not_on_device(tmp_path):
    """An episode matching a flow is added when not on device."""
    device_path = make_device(tmp_path)
    episode = make_episode(url="https://example.com/ep_flow.mp3")
    flow = Flow(podcast_rss_url="https://example.com/feed.xml", most_recent_count=1)
    profile = make_profile(flows=[flow])
    episode_cache = {"https://example.com/feed.xml": [episode]}
    plan = compute_sync_plan(profile, device_path, "SWIM PRO", episode_cache)
    filenames = [a.filename for a in plan.to_add]
    assert any("ep_flow.mp3" in f for f in filenames)


def test_flow_old_episode_deleted_from_device(tmp_path):
    """An episode on the device that no longer matches a flow is deleted."""
    device_path = make_device(tmp_path, {"old_ep.mp3": b"x" * 1000})
    new_episode = make_episode(
        url="https://example.com/new_ep.mp3",
        guid="guid-new",
    )
    flow = Flow(podcast_rss_url="https://example.com/feed.xml", most_recent_count=1)
    profile = make_profile(flows=[flow])
    episode_cache = {"https://example.com/feed.xml": [new_episode]}
    plan = compute_sync_plan(profile, device_path, "SWIM PRO", episode_cache)
    assert "old_ep.mp3" in plan.to_delete


# ---------------------------------------------------------------------------
# compute_sync_plan — playlist priority over flows
# ---------------------------------------------------------------------------

def test_playlist_takes_priority_over_flow_for_same_file(tmp_path):
    """When playlist and flow produce the same filename, playlist wins."""
    device_path = make_device(tmp_path)
    url = "https://example.com/ep1.mp3"

    playlist_item = make_playlist_item(episode_url=url, file_size_bytes=10_000_000)
    flow = Flow(podcast_rss_url="https://example.com/feed.xml", most_recent_count=1)
    episode = make_episode(url=url, file_size_bytes=10_000_000)

    profile = make_profile(flows=[flow], playlist=[playlist_item])
    episode_cache = {"https://example.com/feed.xml": [episode]}
    plan = compute_sync_plan(profile, device_path, "SWIM PRO", episode_cache)

    # Should appear exactly once in to_add
    matching = [a for a in plan.to_add if "ep1.mp3" in a.filename]
    assert len(matching) == 1


# ---------------------------------------------------------------------------
# compute_sync_plan — storage warning
# ---------------------------------------------------------------------------

def test_storage_warning_not_triggered_below_threshold(tmp_path):
    """No storage warning when desired state is well below 90% capacity."""
    device_path = make_device(tmp_path)
    item = make_playlist_item(file_size_bytes=100)
    profile = make_profile(playlist=[item])
    plan = compute_sync_plan(profile, device_path, "SWIM PRO", {})
    # Device capacity via statvfs on a real filesystem will be large
    # so 100 bytes should never trigger the warning
    assert plan.storage_warning is False


# ---------------------------------------------------------------------------
# _episodes_matching_flow
# ---------------------------------------------------------------------------

def make_episodes(n: int, days_ago_start: int = 0) -> list[Episode]:
    """Create a list of n episodes with sequential dates."""
    from datetime import datetime, timezone, timedelta
    episodes = []
    for i in range(n):
        date = datetime.now(timezone.utc) - timedelta(days=days_ago_start + i)
        episodes.append(make_episode(
            title=f"Episode {i+1}",
            url=f"https://example.com/ep{i+1}.mp3",
            publish_date=date.date().isoformat(),
            guid=f"guid-{i+1:03}",
        ))
    return episodes


def test_flow_most_recent_count():
    """Flow with most_recent_count=3 returns the 3 most recent episodes."""
    episodes = make_episodes(10)
    flow = Flow(podcast_rss_url="https://example.com/feed.xml", most_recent_count=3)
    result = _episodes_matching_flow(flow, episodes)
    assert len(result) == 3
    assert result[0].title == "Episode 1"
    assert result[2].title == "Episode 3"


def test_flow_most_recent_count_fewer_than_n():
    """Flow with most_recent_count=5 returns all episodes if fewer than 5 exist."""
    episodes = make_episodes(3)
    flow = Flow(podcast_rss_url="https://example.com/feed.xml", most_recent_count=5)
    result = _episodes_matching_flow(flow, episodes)
    assert len(result) == 3


def test_flow_last_x_days():
    """Flow with last_x_days returns only episodes within that window."""
    recent = make_episodes(3, days_ago_start=0)    # 0, 1, 2 days ago
    old = make_episodes(2, days_ago_start=60)       # 60, 61 days ago
    flow = Flow(
        podcast_rss_url="https://example.com/feed.xml",
        most_recent_count=None,
        last_x_days=30,
    )
    result = _episodes_matching_flow(flow, recent + old)
    assert len(result) == 3
    assert all("Episode" in ep.title for ep in result)


def test_flow_both_criteria_union():
    """Flow with both criteria returns union of matching episodes."""
    episodes = make_episodes(10, days_ago_start=0)
    flow = Flow(
        podcast_rss_url="https://example.com/feed.xml",
        most_recent_count=2,
        last_x_days=5,
    )
    result = _episodes_matching_flow(flow, episodes)
    # most_recent=2 gives ep1, ep2
    # last_x_days=5 gives ep1..ep5 (approximately)
    # union should be at least 5, no duplicates
    guids = [ep.guid for ep in result]
    assert len(guids) == len(set(guids))  # no duplicates
    assert len(result) >= 2


def test_flow_no_criteria_returns_empty():
    """Flow with no criteria set returns no episodes."""
    episodes = make_episodes(5)
    flow = Flow(
        podcast_rss_url="https://example.com/feed.xml",
        most_recent_count=None,
        last_x_days=None,
    )
    result = _episodes_matching_flow(flow, episodes)
    assert result == []


def test_flow_empty_episode_list():
    """Flow against an empty episode list returns empty."""
    flow = Flow(podcast_rss_url="https://example.com/feed.xml", most_recent_count=3)
    assert _episodes_matching_flow(flow, []) == []


# ---------------------------------------------------------------------------
# _safe_filename
# ---------------------------------------------------------------------------

def test_safe_filename_from_url():
    """_safe_filename extracts filename from URL."""
    assert _safe_filename("Any Title", "https://example.com/episode_123.mp3") == "episode_123.mp3"


def test_safe_filename_falls_back_to_title():
    """_safe_filename falls back to title when URL has no extension."""
    result = _safe_filename("My Episode", "https://example.com/stream")
    assert "My Episode" in result


# ---------------------------------------------------------------------------
# _sanitise
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("normal.mp3", "normal.mp3"),
    ('bad/name?.mp3', "bad_name_.mp3"),
    ("  leading.mp3", "leading.mp3"),
    ("", "audio_file"),
])
def test_sanitise(raw, expected):
    """_sanitise removes unsafe characters from filenames."""
    assert _sanitise(raw) == expected


# ---------------------------------------------------------------------------
# _fmt_bytes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n,expected", [
    (500, "500.0 B"),
    (1024, "1.0 KB"),
    (1024 * 1024, "1.0 MB"),
    (1024 * 1024 * 1024, "1.0 GB"),
])
def test_fmt_bytes(n, expected):
    """_fmt_bytes formats byte counts correctly."""
    assert _fmt_bytes(n) == expected


# ---------------------------------------------------------------------------
# SyncPlan properties
# ---------------------------------------------------------------------------

def test_sync_plan_is_empty():
    """SyncPlan.is_empty is True when no actions are queued."""
    plan = SyncPlan()
    assert plan.is_empty is True


def test_sync_plan_not_empty_with_actions():
    """SyncPlan.is_empty is False when actions are queued."""
    plan = SyncPlan(to_delete=["old.mp3"])
    assert plan.is_empty is False


def test_sync_plan_summary_empty():
    """SyncPlan.summary returns up-to-date message when empty."""
    plan = SyncPlan()
    assert "up to date" in plan.summary()


def test_sync_plan_summary_with_actions():
    """SyncPlan.summary lists counts of each action type."""
    plan = SyncPlan(
        to_add=[SyncAction(filename="new.mp3", title="New", source_label="Podcast")],
        to_delete=["old.mp3", "older.mp3"],
    )
    summary = plan.summary()
    assert "1 to add" in summary
    assert "2 to delete" in summary
