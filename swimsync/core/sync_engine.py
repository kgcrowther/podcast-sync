"""
SwimSync sync engine.

Computes the desired state of a device from a Profile (flows + playlist),
compares it against the device's current contents, and returns a SyncPlan
describing exactly what needs to be added and deleted.

No files are downloaded or deleted here — this module only plans.
Execution is handled by the downloader and file_utils modules.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from swimsync.models.profile import Profile, PlaylistItem, Flow, Episode
from swimsync.models.sync_plan import SyncPlan, SyncAction
from swimsync.utils.file_utils import get_exact_file_size
from swimsync.utils.logger import get_logger

log = get_logger(__name__)

# Warn the user if desired state exceeds this fraction of device capacity
STORAGE_WARNING_THRESHOLD = 0.90


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_sync_plan(
    profile: Profile,
    device_path: str,
    device_label: str,
    episode_cache: dict[str, list[Episode]],
) -> SyncPlan:
    """
    Compute the full sync plan for a device given a profile.

    Args:
        profile: The user profile defining desired state.
        device_path: Filesystem path to the mounted device (e.g. "/Volumes/SWIM PRO").
        device_label: The drive label (e.g. "SWIM PRO").
        episode_cache: Dict mapping RSS feed URL to list of Episode objects
                       (most recent first). Used to evaluate flows without
                       making network requests from within this module.

    Returns:
        A SyncPlan describing all required add and delete operations.
    """
    log.info(f"Computing sync plan for profile '{profile.name}' on device '{device_label}'")

    plan = SyncPlan(
        device_path=device_path,
        device_label=device_label,
        profile_name=profile.name,
    )

    # Get device capacity info
    plan.device_capacity_bytes, plan.device_used_bytes = _get_device_storage(device_path)

    # Build the desired state: a dict of filename -> SyncAction
    desired: dict[str, SyncAction] = {}

    # 1. Add playlist items first (highest priority)
    playlist_actions = _actions_from_playlist(profile.playlist)
    for action in playlist_actions:
        desired[action.filename] = action

    # 2. Add flow items (lower priority — will not overwrite playlist items)
    flow_actions = _actions_from_flows(profile.flows, episode_cache)
    for action in flow_actions:
        if action.filename not in desired:
            desired[action.filename] = action

    # 3. Check storage threshold
    plan.desired_total_bytes = sum(
        a.file_size_bytes for a in desired.values() if a.file_size_bytes
    )
    capacity = plan.device_capacity_bytes
    if capacity > 0:
        ratio = plan.desired_total_bytes / capacity
        if ratio >= STORAGE_WARNING_THRESHOLD:
            plan.storage_warning = True
            plan.storage_warning_message = (
                f"Desired content ({_fmt_bytes(plan.desired_total_bytes)}) would use "
                f"{ratio:.0%} of device capacity ({_fmt_bytes(capacity)}), "
                f"which exceeds the 90% threshold. "
                f"Please remove items from your playlist or reduce flow episode counts."
            )
            log.warning(plan.storage_warning_message)

    # 4. Get current device contents: filename -> exact byte size
    current_device: dict[str, int] = _get_device_contents(device_path)

    # 5. Determine what to add, re-download, and delete
    desired_filenames = set(desired.keys())
    current_filenames = set(current_device.keys())

    # Files in desired state but not on device → add
    for filename in desired_filenames - current_filenames:
        plan.to_add.append(desired[filename])

    # Files on device but not in desired state → delete
    for filename in current_filenames - desired_filenames:
        plan.to_delete.append(filename)

    # Files in both — check byte size for corruption/truncation
    for filename in desired_filenames & current_filenames:
        action = desired[filename]
        if action.file_size_bytes is not None:
            device_size = current_device[filename]
            if device_size != action.file_size_bytes:
                log.warning(
                    f"Size mismatch for '{filename}': "
                    f"expected {action.file_size_bytes} bytes, "
                    f"found {device_size} bytes on device — will re-download"
                )
                plan.to_redownload.append(action)

    log.info(
        f"Sync plan complete: {len(plan.to_add)} to add, "
        f"{len(plan.to_redownload)} to re-download, "
        f"{len(plan.to_delete)} to delete"
    )

    return plan


# ---------------------------------------------------------------------------
# Desired state builders
# ---------------------------------------------------------------------------

def _actions_from_playlist(playlist: list[PlaylistItem]) -> list[SyncAction]:
    """
    Convert playlist items into SyncAction objects.

    Args:
        playlist: The profile's playlist items.

    Returns:
        List of SyncAction objects representing playlist items.
    """
    actions = []
    for item in playlist:
        filename = _safe_filename(item.title, item.episode_url or item.local_file_path or "")
        action = SyncAction(
            filename=filename,
            title=item.title,
            source_label=item.source_label,
            source_url=item.episode_url,
            local_file_path=item.local_file_path,
            file_size_bytes=item.file_size_bytes,
        )
        actions.append(action)
    return actions


def _actions_from_flows(
    flows: list[Flow],
    episode_cache: dict[str, list[Episode]],
) -> list[SyncAction]:
    """
    Evaluate all flows and return the resulting SyncAction objects.

    Args:
        flows: List of Flow objects from the profile.
        episode_cache: Dict mapping RSS URL to episode list (recent-first).

    Returns:
        List of SyncAction objects for all episodes matching any flow.
    """
    actions = []
    for flow in flows:
        episodes = episode_cache.get(flow.podcast_rss_url, [])
        matching = _episodes_matching_flow(flow, episodes)
        for episode in matching:
            filename = _safe_filename(episode.title, episode.url)
            action = SyncAction(
                filename=filename,
                title=episode.title,
                source_label=flow.podcast_rss_url,
                source_url=episode.url,
                file_size_bytes=episode.file_size_bytes,
            )
            actions.append(action)
    return actions


def _episodes_matching_flow(flow: Flow, episodes: list[Episode]) -> list[Episode]:
    """
    Return the subset of episodes that match a flow's criteria.

    When both most_recent_count and last_x_days are set, returns the
    union of both sets of matching episodes.

    Args:
        flow: The Flow defining the selection criteria.
        episodes: Full episode list for this podcast (most recent first).

    Returns:
        List of matching Episode objects (deduplicated, order preserved).
    """
    matched_guids: set[str] = set()
    result: list[Episode] = []

    def add(ep: Episode) -> None:
        if ep.guid not in matched_guids:
            matched_guids.add(ep.guid)
            result.append(ep)

    # Criterion 1: most recent N episodes
    if flow.most_recent_count is not None:
        for ep in episodes[:flow.most_recent_count]:
            add(ep)

    # Criterion 2: episodes published within last X days
    if flow.last_x_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=flow.last_x_days)
        for ep in episodes:
            if not ep.publish_date:
                continue
            try:
                pub = datetime.fromisoformat(ep.publish_date).replace(tzinfo=timezone.utc)
                if pub >= cutoff:
                    add(ep)
            except ValueError:
                continue

    return result


# ---------------------------------------------------------------------------
# Device inspection
# ---------------------------------------------------------------------------

def _get_device_contents(device_path: str) -> dict[str, int]:
    """
    List all files on the device and return their exact byte sizes.

    Only includes files in the root of the device path (not subdirectories),
    since Shokz devices expect audio files at the root level.

    Args:
        device_path: Filesystem path to the mounted device.

    Returns:
        Dict mapping filename to exact byte size.
    """
    contents: dict[str, int] = {}
    device = Path(device_path)

    if not device.exists():
        log.error(f"Device path does not exist: {device_path}")
        return contents

    for entry in device.iterdir():
        if entry.is_file() and not entry.name.startswith("."):
            size = get_exact_file_size(entry)
            if size is not None:
                contents[entry.name] = size

    log.info(f"Device contains {len(contents)} files at {device_path}")
    return contents


def _get_device_storage(device_path: str) -> tuple[int, int]:
    """
    Return the total capacity and used bytes of the device.

    Args:
        device_path: Filesystem path to the mounted device.

    Returns:
        Tuple of (total_bytes, used_bytes). Returns (0, 0) on error.
    """
    try:
        stat = os.statvfs(device_path)
        total = stat.f_frsize * stat.f_blocks
        free = stat.f_frsize * stat.f_bavail
        used = total - free
        return total, used
    except (OSError, AttributeError):
        log.warning(f"Could not read storage info for {device_path}")
        return 0, 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_filename(title: str, url: str) -> str:
    """
    Derive a safe filename for a file to be stored on the device.

    Prefers the original filename from the URL. Falls back to a sanitised
    version of the episode title with the URL's extension.

    Args:
        title: The episode or file title.
        url: The source URL or local file path.

    Returns:
        A filename string safe for use on a FAT32 filesystem.
    """
    if url:
        url_filename = Path(url).name
        if url_filename and "." in url_filename:
            return _sanitise(url_filename)

    # Fall back to title + .mp3
    ext = Path(url).suffix if url else ".mp3"
    return _sanitise(f"{title}{ext}")


def _sanitise(filename: str) -> str:
    """
    Remove or replace characters that are unsafe on FAT32 filesystems.

    Args:
        filename: The raw filename string.

    Returns:
        A sanitised filename string.
    """
    unsafe = r'\/:*?"<>|'
    result = filename
    for ch in unsafe:
        result = result.replace(ch, "_")
    # Collapse multiple underscores and strip leading/trailing spaces and dots
    result = result.strip(". ")
    return result or "audio_file"


def _fmt_bytes(n: int) -> str:
    """Format a byte count as a human-readable string (e.g. '3.2 GB')."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"
