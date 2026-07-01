"""
SwimSync Devices view.

Displays the list of device trigger configurations (drive label + supported
file types). Each row has Edit and Delete buttons. A + Add Device button
opens the config dialog in add mode.

Requirements §3: a drive label triggers sync when the volume mounts;
supported file types determine what SwimSync considers playable on that device.
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
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from swimsync.models.profile import DeviceConfig, Profile
from swimsync.utils.logger import get_logger

log = get_logger(__name__)

_ALL_EXTENSIONS: list[str] = ["mp3", "flac", "wma", "wav", "aac", "m4a", "ape"]
_EXTENSION_LABELS: dict[str, str] = {
    "mp3": "MP3",
    "flac": "FLAC",
    "wma": "WMA",
    "wav": "WAV",
    "aac": "AAC",
    "m4a": "M4A",
    "ape": "APE",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extensions_display(extensions: list[str]) -> str:
    """Canonical ordered, uppercase display string for a set of extensions."""
    ext_set = {e.lower() for e in extensions}
    ordered = [e for e in _ALL_EXTENSIONS if e in ext_set]
    return "  ".join(_EXTENSION_LABELS.get(e, e.upper()) for e in ordered)


# ---------------------------------------------------------------------------
# Devices view
# ---------------------------------------------------------------------------

class DevicesView(QWidget):
    """
    Devices section of the main window.

    Args:
        profile: The active user profile (device_configs mutated in-place).
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
        self._row_widgets: list[_DeviceRowWidget] = []
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
        self._add_btn = QPushButton("+ Add Device")
        self._add_btn.setObjectName("devices_add_btn")
        self._add_btn.clicked.connect(self._on_add_device)
        top.addWidget(self._add_btn)
        layout.addLayout(top)

        self._empty_label = QLabel(
            "No device configurations. Use + Add Device to add one."
        )
        self._empty_label.setObjectName("devices_empty_label")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_label)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("devices_scroll")
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

    def refresh_profile(self, profile: Profile) -> None:
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

        for config in self._profile.device_configs:
            row = _DeviceRowWidget(config)
            row.edit_requested.connect(self._on_edit_device)
            row.delete_requested.connect(self._on_delete_device)
            self._rows_layout.insertWidget(self._rows_layout.count(), row)
            self._row_widgets.append(row)

        self._rows_layout.addStretch()
        self._update_empty_state()

    def _update_empty_state(self) -> None:
        has_rows = len(self._row_widgets) > 0
        self._empty_label.setVisible(not has_rows)
        self._scroll.setVisible(has_rows)

    # ------------------------------------------------------------------
    # Add / edit / delete
    # ------------------------------------------------------------------

    def _on_add_device(self) -> None:
        existing_labels = [d.drive_label for d in self._profile.device_configs]
        dlg = _DeviceConfigDialog(
            existing_config=None,
            existing_labels=existing_labels,
            parent=self,
        )
        dlg.device_saved.connect(self._on_device_added)
        dlg.exec()

    def _on_edit_device(self, config: DeviceConfig) -> None:
        other_labels = [
            d.drive_label for d in self._profile.device_configs if d is not config
        ]
        dlg = _DeviceConfigDialog(
            existing_config=config,
            existing_labels=other_labels,
            parent=self,
        )
        dlg.device_saved.connect(
            lambda new_cfg, old=config: self._on_device_updated(old, new_cfg)
        )
        dlg.exec()

    def _on_delete_device(self, config: DeviceConfig) -> None:
        self._profile.device_configs = [
            d for d in self._profile.device_configs if d is not config
        ]
        self._on_profile_changed(self._profile)
        self._populate_rows()
        log.info(f"Device config deleted: '{config.drive_label}'")

    def _on_device_added(self, config: DeviceConfig) -> None:
        self._profile.device_configs.append(config)
        self._on_profile_changed(self._profile)
        self._populate_rows()
        log.info(f"Device config added: '{config.drive_label}'")

    def _on_device_updated(self, old: DeviceConfig, new: DeviceConfig) -> None:
        for i, d in enumerate(self._profile.device_configs):
            if d is old:
                self._profile.device_configs[i] = new
                break
        self._on_profile_changed(self._profile)
        self._populate_rows()
        log.info(f"Device config updated: '{old.drive_label}' → '{new.drive_label}'")


# ---------------------------------------------------------------------------
# Device row widget
# ---------------------------------------------------------------------------

class _DeviceRowWidget(QFrame):
    """
    A single row in the devices list: drive label (bold), supported file
    types, Edit button, Delete button.
    """

    edit_requested = pyqtSignal(object)    # DeviceConfig
    delete_requested = pyqtSignal(object)  # DeviceConfig

    def __init__(
        self,
        config: DeviceConfig,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()

    @property
    def config(self) -> DeviceConfig:
        return self._config

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self._label_label = QLabel(self._config.drive_label)
        self._label_label.setObjectName("device_row_label")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(13)
        self._label_label.setFont(title_font)
        text_col.addWidget(self._label_label)

        self._types_label = QLabel(_extensions_display(self._config.supported_extensions))
        self._types_label.setObjectName("device_row_types")
        types_font = QFont()
        types_font.setPointSize(10)
        self._types_label.setFont(types_font)
        text_col.addWidget(self._types_label)

        outer.addLayout(text_col, stretch=1)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setObjectName("device_row_edit_btn")
        self._edit_btn.clicked.connect(lambda: self.edit_requested.emit(self._config))
        outer.addWidget(self._edit_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("device_row_delete_btn")
        self._delete_btn.clicked.connect(lambda: self.delete_requested.emit(self._config))
        outer.addWidget(self._delete_btn, alignment=Qt.AlignmentFlag.AlignVCenter)


# ---------------------------------------------------------------------------
# Device config dialog
# ---------------------------------------------------------------------------

class _DeviceConfigDialog(QDialog):
    """
    Add or edit a device configuration.

    Save is disabled until the drive label is non-empty, not a duplicate of
    another existing config, and at least one file type is selected.

    Emits device_saved(DeviceConfig) on Save.
    """

    device_saved = pyqtSignal(object)  # DeviceConfig

    def __init__(
        self,
        existing_config: Optional[DeviceConfig] = None,
        existing_labels: Optional[list[str]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._existing_config = existing_config
        self._existing_labels_lower = [l.lower() for l in (existing_labels or [])]
        mode = "Edit Device" if existing_config else "Add Device"
        self.setWindowTitle(mode)
        self.setMinimumWidth(380)
        self._build_ui()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Drive label
        layout.addWidget(QLabel("Drive label:"))
        self._label_edit = QLineEdit()
        self._label_edit.setObjectName("device_label_edit")
        self._label_edit.setPlaceholderText("e.g. SWIM PRO")
        layout.addWidget(self._label_edit)

        self._duplicate_warning = QLabel("A device with this label already exists.")
        self._duplicate_warning.setObjectName("device_duplicate_warning")
        self._duplicate_warning.setVisible(False)
        layout.addWidget(self._duplicate_warning)

        # File type checkboxes
        layout.addWidget(QLabel("Supported file types:"))
        types_row = QHBoxLayout()
        self._checkboxes: dict[str, QCheckBox] = {}
        for ext in _ALL_EXTENSIONS:
            cb = QCheckBox(_EXTENSION_LABELS[ext])
            cb.setObjectName(f"device_type_{ext}")
            self._checkboxes[ext] = cb
            types_row.addWidget(cb)
        types_row.addStretch()
        layout.addLayout(types_row)

        # Buttons — created before setting initial state so _on_criteria_changed
        # can reference _save_btn when textChanged / toggled fires
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("device_cancel_btn")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("device_save_btn")
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)

        layout.addLayout(btn_row)

        # Connect signals after _save_btn exists
        self._label_edit.textChanged.connect(self._on_criteria_changed)
        for cb in self._checkboxes.values():
            cb.toggled.connect(self._on_criteria_changed)

        # Set initial state
        if self._existing_config:
            self._label_edit.setText(self._existing_config.drive_label)
            for ext, cb in self._checkboxes.items():
                cb.setChecked(
                    ext in {e.lower() for e in self._existing_config.supported_extensions}
                )

        self._on_criteria_changed()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _on_criteria_changed(self) -> None:
        label = self._label_edit.text().strip()
        is_duplicate = label.lower() in self._existing_labels_lower
        at_least_one = any(cb.isChecked() for cb in self._checkboxes.values())

        self._duplicate_warning.setVisible(bool(label) and is_duplicate)
        self._save_btn.setEnabled(bool(label) and not is_duplicate and at_least_one)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        label = self._label_edit.text().strip()
        extensions = [ext for ext, cb in self._checkboxes.items() if cb.isChecked()]
        config = DeviceConfig(drive_label=label, supported_extensions=extensions)
        self.device_saved.emit(config)
        self.accept()
