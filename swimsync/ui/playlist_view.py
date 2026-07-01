"""
SwimSync Playlist view.

Displays the manually curated ordered list of episodes and local audio files
the user wants on the device. Items can be added from the episode browser
(podcast episodes) or via the + Add File button / drag-and-drop (local files).

Requirements §7: each item shows title, source, duration, file size, ▶ Preview,
and a Remove button. Total playlist size is shown at the bottom.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from PyQt6.QtCore import QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from swimsync.models.profile import PlaylistItem, Profile
from swimsync.utils.logger import get_logger

log = get_logger(__name__)

_AUDIO_FILTER = "Audio Files (*.mp3 *.flac *.wma *.wav *.aac *.m4a *.ape);;All Files (*)"
_UNSUPPORTED_WARNING = (
    "This file type might not be supported or has limitations — "
    "please check the device's manual for details."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return ""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_size(bytes_: Optional[int]) -> str:
    if bytes_ is None:
        return ""
    return f"{bytes_ / (1024 * 1024):.1f} MB"


def _total_size_str(items: list[PlaylistItem]) -> str:
    total = sum(i.file_size_bytes for i in items if i.file_size_bytes is not None)
    if total >= 1024 ** 3:
        return f"Total: {total / (1024 ** 3):.2f} GB"
    return f"Total: {total / (1024 * 1024):.1f} MB"


def _is_supported_type(path: str, profile: Profile) -> bool:
    """
    Return True if the file extension is in at least one device config's
    supported list. Returns True when no device configs are present
    (nothing to warn about).
    """
    if not profile.device_configs:
        return True
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    for device in profile.device_configs:
        if ext in [e.lower() for e in device.supported_extensions]:
            return True
    return False


# ---------------------------------------------------------------------------
# Playlist view
# ---------------------------------------------------------------------------

class PlaylistView(QWidget):
    """
    Playlist section of the main window.

    Args:
        profile: The active user profile (playlist mutated in-place on changes).
        on_profile_changed: Called with the mutated profile after any change.
    """

    def __init__(
        self,
        profile: Profile,
        on_profile_changed: Callable[[Profile], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._profile = profile
        self._on_profile_changed = on_profile_changed
        self._row_widgets: list[_PlaylistItemRowWidget] = []
        self.setAcceptDrops(True)
        self._build_ui()
        self._populate_rows()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        top = QHBoxLayout()
        top.addStretch()
        self._add_file_btn = QPushButton("+ Add File")
        self._add_file_btn.setObjectName("playlist_add_file_btn")
        self._add_file_btn.clicked.connect(self._open_file_picker)
        top.addWidget(self._add_file_btn)
        layout.addLayout(top)

        self._empty_label = QLabel(
            "No items in playlist. Add episodes from the Podcasts view, "
            "or use + Add File to add a local audio file."
        )
        self._empty_label.setObjectName("playlist_empty_label")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        layout.addWidget(self._empty_label)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("playlist_scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setSpacing(0)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.addStretch()
        self._scroll.setWidget(self._rows_container)
        layout.addWidget(self._scroll)

        self._total_label = QLabel("Total: 0.0 MB")
        self._total_label.setObjectName("playlist_total_label")
        self._total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._total_label)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_profile(self, profile: Profile) -> None:
        """Reload from an updated profile (e.g. after an episode is added elsewhere)."""
        self._profile = profile
        self._populate_rows()

    # ------------------------------------------------------------------
    # Row management
    # ------------------------------------------------------------------

    def _populate_rows(self) -> None:
        while self._rows_layout.count():
            it = self._rows_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._row_widgets.clear()

        for item in self._profile.playlist:
            row = _PlaylistItemRowWidget(item)
            row.remove_requested.connect(self._on_remove)
            self._rows_layout.insertWidget(self._rows_layout.count(), row)
            self._row_widgets.append(row)

        self._rows_layout.addStretch()
        self._update_empty_state()
        self._update_total_label()

    def _update_empty_state(self) -> None:
        has_items = len(self._row_widgets) > 0
        self._empty_label.setVisible(not has_items)
        self._scroll.setVisible(has_items)

    def _update_total_label(self) -> None:
        self._total_label.setText(_total_size_str(self._profile.playlist))

    # ------------------------------------------------------------------
    # Item removal
    # ------------------------------------------------------------------

    def _on_remove(self, item: PlaylistItem) -> None:
        self._profile.playlist = [i for i in self._profile.playlist if i is not item]
        self._on_profile_changed(self._profile)
        self._populate_rows()
        log.info(f"Removed from playlist: '{item.title}'")

    # ------------------------------------------------------------------
    # File picker
    # ------------------------------------------------------------------

    def _open_file_picker(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Add Audio File",
            "",
            _AUDIO_FILTER,
        )
        if path:
            self._add_file(path)

    # ------------------------------------------------------------------
    # Add local file (shared by picker and drag-and-drop)
    # ------------------------------------------------------------------

    def _add_file(self, path: str) -> None:
        if not _is_supported_type(path, self._profile):
            QMessageBox.warning(self, "Unsupported File Type", _UNSUPPORTED_WARNING)

        filename = os.path.basename(path)
        stem = os.path.splitext(filename)[0]
        try:
            size: Optional[int] = os.path.getsize(path)
        except OSError:
            size = None

        item = PlaylistItem(
            title=stem,
            source_label=filename,
            file_size_bytes=size,
            duration_seconds=None,
            local_file_path=path,
        )
        self._profile.playlist.append(item)
        self._on_profile_changed(self._profile)
        self._populate_rows()
        log.info(f"Added local file to playlist: '{filename}'")

    # ------------------------------------------------------------------
    # Drag-and-drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(
            url.isLocalFile() for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self._add_file(path)
        event.acceptProposedAction()


# ---------------------------------------------------------------------------
# Playlist item row widget
# ---------------------------------------------------------------------------

class _PlaylistItemRowWidget(QFrame):
    """
    A single row in the playlist: bold title, italic source, duration/size
    metadata, ▶ Preview button, and a Remove button.
    """

    remove_requested = pyqtSignal(object)  # PlaylistItem

    def __init__(
        self,
        item: PlaylistItem,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._item = item
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()

    @property
    def item(self) -> PlaylistItem:
        return self._item

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(8)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self._title_label = QLabel(self._item.title)
        self._title_label.setObjectName("playlist_item_title")
        self._title_label.setWordWrap(True)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        self._title_label.setFont(title_font)
        text_col.addWidget(self._title_label)

        self._source_label = QLabel(self._item.source_label)
        self._source_label.setObjectName("playlist_item_source")
        source_font = QFont()
        source_font.setItalic(True)
        source_font.setPointSize(10)
        self._source_label.setFont(source_font)
        text_col.addWidget(self._source_label)

        meta_parts: list[str] = []
        dur = _fmt_duration(self._item.duration_seconds)
        if dur:
            meta_parts.append(dur)
        sz = _fmt_size(self._item.file_size_bytes)
        if sz:
            meta_parts.append(sz)

        self._meta_label = QLabel(" · ".join(meta_parts) if meta_parts else "")
        self._meta_label.setObjectName("playlist_item_meta")
        meta_font = QFont()
        meta_font.setPointSize(10)
        self._meta_label.setFont(meta_font)
        text_col.addWidget(self._meta_label)

        outer.addLayout(text_col, stretch=1)

        self._preview_btn = QPushButton("▶ Preview")
        self._preview_btn.setObjectName("playlist_preview_btn")
        self._preview_btn.clicked.connect(self._on_preview)
        outer.addWidget(self._preview_btn)

        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setObjectName("playlist_remove_btn")
        self._remove_btn.clicked.connect(self._on_remove)
        outer.addWidget(self._remove_btn)

    def _on_preview(self) -> None:
        if self._item.local_file_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._item.local_file_path))
        elif self._item.episode_url:
            QDesktopServices.openUrl(QUrl(self._item.episode_url))

    def _on_remove(self) -> None:
        self.remove_requested.emit(self._item)
