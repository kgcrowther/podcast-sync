"""
SwimSync Flows view.

Lists all configured flows (one per podcast). Each row shows the podcast
name, the rule summary, and stale/error indicators. An Edit button on each
row opens the flow configuration dialog.

The + Add Flow button opens a podcast-picker dialog (podcasts without a flow),
then chains to the config dialog.

FlowsView also exposes open_add_flow(podcast) and open_edit_flow(podcast)
so that main_window can route the Add/Edit Flow tile buttons directly.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from swimsync.models.profile import Flow, Podcast, Profile
from swimsync.utils.logger import get_logger

log = get_logger(__name__)

_DEFAULT_MOST_RECENT = 3
_DEFAULT_LAST_X_DAYS = 7
_STALE_TEXT = "● No new episodes in 45+ days"
_ERROR_TEXT = "⚠ Feed unavailable"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rule_summary(flow: Flow) -> str:
    """Human-readable description of a flow's sync criteria."""
    parts: list[str] = []
    if flow.most_recent_count is not None:
        n = flow.most_recent_count
        parts.append(f"{n} most recent episode{'s' if n != 1 else ''}")
    if flow.last_x_days is not None:
        parts.append(f"Last {flow.last_x_days} days")
    return " · ".join(parts) if parts else "No criteria set"


# ---------------------------------------------------------------------------
# Flows view
# ---------------------------------------------------------------------------

class FlowsView(QWidget):
    """
    Flows section of the main window.

    Args:
        profile: The active user profile (mutated in-place on add/edit/delete).
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
        self._row_widgets: list[_FlowRowWidget] = []
        self._statuses: dict[str, tuple[bool, bool]] = {}  # rss_url -> (is_stale, has_error)
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
        self._add_flow_btn = QPushButton("+ Add Flow")
        self._add_flow_btn.setObjectName("add_flow_btn")
        self._add_flow_btn.clicked.connect(self._open_picker)
        top.addWidget(self._add_flow_btn)
        layout.addLayout(top)

        self._empty_label = QLabel("No flows configured. Use + Add Flow to create one.")
        self._empty_label.setObjectName("flows_empty_label")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_label)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("flows_scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setSpacing(6)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.addStretch()
        self._scroll.setWidget(self._rows_container)
        layout.addWidget(self._scroll)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_statuses(self, statuses: dict[str, tuple[bool, bool]]) -> None:
        """Update stale/error indicators without rebuilding rows."""
        self._statuses = dict(statuses)
        for row in self._row_widgets:
            is_stale, has_error = self._statuses.get(row.rss_url, (False, False))
            row.update_status(is_stale=is_stale, has_error=has_error)

    def refresh_profile(self, profile: Profile) -> None:
        """Reload with an updated profile (e.g. after a profile switch)."""
        self._profile = profile
        self._populate_rows()

    def open_add_flow(self, podcast: Podcast) -> None:
        """Open the flow config dialog to create a new flow for *podcast*."""
        dlg = _FlowConfigDialog(podcast, existing_flow=None, parent=self)
        dlg.flow_saved.connect(self._on_flow_saved)
        dlg.exec()

    def open_edit_flow(self, podcast: Podcast) -> None:
        """Open the flow config dialog to edit the existing flow for *podcast*."""
        existing = self._profile.get_flow(podcast.rss_url)
        dlg = _FlowConfigDialog(podcast, existing_flow=existing, parent=self)
        dlg.flow_saved.connect(self._on_flow_saved)
        dlg.flow_deleted.connect(self._on_flow_deleted)
        dlg.exec()

    # ------------------------------------------------------------------
    # Row management
    # ------------------------------------------------------------------

    def _populate_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._row_widgets.clear()

        for flow in self._profile.flows:
            podcast = self._profile.get_podcast(flow.podcast_rss_url)
            if podcast is None:
                continue
            is_stale, has_error = self._statuses.get(flow.podcast_rss_url, (False, False))
            row = _FlowRowWidget(podcast, flow, is_stale=is_stale, has_error=has_error)
            row.edit_requested.connect(self.open_edit_flow)
            self._rows_layout.insertWidget(self._rows_layout.count(), row)
            self._row_widgets.append(row)

        self._rows_layout.addStretch()
        self._empty_label.setVisible(len(self._row_widgets) == 0)
        self._scroll.setVisible(len(self._row_widgets) > 0)
        self._update_add_btn()

    def _update_add_btn(self) -> None:
        self._add_flow_btn.setEnabled(bool(self._podcasts_without_flows()))

    def _podcasts_without_flows(self) -> list[Podcast]:
        flow_urls = {f.podcast_rss_url for f in self._profile.flows}
        return [p for p in self._profile.podcasts if p.rss_url not in flow_urls]

    # ------------------------------------------------------------------
    # Picker → Add Flow dialog
    # ------------------------------------------------------------------

    def _open_picker(self) -> None:
        candidates = self._podcasts_without_flows()
        if not candidates:
            return
        dlg = _PodcastPickerDialog(candidates, parent=self)
        dlg.podcast_picked.connect(self.open_add_flow)
        dlg.exec()

    # ------------------------------------------------------------------
    # Flow mutation handlers
    # ------------------------------------------------------------------

    def _on_flow_saved(self, flow: Flow) -> None:
        for i, f in enumerate(self._profile.flows):
            if f.podcast_rss_url == flow.podcast_rss_url:
                self._profile.flows[i] = flow
                break
        else:
            self._profile.flows.append(flow)
        self._on_profile_changed(self._profile)
        self._populate_rows()
        log.info(f"Flow saved for {flow.podcast_rss_url}: {_rule_summary(flow)}")

    def _on_flow_deleted(self, flow: Flow) -> None:
        self._profile.flows = [
            f for f in self._profile.flows
            if f.podcast_rss_url != flow.podcast_rss_url
        ]
        self._on_profile_changed(self._profile)
        self._populate_rows()
        log.info(f"Flow deleted for {flow.podcast_rss_url}")


# ---------------------------------------------------------------------------
# Flow row widget
# ---------------------------------------------------------------------------

class _FlowRowWidget(QFrame):
    """
    A single row in the flows list: podcast name, rule summary,
    status indicator, and an Edit button.
    """

    edit_requested = pyqtSignal(object)  # Podcast

    def __init__(
        self,
        podcast: Podcast,
        flow: Flow,
        is_stale: bool = False,
        has_error: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._podcast = podcast
        self._flow = flow
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()
        self.update_status(is_stale=is_stale, has_error=has_error)

    @property
    def rss_url(self) -> str:
        return self._podcast.rss_url

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self._podcast_label = QLabel(self._podcast.title)
        self._podcast_label.setObjectName("flow_row_podcast")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(13)
        self._podcast_label.setFont(title_font)
        text_col.addWidget(self._podcast_label)

        self._summary_label = QLabel(_rule_summary(self._flow))
        self._summary_label.setObjectName("flow_row_summary")
        text_col.addWidget(self._summary_label)

        self._indicator_label = QLabel("")
        self._indicator_label.setObjectName("flow_row_indicator")
        text_col.addWidget(self._indicator_label)

        outer.addLayout(text_col, stretch=1)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setObjectName("flow_row_edit_btn")
        self._edit_btn.clicked.connect(lambda: self.edit_requested.emit(self._podcast))
        outer.addWidget(self._edit_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    def update_status(self, is_stale: bool, has_error: bool) -> None:
        if is_stale:
            self._indicator_label.setText(_STALE_TEXT)
        elif has_error:
            self._indicator_label.setText(_ERROR_TEXT)
        else:
            self._indicator_label.setText("")


# ---------------------------------------------------------------------------
# Flow configuration dialog
# ---------------------------------------------------------------------------

class _FlowConfigDialog(QDialog):
    """
    Create or edit a flow for a single podcast.

    In add mode (existing_flow=None): Save creates a new Flow.
    In edit mode: Save updates the existing flow; Delete removes it.

    Emits flow_saved(Flow) on Save, flow_deleted(Flow) on Delete.
    """

    flow_saved = pyqtSignal(object)    # Flow
    flow_deleted = pyqtSignal(object)  # Flow

    def __init__(
        self,
        podcast: Podcast,
        existing_flow: Optional[Flow] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._podcast = podcast
        self._existing_flow = existing_flow
        mode = "Edit Flow" if existing_flow else "Add Flow"
        self.setWindowTitle(f"{mode} — {podcast.title}")
        self.setMinimumWidth(420)
        self._build_ui()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Podcast header
        self._title_label = QLabel(self._podcast.title)
        self._title_label.setObjectName("flow_config_title")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(14)
        self._title_label.setFont(title_font)
        layout.addWidget(self._title_label)

        self._author_label = QLabel(self._podcast.author)
        self._author_label.setObjectName("flow_config_author")
        author_font = QFont()
        author_font.setItalic(True)
        author_font.setPointSize(11)
        self._author_label.setFont(author_font)
        layout.addWidget(self._author_label)

        # Most recent N episodes — widget only, signal connected later
        mr_row = QHBoxLayout()
        self._most_recent_check = QCheckBox("Most recent")
        self._most_recent_check.setObjectName("most_recent_check")
        mr_row.addWidget(self._most_recent_check)

        self._most_recent_spin = QSpinBox()
        self._most_recent_spin.setObjectName("most_recent_spin")
        self._most_recent_spin.setRange(1, 100)
        self._most_recent_spin.setValue(_DEFAULT_MOST_RECENT)
        mr_row.addWidget(self._most_recent_spin)

        mr_row.addWidget(QLabel("episodes"))
        mr_row.addStretch()
        layout.addLayout(mr_row)

        # Last X days — widget only, signal connected later
        days_row = QHBoxLayout()
        self._last_days_check = QCheckBox("Last")
        self._last_days_check.setObjectName("last_days_check")
        days_row.addWidget(self._last_days_check)

        self._last_days_spin = QSpinBox()
        self._last_days_spin.setObjectName("last_days_spin")
        self._last_days_spin.setRange(1, 365)
        self._last_days_spin.setValue(_DEFAULT_LAST_X_DAYS)
        days_row.addWidget(self._last_days_spin)

        days_row.addWidget(QLabel("days"))
        days_row.addStretch()
        layout.addLayout(days_row)

        # Button row — created before setting initial check state so that
        # _on_criteria_changed (fired by setChecked) finds _save_btn ready
        btn_row = QHBoxLayout()

        if self._existing_flow:
            self._delete_btn = QPushButton("Delete Flow")
            self._delete_btn.setObjectName("flow_delete_btn")
            self._delete_btn.clicked.connect(self._on_delete)
            btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("flow_cancel_btn")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("flow_save_btn")
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)

        layout.addLayout(btn_row)

        # Connect criteria signals after _save_btn exists
        self._most_recent_check.toggled.connect(self._on_criteria_changed)
        self._last_days_check.toggled.connect(self._on_criteria_changed)

        # Set initial check state — signals fire here but _save_btn is ready
        if self._existing_flow:
            if self._existing_flow.most_recent_count is not None:
                self._most_recent_check.setChecked(True)
                self._most_recent_spin.setValue(self._existing_flow.most_recent_count)
            if self._existing_flow.last_x_days is not None:
                self._last_days_check.setChecked(True)
                self._last_days_spin.setValue(self._existing_flow.last_x_days)
        else:
            self._most_recent_check.setChecked(True)

        self._on_criteria_changed()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _on_criteria_changed(self) -> None:
        at_least_one = (
            self._most_recent_check.isChecked()
            or self._last_days_check.isChecked()
        )
        self._save_btn.setEnabled(at_least_one)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        flow = Flow(
            podcast_rss_url=self._podcast.rss_url,
            most_recent_count=(
                self._most_recent_spin.value()
                if self._most_recent_check.isChecked()
                else None
            ),
            last_x_days=(
                self._last_days_spin.value()
                if self._last_days_check.isChecked()
                else None
            ),
        )
        self.flow_saved.emit(flow)
        self.accept()

    def _on_delete(self) -> None:
        flow = self._existing_flow or Flow(podcast_rss_url=self._podcast.rss_url)
        self.flow_deleted.emit(flow)
        self.accept()


# ---------------------------------------------------------------------------
# Podcast picker dialog
# ---------------------------------------------------------------------------

class _PodcastPickerDialog(QDialog):
    """
    Shows podcasts that do not yet have a flow. The user selects one and
    clicks Add Flow, which emits podcast_picked and closes the dialog.
    """

    podcast_picked = pyqtSignal(object)  # Podcast

    def __init__(
        self,
        podcasts: list[Podcast],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._podcasts = podcasts
        self.setWindowTitle("Add Flow — Select Podcast")
        self.setMinimumWidth(360)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Select a podcast to add a flow:"))

        self._list = QListWidget()
        self._list.setObjectName("picker_list")
        for podcast in self._podcasts:
            item = QListWidgetItem(podcast.title)
            item.setData(Qt.ItemDataRole.UserRole, podcast)
            self._list.addItem(item)
        self._list.currentRowChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("picker_cancel_btn")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)

        self._select_btn = QPushButton("Add Flow")
        self._select_btn.setObjectName("picker_select_btn")
        self._select_btn.setDefault(True)
        self._select_btn.setEnabled(False)
        self._select_btn.clicked.connect(self._on_select)
        btn_row.addWidget(self._select_btn)

        layout.addLayout(btn_row)

    def _on_selection_changed(self, row: int) -> None:
        self._select_btn.setEnabled(row >= 0)

    def _on_select(self) -> None:
        item = self._list.currentItem()
        if item:
            podcast = item.data(Qt.ItemDataRole.UserRole)
            self.podcast_picked.emit(podcast)
            self.accept()
