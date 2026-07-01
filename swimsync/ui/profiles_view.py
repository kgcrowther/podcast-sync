"""
SwimSync Profiles view.

Lists all saved profiles. Supports creating new profiles, switching the
active profile, exporting the active profile to a .swimsync file, and
importing a .swimsync file.

Requirements §4: each profile is a named container for podcasts, flows,
playlist, and device configs. Multiple profiles allow different household
members to share one Mac with independent libraries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from swimsync.core.profile_manager import (
    create_default_profile,
    delete_profile,
    export_profile,
    import_profile,
    list_profiles,
    load_profile,
)
from swimsync.models.profile import Profile
from swimsync.utils.logger import get_logger

log = get_logger(__name__)

_SWIMSYNC_FILTER = "SwimSync Profile (*.swimsync);;All Files (*)"
_OVERWRITE_MSG = (
    "A profile with the same name already exists.\n\n"
    "Overwrite it with the imported profile?"
)


# ---------------------------------------------------------------------------
# Profiles view
# ---------------------------------------------------------------------------

class ProfilesView(QWidget):
    """
    Profiles section of the main window.

    Each argument ending in ``_fn`` is an injectable seam defaulting to the
    real profile-manager function. Pass mocks in tests to avoid the filesystem.

    Args:
        active_profile: The currently active profile.
        on_profile_switched: Called with the newly loaded Profile when the
            user switches to a different profile.
    """

    def __init__(
        self,
        active_profile: Profile,
        on_profile_switched: Callable[[Profile], None],
        list_profiles_fn: Callable[[], list[str]] = list_profiles,
        load_profile_fn: Callable[[str], Optional[Profile]] = load_profile,
        create_profile_fn: Callable[[str], Profile] = create_default_profile,
        delete_profile_fn: Callable[[str], bool] = delete_profile,
        export_profile_fn: Callable[[Profile, Path], bool] = export_profile,
        import_profile_fn: Callable[..., Optional[Profile]] = import_profile,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._active_profile = active_profile
        self._on_profile_switched = on_profile_switched
        self._list_profiles_fn = list_profiles_fn
        self._load_profile_fn = load_profile_fn
        self._create_profile_fn = create_profile_fn
        self._delete_profile_fn = delete_profile_fn
        self._export_profile_fn = export_profile_fn
        self._import_profile_fn = import_profile_fn
        self._row_widgets: list[_ProfileRowWidget] = []
        self._build_ui()
        self._populate_rows()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        top = QHBoxLayout()

        self._new_btn = QPushButton("+ New Profile")
        self._new_btn.setObjectName("profiles_new_btn")
        self._new_btn.clicked.connect(self._on_new_profile)
        top.addWidget(self._new_btn)

        self._export_btn = QPushButton("Export Profile")
        self._export_btn.setObjectName("profiles_export_btn")
        self._export_btn.clicked.connect(self._on_export)
        top.addWidget(self._export_btn)

        self._import_btn = QPushButton("Import Profile")
        self._import_btn.setObjectName("profiles_import_btn")
        self._import_btn.clicked.connect(self._on_import)
        top.addWidget(self._import_btn)

        top.addStretch()
        layout.addLayout(top)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("profiles_scroll")
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

    def refresh(self, active_profile: Profile) -> None:
        """Update the active-profile indicator without reinstalling the view."""
        self._active_profile = active_profile
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

        names = self._list_profiles_fn()
        is_last = len(names) == 1

        for name in names:
            is_active = (name == self._active_profile.name)
            row = _ProfileRowWidget(name, is_active=is_active, is_last=is_last)
            row.switch_requested.connect(self._on_switch)
            row.delete_requested.connect(self._on_delete)
            self._rows_layout.insertWidget(self._rows_layout.count(), row)
            self._row_widgets.append(row)

        self._rows_layout.addStretch()

    def _refresh_profile_list(self) -> None:
        self._populate_rows()

    # ------------------------------------------------------------------
    # New profile
    # ------------------------------------------------------------------

    def _on_new_profile(self) -> None:
        existing = self._list_profiles_fn()
        dlg = _NewProfileDialog(existing_names=existing, parent=self)
        dlg.profile_name_entered.connect(self._on_profile_name_confirmed)
        dlg.exec()

    def _on_profile_name_confirmed(self, name: str) -> None:
        self._create_profile_fn(name)
        self._refresh_profile_list()
        log.info(f"Created new profile: '{name}'")

    # ------------------------------------------------------------------
    # Switch
    # ------------------------------------------------------------------

    def _on_switch(self, name: str) -> None:
        profile = self._load_profile_fn(name)
        if profile is None:
            QMessageBox.warning(
                self, "Load Failed", f'Could not load profile "{name}".'
            )
            return
        log.info(f"Switching to profile: '{name}'")
        self._on_profile_switched(profile)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _on_export(self) -> None:
        default_name = f"{self._active_profile.name}.swimsync"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Profile", default_name, _SWIMSYNC_FILTER
        )
        if not path:
            return
        ok = self._export_profile_fn(self._active_profile, Path(path))
        if ok:
            QMessageBox.information(
                self, "Export Successful", f"Profile exported to:\n{path}"
            )
        else:
            QMessageBox.warning(self, "Export Failed", "Could not export the profile.")

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Profile", "", _SWIMSYNC_FILTER
        )
        if not path:
            return

        result = self._import_profile_fn(Path(path))
        if result is None:
            btn = QMessageBox.question(
                self, "Profile Already Exists", _OVERWRITE_MSG
            )
            if btn == QMessageBox.StandardButton.Yes:
                result = self._import_profile_fn(Path(path), True)
            if result is None:
                QMessageBox.warning(
                    self, "Import Failed", "Could not import the profile."
                )
                return

        self._refresh_profile_list()
        log.info(f"Imported profile: '{result.name}'")

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def _on_delete(self, name: str) -> None:
        self._delete_profile_fn(name)
        self._refresh_profile_list()
        log.info(f"Deleted profile: '{name}'")


# ---------------------------------------------------------------------------
# Profile row widget
# ---------------------------------------------------------------------------

class _ProfileRowWidget(QFrame):
    """
    A single row in the profiles list: name (bold), "(active)" label,
    Switch to button (disabled if already active), Delete button (disabled
    if active or the only profile).
    """

    switch_requested = pyqtSignal(str)   # profile name
    delete_requested = pyqtSignal(str)   # profile name

    def __init__(
        self,
        name: str,
        is_active: bool = False,
        is_last: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._is_active = is_active
        self._is_last = is_last
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_active(self) -> bool:
        return self._is_active

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(12)

        self._name_label = QLabel(self._name)
        self._name_label.setObjectName("profile_row_name")
        name_font = QFont()
        name_font.setBold(True)
        name_font.setPointSize(13)
        self._name_label.setFont(name_font)
        outer.addWidget(self._name_label)

        self._active_label = QLabel("(active)")
        self._active_label.setObjectName("profile_row_active")
        active_font = QFont()
        active_font.setItalic(True)
        active_font.setPointSize(11)
        self._active_label.setFont(active_font)
        self._active_label.setVisible(self._is_active)
        outer.addWidget(self._active_label)

        outer.addStretch()

        self._switch_btn = QPushButton("Switch to")
        self._switch_btn.setObjectName("profile_row_switch_btn")
        self._switch_btn.setEnabled(not self._is_active)
        self._switch_btn.clicked.connect(lambda: self.switch_requested.emit(self._name))
        outer.addWidget(self._switch_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("profile_row_delete_btn")
        self._delete_btn.setEnabled(not self._is_active and not self._is_last)
        self._delete_btn.clicked.connect(lambda: self.delete_requested.emit(self._name))
        outer.addWidget(self._delete_btn, alignment=Qt.AlignmentFlag.AlignVCenter)


# ---------------------------------------------------------------------------
# New profile dialog
# ---------------------------------------------------------------------------

class _NewProfileDialog(QDialog):
    """
    Prompt the user for a new profile name.

    Save is disabled until the name is non-empty and not a duplicate of an
    existing profile (case-insensitive). Emits profile_name_entered(str) on
    save; the caller is responsible for creating the profile on disk.
    """

    profile_name_entered = pyqtSignal(str)

    def __init__(
        self,
        existing_names: Optional[list[str]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._existing_lower = [n.lower() for n in (existing_names or [])]
        self.setWindowTitle("New Profile")
        self.setMinimumWidth(320)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Profile name:"))

        self._name_edit = QLineEdit()
        self._name_edit.setObjectName("new_profile_name_edit")
        self._name_edit.setPlaceholderText("e.g. Kenneth")
        layout.addWidget(self._name_edit)

        self._duplicate_warning = QLabel("A profile with this name already exists.")
        self._duplicate_warning.setObjectName("new_profile_duplicate_warning")
        self._duplicate_warning.setVisible(False)
        layout.addWidget(self._duplicate_warning)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("new_profile_cancel_btn")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("Create")
        self._save_btn.setObjectName("new_profile_save_btn")
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)

        layout.addLayout(btn_row)

        # Connect after _save_btn exists so _on_criteria_changed can reference it
        self._name_edit.textChanged.connect(self._on_criteria_changed)
        self._on_criteria_changed()

    def _on_criteria_changed(self) -> None:
        name = self._name_edit.text().strip()
        is_duplicate = name.lower() in self._existing_lower
        self._duplicate_warning.setVisible(bool(name) and is_duplicate)
        self._save_btn.setEnabled(bool(name) and not is_duplicate)

    def _on_save(self) -> None:
        name = self._name_edit.text().strip()
        self.profile_name_entered.emit(name)
        self.accept()
