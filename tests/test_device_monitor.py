"""
Tests for swimsync.core.device_monitor.

All tests mock psutil so no real USB device is required.

Run with: pytest tests/test_device_monitor.py -v
"""

from __future__ import annotations

import threading
from collections import namedtuple
from unittest.mock import patch

import pytest

from swimsync.core.device_monitor import (
    DEFAULT_POLL_INTERVAL,
    DeviceMonitor,
    MountedDevice,
    _fmt_bytes,
    _label_from_mountpoint,
    get_mounted_devices,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_Partition = namedtuple("Partition", ["device", "mountpoint", "fstype", "opts"])
_Usage = namedtuple("Usage", ["total", "used", "free", "percent"])


def _part(mountpoint: str) -> _Partition:
    return _Partition(device="/dev/disk2s1", mountpoint=mountpoint, fstype="msdos", opts="rw")


def _usage(total: int = 16_000_000_000, used: int = 4_000_000_000) -> _Usage:
    return _Usage(total=total, used=used, free=total - used, percent=used / total * 100)


SWIM_PRO = MountedDevice(
    drive_label="SWIM PRO",
    mount_point="/Volumes/SWIM PRO",
    capacity_bytes=16_000_000_000,
    used_bytes=4_000_000_000,
)

OPENSW = MountedDevice(
    drive_label="OpenSwim",
    mount_point="/Volumes/OpenSwim",
    capacity_bytes=4_000_000_000,
    used_bytes=1_000_000_000,
)


# ---------------------------------------------------------------------------
# _label_from_mountpoint
# ---------------------------------------------------------------------------

class TestLabelFromMountpoint:
    def test_macos_swim_pro(self):
        assert _label_from_mountpoint("/Volumes/SWIM PRO") == "SWIM PRO"

    def test_macos_opensw(self):
        assert _label_from_mountpoint("/Volumes/OpenSwim") == "OpenSwim"

    def test_trailing_slash_stripped(self):
        assert _label_from_mountpoint("/Volumes/SWIM PRO/") == "SWIM PRO"

    def test_linux_media_path(self):
        assert _label_from_mountpoint("/media/user/SWIM PRO") == "SWIM PRO"

    def test_single_component(self):
        assert _label_from_mountpoint("/Volumes/MyDrive") == "MyDrive"

    def test_root_returns_empty_string(self):
        assert _label_from_mountpoint("/") == ""


# ---------------------------------------------------------------------------
# get_mounted_devices
# ---------------------------------------------------------------------------

class TestGetMountedDevices:
    def test_returns_matching_device(self):
        partitions = [_part("/Volumes/SWIM PRO"), _part("/Volumes/Other")]
        with patch("psutil.disk_partitions", return_value=partitions), \
             patch("psutil.disk_usage", return_value=_usage()):
            result = get_mounted_devices({"SWIM PRO"})

        assert len(result) == 1
        assert result[0].drive_label == "SWIM PRO"
        assert result[0].mount_point == "/Volumes/SWIM PRO"

    def test_ignores_non_watched_partitions(self):
        partitions = [_part("/Volumes/SomeOtherDrive")]
        with patch("psutil.disk_partitions", return_value=partitions), \
             patch("psutil.disk_usage", return_value=_usage()):
            result = get_mounted_devices({"SWIM PRO"})

        assert result == []

    def test_returns_multiple_matching_devices(self):
        partitions = [_part("/Volumes/SWIM PRO"), _part("/Volumes/OpenSwim")]
        with patch("psutil.disk_partitions", return_value=partitions), \
             patch("psutil.disk_usage", return_value=_usage()):
            result = get_mounted_devices({"SWIM PRO", "OpenSwim"})

        assert {r.drive_label for r in result} == {"SWIM PRO", "OpenSwim"}

    def test_capacity_and_used_populated(self):
        partitions = [_part("/Volumes/SWIM PRO")]
        with patch("psutil.disk_partitions", return_value=partitions), \
             patch("psutil.disk_usage", return_value=_usage(total=16_000_000_000, used=4_000_000_000)):
            result = get_mounted_devices({"SWIM PRO"})

        assert result[0].capacity_bytes == 16_000_000_000
        assert result[0].used_bytes == 4_000_000_000

    def test_disk_usage_permission_error_gives_zero_capacity(self):
        partitions = [_part("/Volumes/SWIM PRO")]
        with patch("psutil.disk_partitions", return_value=partitions), \
             patch("psutil.disk_usage", side_effect=PermissionError("no access")):
            result = get_mounted_devices({"SWIM PRO"})

        assert len(result) == 1
        assert result[0].capacity_bytes == 0
        assert result[0].used_bytes == 0

    def test_disk_usage_os_error_gives_zero_capacity(self):
        partitions = [_part("/Volumes/SWIM PRO")]
        with patch("psutil.disk_partitions", return_value=partitions), \
             patch("psutil.disk_usage", side_effect=OSError("gone")):
            result = get_mounted_devices({"SWIM PRO"})

        assert len(result) == 1
        assert result[0].capacity_bytes == 0

    def test_psutil_error_returns_empty_list(self):
        with patch("psutil.disk_partitions", side_effect=RuntimeError("oops")):
            result = get_mounted_devices({"SWIM PRO"})

        assert result == []

    def test_empty_watched_labels_returns_empty(self):
        partitions = [_part("/Volumes/SWIM PRO")]
        with patch("psutil.disk_partitions", return_value=partitions), \
             patch("psutil.disk_usage", return_value=_usage()):
            result = get_mounted_devices(set())

        assert result == []

    def test_no_partitions_returns_empty(self):
        with patch("psutil.disk_partitions", return_value=[]):
            result = get_mounted_devices({"SWIM PRO"})

        assert result == []


# ---------------------------------------------------------------------------
# DeviceMonitor — initialisation
# ---------------------------------------------------------------------------

class TestDeviceMonitorInit:
    def test_default_state(self):
        monitor = DeviceMonitor()
        assert monitor.get_watched_labels() == set()
        assert monitor.get_currently_mounted() == {}
        assert not monitor.is_running

    def test_initial_labels_stored(self):
        monitor = DeviceMonitor(watched_labels={"SWIM PRO", "OpenSwim"})
        assert monitor.get_watched_labels() == {"SWIM PRO", "OpenSwim"}

    def test_default_poll_interval(self):
        monitor = DeviceMonitor()
        assert monitor._poll_interval == DEFAULT_POLL_INTERVAL

    def test_callbacks_default_to_none(self):
        monitor = DeviceMonitor()
        assert monitor.on_device_connected is None
        assert monitor.on_device_disconnected is None


# ---------------------------------------------------------------------------
# DeviceMonitor — watched label management
# ---------------------------------------------------------------------------

class TestDeviceMonitorWatchedLabels:
    def test_add_watched_label(self):
        monitor = DeviceMonitor()
        monitor.add_watched_label("SWIM PRO")
        assert "SWIM PRO" in monitor.get_watched_labels()

    def test_add_duplicate_label_is_safe(self):
        monitor = DeviceMonitor(watched_labels={"SWIM PRO"})
        monitor.add_watched_label("SWIM PRO")
        assert monitor.get_watched_labels() == {"SWIM PRO"}

    def test_remove_watched_label(self):
        monitor = DeviceMonitor(watched_labels={"SWIM PRO"})
        monitor.remove_watched_label("SWIM PRO")
        assert "SWIM PRO" not in monitor.get_watched_labels()

    def test_remove_nonexistent_label_is_safe(self):
        monitor = DeviceMonitor()
        monitor.remove_watched_label("NonExistent")  # must not raise
        assert monitor.get_watched_labels() == set()

    def test_set_watched_labels_replaces_all(self):
        monitor = DeviceMonitor(watched_labels={"SWIM PRO"})
        monitor.set_watched_labels({"OpenSwim", "MyDrive"})
        assert monitor.get_watched_labels() == {"OpenSwim", "MyDrive"}

    def test_set_watched_labels_to_empty(self):
        monitor = DeviceMonitor(watched_labels={"SWIM PRO"})
        monitor.set_watched_labels(set())
        assert monitor.get_watched_labels() == set()

    def test_get_watched_labels_returns_copy(self):
        monitor = DeviceMonitor(watched_labels={"SWIM PRO"})
        labels = monitor.get_watched_labels()
        labels.add("ExtraLabel")
        assert "ExtraLabel" not in monitor.get_watched_labels()


# ---------------------------------------------------------------------------
# DeviceMonitor — _check_devices (called directly, no thread)
# ---------------------------------------------------------------------------

class TestCheckDevices:
    def test_fires_connected_callback_for_new_device(self):
        connected = []
        monitor = DeviceMonitor(
            watched_labels={"SWIM PRO"},
            on_device_connected=connected.append,
        )
        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[SWIM_PRO],
        ):
            monitor._check_devices()

        assert len(connected) == 1
        assert connected[0].drive_label == "SWIM PRO"
        assert connected[0].mount_point == "/Volumes/SWIM PRO"

    def test_fires_disconnected_callback_when_device_removed(self):
        disconnected = []
        monitor = DeviceMonitor(
            watched_labels={"SWIM PRO"},
            on_device_disconnected=disconnected.append,
        )
        monitor._currently_mounted = {"SWIM PRO": SWIM_PRO}

        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[],
        ):
            monitor._check_devices()

        assert disconnected == ["SWIM PRO"]

    def test_no_callbacks_when_device_stays_mounted(self):
        connected = []
        disconnected = []
        monitor = DeviceMonitor(
            watched_labels={"SWIM PRO"},
            on_device_connected=connected.append,
            on_device_disconnected=disconnected.append,
        )
        monitor._currently_mounted = {"SWIM PRO": SWIM_PRO}

        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[SWIM_PRO],
        ):
            monitor._check_devices()

        assert connected == []
        assert disconnected == []

    def test_no_callbacks_when_nothing_mounted_and_nothing_prior(self):
        connected = []
        disconnected = []
        monitor = DeviceMonitor(
            watched_labels={"SWIM PRO"},
            on_device_connected=connected.append,
            on_device_disconnected=disconnected.append,
        )
        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[],
        ):
            monitor._check_devices()

        assert connected == []
        assert disconnected == []

    def test_multiple_devices_connect_at_once(self):
        connected = []
        monitor = DeviceMonitor(
            watched_labels={"SWIM PRO", "OpenSwim"},
            on_device_connected=connected.append,
        )
        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[SWIM_PRO, OPENSW],
        ):
            monitor._check_devices()

        assert len(connected) == 2
        assert {d.drive_label for d in connected} == {"SWIM PRO", "OpenSwim"}

    def test_connected_callback_exception_does_not_crash(self):
        def bad_callback(dev):
            raise RuntimeError("callback failure")

        monitor = DeviceMonitor(
            watched_labels={"SWIM PRO"},
            on_device_connected=bad_callback,
        )
        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[SWIM_PRO],
        ):
            monitor._check_devices()  # must not raise

    def test_disconnected_callback_exception_does_not_crash(self):
        def bad_callback(label):
            raise RuntimeError("callback failure")

        monitor = DeviceMonitor(
            watched_labels={"SWIM PRO"},
            on_device_disconnected=bad_callback,
        )
        monitor._currently_mounted = {"SWIM PRO": SWIM_PRO}

        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[],
        ):
            monitor._check_devices()  # must not raise

    def test_currently_mounted_updated_on_connect(self):
        monitor = DeviceMonitor(watched_labels={"SWIM PRO"})
        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[SWIM_PRO],
        ):
            monitor._check_devices()

        mounted = monitor.get_currently_mounted()
        assert "SWIM PRO" in mounted
        assert mounted["SWIM PRO"].mount_point == "/Volumes/SWIM PRO"

    def test_currently_mounted_cleared_on_disconnect(self):
        monitor = DeviceMonitor(watched_labels={"SWIM PRO"})
        monitor._currently_mounted = {"SWIM PRO": SWIM_PRO}

        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[],
        ):
            monitor._check_devices()

        assert monitor.get_currently_mounted() == {}

    def test_get_currently_mounted_returns_copy(self):
        monitor = DeviceMonitor(watched_labels={"SWIM PRO"})
        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[SWIM_PRO],
        ):
            monitor._check_devices()

        snapshot = monitor.get_currently_mounted()
        del snapshot["SWIM PRO"]
        assert "SWIM PRO" in monitor.get_currently_mounted()

    def test_no_connected_callback_set(self):
        # Should not raise when on_device_connected is None
        monitor = DeviceMonitor(watched_labels={"SWIM PRO"})
        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[SWIM_PRO],
        ):
            monitor._check_devices()

    def test_no_disconnected_callback_set(self):
        # Should not raise when on_device_disconnected is None
        monitor = DeviceMonitor(watched_labels={"SWIM PRO"})
        monitor._currently_mounted = {"SWIM PRO": SWIM_PRO}

        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[],
        ):
            monitor._check_devices()

    def test_device_swap_fires_both_callbacks(self):
        """Disconnecting one device and connecting another in the same poll cycle."""
        connected = []
        disconnected = []
        monitor = DeviceMonitor(
            watched_labels={"SWIM PRO", "OpenSwim"},
            on_device_connected=connected.append,
            on_device_disconnected=disconnected.append,
        )
        monitor._currently_mounted = {"SWIM PRO": SWIM_PRO}

        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[OPENSW],
        ):
            monitor._check_devices()

        assert len(connected) == 1
        assert connected[0].drive_label == "OpenSwim"
        assert disconnected == ["SWIM PRO"]


# ---------------------------------------------------------------------------
# DeviceMonitor — thread lifecycle
# ---------------------------------------------------------------------------

class TestDeviceMonitorThread:
    def test_start_creates_running_thread(self):
        monitor = DeviceMonitor(poll_interval=0.05)
        with patch("swimsync.core.device_monitor.get_mounted_devices", return_value=[]):
            monitor.start()
            try:
                assert monitor.is_running
            finally:
                monitor.stop()

    def test_stop_terminates_thread(self):
        monitor = DeviceMonitor(poll_interval=0.05)
        with patch("swimsync.core.device_monitor.get_mounted_devices", return_value=[]):
            monitor.start()
            monitor.stop()

        assert not monitor.is_running

    def test_start_is_idempotent(self):
        monitor = DeviceMonitor(poll_interval=0.05)
        with patch("swimsync.core.device_monitor.get_mounted_devices", return_value=[]):
            monitor.start()
            thread_id = id(monitor._thread)
            monitor.start()  # second call should not create a new thread
            assert id(monitor._thread) == thread_id
            monitor.stop()

    def test_stop_before_start_is_safe(self):
        monitor = DeviceMonitor()
        monitor.stop()  # must not raise

    def test_thread_is_daemon(self):
        monitor = DeviceMonitor(poll_interval=0.05)
        with patch("swimsync.core.device_monitor.get_mounted_devices", return_value=[]):
            monitor.start()
            assert monitor._thread.daemon is True
            monitor.stop()

    def test_callback_fires_via_background_thread(self):
        connected = []
        event = threading.Event()

        def on_connected(dev):
            connected.append(dev)
            event.set()

        monitor = DeviceMonitor(
            watched_labels={"SWIM PRO"},
            on_device_connected=on_connected,
            poll_interval=0.05,
        )
        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[SWIM_PRO],
        ):
            monitor.start()
            fired = event.wait(timeout=2.0)
            monitor.stop()

        assert fired, "on_device_connected was not called within the timeout"
        assert connected[0].drive_label == "SWIM PRO"

    def test_disconnect_callback_fires_via_background_thread(self):
        disconnected = []
        event = threading.Event()

        def on_disconnected(label):
            disconnected.append(label)
            event.set()

        monitor = DeviceMonitor(
            watched_labels={"SWIM PRO"},
            on_device_disconnected=on_disconnected,
            poll_interval=0.05,
        )
        monitor._currently_mounted = {"SWIM PRO": SWIM_PRO}

        with patch(
            "swimsync.core.device_monitor.get_mounted_devices",
            return_value=[],
        ):
            monitor.start()
            fired = event.wait(timeout=2.0)
            monitor.stop()

        assert fired, "on_device_disconnected was not called within the timeout"
        assert disconnected == ["SWIM PRO"]


# ---------------------------------------------------------------------------
# _fmt_bytes
# ---------------------------------------------------------------------------

class TestFmtBytes:
    def test_bytes(self):
        assert _fmt_bytes(512) == "512.0 B"

    def test_kilobytes(self):
        assert _fmt_bytes(1024) == "1.0 KB"

    def test_megabytes(self):
        assert _fmt_bytes(1024 * 1024) == "1.0 MB"

    def test_gigabytes(self):
        assert _fmt_bytes(1024 ** 3) == "1.0 GB"

    def test_terabytes(self):
        assert _fmt_bytes(1024 ** 4) == "1.0 TB"

    def test_multiple_gigabytes(self):
        assert _fmt_bytes(2 * 1024 ** 3) == "2.0 GB"

    def test_terabytes_value(self):
        assert _fmt_bytes(2 * 1024 ** 4) == "2.0 TB"
