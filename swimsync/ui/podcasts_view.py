"""
SwimSync Podcasts view.

Displays the list of followed podcasts with stale/error indicators,
a filter bar, and a Follow Podcast button. Emits `podcast_selected`
when the user clicks a podcast row to open its episode browser.

Stale and error state are not computed here — the caller passes them in
via `refresh_statuses()` after checking feeds, keeping the view free of
network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
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

# Unicode prefixes painted into item text; styled via object name in stylesheets.
_STALE_PREFIX = "● "   # red dot
_ERROR_PREFIX = "⚠ "   # warning triangle

# Extra UserRole slot for status string ("stale" | "error" | None)
_STATUS_ROLE = Qt.ItemDataRole.UserRole + 1


@dataclass
class PodcastStatus:
    """Per-podcast display state derived from the last RSS check."""
    is_stale: bool = False
    has_error: bool = False


class PodcastsView(QWidget):
    """
    Podcasts section of the main window.

    Shows all followed podcasts from *profile*. Stale / error indicators
    are updated separately via `refresh_statuses()` so the view never
    performs network I/O itself.

    Args:
        profile: The active user profile.
        on_profile_changed: Called with the mutated profile after any
            follow or unfollow so the caller can persist it.
        search_fn: Injectable callable for iTunes search (test seam).
        validate_fn: Injectable callable for RSS validation (test seam).
    """

    podcast_selected = pyqtSignal(object)  # Podcast

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
        self._build_ui()
        self._populate_list()

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

        self._list = QListWidget()
        self._list.setObjectName("podcast_list")
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._list)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_statuses(self, statuses: dict[str, PodcastStatus]) -> None:
        """Replace per-podcast stale/error indicators and rebuild the list."""
        self._statuses = dict(statuses)
        self._populate_list()

    def refresh_profile(self, profile: Profile) -> None:
        """Reload the view when the profile has changed externally."""
        self._profile = profile
        self._populate_list()

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def _populate_list(self) -> None:
        self._list.clear()
        for podcast in self._profile.podcasts:
            self._list.addItem(self._make_item(podcast))
        self._apply_filter(self._filter_edit.text())

    def _make_item(self, podcast: Podcast) -> QListWidgetItem:
        status = self._statuses.get(podcast.rss_url, PodcastStatus())
        if status.is_stale:
            prefix = _STALE_PREFIX
            flag = "stale"
        elif status.has_error:
            prefix = _ERROR_PREFIX
            flag = "error"
        else:
            prefix = ""
            flag = None

        lines = [f"{prefix}{podcast.title}"]
        if podcast.author:
            lines.append(podcast.author)

        item = QListWidgetItem("\n".join(lines))
        item.setData(Qt.ItemDataRole.UserRole, podcast)
        item.setData(_STATUS_ROLE, flag)
        return item

    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            podcast: Podcast = item.data(Qt.ItemDataRole.UserRole)
            match = (
                not query
                or query in podcast.title.lower()
                or query in podcast.author.lower()
            )
            item.setHidden(not match)

    # ------------------------------------------------------------------
    # Podcast selection
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        podcast: Podcast = item.data(Qt.ItemDataRole.UserRole)
        if podcast:
            log.info(f"Podcast selected: '{podcast.title}'")
            self.podcast_selected.emit(podcast)

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
        self._populate_list()
        log.info(f"Now following: '{podcast.title}'")

    # ------------------------------------------------------------------
    # Unfollow podcast (context menu)
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if not item:
            return
        podcast: Podcast = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        unfollow_action = menu.addAction(f"Unfollow “{podcast.title}”")
        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen is unfollow_action:
            self._unfollow(podcast)

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
        self._populate_list()
        log.info(f"Unfollowed: '{podcast.title}'")

    def _confirm_unfollow(self, podcast: Podcast, detail: str) -> bool:
        """Show a confirmation dialog. Returns True if the user confirmed."""
        answer = QMessageBox.question(
            self,
            "Unfollow Podcast",
            f"“{podcast.title}” has {detail}.\n\n"
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

    Search tab: query the iTunes Search API, pick a result, follow.
    RSS URL tab: paste a feed URL, validate it, follow.

    Connect `podcast_followed` before calling `exec()`. The signal is
    emitted (and the dialog closed via `accept()`) when the user confirms.
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
        self.setMinimumWidth(520)
        self.setMinimumHeight(420)
        self._search_fn = search_fn
        self._validate_fn = validate_fn
        self._search_results: list[PodcastSearchResult] = []
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

        self._results_list = QListWidget()
        self._results_list.setObjectName("search_results_list")
        self._results_list.itemSelectionChanged.connect(self._on_result_selection_changed)
        layout.addWidget(self._results_list)

        self._follow_search_btn = QPushButton("Follow Selected")
        self._follow_search_btn.setObjectName("follow_search_btn")
        self._follow_search_btn.setEnabled(False)
        self._follow_search_btn.clicked.connect(self._follow_from_search)
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
        self._results_list.clear()
        self._search_results = []
        self._search_status.setText("Searching…")

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
        self._search_results = outcome.results
        if not outcome.results:
            self._search_status.setText("No results found.")
            return
        n = len(outcome.results)
        self._search_status.setText(f"{n} result{'s' if n != 1 else ''}")
        for result in outcome.results:
            item = QListWidgetItem(f"{result.title}\n{result.author}")
            item.setData(Qt.ItemDataRole.UserRole, result)
            self._results_list.addItem(item)

    def _on_result_selection_changed(self) -> None:
        self._follow_search_btn.setEnabled(bool(self._results_list.selectedItems()))

    def _follow_from_search(self) -> None:
        items = self._results_list.selectedItems()
        if not items:
            return
        result: PodcastSearchResult = items[0].data(Qt.ItemDataRole.UserRole)
        podcast = Podcast(
            title=result.title,
            rss_url=result.rss_url,
            author=result.author,
            description="",
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
        # Any URL edit invalidates a prior successful validation.
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
            self._follow_rss_btn.setEnabled(False)
            return
        self._validated_result = result
        self._validated_url = url
        summary = f"✓ {result.title}"
        if result.episode_count is not None:
            summary += f" — {result.episode_count} episodes"
        if result.most_recent_episode:
            summary += f"\nMost recent: “{result.most_recent_episode}”"
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
# Background worker
# ---------------------------------------------------------------------------

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
