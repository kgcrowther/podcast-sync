"""
Tests for SwimSync data models (models/profile.py).

Run with: pytest tests/test_profile_manager.py
"""

from swimsync.models.profile import (
    Profile,
    Podcast,
    Episode,
    Flow,
    PlaylistItem,
    DeviceConfig,
    DEFAULT_DEVICES,
)


# ---------------------------------------------------------------------------
# DeviceConfig
# ---------------------------------------------------------------------------

def test_device_config_roundtrip():
    """DeviceConfig survives a to_dict / from_dict round trip."""
    device = DeviceConfig(
        drive_label="SWIM PRO",
        supported_extensions=["mp3", "flac"],
    )
    assert DeviceConfig.from_dict(device.to_dict()) == device


def test_default_devices_exist():
    """Two default devices are defined."""
    assert len(DEFAULT_DEVICES) == 2
    labels = [d.drive_label for d in DEFAULT_DEVICES]
    assert "SWIM PRO" in labels
    assert "OpenSwim" in labels


# ---------------------------------------------------------------------------
# Podcast
# ---------------------------------------------------------------------------

def test_podcast_roundtrip():
    """Podcast survives a to_dict / from_dict round trip."""
    podcast = Podcast(
        title="Test Podcast",
        rss_url="https://example.com/feed.xml",
        author="Test Author",
        description="A test podcast.",
        artwork_url="https://example.com/art.jpg",
        last_checked="2026-06-01T12:00:00",
    )
    assert Podcast.from_dict(podcast.to_dict()) == podcast


def test_podcast_optional_fields_default():
    """Podcast can be created with minimal fields."""
    podcast = Podcast.from_dict({
        "title": "Minimal",
        "rss_url": "https://example.com/feed.xml",
    })
    assert podcast.author == ""
    assert podcast.artwork_url is None
    assert podcast.last_checked is None


# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------

def test_episode_roundtrip():
    """Episode survives a to_dict / from_dict round trip."""
    episode = Episode(
        title="Episode 1",
        url="https://example.com/ep1.mp3",
        publish_date="2026-05-01",
        duration_seconds=3600,
        file_size_bytes=50_000_000,
        guid="abc-123",
    )
    assert Episode.from_dict(episode.to_dict()) == episode


def test_episode_optional_fields():
    """Episode handles missing duration and file size gracefully."""
    episode = Episode.from_dict({
        "title": "Episode 2",
        "url": "https://example.com/ep2.mp3",
        "publish_date": "2026-05-02",
        "guid": "abc-124",
    })
    assert episode.duration_seconds is None
    assert episode.file_size_bytes is None


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------

def test_flow_roundtrip():
    """Flow survives a to_dict / from_dict round trip."""
    flow = Flow(
        podcast_rss_url="https://example.com/feed.xml",
        most_recent_count=5,
        last_x_days=30,
    )
    assert Flow.from_dict(flow.to_dict()) == flow


def test_flow_default_count():
    """Flow defaults to 3 most recent episodes."""
    flow = Flow.from_dict({"podcast_rss_url": "https://example.com/feed.xml"})
    assert flow.most_recent_count == 3
    assert flow.last_x_days is None


# ---------------------------------------------------------------------------
# PlaylistItem
# ---------------------------------------------------------------------------

def test_playlist_item_episode_roundtrip():
    """PlaylistItem for a podcast episode survives round trip."""
    item = PlaylistItem(
        title="Great Episode",
        source_label="Test Podcast",
        file_size_bytes=40_000_000,
        duration_seconds=2700,
        podcast_rss_url="https://example.com/feed.xml",
        episode_guid="abc-123",
        episode_url="https://example.com/ep1.mp3",
    )
    assert PlaylistItem.from_dict(item.to_dict()) == item
    assert not item.is_local_file()


def test_playlist_item_local_file_roundtrip():
    """PlaylistItem for a local file survives round trip."""
    item = PlaylistItem(
        title="My Audio File",
        source_label="my_audio.mp3",
        file_size_bytes=10_000_000,
        duration_seconds=600,
        local_file_path="/Users/kenneth/Music/my_audio.mp3",
    )
    assert PlaylistItem.from_dict(item.to_dict()) == item
    assert item.is_local_file()


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def test_profile_roundtrip():
    """A complete Profile survives a to_dict / from_dict round trip."""
    profile = Profile(
        name="Kenneth",
        podcasts=[
            Podcast(
                title="Test Podcast",
                rss_url="https://example.com/feed.xml",
                author="Author",
                description="Description",
                artwork_url=None,
                last_checked=None,
            )
        ],
        flows=[
            Flow(podcast_rss_url="https://example.com/feed.xml", most_recent_count=3)
        ],
        playlist=[],
        device_configs=list(DEFAULT_DEVICES),
    )
    restored = Profile.from_dict(profile.to_dict())
    assert restored.name == profile.name
    assert len(restored.podcasts) == 1
    assert len(restored.flows) == 1
    assert restored.flows[0].most_recent_count == 3


def test_profile_get_podcast():
    """Profile.get_podcast returns the right podcast by RSS URL."""
    podcast = Podcast(
        title="Test",
        rss_url="https://example.com/feed.xml",
        author="",
        description="",
        artwork_url=None,
        last_checked=None,
    )
    profile = Profile(name="Test", podcasts=[podcast])
    assert profile.get_podcast("https://example.com/feed.xml") == podcast
    assert profile.get_podcast("https://other.com/feed.xml") is None


def test_profile_get_flow():
    """Profile.get_flow returns the right flow by RSS URL."""
    flow = Flow(podcast_rss_url="https://example.com/feed.xml", most_recent_count=3)
    profile = Profile(name="Test", flows=[flow])
    assert profile.get_flow("https://example.com/feed.xml") == flow
    assert profile.get_flow("https://other.com/feed.xml") is None


def test_profile_get_device_config():
    """Profile.get_device_config returns the right config by drive label."""
    profile = Profile(name="Test")
    config = profile.get_device_config("SWIM PRO")
    assert config is not None
    assert "mp3" in config.supported_extensions


def test_new_profile_has_default_devices():
    """A new Profile always includes the two default Shokz device configs."""
    profile = Profile(name="New User")
    labels = [d.drive_label for d in profile.device_configs]
    assert "SWIM PRO" in labels
    assert "OpenSwim" in labels
