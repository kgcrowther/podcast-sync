"""
Behavior tests for swimsync/ui/devices_view.py.

Covers:
  - _extensions_display: ordering, uppercase, unknown extensions
  - DevicesView empty state (label, scroll, button)
  - DevicesView with configs: row count, labels, types display
  - refresh_profile: adds/removes rows
  - Add device: dialog wiring, new config appended, on_changed called
  - Edit device: dialog wiring, config replaced in-place, label can change
  - Delete device: config removed, on_changed called, row gone
  - _DeviceRowWidget: label, types text, edit/delete signals
  - _DeviceConfigDialog add mode: defaults, save disabled until valid,
    duplicate label check, save emits correct DeviceConfig
  - _DeviceConfigDialog edit mode: pre-fill, same-label allowed,
    duplicate check excludes self, save emits updated config
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication

from swimsync.models.profile import DeviceConfig, Profile
from swimsync.ui.devices_view import (
    DevicesView,
    _DeviceConfigDialog,
    _DeviceRowWidget,
    _ALL_EXTENSIONS,
    _extensions_display,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _cfg(label="SWIM PRO", exts=None) -> DeviceConfig:
    if exts is None:
        exts = ["mp3", "flac", "wma", "wav", "aac", "m4a", "ape"]
    return DeviceConfig(drive_label=label, supported_extensions=list(exts))


def _profile(*configs: DeviceConfig) -> Profile:
    return Profile(name="Test", device_configs=list(configs))


def _view(profile=None, on_changed=None) -> DevicesView:
    if profile is None:
        profile = _profile()
    if on_changed is None:
        on_changed = MagicMock()
    return DevicesView(profile=profile, on_profile_changed=on_changed)


def _rows(view: DevicesView) -> list[_DeviceRowWidget]:
    return list(view._row_widgets)


# ---------------------------------------------------------------------------
# _extensions_display
# ---------------------------------------------------------------------------

class TestExtensionsDisplay:
    def test_canonical_order_preserved(self):
        # Extensions are displayed in _ALL_EXTENSIONS order regardless of input order
        result = _extensions_display(["wav", "mp3", "aac"])
        parts = result.split()
        assert parts.index("MP3") < parts.index("WAV") < parts.index("AAC")

    def test_uppercase(self):
        result = _extensions_display(["mp3"])
        assert "MP3" in result
        assert "mp3" not in result

    def test_all_extensions(self):
        result = _extensions_display(["mp3", "flac", "wma", "wav", "aac", "m4a", "ape"])
        for label in ["MP3", "FLAC", "WMA", "WAV", "AAC", "M4A", "APE"]:
            assert label in result

    def test_single_extension(self):
        result = _extensions_display(["mp3"])
        assert result == "MP3"

    def test_empty_list(self):
        assert _extensions_display([]) == ""

    def test_unknown_extension_not_shown(self):
        # Extensions not in _ALL_EXTENSIONS are excluded from display
        result = _extensions_display(["mp3", "ogg"])
        assert "ogg" not in result.lower()
        assert "MP3" in result

    def test_case_insensitive_input(self):
        result = _extensions_display(["MP3", "FLAC"])
        assert "MP3" in result
        assert "FLAC" in result


# ---------------------------------------------------------------------------
# DevicesView — empty state
# ---------------------------------------------------------------------------

class TestDevicesViewEmpty:
    def test_empty_label_visible_when_no_configs(self, app):
        view = _view(profile=_profile())
        assert not view._empty_label.isHidden()

    def test_scroll_hidden_when_no_configs(self, app):
        view = _view(profile=_profile())
        assert view._scroll.isHidden()

    def test_no_row_widgets(self, app):
        view = _view(profile=_profile())
        assert _rows(view) == []

    def test_add_btn_always_enabled(self, app):
        view = _view(profile=_profile())
        assert view._add_btn.isEnabled()

    def test_empty_label_text(self, app):
        view = _view(profile=_profile())
        assert "Add Device" in view._empty_label.text()


# ---------------------------------------------------------------------------
# DevicesView — with configs
# ---------------------------------------------------------------------------

class TestDevicesViewWithConfigs:
    def setup_method(self):
        self.c1 = _cfg("SWIM PRO", ["mp3", "flac"])
        self.c2 = _cfg("OpenSwim", ["mp3", "wma"])

    def test_row_count_matches_config_count(self, app):
        view = _view(profile=_profile(self.c1, self.c2))
        assert len(_rows(view)) == 2

    def test_empty_label_hidden_when_configs_present(self, app):
        view = _view(profile=_profile(self.c1))
        assert view._empty_label.isHidden()

    def test_scroll_visible_when_configs_present(self, app):
        view = _view(profile=_profile(self.c1))
        assert not view._scroll.isHidden()

    def test_row_shows_drive_label(self, app):
        view = _view(profile=_profile(self.c1))
        row = _rows(view)[0]
        assert row._label_label.text() == "SWIM PRO"

    def test_row_shows_file_types(self, app):
        view = _view(profile=_profile(self.c1))
        row = _rows(view)[0]
        assert "MP3" in row._types_label.text()
        assert "FLAC" in row._types_label.text()

    def test_row_order_matches_profile(self, app):
        view = _view(profile=_profile(self.c1, self.c2))
        assert _rows(view)[0].config is self.c1
        assert _rows(view)[1].config is self.c2


# ---------------------------------------------------------------------------
# DevicesView — refresh_profile
# ---------------------------------------------------------------------------

class TestRefreshProfile:
    def test_refresh_adds_new_config(self, app):
        profile = _profile()
        view = _view(profile=profile)
        assert len(_rows(view)) == 0

        profile.device_configs.append(_cfg("New Device"))
        view.refresh_profile(profile)
        assert len(_rows(view)) == 1

    def test_refresh_removes_deleted_config(self, app):
        c = _cfg()
        profile = _profile(c)
        view = _view(profile=profile)
        assert len(_rows(view)) == 1

        profile.device_configs.clear()
        view.refresh_profile(profile)
        assert len(_rows(view)) == 0

    def test_refresh_shows_empty_label(self, app):
        c = _cfg()
        profile = _profile(c)
        view = _view(profile=profile)
        profile.device_configs.clear()
        view.refresh_profile(profile)
        assert not view._empty_label.isHidden()


# ---------------------------------------------------------------------------
# DevicesView — add device
# ---------------------------------------------------------------------------

class TestAddDevice:
    def test_add_opens_dialog(self, app):
        view = _view(profile=_profile())
        with patch.object(_DeviceConfigDialog, "exec", return_value=None):
            view._on_add_device()

    def test_add_appends_config_to_profile(self, app):
        profile = _profile()
        view = _view(profile=profile)
        new_cfg = _cfg("MyDevice", ["mp3"])

        def fake_exec(self):
            self.device_saved.emit(new_cfg)

        with patch.object(_DeviceConfigDialog, "exec", fake_exec):
            view._on_add_device()

        assert any(d.drive_label == "MyDevice" for d in profile.device_configs)

    def test_add_calls_on_changed(self, app):
        on_changed = MagicMock()
        view = _view(profile=_profile(), on_changed=on_changed)
        new_cfg = _cfg("MyDevice", ["mp3"])

        def fake_exec(self):
            self.device_saved.emit(new_cfg)

        with patch.object(_DeviceConfigDialog, "exec", fake_exec):
            view._on_add_device()

        on_changed.assert_called_once()

    def test_add_creates_row(self, app):
        view = _view(profile=_profile())
        new_cfg = _cfg("MyDevice", ["mp3"])

        def fake_exec(self):
            self.device_saved.emit(new_cfg)

        with patch.object(_DeviceConfigDialog, "exec", fake_exec):
            view._on_add_device()

        assert len(_rows(view)) == 1

    def test_cancel_does_not_add(self, app):
        profile = _profile()
        on_changed = MagicMock()
        view = _view(profile=profile, on_changed=on_changed)

        with patch.object(_DeviceConfigDialog, "exec", return_value=None):
            view._on_add_device()

        on_changed.assert_not_called()
        assert len(profile.device_configs) == 0

    def test_add_passes_existing_labels_to_dialog(self, app):
        c = _cfg("SWIM PRO")
        view = _view(profile=_profile(c))

        captured_labels: list[list[str]] = []
        original_init = _DeviceConfigDialog.__init__

        def patched_init(self, existing_config=None, existing_labels=None, parent=None):
            captured_labels.append(list(existing_labels or []))
            original_init(self, existing_config, existing_labels, parent)

        with patch.object(_DeviceConfigDialog, "__init__", patched_init):
            with patch.object(_DeviceConfigDialog, "exec", return_value=None):
                view._on_add_device()

        assert captured_labels[0] == ["SWIM PRO"]


# ---------------------------------------------------------------------------
# DevicesView — edit device
# ---------------------------------------------------------------------------

class TestEditDevice:
    def test_edit_replaces_config_in_profile(self, app):
        c = _cfg("SWIM PRO", ["mp3"])
        profile = _profile(c)
        view = _view(profile=profile)

        updated = _cfg("SWIM PRO", ["mp3", "flac"])

        def fake_exec(self):
            self.device_saved.emit(updated)

        with patch.object(_DeviceConfigDialog, "exec", fake_exec):
            view._on_edit_device(c)

        assert profile.device_configs[0].supported_extensions == ["mp3", "flac"]

    def test_edit_can_change_drive_label(self, app):
        c = _cfg("OldLabel", ["mp3"])
        profile = _profile(c)
        view = _view(profile=profile)

        renamed = _cfg("NewLabel", ["mp3"])

        def fake_exec(self):
            self.device_saved.emit(renamed)

        with patch.object(_DeviceConfigDialog, "exec", fake_exec):
            view._on_edit_device(c)

        assert profile.device_configs[0].drive_label == "NewLabel"

    def test_edit_does_not_duplicate(self, app):
        c = _cfg("SWIM PRO", ["mp3"])
        profile = _profile(c)
        view = _view(profile=profile)
        updated = _cfg("SWIM PRO", ["mp3", "wav"])

        def fake_exec(self):
            self.device_saved.emit(updated)

        with patch.object(_DeviceConfigDialog, "exec", fake_exec):
            view._on_edit_device(c)

        assert len(profile.device_configs) == 1

    def test_edit_calls_on_changed(self, app):
        c = _cfg()
        on_changed = MagicMock()
        view = _view(profile=_profile(c), on_changed=on_changed)
        updated = _cfg("SWIM PRO", ["mp3", "wav"])

        def fake_exec(self):
            self.device_saved.emit(updated)

        with patch.object(_DeviceConfigDialog, "exec", fake_exec):
            view._on_edit_device(c)

        on_changed.assert_called_once()

    def test_edit_passes_other_labels_to_dialog(self, app):
        c1 = _cfg("SWIM PRO")
        c2 = _cfg("OpenSwim")
        view = _view(profile=_profile(c1, c2))

        captured: list[list[str]] = []
        original_init = _DeviceConfigDialog.__init__

        def patched_init(self, existing_config=None, existing_labels=None, parent=None):
            captured.append(list(existing_labels or []))
            original_init(self, existing_config, existing_labels, parent)

        with patch.object(_DeviceConfigDialog, "__init__", patched_init):
            with patch.object(_DeviceConfigDialog, "exec", return_value=None):
                view._on_edit_device(c1)

        # Only the OTHER device's label should be in existing_labels
        assert captured[0] == ["OpenSwim"]
        assert "SWIM PRO" not in captured[0]

    def test_edit_row_edit_btn_triggers_edit(self, app):
        c = _cfg()
        on_changed = MagicMock()
        view = _view(profile=_profile(c), on_changed=on_changed)
        row = _rows(view)[0]

        updated = _cfg("SWIM PRO", ["mp3"])

        def fake_exec(self):
            self.device_saved.emit(updated)

        with patch.object(_DeviceConfigDialog, "exec", fake_exec):
            row._edit_btn.click()

        on_changed.assert_called_once()


# ---------------------------------------------------------------------------
# DevicesView — delete device
# ---------------------------------------------------------------------------

class TestDeleteDevice:
    def test_delete_removes_config(self, app):
        c = _cfg("SWIM PRO")
        profile = _profile(c)
        view = _view(profile=profile)
        view._on_delete_device(c)
        assert c not in profile.device_configs

    def test_delete_calls_on_changed(self, app):
        c = _cfg()
        on_changed = MagicMock()
        view = _view(profile=_profile(c), on_changed=on_changed)
        view._on_delete_device(c)
        on_changed.assert_called_once()

    def test_delete_removes_row(self, app):
        c = _cfg()
        view = _view(profile=_profile(c))
        assert len(_rows(view)) == 1
        view._on_delete_device(c)
        assert len(_rows(view)) == 0

    def test_delete_only_target_config(self, app):
        c1 = _cfg("SWIM PRO")
        c2 = _cfg("OpenSwim")
        profile = _profile(c1, c2)
        view = _view(profile=profile)
        view._on_delete_device(c1)
        assert c2 in profile.device_configs
        assert c1 not in profile.device_configs

    def test_delete_shows_empty_label_when_last(self, app):
        c = _cfg()
        view = _view(profile=_profile(c))
        view._on_delete_device(c)
        assert not view._empty_label.isHidden()

    def test_delete_btn_on_row_triggers_delete(self, app):
        c = _cfg()
        on_changed = MagicMock()
        view = _view(profile=_profile(c), on_changed=on_changed)
        row = _rows(view)[0]
        row._delete_btn.click()
        on_changed.assert_called_once()
        assert len(_rows(view)) == 0


# ---------------------------------------------------------------------------
# _DeviceRowWidget
# ---------------------------------------------------------------------------

class TestDeviceRowWidget:
    def test_drive_label_shown(self, app):
        row = _DeviceRowWidget(_cfg("SWIM PRO"))
        assert row._label_label.text() == "SWIM PRO"

    def test_file_types_shown(self, app):
        row = _DeviceRowWidget(_cfg("X", ["mp3", "flac"]))
        assert "MP3" in row._types_label.text()
        assert "FLAC" in row._types_label.text()

    def test_types_in_canonical_order(self, app):
        row = _DeviceRowWidget(_cfg("X", ["wav", "mp3"]))
        text = row._types_label.text()
        assert text.index("MP3") < text.index("WAV")

    def test_edit_btn_emits_edit_requested(self, app):
        c = _cfg()
        row = _DeviceRowWidget(c)
        received: list[DeviceConfig] = []
        row.edit_requested.connect(received.append)
        row._edit_btn.click()
        assert len(received) == 1
        assert received[0] is c

    def test_delete_btn_emits_delete_requested(self, app):
        c = _cfg()
        row = _DeviceRowWidget(c)
        received: list[DeviceConfig] = []
        row.delete_requested.connect(received.append)
        row._delete_btn.click()
        assert len(received) == 1
        assert received[0] is c

    def test_config_property(self, app):
        c = _cfg()
        row = _DeviceRowWidget(c)
        assert row.config is c

    def test_edit_btn_label(self, app):
        row = _DeviceRowWidget(_cfg())
        assert row._edit_btn.text() == "Edit"

    def test_delete_btn_label(self, app):
        row = _DeviceRowWidget(_cfg())
        assert row._delete_btn.text() == "Delete"


# ---------------------------------------------------------------------------
# _DeviceConfigDialog — add mode
# ---------------------------------------------------------------------------

class TestDeviceConfigDialogAddMode:
    def test_window_title_add_mode(self, app):
        dlg = _DeviceConfigDialog()
        assert "Add Device" in dlg.windowTitle()

    def test_label_edit_empty_by_default(self, app):
        dlg = _DeviceConfigDialog()
        assert dlg._label_edit.text() == ""

    def test_all_checkboxes_unchecked_by_default(self, app):
        dlg = _DeviceConfigDialog()
        assert not any(cb.isChecked() for cb in dlg._checkboxes.values())

    def test_save_disabled_by_default(self, app):
        dlg = _DeviceConfigDialog()
        assert not dlg._save_btn.isEnabled()

    def test_save_disabled_when_only_label_set(self, app):
        dlg = _DeviceConfigDialog()
        dlg._label_edit.setText("MyDevice")
        assert not dlg._save_btn.isEnabled()

    def test_save_disabled_when_only_type_checked(self, app):
        dlg = _DeviceConfigDialog()
        dlg._checkboxes["mp3"].setChecked(True)
        assert not dlg._save_btn.isEnabled()

    def test_save_enabled_when_label_and_type(self, app):
        dlg = _DeviceConfigDialog()
        dlg._label_edit.setText("MyDevice")
        dlg._checkboxes["mp3"].setChecked(True)
        assert dlg._save_btn.isEnabled()

    def test_save_emits_device_saved(self, app):
        dlg = _DeviceConfigDialog()
        received: list[DeviceConfig] = []
        dlg.device_saved.connect(received.append)
        dlg._label_edit.setText("MyDevice")
        dlg._checkboxes["mp3"].setChecked(True)
        dlg._on_save()
        assert len(received) == 1

    def test_save_emits_correct_drive_label(self, app):
        dlg = _DeviceConfigDialog()
        received: list[DeviceConfig] = []
        dlg.device_saved.connect(received.append)
        dlg._label_edit.setText("  MyDevice  ")
        dlg._checkboxes["mp3"].setChecked(True)
        dlg._on_save()
        assert received[0].drive_label == "MyDevice"

    def test_save_emits_correct_extensions(self, app):
        dlg = _DeviceConfigDialog()
        received: list[DeviceConfig] = []
        dlg.device_saved.connect(received.append)
        dlg._label_edit.setText("X")
        dlg._checkboxes["mp3"].setChecked(True)
        dlg._checkboxes["flac"].setChecked(True)
        dlg._on_save()
        assert set(received[0].supported_extensions) == {"mp3", "flac"}

    def test_duplicate_label_disables_save(self, app):
        dlg = _DeviceConfigDialog(existing_labels=["SWIM PRO"])
        dlg._label_edit.setText("SWIM PRO")
        dlg._checkboxes["mp3"].setChecked(True)
        assert not dlg._save_btn.isEnabled()

    def test_duplicate_check_case_insensitive(self, app):
        dlg = _DeviceConfigDialog(existing_labels=["swim pro"])
        dlg._label_edit.setText("SWIM PRO")
        dlg._checkboxes["mp3"].setChecked(True)
        assert not dlg._save_btn.isEnabled()

    def test_duplicate_warning_shown_on_duplicate(self, app):
        dlg = _DeviceConfigDialog(existing_labels=["SWIM PRO"])
        dlg._label_edit.setText("SWIM PRO")
        assert not dlg._duplicate_warning.isHidden()

    def test_duplicate_warning_hidden_on_unique_label(self, app):
        dlg = _DeviceConfigDialog(existing_labels=["SWIM PRO"])
        dlg._label_edit.setText("NewDevice")
        assert dlg._duplicate_warning.isHidden()

    def test_duplicate_warning_hidden_when_label_empty(self, app):
        dlg = _DeviceConfigDialog(existing_labels=["SWIM PRO"])
        dlg._label_edit.setText("")
        assert dlg._duplicate_warning.isHidden()

    def test_save_disabled_when_label_becomes_empty(self, app):
        dlg = _DeviceConfigDialog()
        dlg._label_edit.setText("X")
        dlg._checkboxes["mp3"].setChecked(True)
        dlg._label_edit.setText("")
        assert not dlg._save_btn.isEnabled()

    def test_checkboxes_exist_for_all_extensions(self, app):
        dlg = _DeviceConfigDialog()
        for ext in _ALL_EXTENSIONS:
            assert ext in dlg._checkboxes

    def test_all_extensions_unchecked_disables_save(self, app):
        dlg = _DeviceConfigDialog()
        dlg._label_edit.setText("X")
        for cb in dlg._checkboxes.values():
            cb.setChecked(False)
        assert not dlg._save_btn.isEnabled()


# ---------------------------------------------------------------------------
# _DeviceConfigDialog — edit mode
# ---------------------------------------------------------------------------

class TestDeviceConfigDialogEditMode:
    def setup_method(self):
        self.existing = _cfg("SWIM PRO", ["mp3", "flac", "wav"])

    def test_window_title_edit_mode(self, app):
        dlg = _DeviceConfigDialog(existing_config=self.existing)
        assert "Edit Device" in dlg.windowTitle()

    def test_label_prefilled(self, app):
        dlg = _DeviceConfigDialog(existing_config=self.existing)
        assert dlg._label_edit.text() == "SWIM PRO"

    def test_checked_types_prefilled(self, app):
        dlg = _DeviceConfigDialog(existing_config=self.existing)
        assert dlg._checkboxes["mp3"].isChecked()
        assert dlg._checkboxes["flac"].isChecked()
        assert dlg._checkboxes["wav"].isChecked()

    def test_unchecked_types_not_prefilled(self, app):
        dlg = _DeviceConfigDialog(existing_config=self.existing)
        for ext in ["wma", "aac", "m4a", "ape"]:
            assert not dlg._checkboxes[ext].isChecked()

    def test_save_enabled_when_pre_filled(self, app):
        dlg = _DeviceConfigDialog(existing_config=self.existing)
        assert dlg._save_btn.isEnabled()

    def test_same_label_allowed_in_edit_mode(self, app):
        # existing_labels excludes self (handled by caller), so empty here
        dlg = _DeviceConfigDialog(existing_config=self.existing, existing_labels=[])
        assert dlg._save_btn.isEnabled()

    def test_other_existing_label_still_blocked(self, app):
        dlg = _DeviceConfigDialog(
            existing_config=self.existing,
            existing_labels=["OpenSwim"],
        )
        dlg._label_edit.setText("OpenSwim")
        assert not dlg._save_btn.isEnabled()

    def test_edit_save_emits_updated_config(self, app):
        dlg = _DeviceConfigDialog(existing_config=self.existing, existing_labels=[])
        received: list[DeviceConfig] = []
        dlg.device_saved.connect(received.append)
        dlg._checkboxes["aac"].setChecked(True)
        dlg._on_save()
        assert "aac" in received[0].supported_extensions

    def test_edit_label_change_emitted(self, app):
        dlg = _DeviceConfigDialog(existing_config=self.existing, existing_labels=[])
        received: list[DeviceConfig] = []
        dlg.device_saved.connect(received.append)
        dlg._label_edit.setText("NewLabel")
        dlg._on_save()
        assert received[0].drive_label == "NewLabel"

    def test_unchecked_type_not_in_saved_config(self, app):
        dlg = _DeviceConfigDialog(existing_config=self.existing, existing_labels=[])
        received: list[DeviceConfig] = []
        dlg.device_saved.connect(received.append)
        dlg._checkboxes["mp3"].setChecked(False)
        dlg._on_save()
        assert "mp3" not in received[0].supported_extensions
