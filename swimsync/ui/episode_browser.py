"""
SwimSync Episode Browser.

Displays a podcast's header (artwork, title, author, description,
stale/error indicators) followed by a paginated list of episodes.

Episodes are fetched from the RSS feed in a background thread. Ten
episodes are shown on first load; "Show 10 more" and "Show 50 more"
reveal more from the already-fetched list without a second network call.

Each episode row has a Preview button (opens the URL in the system player)
and an Add to Playlist button that persists the change through
on_profile_changed.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from swimsync.core.rss_client import FeedResult, fetch_feed
from swimsync.models.profile import Episode, PlaylistItem, Podcast, Profile
from swimsync.utils.logger import get_logger

log = get_logger(__name__)

_HEADER_ARTWORK_SIZE = 120
_INITIAL_COUNT = 10
_STALE_TEXT = "● No new episodes in 45+ days"
_ERROR_TEXT = "⚠ Feed unavailable"


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


# ---------------------------------------------------------------------------
# Episode Browser
# ---------------------------------------------------------------------------

class EpisodeBrowser(QWidget):
    """
    Episode list view for a single followed podcast.

    Args:
        podcast: The followed podcast to browse.
        profile: The active user profile (read for playlist state; mutated on add).
        on_profile_changed: Called with the mutated profile after an add.
        fetch_fn: Injectable RSS fetch callable (test seam).
    """

    back_requested = pyqtSignal()

    def __init__(
        self,
        podcast: Podcast,
        profile: Profile,
        on_profile_changed: Callable[[Profile], None],
        fetch_fn: Callable[[str], FeedResult] = fetch_feed,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._podcast = podcast
        self._profile = profile
        self._on_profile_changed = on_profile_changed
        self._fetch_fn = fetch_fn
        self._all_episodes: list[Episode] = []
        self._shown_count = 0
        self._loader: Optional[_ArtworkLoader] = None
        self._worker: Optional[_Worker] = None
        self._build_ui()
        self._load_feed()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # Back button row
        back_row = QHBoxLayout()
        self._back_btn = QPushButton("← Podcasts")
        self._back_btn.setObjectName("back_btn")
        self._back_btn.clicked.connect(self.back_requested)
        back_row.addWidget(self._back_btn)
        back_row.addStretch()
        layout.addLayout(back_row)

        # Header: artwork left, text right
        header = QHBoxLayout()
        header.setSpacing(16)

        self._artwork_label = QLabel()
        self._artwork_label.setObjectName("episode_browser_artwork")
        self._artwork_label.setFixedSize(_HEADER_ARTWORK_SIZE, _HEADER_ARTWORK_SIZE)
        self._artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._artwork_label.setText("♪")
        header.addWidget(self._artwork_label, alignment=Qt.AlignmentFlag.AlignTop)

        header_text = QVBoxLayout()
        header_text.setSpacing(4)

        self._title_label = QLabel(self._podcast.title)
        self._title_label.setObjectName("episode_browser_title")
        self._title_label.setWordWrap(True)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        self._title_label.setFont(title_font)
        header_text.addWidget(self._title_label)

        self._author_label = QLabel(self._podcast.author)
        self._author_label.setObjectName("episode_browser_author")
        author_font = QFont()
        author_font.setItalic(True)
        author_font.setPointSize(11)
        self._author_label.setFont(author_font)
        header_text.addWidget(self._author_label)

        self._desc_label = QLabel(self._podcast.description or "")
        self._desc_label.setObjectName("episode_browser_desc")
        self._desc_label.setWordWrap(True)
        desc_font = QFont()
        desc_font.setPointSize(10)
        self._desc_label.setFont(desc_font)
        header_text.addWidget(self._desc_label)

        self._indicator_label = QLabel("")
        self._indicator_label.setObjectName("episode_browser_indicator")
        header_text.addWidget(self._indicator_label)

        header.addLayout(header_text, stretch=1)
        layout.addLayout(header)

        # Loading / error status
        self._status_label = QLabel("Loading episodes…")
        self._status_label.setObjectName("episode_browser_status")
        layout.addWidget(self._status_label)

        # Scrollable episode list
        self._scroll = QScrollArea()
        self._scroll.setObjectName("episode_browser_scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._episodes_container = QWidget()
        self._episodes_layout = QVBoxLayout(self._episodes_container)
        self._episodes_layout.setSpacing(0)
        self._episodes_layout.setContentsMargins(0, 0, 0, 0)
        self._episodes_layout.addStretch()
        self._scroll.setWidget(self._episodes_container)
        layout.addWidget(self._scroll)

        # Load-more buttons
        btn_row = QHBoxLayout()
        self._show10_btn = QPushButton("Show 10 more")
        self._show10_btn.setObjectName("show10_btn")
        self._show10_btn.setEnabled(False)
        self._show10_btn.clicked.connect(lambda: self._show_more(10))
        btn_row.addWidget(self._show10_btn)

        self._show50_btn = QPushButton("Show 50 more")
        self._show50_btn.setObjectName("show50_btn")
        self._show50_btn.setEnabled(False)
        self._show50_btn.clicked.connect(lambda: self._show_more(50))
        btn_row.addWidget(self._show50_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        if self._podcast.artwork_url:
            self._load_artwork(self._podcast.artwork_url)

    # ------------------------------------------------------------------
    # Feed loading
    # ------------------------------------------------------------------

    def _load_feed(self) -> None:
        self._worker = _Worker(self._fetch_fn, self._podcast.rss_url)
        self._worker.finished.connect(self._on_feed_loaded)
        self._worker.start()

    def _on_feed_loaded(self, result: object) -> None:
        if not isinstance(result, FeedResult):
            self._status_label.setText("Failed to load episodes.")
            return

        if not result.ok:
            self._indicator_label.setText(_ERROR_TEXT)
            self._status_label.setText(f"Could not load feed: {result.error}")
            return

        self._all_episodes = result.episodes

        if result.is_stale:
            self._indicator_label.setText(_STALE_TEXT)

        if not self._all_episodes:
            self._status_label.setText("No episodes found in this feed.")
            return

        self._status_label.setText("")
        self._show_more(_INITIAL_COUNT)

    # ------------------------------------------------------------------
    # Episode pagination
    # ------------------------------------------------------------------

    def _show_more(self, count: int) -> None:
        start = self._shown_count
        end = min(start + count, len(self._all_episodes))

        for episode in self._all_episodes[start:end]:
            in_playlist = self._is_in_playlist(episode)
            row = _EpisodeRowWidget(episode, in_playlist=in_playlist)
            row.add_to_playlist_requested.connect(self._add_to_playlist)
            idx = self._episodes_layout.count() - 1  # insert before trailing stretch
            self._episodes_layout.insertWidget(idx, row)

        self._shown_count = end
        self._update_load_more_buttons()

    def _update_load_more_buttons(self) -> None:
        remaining = len(self._all_episodes) - self._shown_count
        self._show10_btn.setEnabled(remaining > 0)
        self._show50_btn.setEnabled(remaining > 0)

    # ------------------------------------------------------------------
    # Playlist management
    # ------------------------------------------------------------------

    def _is_in_playlist(self, episode: Episode) -> bool:
        return any(item.episode_guid == episode.guid for item in self._profile.playlist)

    def _add_to_playlist(self, episode: Episode) -> None:
        if self._is_in_playlist(episode):
            return
        item = PlaylistItem(
            title=episode.title,
            source_label=self._podcast.title,
            file_size_bytes=episode.file_size_bytes,
            duration_seconds=episode.duration_seconds,
            podcast_rss_url=self._podcast.rss_url,
            episode_guid=episode.guid,
            episode_url=episode.url,
        )
        self._profile.playlist.append(item)
        self._on_profile_changed(self._profile)
        log.info(f"Added to playlist: '{episode.title}'")

        for i in range(self._episodes_layout.count()):
            widget = self._episodes_layout.itemAt(i).widget()
            if isinstance(widget, _EpisodeRowWidget) and widget.episode.guid == episode.guid:
                widget.mark_in_playlist(True)

    # ------------------------------------------------------------------
    # Artwork loading
    # ------------------------------------------------------------------

    def _load_artwork(self, url: str) -> None:
        loader = _ArtworkLoader(url)
        loader.loaded.connect(self._on_artwork_loaded)
        loader.start()
        self._loader = loader

    def _on_artwork_loaded(self, url: str, data: bytes) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if pixmap.isNull():
            return
        self._artwork_label.setPixmap(
            pixmap.scaled(
                _HEADER_ARTWORK_SIZE, _HEADER_ARTWORK_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._artwork_label.setText("")


# ---------------------------------------------------------------------------
# Episode row widget
# ---------------------------------------------------------------------------

class _EpisodeRowWidget(QFrame):
    """
    A single episode row: title, metadata (date · duration · size),
    Preview button, and Add to Playlist / In Playlist button.
    """

    add_to_playlist_requested = pyqtSignal(object)  # Episode

    def __init__(
        self,
        episode: Episode,
        in_playlist: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._episode = episode
        self._in_playlist = in_playlist
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()

    @property
    def episode(self) -> Episode:
        return self._episode

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(8)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self._title_label = QLabel(self._episode.title)
        self._title_label.setObjectName("episode_title")
        self._title_label.setWordWrap(True)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        self._title_label.setFont(title_font)
        text_col.addWidget(self._title_label)

        meta_parts: list[str] = []
        if self._episode.publish_date:
            meta_parts.append(self._episode.publish_date)
        dur = _fmt_duration(self._episode.duration_seconds)
        if dur:
            meta_parts.append(dur)
        sz = _fmt_size(self._episode.file_size_bytes)
        if sz:
            meta_parts.append(sz)

        self._meta_label = QLabel(" · ".join(meta_parts) if meta_parts else "")
        self._meta_label.setObjectName("episode_meta")
        meta_font = QFont()
        meta_font.setItalic(True)
        meta_font.setPointSize(10)
        self._meta_label.setFont(meta_font)
        text_col.addWidget(self._meta_label)

        outer.addLayout(text_col, stretch=1)

        self._preview_btn = QPushButton("▶ Preview")
        self._preview_btn.setObjectName("preview_btn")
        self._preview_btn.clicked.connect(self._on_preview)
        outer.addWidget(self._preview_btn)

        self._add_btn = QPushButton()
        self._add_btn.setObjectName("add_to_playlist_btn")
        self._add_btn.clicked.connect(self._on_add_clicked)
        outer.addWidget(self._add_btn)

        self._apply_playlist_state()

    def mark_in_playlist(self, in_playlist: bool) -> None:
        self._in_playlist = in_playlist
        self._apply_playlist_state()

    def _apply_playlist_state(self) -> None:
        if self._in_playlist:
            self._add_btn.setText("✓ In Playlist")
            self._add_btn.setEnabled(False)
        else:
            self._add_btn.setText("+ Add to Playlist")
            self._add_btn.setEnabled(True)

    def _on_preview(self) -> None:
        QDesktopServices.openUrl(QUrl(self._episode.url))

    def _on_add_clicked(self) -> None:
        self.add_to_playlist_requested.emit(self._episode)


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _ArtworkLoader(QThread):
    """Fetches raw image bytes from a URL in a background thread."""

    loaded = pyqtSignal(str, bytes)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:
        try:
            import requests
            resp = requests.get(self._url, timeout=10)
            resp.raise_for_status()
            self.loaded.emit(self._url, resp.content)
        except Exception as exc:
            log.warning(f"Artwork fetch failed for {self._url}: {exc}")


class _Worker(QThread):
    """Runs a callable in a background thread and emits the result."""

    finished = pyqtSignal(object)

    def __init__(self, fn: Callable, *args) -> None:
        super().__init__()
        self._fn = fn
        self._args = args

    def run(self) -> None:
        try:
            result = self._fn(*self._args)
        except Exception as exc:
            log.error(f"Worker error: {exc}")
            result = None
        self.finished.emit(result)
