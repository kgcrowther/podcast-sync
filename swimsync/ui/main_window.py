"""
SwimSync main window.

The application shell: a left sidebar for navigation and a stacked content
area that switches between the six main views. Views start as placeholder
widgets and are swapped for real implementations by calling replace_view().

Device-mount events arrive from the DeviceMonitor background thread. They are
routed through Qt signals so the UI update always executes on the main thread.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from swimsync.core.device_monitor import DeviceMonitor, MountedDevice
from swimsync.core.profile_manager import (
    create_default_profile,
    load_last_profile,
    save_profile,
    set_last_profile_name,
)
from swimsync.models.profile import Profile
from swimsync.ui.episode_browser import EpisodeBrowser
from swimsync.ui.podcasts_view import PodcastsView
from swimsync.utils.logger import get_logger

log = get_logger(__name__)

# Sidebar section names in display order; index maps to QStackedWidget page.
NAV_SECTIONS: list[str] = [
    "Podcasts",
    "Flows",
    "Playlist",
    "Devices",
    "Profiles",
    "Log",
]


class MainWindow(QMainWindow):
    """
    SwimSync application shell.

    Pass *profile* and *device_monitor* in tests to avoid touching the
    filesystem or spawning a real polling thread.
    """

    # Emitted from the DeviceMonitor thread; auto-queued to the main thread.
    _sig_device_connected = pyqtSignal(object)   # MountedDevice
    _sig_device_disconnected = pyqtSignal(str)   # drive label

    def __init__(
        self,
        profile: Optional[Profile] = None,
        device_monitor: Optional[DeviceMonitor] = None,
    ) -> None:
        super().__init__()

        # Profile -------------------------------------------------------
        if profile is None:
            profile = load_last_profile()
            if profile is None:
                profile = create_default_profile("Default")
                set_last_profile_name(profile.name)
        self._profile = profile

        # Device monitor ------------------------------------------------
        # Wire Qt signals before creating the monitor so the callbacks are
        # ready even if a device is already mounted when the monitor starts.
        self._sig_device_connected.connect(self._on_device_connected)
        self._sig_device_disconnected.connect(self._on_device_disconnected)

        if device_monitor is None:
            device_monitor = DeviceMonitor(
                watched_labels={d.drive_label for d in self._profile.device_configs},
                on_device_connected=self._sig_device_connected.emit,
                on_device_disconnected=self._sig_device_disconnected.emit,
            )
        self._device_monitor = device_monitor

        self._build_ui()
        self._install_views()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _install_views(self) -> None:
        podcasts_view = PodcastsView(
            profile=self._profile,
            on_profile_changed=self._on_profile_mutated,
        )
        podcasts_view.podcast_selected.connect(self._on_podcast_selected)
        self.replace_view("Podcasts", podcasts_view)

    def _build_ui(self) -> None:
        self.setWindowTitle("SwimSync")
        self.resize(1000, 700)
        self.setMinimumSize(800, 500)

        central = QWidget()
        self.setCentralWidget(central)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        self._nav = QListWidget()
        self._nav.setFixedWidth(160)
        for name in NAV_SECTIONS:
            self._nav.addItem(name)
        layout.addWidget(self._nav)

        # Content area
        self._stack = QStackedWidget()
        for name in NAV_SECTIONS:
            self._stack.addWidget(_make_placeholder(name))
        layout.addWidget(self._stack, stretch=1)

        # Wire sidebar selection → content page switch
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def profile(self) -> Profile:
        """The currently active user profile."""
        return self._profile

    def current_section(self) -> str:
        """Return the name of the section currently shown in the content area."""
        return NAV_SECTIONS[self._nav.currentRow()]

    def navigate_to(self, section: str) -> None:
        """
        Switch to a named section.

        Raises ValueError if *section* is not a known NAV_SECTIONS entry.
        """
        self._nav.setCurrentRow(NAV_SECTIONS.index(section))

    def replace_view(self, section: str, widget: QWidget) -> None:
        """
        Swap the placeholder for *section* with a real view widget.

        The stacked widget page count stays at 6. If *section* is the
        currently displayed page, the new widget becomes visible immediately.
        """
        idx = NAV_SECTIONS.index(section)
        old = self._stack.widget(idx)
        self._stack.removeWidget(old)
        old.deleteLater()
        self._stack.insertWidget(idx, widget)
        if self._nav.currentRow() == idx:
            self._stack.setCurrentIndex(idx)

    def set_profile(self, profile: Profile) -> None:
        """Switch to a different profile and persist the last-used name."""
        self._profile = profile
        set_last_profile_name(profile.name)
        self._device_monitor.set_watched_labels(
            {d.drive_label for d in profile.device_configs}
        )
        log.info(f"Active profile changed to '{profile.name}'")

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def show(self) -> None:  # type: ignore[override]
        super().show()
        self._device_monitor.start()
        log.info("SwimSync started")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._device_monitor.stop()
        save_profile(self._profile)
        log.info("SwimSync closed")
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Profile mutation (called by views that modify the profile)
    # ------------------------------------------------------------------

    def _on_profile_mutated(self, profile: Profile) -> None:
        self._profile = profile
        save_profile(profile)

    # ------------------------------------------------------------------
    # View navigation callbacks
    # ------------------------------------------------------------------

    def _on_podcast_selected(self, podcast) -> None:
        browser = EpisodeBrowser(
            podcast=podcast,
            profile=self._profile,
            on_profile_changed=self._on_profile_mutated,
        )
        browser.back_requested.connect(self._on_browser_back)
        self.replace_view("Podcasts", browser)
        self.navigate_to("Podcasts")
        log.info(f"Opened episode browser for '{podcast.title}'")

    def _on_browser_back(self) -> None:
        self._install_views()

    # ------------------------------------------------------------------
    # Device event handlers (always called on the main thread)
    # ------------------------------------------------------------------

    def _on_device_connected(self, device: MountedDevice) -> None:
        log.info(
            f"Device connected: '{device.drive_label}' "
            f"at {device.mount_point}"
        )
        # TODO: show SyncDialog(device, self._profile, parent=self)

    def _on_device_disconnected(self, label: str) -> None:
        log.info(f"Device disconnected: '{label}'")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_placeholder(section: str) -> QLabel:
    """Centred label used until the real view for *section* is installed."""
    lbl = QLabel(section)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setObjectName(f"placeholder_{section.lower()}")
    return lbl
