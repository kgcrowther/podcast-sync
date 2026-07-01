"""
Behavior tests for swimsync/ui/profiles_view.py.

Covers:
  - ProfilesView row population: count, names, active indicator
  - Active profile: switch btn disabled, delete btn disabled
  - Last profile: delete btn disabled regardless of active state
  - refresh(): updates active indicator
  - New profile: dialog wiring, create_fn called, list refreshed
  - New profile cancel: create_fn not called
  - Switch: load_fn called, on_profile_switched called with Profile
  - Switch load failure: warning shown, callback NOT called
  - Export: file dialog called with default name, export_fn called
  - Export cancel: export_fn not called
  - Export failure: warning shown
  - Export success: information shown
  - Import success: list refreshed
  - Import cancel: import_fn not called
  - Import conflict: question dialog shown, overwrite tried on Yes
  - Import conflict declined: no overwrite attempted
  - Import failure after overwrite: warning shown
  - Delete: delete_fn called, list refreshed
  - _ProfileRowWidget: name label, active label visibility, button states,
    switch and delete signals
  - _NewProfileDialog: empty disabled, duplicate disabled, case-insensitive
    duplicate check, warning visibility, create emits name
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call, patch
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox

from swimsync.models.profile import Profile
from swimsync.ui.profiles_view import (
    ProfilesView,
    _NewProfileDialog,
    _ProfileRowWidget,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _profile(name="Kenneth") -> Profile:
    return Profile(name=name)


def _view(
    active=None,
    names=None,
    on_switched=None,
    load_fn=None,
    create_fn=None,
    delete_fn=None,
    export_fn=None,
    import_fn=None,
) -> ProfilesView:
    if active is None:
        active = _profile("Kenneth")
    if names is None:
        names = [active.name]
    if on_switched is None:
        on_switched = MagicMock()
    if load_fn is None:
        load_fn = MagicMock(return_value=_profile("Other"))
    if create_fn is None:
        create_fn = MagicMock(side_effect=lambda n: _profile(n))
    if delete_fn is None:
        delete_fn = MagicMock(return_value=True)
    if export_fn is None:
        export_fn = MagicMock(return_value=True)
    if import_fn is None:
        import_fn = MagicMock(return_value=_profile("Imported"))

    return ProfilesView(
        active_profile=active,
        on_profile_switched=on_switched,
        list_profiles_fn=lambda: list(names),
        load_profile_fn=load_fn,
        create_profile_fn=create_fn,
        delete_profile_fn=delete_fn,
        export_profile_fn=export_fn,
        import_profile_fn=import_fn,
    )


def _rows(view: ProfilesView) -> list[_ProfileRowWidget]:
    return list(view._row_widgets)


# ---------------------------------------------------------------------------
# ProfilesView — row population
# ---------------------------------------------------------------------------

class TestProfilesViewRows:
    def test_row_count_matches_profile_list(self, app):
        view = _view(names=["Alice", "Bob", "Carol"],
                     active=_profile("Alice"))
        assert len(_rows(view)) == 3

    def test_row_names(self, app):
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"))
        names = [r.name for r in _rows(view)]
        assert names == ["Alice", "Bob"]

    def test_active_row_marked(self, app):
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"))
        rows = _rows(view)
        assert rows[0].is_active
        assert not rows[1].is_active

    def test_single_profile_has_no_rows_unless_listed(self, app):
        view = _view(names=[], active=_profile("A"))
        assert len(_rows(view)) == 0

    def test_order_matches_list(self, app):
        view = _view(names=["Zara", "Aaron"], active=_profile("Zara"))
        assert _rows(view)[0].name == "Zara"
        assert _rows(view)[1].name == "Aaron"


# ---------------------------------------------------------------------------
# ProfilesView — button states
# ---------------------------------------------------------------------------

class TestButtonStates:
    def test_switch_disabled_for_active_profile(self, app):
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"))
        alice_row = _rows(view)[0]
        assert not alice_row._switch_btn.isEnabled()

    def test_switch_enabled_for_inactive_profile(self, app):
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"))
        bob_row = _rows(view)[1]
        assert bob_row._switch_btn.isEnabled()

    def test_delete_disabled_for_active_profile(self, app):
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"))
        alice_row = _rows(view)[0]
        assert not alice_row._delete_btn.isEnabled()

    def test_delete_enabled_for_inactive_non_last_profile(self, app):
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"))
        bob_row = _rows(view)[1]
        assert bob_row._delete_btn.isEnabled()

    def test_delete_disabled_when_only_one_profile(self, app):
        view = _view(names=["Alice"], active=_profile("Alice"))
        assert not _rows(view)[0]._delete_btn.isEnabled()

    def test_delete_disabled_for_last_profile_even_if_inactive(self, app):
        # Edge case: single profile that isn't marked as active (shouldn't happen
        # normally, but the is_last flag should still disable delete)
        view = _view(names=["Bob"], active=_profile("Alice"))
        assert not _rows(view)[0]._delete_btn.isEnabled()

    def test_active_label_visible_for_active(self, app):
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"))
        assert not _rows(view)[0]._active_label.isHidden()

    def test_active_label_hidden_for_inactive(self, app):
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"))
        assert _rows(view)[1]._active_label.isHidden()

    def test_top_buttons_always_enabled(self, app):
        view = _view(names=["Alice"], active=_profile("Alice"))
        assert view._new_btn.isEnabled()
        assert view._export_btn.isEnabled()
        assert view._import_btn.isEnabled()


# ---------------------------------------------------------------------------
# ProfilesView — refresh
# ---------------------------------------------------------------------------

class TestRefresh:
    def test_refresh_updates_active_indicator(self, app):
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"))
        assert _rows(view)[0].is_active
        assert not _rows(view)[1].is_active

        view.refresh(_profile("Bob"))
        assert not _rows(view)[0].is_active
        assert _rows(view)[1].is_active

    def test_refresh_repopulates_row_count(self, app):
        names = ["Alice"]
        view = _view(names=names, active=_profile("Alice"))
        assert len(_rows(view)) == 1

        names.append("Bob")
        view.refresh(_profile("Alice"))
        assert len(_rows(view)) == 2


# ---------------------------------------------------------------------------
# ProfilesView — new profile
# ---------------------------------------------------------------------------

class TestNewProfile:
    def test_new_profile_opens_dialog(self, app):
        view = _view()
        with patch.object(_NewProfileDialog, "exec", return_value=None):
            view._on_new_profile()

    def test_new_profile_calls_create_fn(self, app):
        create_fn = MagicMock(side_effect=lambda n: _profile(n))
        view = _view(names=["Alice"], active=_profile("Alice"),
                     create_fn=create_fn)

        def fake_exec(self):
            self.profile_name_entered.emit("NewProfile")

        with patch.object(_NewProfileDialog, "exec", fake_exec):
            view._on_new_profile()

        create_fn.assert_called_once_with("NewProfile")

    def test_new_profile_refreshes_list(self, app):
        names = ["Alice"]
        create_fn = MagicMock(side_effect=lambda n: _profile(n))
        view = _view(names=names, active=_profile("Alice"), create_fn=create_fn)

        def fake_exec(self):
            names.append("Bob")  # must precede emit — signal fires synchronously
            self.profile_name_entered.emit("Bob")

        with patch.object(_NewProfileDialog, "exec", fake_exec):
            view._on_new_profile()

        assert len(_rows(view)) == 2

    def test_cancel_does_not_call_create_fn(self, app):
        create_fn = MagicMock()
        view = _view(names=["Alice"], active=_profile("Alice"),
                     create_fn=create_fn)

        with patch.object(_NewProfileDialog, "exec", return_value=None):
            view._on_new_profile()

        create_fn.assert_not_called()

    def test_new_profile_passes_existing_names_to_dialog(self, app):
        captured: list[list[str]] = []
        original_init = _NewProfileDialog.__init__

        def patched_init(self, existing_names=None, parent=None):
            captured.append(list(existing_names or []))
            original_init(self, existing_names, parent)

        view = _view(names=["Alice", "Bob"], active=_profile("Alice"))

        with patch.object(_NewProfileDialog, "__init__", patched_init):
            with patch.object(_NewProfileDialog, "exec", return_value=None):
                view._on_new_profile()

        assert "Alice" in captured[0]
        assert "Bob" in captured[0]


# ---------------------------------------------------------------------------
# ProfilesView — switch profile
# ---------------------------------------------------------------------------

class TestSwitchProfile:
    def test_switch_calls_load_fn(self, app):
        load_fn = MagicMock(return_value=_profile("Bob"))
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"),
                     load_fn=load_fn)
        view._on_switch("Bob")
        load_fn.assert_called_once_with("Bob")

    def test_switch_calls_on_profile_switched(self, app):
        bob = _profile("Bob")
        on_switched = MagicMock()
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"),
                     on_switched=on_switched,
                     load_fn=MagicMock(return_value=bob))
        view._on_switch("Bob")
        on_switched.assert_called_once_with(bob)

    def test_switch_load_failure_shows_warning(self, app):
        load_fn = MagicMock(return_value=None)
        on_switched = MagicMock()
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"),
                     on_switched=on_switched, load_fn=load_fn)
        with patch("swimsync.ui.profiles_view.QMessageBox.warning") as mock_warn:
            view._on_switch("Bob")
        mock_warn.assert_called_once()
        on_switched.assert_not_called()

    def test_switch_btn_click_triggers_switch(self, app):
        on_switched = MagicMock()
        bob = _profile("Bob")
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"),
                     on_switched=on_switched,
                     load_fn=MagicMock(return_value=bob))
        bob_row = _rows(view)[1]
        bob_row._switch_btn.click()
        on_switched.assert_called_once_with(bob)


# ---------------------------------------------------------------------------
# ProfilesView — export
# ---------------------------------------------------------------------------

class TestExport:
    def test_export_calls_file_dialog_with_default_name(self, app):
        view = _view(active=_profile("Kenneth"))
        with patch("swimsync.ui.profiles_view.QFileDialog.getSaveFileName",
                   return_value=("", "")) as mock_dlg:
            view._on_export()
        args = mock_dlg.call_args[0]
        assert "Kenneth.swimsync" in args[2]

    def test_export_calls_export_fn_with_profile_and_path(self, app):
        export_fn = MagicMock(return_value=True)
        active = _profile("Kenneth")
        view = _view(active=active, export_fn=export_fn)
        with patch("swimsync.ui.profiles_view.QFileDialog.getSaveFileName",
                   return_value=("/tmp/Kenneth.swimsync", "")):
            with patch("swimsync.ui.profiles_view.QMessageBox.information"):
                view._on_export()
        export_fn.assert_called_once_with(active, Path("/tmp/Kenneth.swimsync"))

    def test_export_cancel_does_not_call_export_fn(self, app):
        export_fn = MagicMock()
        view = _view(export_fn=export_fn)
        with patch("swimsync.ui.profiles_view.QFileDialog.getSaveFileName",
                   return_value=("", "")):
            view._on_export()
        export_fn.assert_not_called()

    def test_export_success_shows_information(self, app):
        view = _view(export_fn=MagicMock(return_value=True))
        with patch("swimsync.ui.profiles_view.QFileDialog.getSaveFileName",
                   return_value=("/tmp/out.swimsync", "")):
            with patch("swimsync.ui.profiles_view.QMessageBox.information") as mock_info:
                view._on_export()
        mock_info.assert_called_once()

    def test_export_failure_shows_warning(self, app):
        view = _view(export_fn=MagicMock(return_value=False))
        with patch("swimsync.ui.profiles_view.QFileDialog.getSaveFileName",
                   return_value=("/tmp/out.swimsync", "")):
            with patch("swimsync.ui.profiles_view.QMessageBox.warning") as mock_warn:
                view._on_export()
        mock_warn.assert_called_once()

    def test_export_btn_click_opens_dialog(self, app):
        view = _view()
        with patch("swimsync.ui.profiles_view.QFileDialog.getSaveFileName",
                   return_value=("", "")) as mock_dlg:
            view._export_btn.click()
        mock_dlg.assert_called_once()


# ---------------------------------------------------------------------------
# ProfilesView — import
# ---------------------------------------------------------------------------

class TestImport:
    def test_import_calls_import_fn(self, app):
        imported = _profile("Imported")
        import_fn = MagicMock(return_value=imported)
        view = _view(import_fn=import_fn)
        with patch("swimsync.ui.profiles_view.QFileDialog.getOpenFileName",
                   return_value=("/tmp/p.swimsync", "")):
            view._on_import()
        import_fn.assert_called_once_with(Path("/tmp/p.swimsync"))

    def test_import_cancel_does_not_call_import_fn(self, app):
        import_fn = MagicMock()
        view = _view(import_fn=import_fn)
        with patch("swimsync.ui.profiles_view.QFileDialog.getOpenFileName",
                   return_value=("", "")):
            view._on_import()
        import_fn.assert_not_called()

    def test_import_success_refreshes_list(self, app):
        names = ["Alice"]
        imported = _profile("Bob")
        import_fn = MagicMock(return_value=imported)
        view = _view(names=names, active=_profile("Alice"), import_fn=import_fn)
        names.append("Bob")
        with patch("swimsync.ui.profiles_view.QFileDialog.getOpenFileName",
                   return_value=("/tmp/p.swimsync", "")):
            view._on_import()
        assert len(_rows(view)) == 2

    def test_import_conflict_shows_question(self, app):
        import_fn = MagicMock(return_value=None)
        view = _view(import_fn=import_fn)
        with patch("swimsync.ui.profiles_view.QFileDialog.getOpenFileName",
                   return_value=("/tmp/p.swimsync", "")):
            with patch("swimsync.ui.profiles_view.QMessageBox.question",
                       return_value=QMessageBox.StandardButton.No) as mock_q:
                with patch("swimsync.ui.profiles_view.QMessageBox.warning"):
                    view._on_import()
        mock_q.assert_called_once()

    def test_import_conflict_yes_retries_with_overwrite(self, app):
        imported = _profile("Imported")
        import_fn = MagicMock(side_effect=[None, imported])
        view = _view(import_fn=import_fn)
        with patch("swimsync.ui.profiles_view.QFileDialog.getOpenFileName",
                   return_value=("/tmp/p.swimsync", "")):
            with patch("swimsync.ui.profiles_view.QMessageBox.question",
                       return_value=QMessageBox.StandardButton.Yes):
                view._on_import()
        assert import_fn.call_count == 2
        assert import_fn.call_args_list[1] == call(Path("/tmp/p.swimsync"), True)

    def test_import_conflict_no_does_not_retry(self, app):
        import_fn = MagicMock(return_value=None)
        view = _view(import_fn=import_fn)
        with patch("swimsync.ui.profiles_view.QFileDialog.getOpenFileName",
                   return_value=("/tmp/p.swimsync", "")):
            with patch("swimsync.ui.profiles_view.QMessageBox.question",
                       return_value=QMessageBox.StandardButton.No):
                with patch("swimsync.ui.profiles_view.QMessageBox.warning"):
                    view._on_import()
        assert import_fn.call_count == 1

    def test_import_failure_after_overwrite_shows_warning(self, app):
        import_fn = MagicMock(return_value=None)
        view = _view(import_fn=import_fn)
        with patch("swimsync.ui.profiles_view.QFileDialog.getOpenFileName",
                   return_value=("/tmp/p.swimsync", "")):
            with patch("swimsync.ui.profiles_view.QMessageBox.question",
                       return_value=QMessageBox.StandardButton.Yes):
                with patch("swimsync.ui.profiles_view.QMessageBox.warning") as mock_warn:
                    view._on_import()
        mock_warn.assert_called_once()

    def test_import_btn_click_opens_dialog(self, app):
        view = _view()
        with patch("swimsync.ui.profiles_view.QFileDialog.getOpenFileName",
                   return_value=("", "")) as mock_dlg:
            view._import_btn.click()
        mock_dlg.assert_called_once()


# ---------------------------------------------------------------------------
# ProfilesView — delete
# ---------------------------------------------------------------------------

class TestDeleteProfile:
    def test_delete_calls_delete_fn(self, app):
        delete_fn = MagicMock(return_value=True)
        view = _view(names=["Alice", "Bob"], active=_profile("Alice"),
                     delete_fn=delete_fn)
        view._on_delete("Bob")
        delete_fn.assert_called_once_with("Bob")

    def test_delete_refreshes_list(self, app):
        names = ["Alice", "Bob"]
        delete_fn = MagicMock(return_value=True)
        view = _view(names=names, active=_profile("Alice"), delete_fn=delete_fn)
        assert len(_rows(view)) == 2

        names.remove("Bob")
        view._on_delete("Bob")
        assert len(_rows(view)) == 1

    def test_delete_btn_click_triggers_delete(self, app):
        delete_fn = MagicMock(return_value=True)
        names = ["Alice", "Bob"]
        view = _view(names=names, active=_profile("Alice"), delete_fn=delete_fn)
        bob_row = _rows(view)[1]
        names.remove("Bob")
        bob_row._delete_btn.click()
        delete_fn.assert_called_once_with("Bob")


# ---------------------------------------------------------------------------
# _ProfileRowWidget
# ---------------------------------------------------------------------------

class TestProfileRowWidget:
    def test_name_label(self, app):
        row = _ProfileRowWidget("Kenneth")
        assert row._name_label.text() == "Kenneth"

    def test_active_label_visible_when_active(self, app):
        row = _ProfileRowWidget("Kenneth", is_active=True)
        assert not row._active_label.isHidden()

    def test_active_label_hidden_when_not_active(self, app):
        row = _ProfileRowWidget("Kenneth", is_active=False)
        assert row._active_label.isHidden()

    def test_switch_enabled_when_inactive(self, app):
        row = _ProfileRowWidget("Kenneth", is_active=False, is_last=False)
        assert row._switch_btn.isEnabled()

    def test_switch_disabled_when_active(self, app):
        row = _ProfileRowWidget("Kenneth", is_active=True)
        assert not row._switch_btn.isEnabled()

    def test_delete_enabled_when_inactive_and_not_last(self, app):
        row = _ProfileRowWidget("Kenneth", is_active=False, is_last=False)
        assert row._delete_btn.isEnabled()

    def test_delete_disabled_when_active(self, app):
        row = _ProfileRowWidget("Kenneth", is_active=True, is_last=False)
        assert not row._delete_btn.isEnabled()

    def test_delete_disabled_when_last(self, app):
        row = _ProfileRowWidget("Kenneth", is_active=False, is_last=True)
        assert not row._delete_btn.isEnabled()

    def test_switch_emits_name(self, app):
        row = _ProfileRowWidget("Kenneth", is_active=False)
        received: list[str] = []
        row.switch_requested.connect(received.append)
        row._switch_btn.click()
        assert received == ["Kenneth"]

    def test_delete_emits_name(self, app):
        row = _ProfileRowWidget("Kenneth", is_active=False, is_last=False)
        received: list[str] = []
        row.delete_requested.connect(received.append)
        row._delete_btn.click()
        assert received == ["Kenneth"]

    def test_name_property(self, app):
        row = _ProfileRowWidget("Alice")
        assert row.name == "Alice"

    def test_is_active_property(self, app):
        assert _ProfileRowWidget("X", is_active=True).is_active
        assert not _ProfileRowWidget("X", is_active=False).is_active


# ---------------------------------------------------------------------------
# _NewProfileDialog
# ---------------------------------------------------------------------------

class TestNewProfileDialog:
    def test_save_disabled_initially(self, app):
        dlg = _NewProfileDialog()
        assert not dlg._save_btn.isEnabled()

    def test_save_enabled_when_name_entered(self, app):
        dlg = _NewProfileDialog()
        dlg._name_edit.setText("Alice")
        assert dlg._save_btn.isEnabled()

    def test_save_disabled_when_name_cleared(self, app):
        dlg = _NewProfileDialog()
        dlg._name_edit.setText("Alice")
        dlg._name_edit.setText("")
        assert not dlg._save_btn.isEnabled()

    def test_save_disabled_on_duplicate_name(self, app):
        dlg = _NewProfileDialog(existing_names=["Alice"])
        dlg._name_edit.setText("Alice")
        assert not dlg._save_btn.isEnabled()

    def test_duplicate_check_case_insensitive(self, app):
        dlg = _NewProfileDialog(existing_names=["alice"])
        dlg._name_edit.setText("ALICE")
        assert not dlg._save_btn.isEnabled()

    def test_duplicate_warning_shown(self, app):
        dlg = _NewProfileDialog(existing_names=["Alice"])
        dlg._name_edit.setText("Alice")
        assert not dlg._duplicate_warning.isHidden()

    def test_duplicate_warning_hidden_for_unique_name(self, app):
        dlg = _NewProfileDialog(existing_names=["Alice"])
        dlg._name_edit.setText("Bob")
        assert dlg._duplicate_warning.isHidden()

    def test_duplicate_warning_hidden_when_empty(self, app):
        dlg = _NewProfileDialog(existing_names=["Alice"])
        dlg._name_edit.setText("")
        assert dlg._duplicate_warning.isHidden()

    def test_save_emits_name(self, app):
        dlg = _NewProfileDialog()
        received: list[str] = []
        dlg.profile_name_entered.connect(received.append)
        dlg._name_edit.setText("NewProfile")
        dlg._on_save()
        assert received == ["NewProfile"]

    def test_save_strips_whitespace(self, app):
        dlg = _NewProfileDialog()
        received: list[str] = []
        dlg.profile_name_entered.connect(received.append)
        dlg._name_edit.setText("  Alice  ")
        dlg._on_save()
        assert received == ["Alice"]

    def test_window_title(self, app):
        dlg = _NewProfileDialog()
        assert "Profile" in dlg.windowTitle()

    def test_no_existing_names_allows_any_name(self, app):
        dlg = _NewProfileDialog(existing_names=[])
        dlg._name_edit.setText("AnyName")
        assert dlg._save_btn.isEnabled()
