"""
SwimSync data models.

These dataclasses define the core data structures used throughout the app.
All models are serializable to/from plain dicts for JSON profile storage.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------

@dataclass
class DeviceConfig:
    """Defines a drive label that triggers sync and its supported file types."""
    drive_label: str
    supported_extensions: list[str]

    def to_dict(self) -> dict:
        return {
            "drive_label": self.drive_label,
            "supported_extensions": self.supported_extensions,
        }

    @staticmethod
    def from_dict(data: dict) -> DeviceConfig:
        return DeviceConfig(
            drive_label=data["drive_label"],
            supported_extensions=data["supported_extensions"],
        )


# Default devices SwimSync recognises out of the box
DEFAULT_DEVICES = [
    DeviceConfig(
        drive_label="SWIM PRO",
        supported_extensions=["mp3", "flac", "wma", "wav", "aac", "m4a", "ape"],
    ),
    DeviceConfig(
        drive_label="OpenSwim",
        supported_extensions=["mp3", "wma", "flac", "wav", "aac"],
    ),
]


# ---------------------------------------------------------------------------
# Podcast & Episode
# ---------------------------------------------------------------------------

@dataclass
class Episode:
    """A single podcast episode."""
    title: str
    url: str                          # Direct URL to the audio file
    publish_date: str                 # ISO-8601 string, e.g. "2026-06-01"
    duration_seconds: Optional[int]   # None if not provided by feed
    file_size_bytes: Optional[int]    # None if not provided by feed
    guid: str                         # Unique ID from the RSS feed

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "publish_date": self.publish_date,
            "duration_seconds": self.duration_seconds,
            "file_size_bytes": self.file_size_bytes,
            "guid": self.guid,
        }

    @staticmethod
    def from_dict(data: dict) -> Episode:
        return Episode(
            title=data["title"],
            url=data["url"],
            publish_date=data["publish_date"],
            duration_seconds=data.get("duration_seconds"),
            file_size_bytes=data.get("file_size_bytes"),
            guid=data["guid"],
        )


@dataclass
class Podcast:
    """A podcast the user is following."""
    title: str
    rss_url: str
    author: str
    description: str
    artwork_url: Optional[str]
    last_checked: Optional[str]       # ISO-8601 datetime of last RSS fetch

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "rss_url": self.rss_url,
            "author": self.author,
            "description": self.description,
            "artwork_url": self.artwork_url,
            "last_checked": self.last_checked,
        }

    @staticmethod
    def from_dict(data: dict) -> Podcast:
        return Podcast(
            title=data["title"],
            rss_url=data["rss_url"],
            author=data.get("author", ""),
            description=data.get("description", ""),
            artwork_url=data.get("artwork_url"),
            last_checked=data.get("last_checked"),
        )


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------

@dataclass
class Flow:
    """
    An automatic sync rule for a followed podcast.

    A flow selects episodes by one or both criteria:
      - most_recent_count: keep the N most recently published episodes
      - last_x_days: keep all episodes published within X days

    When both are set, the union of matching episodes is used.
    """
    podcast_rss_url: str              # Foreign key back to Podcast
    most_recent_count: Optional[int] = 3
    last_x_days: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "podcast_rss_url": self.podcast_rss_url,
            "most_recent_count": self.most_recent_count,
            "last_x_days": self.last_x_days,
        }

    @staticmethod
    def from_dict(data: dict) -> Flow:
        return Flow(
            podcast_rss_url=data["podcast_rss_url"],
            most_recent_count=data.get("most_recent_count", 3),
            last_x_days=data.get("last_x_days"),
        )


# ---------------------------------------------------------------------------
# Playlist Item
# ---------------------------------------------------------------------------

@dataclass
class PlaylistItem:
    """
    A manually added item in the user's playlist.

    Can be either a podcast episode (has podcast_rss_url + episode_guid)
    or a local audio file (has local_file_path).
    """
    title: str
    source_label: str                 # Podcast name or filename shown in UI
    file_size_bytes: Optional[int]
    duration_seconds: Optional[int]

    # Exactly one of these pairs will be set:
    podcast_rss_url: Optional[str] = None   # Set for podcast episodes
    episode_guid: Optional[str] = None      # Set for podcast episodes
    episode_url: Optional[str] = None       # Download URL for podcast episodes
    local_file_path: Optional[str] = None   # Set for drag-and-dropped files

    def is_local_file(self) -> bool:
        """Returns True if this item came from a local file drag-and-drop."""
        return self.local_file_path is not None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "source_label": self.source_label,
            "file_size_bytes": self.file_size_bytes,
            "duration_seconds": self.duration_seconds,
            "podcast_rss_url": self.podcast_rss_url,
            "episode_guid": self.episode_guid,
            "episode_url": self.episode_url,
            "local_file_path": self.local_file_path,
        }

    @staticmethod
    def from_dict(data: dict) -> PlaylistItem:
        return PlaylistItem(
            title=data["title"],
            source_label=data["source_label"],
            file_size_bytes=data.get("file_size_bytes"),
            duration_seconds=data.get("duration_seconds"),
            podcast_rss_url=data.get("podcast_rss_url"),
            episode_guid=data.get("episode_guid"),
            episode_url=data.get("episode_url"),
            local_file_path=data.get("local_file_path"),
        )


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@dataclass
class Profile:
    """
    A complete user profile.

    Contains everything needed to define one user's desired device state.
    This is what gets exported to / imported from a .swimsync file.
    """
    name: str
    podcasts: list[Podcast] = field(default_factory=list)
    flows: list[Flow] = field(default_factory=list)
    playlist: list[PlaylistItem] = field(default_factory=list)
    device_configs: list[DeviceConfig] = field(default_factory=lambda: list(DEFAULT_DEVICES))

    def get_podcast(self, rss_url: str) -> Optional[Podcast]:
        """Return the Podcast with the given RSS URL, or None."""
        for podcast in self.podcasts:
            if podcast.rss_url == rss_url:
                return podcast
        return None

    def get_flow(self, rss_url: str) -> Optional[Flow]:
        """Return the Flow for the given podcast RSS URL, or None."""
        for flow in self.flows:
            if flow.podcast_rss_url == rss_url:
                return flow
        return None

    def get_device_config(self, drive_label: str) -> Optional[DeviceConfig]:
        """Return the DeviceConfig matching the given drive label, or None."""
        for device in self.device_configs:
            if device.drive_label == drive_label:
                return device
        return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "podcasts": [p.to_dict() for p in self.podcasts],
            "flows": [f.to_dict() for f in self.flows],
            "playlist": [item.to_dict() for item in self.playlist],
            "device_configs": [d.to_dict() for d in self.device_configs],
        }

    @staticmethod
    def from_dict(data: dict) -> Profile:
        return Profile(
            name=data["name"],
            podcasts=[Podcast.from_dict(p) for p in data.get("podcasts", [])],
            flows=[Flow.from_dict(f) for f in data.get("flows", [])],
            playlist=[PlaylistItem.from_dict(i) for i in data.get("playlist", [])],
            device_configs=[DeviceConfig.from_dict(d) for d in data.get("device_configs", DEFAULT_DEVICES)],
        )
