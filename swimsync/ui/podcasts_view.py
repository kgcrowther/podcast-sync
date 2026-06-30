"""
SwimSync Podcasts view.

Displays followed podcasts as a scrollable list of tiles. Each tile shows
artwork, title, author, a description excerpt, stale/error indicators, and
buttons for View Episodes and Add/Edit Flow.

The Follow Podcast dialog has two tabs: Search (iTunes API with expandable
Details panels) and RSS URL (validate then follow).

Artwork is fetched asynchronously and cached for the session lifetime.
Network calls (search, validate, artwork) run in background QThreads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from swimsync.core.podcast_search import (
    FeedValidationResult,
    PodcastSearchResult,
    SearchOutcome,
    search_podcasts,
    validate_rss_url,
)
from swimsync.models.profile import Podcast, Profile
from swimsync.utils.logger import get_logger

log = get_logger(__name__)

# Session-scoped artwork cache: artwork_url -> scaled QPixmap
_artwork_cache: dict[str, QPixmap] = {}

_TILE_ARTWORK_SIZE = 64   # pixels, square
_DETAIL_ARTWORK_SIZE = 80

_STALE_TEXT = "● No new episodes in 45+ days"
_ERROR_TEXT = "⚠ Feed unavailable"


@dataclass
class PodcastStatus:
    """Per-podcast display state derived from the last RSS check."""
    is_stale: bool = False
    has_error: bool = False


# ---------------------------------------------------------------------------
# Podcast tile widget
# ---------------------------------------------------------------------------

class PodcastTileWidget(QFrame):
    """
    A single followed-podcast tile.

    Signals:
        view_episodes_clicked: user clicked View Episodes
        flow_btn_clicked: user clicked Add Flow or Edit Flow
        unfollow_requested: user chose Unfollow from the context menu
    """

    view_episodes_clicked = pyqtSignal()
    flow_btn_clicked = pyqtSignal()
    unfollow_requested = pyqtSignal()

    def __init__(
        self,
        podcast: Podcast,
        has_flow: bool,
        status: PodcastStatus,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._podcast = podcast
        self._has_flow = has_flow
        self._status = status
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()
        self._apply_status()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(12)

        # Artwork
        self._artwork_label = QLabel()
        self._artwork_label.setObjectName("tile_artwork")
        self._artwork_label.setFixedSize(_TILE_ARTWORK_SIZE, _TILE_ARTWORK_SIZE)
        self._artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._artwork_label.setText("♪")
        outer.addWidget(self._artwork_label, alignment=Qt.AlignmentFlag.AlignTop)

        # Right column
        right = QVBoxLayout()
        right.setSpacing(2)

        self._title_label = QLabel(self._podcast.title)
        self._title_label.setObjectName("tile_title")
        self._title_label.setWordWrap(True)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(13)
        self._title_label.setFont(title_font)
        right.addWidget(self._title_label)

        self._author_label = QLabel(self._podcast.author)
        self._author_label.setObjectName("tile_author")
        author_font = QFont()
        author_font.setItalic(True)
        author_font.setPointSize(10)
        self._author_label.setFont(author_font)
        right.addWidget(self._author_label)

        words = self._podcast.description.split()
        excerpt = " ".join(words[:20]) + ("…" if len(words) > 20 else "")
        self._desc_label = QLabel(excerpt or "No description available.")
        self._desc_label.setObjectName("tile_description")
        self._desc_label.setWordWrap(True)
        desc_font = QFont()
        desc_font.setPointSize(10)
        self._desc_label.setFont(desc_font)
        right.addWidget(self._desc_label)

        self._indicator_label = QLabel("")
        self._indicator_label.setObjectName("tile_indicator")
        right.addWidget(self._indicator_label)

        btn_row = QHBoxLayout()
        self._view_episodes_btn = QPushButton("View Episodes")
        self._view_episodes_btn.setObjectName("view_episodes_btn")
        self._view_episodes_btn.clicked.connect(self.view_episodes_clicked)
        btn_row.addWidget(self._view_episodes_btn)

        self._flow_btn = QPushButton()
        self._flow_btn.setObjectName("flow_btn")
        self._flow_btn.clicked.connect(self.flow_btn_clicked)
        btn_row.addWidget(self._flow_btn)
        btn_row.addStretch()
        right.addLayout(btn_row)

        outer.addLayout(right, stretch=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def podcast(self) -> Podcast:
        return self._podcast

    def update_status(self, status: PodcastStatus, has_flow: bool) -> None:
        self._status = status
        self._has_flow = has_flow
        self._apply_status()

    def apply_artwork(self, pixmap: QPixmap) -> None:
        self._artwork_label.setPixmap(
            pixmap.scaled(
                _TILE_ARTWORK_SIZE, _TILE_ARTWORK_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._artwork_label.setText("")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_status(self) -> None:
        if self._status.is_stale:
            self._indicator_label.setText(_STALE_TEXT)
        elif self._status.has_error:
            self._indicator_label.setText(_ERROR_TEXT)
        else:
            self._indicator_label.setText("")
        self._flow_btn.setText("Edit Flow" if self._has_flow else "Add Flow")

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        action = menu.addAction(f'Unfollow "{self._podcast.title}"')
        if menu.exec(event.globalPos()) is action:
            self.unfollow_requested.emit()


# ---------------------------------------------------------------------------
# Podcasts view
# ---------------------------------------------------------------------------

class PodcastsView(QWidget):
    """
    Podcasts section of the main window.

    Displays followed podcasts as tiles. Stale/error state is passed in via
    `refresh_statuses()` — the view does not perform network I/O itself.

    Args:
        profile: The active user profile.
        on_profile_changed: Called with the mutated profile after follow/unfollow.
        search_fn: Injectable callable for iTunes search (test seam).
        validate_fn: Injectable callable for RSS validation (test seam).
    """

    podcast_selected = pyqtSignal(object)     # Podcast — View Episodes clicked
    add_flow_requested = pyqtSignal(object)   # Podcast — Add Flow clicked
    edit_flow_requested = pyqtSignal(object)  # Podcast — Edit Flow clicked

    def __init__(
        self,
        profile: Profile,
        on_profile_changed: Callable[[Profile], None],
        search_fn: Callable[[str], SearchOutcome] = search_podcasts,
        validate_fn: Callable[[str], FeedValidationResult] = validate_rss_url,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._profile = profile
        self._on_profile_changed = on_profile_changed
        self._search_fn = search_fn
        self._validate_fn = validate_fn
        self._statuses: dict[str, PodcastStatus] = {}
        self._tile_widgets: list[PodcastTileWidget] = []
        self._loaders: list[_ArtworkLoader] = []
        self._build_ui()
        self._populate_tiles()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        top = QHBoxLayout()
        self._filter_edit = QLineEdit()
        self._filter_edit.setObjectName("podcast_filter")
        self._filter_edit.setPlaceholderText("Search followed podcasts…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        top.addWidget(self._filter_edit)

        self._follow_btn = QPushButton("+ Follow Podcast")
        self._follow_btn.setObjectName("follow_podcast_btn")
        self._follow_btn.clicked.connect(self._open_follow_dialog)
        top.addWidget(self._follow_btn)
        layout.addLayout(top)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("podcast_scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._tiles_container = QWidget()
        self._tiles_layout = QVBoxLayout(self._tiles_container)
        self._tiles_layout.setSpacing(6)
        self._tiles_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll.setWidget(self._tiles_container)
        layout.addWidget(self._scroll)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_statuses(self, statuses: dict[str, PodcastStatus]) -> None:
        """Update stale/error indicators without rebuilding tiles."""
        self._statuses = dict(statuses)
        for tile in self._tile_widgets:
            status = self._statuses.get(tile.podcast.rss_url, PodcastStatus())
            has_flow = self._profile.get_flow(tile.podcast.rss_url) is not None
            tile.update_status(status, has_flow)

    def refresh_profile(self, profile: Profile) -> None:
        """Reload with an updated profile (e.g. after a profile switch)."""
        self._profile = profile
        self._populate_tiles()

    # ------------------------------------------------------------------
    # Tile management
    # ------------------------------------------------------------------

    def _populate_tiles(self) -> None:
        # Drop existing tiles from layout and list
        while self._tiles_layout.count():
            item = self._tiles_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._tile_widgets.clear()

        for podcast in self._profile.podcasts:
            status = self._statuses.get(podcast.rss_url, PodcastStatus())
            has_flow = self._profile.get_flow(podcast.rss_url) is not None
            tile = self._make_tile(podcast, has_flow, status)
            self._tiles_layout.addWidget(tile)
            self._tile_widgets.append(tile)
            self._load_artwork(tile)

        self._tiles_layout.addStretch()
        self._apply_filter(self._filter_edit.text())

    def _make_tile(
        self, podcast: Podcast, has_flow: bool, status: PodcastStatus
    ) -> PodcastTileWidget:
        tile = PodcastTileWidget(podcast, has_flow, status)
        tile.view_episodes_clicked.connect(
            lambda p=podcast: self.podcast_selected.emit(p)
        )
        tile.flow_btn_clicked.connect(
            lambda p=podcast, hf=has_flow: (
                self.edit_flow_requested.emit(p)
                if hf
                else self.add_flow_requested.emit(p)
            )
        )
        tile.unfollow_requested.connect(lambda p=podcast: self._unfollow(p))
        return tile

    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        for tile in self._tile_widgets:
            p = tile.podcast
            match = (
                not query
                or query in p.title.lower()
                or query in p.author.lower()
            )
            tile.setVisible(match)

    # ------------------------------------------------------------------
    # Artwork loading
    # ------------------------------------------------------------------

    def _load_artwork(self, tile: PodcastTileWidget) -> None:
        url = tile.podcast.artwork_url
        if not url:
            return
        if url in _artwork_cache:
            tile.apply_artwork(_artwork_cache[url])
            return
        loader = _ArtworkLoader(url)
        loader.loaded.connect(self._on_artwork_loaded)
        loader.start()
        self._loaders.append(loader)

    def _on_artwork_loaded(self, url: str, data: bytes) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if pixmap.isNull():
            return
        _artwork_cache[url] = pixmap
        for tile in self._tile_widgets:
            if tile.podcast.artwork_url == url:
                tile.apply_artwork(pixmap)

    # ------------------------------------------------------------------
    # Follow podcast
    # ------------------------------------------------------------------

    def _open_follow_dialog(self) -> None:
        dlg = FollowPodcastDialog(
            search_fn=self._search_fn,
            validate_fn=self._validate_fn,
            parent=self,
        )
        dlg.podcast_followed.connect(self._add_podcast)
        dlg.exec()

    def _add_podcast(self, podcast: Podcast) -> None:
        if any(p.rss_url == podcast.rss_url for p in self._profile.podcasts):
            log.info(f"Already following '{podcast.title}', skipping duplicate.")
            return
        self._profile.podcasts.append(podcast)
        self._on_profile_changed(self._profile)
        self._populate_tiles()
        log.info(f"Now following: '{podcast.title}'")

    # ------------------------------------------------------------------
    # Unfollow podcast
    # ------------------------------------------------------------------

    def _unfollow(self, podcast: Podcast) -> None:
        has_flow = self._profile.get_flow(podcast.rss_url) is not None
        playlist_count = sum(
            1 for item in self._profile.playlist
            if item.podcast_rss_url == podcast.rss_url
        )

        if has_flow or playlist_count:
            parts = []
            if has_flow:
                parts.append("an active flow")
            if playlist_count:
                n = playlist_count
                parts.append(f"{n} playlist item{'s' if n != 1 else ''}")
            detail = " and ".join(parts)
            if not self._confirm_unfollow(podcast, detail):
                return

        self._profile.flows = [
            f for f in self._profile.flows
            if f.podcast_rss_url != podcast.rss_url
        ]
        self._profile.playlist = [
            item for item in self._profile.playlist
            if item.podcast_rss_url != podcast.rss_url
        ]
        self._profile.podcasts = [
            p for p in self._profile.podcasts if p.rss_url != podcast.rss_url
        ]
        self._on_profile_changed(self._profile)
        self._populate_tiles()
        log.info(f"Unfollowed: '{podcast.title}'")

    def _confirm_unfollow(self, podcast: Podcast, detail: str) -> bool:
        answer = QMessageBox.question(
            self,
            "Unfollow Podcast",
            f'"{podcast.title}" has {detail}.\n\n'
            "Unfollowing will remove the associated flow and playlist items. "
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes


# ---------------------------------------------------------------------------
# Follow Podcast Dialog
# ---------------------------------------------------------------------------

class FollowPodcastDialog(QDialog):
    """
    Two-tab dialog for finding and following a new podcast.

    Search tab: iTunes search with expandable Details panels per result.
    RSS URL tab: paste a feed URL, validate, then follow.

    Emits `podcast_followed(Podcast)` and closes on user confirmation.
    """

    podcast_followed = pyqtSignal(object)  # Podcast

    def __init__(
        self,
        search_fn: Callable[[str], SearchOutcome] = search_podcasts,
        validate_fn: Callable[[str], FeedValidationResult] = validate_rss_url,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Follow Podcast")
        self.setMinimumWidth(560)
        self.setMinimumHeight(480)
        self._search_fn = search_fn
        self._validate_fn = validate_fn
        self._search_rows: list[_SearchResultRow] = []
        self._selected_result: Optional[PodcastSearchResult] = None
        self._validated_result: Optional[FeedValidationResult] = None
        self._validated_url: Optional[str] = None
        self._worker: Optional[_Worker] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._tabs.setObjectName("follow_tabs")
        self._tabs.addTab(self._build_search_tab(), "Search")
        self._tabs.addTab(self._build_rss_tab(), "RSS URL")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs)

    def _build_search_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setObjectName("search_query_edit")
        self._search_edit.setPlaceholderText("Search podcasts…")
        self._search_edit.returnPressed.connect(self._run_search)
        row.addWidget(self._search_edit)
        self._search_btn = QPushButton("Search")
        self._search_btn.setObjectName("search_btn")
        self._search_btn.clicked.connect(self._run_search)
        row.addWidget(self._search_btn)
        layout.addLayout(row)

        self._search_status = QLabel("")
        self._search_status.setObjectName("search_status_label")
        layout.addWidget(self._search_status)

        # Scroll area for result rows
        self._results_scroll = QScrollArea()
        self._results_scroll.setObjectName("results_scroll")
        self._results_scroll.setWidgetResizable(True)
        self._results_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._results_container = QWidget()
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setSpacing(0)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.addStretch()
        self._results_scroll.setWidget(self._results_container)
        layout.addWidget(self._results_scroll)

        self._follow_search_btn = QPushButton("Follow Selected")
        self._follow_search_btn.setObjectName("follow_search_btn")
        self._follow_search_btn.setEnabled(False)
        self._follow_search_btn.clicked.connect(self._follow_selected)
        layout.addWidget(self._follow_search_btn)

        return tab

    def _build_rss_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        row = QHBoxLayout()
        self._rss_edit = QLineEdit()
        self._rss_edit.setObjectName("rss_url_edit")
        self._rss_edit.setPlaceholderText("https://example.com/feed.rss")
        self._rss_edit.textChanged.connect(self._on_rss_url_changed)
        row.addWidget(self._rss_edit)
        self._validate_btn = QPushButton("Validate")
        self._validate_btn.setObjectName("validate_btn")
        self._validate_btn.setEnabled(False)
        self._validate_btn.clicked.connect(self._run_validate)
        row.addWidget(self._validate_btn)
        layout.addLayout(row)

        self._rss_status = QLabel("")
        self._rss_status.setObjectName("rss_status_label")
        self._rss_status.setWordWrap(True)
        layout.addWidget(self._rss_status)

        layout.addStretch()

        self._follow_rss_btn = QPushButton("Follow")
        self._follow_rss_btn.setObjectName("follow_rss_btn")
        self._follow_rss_btn.setEnabled(False)
        self._follow_rss_btn.clicked.connect(self._follow_from_rss)
        layout.addWidget(self._follow_rss_btn)

        return tab

    # ------------------------------------------------------------------
    # Tab lifecycle
    # ------------------------------------------------------------------

    def _on_tab_changed(self, _: int) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.quit()

    # ------------------------------------------------------------------
    # Search tab logic
    # ------------------------------------------------------------------

    def _run_search(self) -> None:
        query = self._search_edit.text().strip()
        if not query:
            return
        self._search_btn.setEnabled(False)
        self._follow_search_btn.setEnabled(False)
        self._selected_result = None
        self._search_status.setText("Searching…")
        self._clear_results()

        self._worker = _Worker(self._search_fn, query)
        self._worker.finished.connect(self._on_search_done)
        self._worker.start()

    def _on_search_done(self, outcome: object) -> None:
        self._search_btn.setEnabled(True)
        if not isinstance(outcome, SearchOutcome):
            self._search_status.setText("Search failed unexpectedly.")
            return
        if not outcome.ok:
            self._search_status.setText(f"Error: {outcome.error}")
            return
        if not outcome.results:
            self._search_status.setText("No results found.")
            return
        n = len(outcome.results)
        self._search_status.setText(f"{n} result{'s' if n != 1 else ''}")
        for result in outcome.results:
            self._add_result_row(result)

    def _clear_results(self) -> None:
        while self._results_layout.count() > 1:  # keep trailing stretch
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._search_rows.clear()

    def _add_result_row(self, result: PodcastSearchResult) -> None:
        row = _SearchResultRow(result)
        row.selected.connect(self._on_result_selected)
        row.expand_requested.connect(self._on_expand_requested)
        row.follow_requested.connect(self._follow_podcast)
        idx = self._results_layout.count() - 1  # insert before stretch
        self._results_layout.insertWidget(idx, row)
        self._search_rows.append(row)

    def _on_result_selected(self, result: PodcastSearchResult) -> None:
        self._selected_result = result
        self._follow_search_btn.setEnabled(True)

    def _on_expand_requested(self, requesting_row: _SearchResultRow) -> None:
        new_state = not requesting_row.is_expanded
        for row in self._search_rows:
            row.set_expanded(row is requesting_row and new_state)

    def _follow_selected(self) -> None:
        if self._selected_result:
            self._follow_podcast(self._selected_result)

    def _follow_podcast(self, result: PodcastSearchResult) -> None:
        podcast = Podcast(
            title=result.title,
            rss_url=result.rss_url,
            author=result.author,
            description=result.description or "",
            artwork_url=result.artwork_url,
            last_checked=None,
        )
        self.podcast_followed.emit(podcast)
        self.accept()

    # ------------------------------------------------------------------
    # RSS URL tab logic
    # ------------------------------------------------------------------

    def _on_rss_url_changed(self, text: str) -> None:
        self._validate_btn.setEnabled(bool(text.strip()))
        self._follow_rss_btn.setEnabled(False)
        self._validated_result = None
        self._validated_url = None
        self._rss_status.setText("")

    def _run_validate(self) -> None:
        url = self._rss_edit.text().strip()
        if not url:
            return
        self._validate_btn.setEnabled(False)
        self._follow_rss_btn.setEnabled(False)
        self._rss_status.setText("Validating…")

        self._worker = _Worker(self._validate_fn, url)
        self._worker.finished.connect(lambda res: self._on_validate_done(url, res))
        self._worker.start()

    def _on_validate_done(self, url: str, result: object) -> None:
        self._validate_btn.setEnabled(True)
        if not isinstance(result, FeedValidationResult):
            self._rss_status.setText("Validation failed unexpectedly.")
            return
        if not result.ok:
            self._rss_status.setText(f"Error: {result.error}")
            return
        self._validated_result = result
        self._validated_url = url
        summary = f"✓ {result.title}"
        if result.episode_count is not None:
            summary += f" — {result.episode_count} episodes"
        if result.most_recent_episode:
            summary += f'\nMost recent: "{result.most_recent_episode}"'
        self._rss_status.setText(summary)
        self._follow_rss_btn.setEnabled(True)

    def _follow_from_rss(self) -> None:
        if not self._validated_result or not self._validated_url:
            return
        podcast = Podcast(
            title=self._validated_result.title or self._validated_url,
            rss_url=self._validated_url,
            author=self._validated_result.author or "",
            description="",
            artwork_url=None,
            last_checked=None,
        )
        self.podcast_followed.emit(podcast)
        self.accept()


# ---------------------------------------------------------------------------
# Search result row (expandable)
# ---------------------------------------------------------------------------

class _SearchResultRow(QFrame):
    """
    A single search result with title (bold), author (italic), a Details
    button that toggles an inline expand panel, and a selected signal.
    """

    selected = pyqtSignal(object)          # PodcastSearchResult
    expand_requested = pyqtSignal(object)  # self
    follow_requested = pyqtSignal(object)  # PodcastSearchResult

    def __init__(
        self,
        result: PodcastSearchResult,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._result = result
        self._expanded = False
        self._loader: Optional[_ArtworkLoader] = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(0)

        # Header row: title + author on left, Details button on right
        header = QHBoxLayout()

        text_col = QVBoxLayout()
        self._title_label = QLabel(self._result.title)
        self._title_label.setObjectName("result_title")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(13)
        self._title_label.setFont(title_font)
        text_col.addWidget(self._title_label)

        self._author_label = QLabel(self._result.author)
        self._author_label.setObjectName("result_author")
        author_font = QFont()
        author_font.setItalic(True)
        author_font.setPointSize(10)
        self._author_label.setFont(author_font)
        text_col.addWidget(self._author_label)

        header.addLayout(text_col, stretch=1)

        self._details_btn = QPushButton("Details")
        self._details_btn.setObjectName("details_btn")
        self._details_btn.clicked.connect(self._on_details_clicked)
        header.addWidget(self._details_btn, alignment=Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)

        # Expand panel (hidden until Details clicked)
        self._expand_panel = QWidget()
        self._expand_panel.setObjectName("expand_panel")
        exp = QHBoxLayout(self._expand_panel)
        exp.setContentsMargins(0, 8, 0, 4)

        self._expand_artwork = QLabel()
        self._expand_artwork.setObjectName("expand_artwork")
        self._expand_artwork.setFixedSize(_DETAIL_ARTWORK_SIZE, _DETAIL_ARTWORK_SIZE)
        self._expand_artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._expand_artwork.setText("♪")
        exp.addWidget(self._expand_artwork, alignment=Qt.AlignmentFlag.AlignTop)

        detail_text = QVBoxLayout()
        desc = self._result.description or "No description available."
        self._expand_desc = QLabel(desc)
        self._expand_desc.setObjectName("expand_description")
        self._expand_desc.setWordWrap(True)
        detail_text.addWidget(self._expand_desc)

        meta_parts = []
        if self._result.episode_count is not None:
            meta_parts.append(f"{self._result.episode_count} episodes")
        if self._result.genre:
            meta_parts.append(self._result.genre)
        self._expand_meta = QLabel(" · ".join(meta_parts))
        self._expand_meta.setObjectName("expand_meta")
        detail_text.addWidget(self._expand_meta)

        self._expand_follow_btn = QPushButton("Follow")
        self._expand_follow_btn.setObjectName("expand_follow_btn")
        self._expand_follow_btn.clicked.connect(
            lambda: self.follow_requested.emit(self._result)
        )
        detail_text.addWidget(self._expand_follow_btn)
        detail_text.addStretch()
        exp.addLayout(detail_text, stretch=1)

        self._expand_panel.setVisible(False)
        outer.addWidget(self._expand_panel)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._expand_panel.setVisible(expanded)
        self._details_btn.setText("Hide" if expanded else "Details")
        if expanded and self._result.artwork_url:
            self._load_expand_artwork()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_details_clicked(self) -> None:
        self.selected.emit(self._result)
        self.expand_requested.emit(self)

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self._result)
        super().mousePressEvent(event)

    def _load_expand_artwork(self) -> None:
        url = self._result.artwork_url
        if not url:
            return
        if url in _artwork_cache:
            self._apply_expand_artwork(_artwork_cache[url])
            return
        self._loader = _ArtworkLoader(url)
        self._loader.loaded.connect(self._on_expand_artwork_loaded)
        self._loader.start()

    def _on_expand_artwork_loaded(self, url: str, data: bytes) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if not pixmap.isNull():
            _artwork_cache[url] = pixmap
            self._apply_expand_artwork(pixmap)

    def _apply_expand_artwork(self, pixmap: QPixmap) -> None:
        self._expand_artwork.setPixmap(
            pixmap.scaled(
                _DETAIL_ARTWORK_SIZE, _DETAIL_ARTWORK_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._expand_artwork.setText("")


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _ArtworkLoader(QThread):
    """Fetches raw image bytes from a URL in a background thread."""

    loaded = pyqtSignal(str, bytes)  # (url, raw_bytes)

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
