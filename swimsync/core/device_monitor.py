"""
SwimSync device monitor.

Polls for mounted USB volumes and fires callbacks when a supported Shokz
device is mounted or unmounted.

Device detection is based on the drive label (the last path component of
the mount point under /Volumes/). The set of watched labels is provided
by the caller and typically comes from the active profile's device_configs.

Usage:
    monitor = DeviceMonitor(
        watched_labels={"SWIM PRO", "OpenSwim"},
        on_device_connected=lambda dev: ...,
        on_device_disconnected=lambda label: ...,
    )
    monitor.start()
    ...
    monitor.stop()
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

import psutil

from swimsync.utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_POLL_INTERVAL = 2.0  # seconds between polls


@dataclass
class MountedDevice:
    """A supported device that is currently mounted."""
    drive_label: str
    mount_point: str
    capacity_bytes: int
    used_bytes: int


def _label_from_mountpoint(mountpoint: str) -> str:
    """
    Extract the drive label from a mount point path.

    On macOS, USB volumes appear as /Volumes/<label>. The label is simply
    the last path component.

    Args:
        mountpoint: The filesystem mount point path.

    Returns:
        The drive label, e.g. "SWIM PRO". Empty string for the root path.
    """
    return mountpoint.rstrip("/").split("/")[-1]


def get_mounted_devices(watched_labels: set[str]) -> list[MountedDevice]:
    """
    Return currently mounted devices whose drive labels match any watched label.

    Args:
        watched_labels: Set of drive label strings to look for.

    Returns:
        List of MountedDevice objects for currently mounted matching devices.
    """
    found: list[MountedDevice] = []

    try:
        partitions = psutil.disk_partitions(all=False)
    except Exception as exc:
        log.error(f"Failed to list disk partitions: {exc}")
        return found

    for partition in partitions:
        label = _label_from_mountpoint(partition.mountpoint)

        if label not in watched_labels:
            continue

        try:
            usage = psutil.disk_usage(partition.mountpoint)
            capacity = usage.total
            used = usage.used
        except (PermissionError, OSError) as exc:
            log.warning(f"Could not read disk usage for {partition.mountpoint}: {exc}")
            capacity = 0
            used = 0

        log.info(
            f"Matched device '{label}' at {partition.mountpoint} "
            f"({_fmt_bytes(capacity)} total, {_fmt_bytes(used)} used)"
        )
        found.append(MountedDevice(
            drive_label=label,
            mount_point=partition.mountpoint,
            capacity_bytes=capacity,
            used_bytes=used,
        ))

    return found


class DeviceMonitor:
    """
    Polls for mounted USB volumes and fires callbacks on connect/disconnect.

    Runs a background daemon thread that checks for matching devices every
    poll_interval seconds. Callbacks are fired outside the internal lock so
    they may safely call any monitor method without deadlocking.

    Attributes:
        on_device_connected: Called with a MountedDevice when a watched
            device is first detected. Must be thread-safe.
        on_device_disconnected: Called with the drive label string when a
            previously-mounted watched device disappears. Must be thread-safe.
    """

    def __init__(
        self,
        watched_labels: set[str] | None = None,
        on_device_connected: Optional[Callable[[MountedDevice], None]] = None,
        on_device_disconnected: Optional[Callable[[str], None]] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ):
        self._watched_labels: set[str] = set(watched_labels or [])
        self._lock = threading.Lock()
        self.on_device_connected = on_device_connected
        self.on_device_disconnected = on_device_disconnected
        self._poll_interval = poll_interval
        self._currently_mounted: dict[str, MountedDevice] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling thread. Safe to call multiple times."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="SwimSync-DeviceMonitor",
            daemon=True,
        )
        self._thread.start()
        log.info("Device monitor started")

    def stop(self) -> None:
        """Stop the background polling thread and wait for it to exit."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._poll_interval + 1)
        log.info("Device monitor stopped")

    @property
    def is_running(self) -> bool:
        """Return True if the polling thread is currently active."""
        return bool(self._thread and self._thread.is_alive())

    def set_watched_labels(self, labels: set[str]) -> None:
        """Replace the full set of watched drive labels."""
        with self._lock:
            self._watched_labels = set(labels)
        log.info(f"Watched labels updated: {labels}")

    def add_watched_label(self, label: str) -> None:
        """Add a single drive label to the watched set."""
        with self._lock:
            self._watched_labels.add(label)
        log.info(f"Watching new drive label: '{label}'")

    def remove_watched_label(self, label: str) -> None:
        """Remove a single drive label from the watched set."""
        with self._lock:
            self._watched_labels.discard(label)
        log.info(f"Stopped watching drive label: '{label}'")

    def get_watched_labels(self) -> set[str]:
        """Return a copy of the current set of watched labels."""
        with self._lock:
            return set(self._watched_labels)

    def get_currently_mounted(self) -> dict[str, MountedDevice]:
        """Return a snapshot of currently mounted matching devices, keyed by label."""
        with self._lock:
            return dict(self._currently_mounted)

    # ------------------------------------------------------------------
    # Internal polling
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Background thread: poll for device changes every poll_interval seconds."""
        while not self._stop_event.wait(timeout=self._poll_interval):
            self._check_devices()

    def _check_devices(self) -> None:
        """
        Compare current mounted devices against the last known state and fire
        callbacks for any newly connected or disconnected devices.
        """
        with self._lock:
            watched = set(self._watched_labels)

        now_mounted = {
            dev.drive_label: dev
            for dev in get_mounted_devices(watched)
        }

        with self._lock:
            prev_mounted = dict(self._currently_mounted)
            self._currently_mounted = now_mounted

        for label, device in now_mounted.items():
            if label not in prev_mounted:
                log.info(
                    f"Device connected: '{label}' at {device.mount_point} "
                    f"({_fmt_bytes(device.capacity_bytes)} capacity)"
                )
                if self.on_device_connected:
                    try:
                        self.on_device_connected(device)
                    except Exception as exc:
                        log.error(f"Error in on_device_connected callback: {exc}")

        for label in prev_mounted:
            if label not in now_mounted:
                log.info(f"Device disconnected: '{label}'")
                if self.on_device_disconnected:
                    try:
                        self.on_device_disconnected(label)
                    except Exception as exc:
                        log.error(f"Error in on_device_disconnected callback: {exc}")


def _fmt_bytes(n: int) -> str:
    """Format a byte count as a human-readable string (e.g. '3.2 GB')."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"
