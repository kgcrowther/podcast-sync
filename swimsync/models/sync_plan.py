"""
SwimSync SyncPlan model.

Represents the result of a sync analysis — the complete set of
actions required to bring a device into alignment with a profile's
desired state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SyncAction:
    """
    A single file operation in a sync plan.

    Attributes:
        filename: The target filename on the device.
        source_url: Download URL for podcast episodes, or None for local files.
        local_file_path: Path to a local file for drag-and-drop items, or None.
        file_size_bytes: Expected file size in bytes, or None if unknown.
        title: Human-readable episode or file title for display in the UI.
        source_label: Podcast name or filename shown in the UI.
    """
    filename: str
    title: str
    source_label: str
    source_url: Optional[str] = None
    local_file_path: Optional[str] = None
    file_size_bytes: Optional[int] = None


@dataclass
class SyncPlan:
    """
    The complete set of actions required to synchronise a device.

    Attributes:
        to_add: Files that need to be downloaded and copied to the device.
        to_delete: Filenames of files that should be removed from the device.
        to_redownload: Files already on device but with wrong byte size
                       (e.g. truncated from a prior interrupted sync).
        device_path: The filesystem path to the mounted device.
        device_label: The drive label of the device (e.g. "SWIM PRO").
        device_capacity_bytes: Total reported device capacity in bytes.
        device_used_bytes: Bytes currently used on the device.
        desired_total_bytes: Total bytes of all desired-state files.
        storage_warning: True if desired state would exceed 90% of capacity.
        storage_warning_message: Human-readable warning, or None.
        profile_name: Name of the profile used to generate this plan.
    """
    to_add: list[SyncAction] = field(default_factory=list)
    to_delete: list[str] = field(default_factory=list)
    to_redownload: list[SyncAction] = field(default_factory=list)
    device_path: str = ""
    device_label: str = ""
    device_capacity_bytes: int = 0
    device_used_bytes: int = 0
    desired_total_bytes: int = 0
    storage_warning: bool = False
    storage_warning_message: Optional[str] = None
    profile_name: str = ""

    @property
    def is_empty(self) -> bool:
        """Return True if no changes are needed — device is already in sync."""
        return not self.to_add and not self.to_delete and not self.to_redownload

    @property
    def total_actions(self) -> int:
        """Return the total number of file operations in this plan."""
        return len(self.to_add) + len(self.to_delete) + len(self.to_redownload)

    def summary(self) -> str:
        """Return a human-readable one-line summary of the sync plan."""
        if self.is_empty:
            return "Device is already up to date — no changes needed."
        parts = []
        if self.to_add:
            parts.append(f"{len(self.to_add)} to add")
        if self.to_redownload:
            parts.append(f"{len(self.to_redownload)} to re-download")
        if self.to_delete:
            parts.append(f"{len(self.to_delete)} to delete")
        return ", ".join(parts)
