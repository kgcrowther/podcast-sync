"""
Behavior tests for swimsync/ui/sync_dialog.py.

Covers:
  - Construction: device label, profile combo, initial phase
  - Profile combo: population, active pre-selected, unknown active inserted
  - Profile switching: load_fn called, PREVIEW resets to READY
  - Analyze phase: worker created, plan_ready→PREVIEW, empty plan→DONE, error→ERROR
  - Preview panel: add/remove/redownload/space labels, storage warning
  - Storage warning: Sync button disabled
  - Empty plan: DONE phase with up-to-date message
  - Sync phase: worker created/started, progress updates, finished (ok→DONE, fail→ERROR)
  - sync_completed signal emitted on success, not on failure
  - Button labels and enabled states per phase
  - Secondary button behaviour (cancel/stop/close) per phase
  - notify_device_disconnected: matching label, wrong label, SYNCING interruption
  - Already-terminal phase ignored by notify_device_disconnected
  - _FetchWorker: run calls fetch/compute, emits plan_ready or error
  - _SyncWorker: run calls execute_fn, emits progress and finished; cancel flag
  - _fmt_bytes helper
  - _default_fetch_feeds: fetches per flow, deduplicates, handles failure
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call, patch

from PyQt6.QtWidgets import QApplication

from swimsync.core.device_monitor import MountedDevice
from swimsync.models.profile import Episode, Flow, Profile
from swimsync.models.sync_plan import SyncAction, SyncPlan
from swimsync.ui.sync_dialog import (
    SyncDialog,
    _FetchWorker,
    _Phase,
    _SyncWorker,
    _default_fetch_feeds,
    _fmt_bytes,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def sync_workers_synchronous(monkeypatch):
    """Run QThread workers synchronously (call run() in-place) for all tests."""
    monkeypatch.setattr(_FetchWorker, "start", lambda self: self.run())
    monkeypatch.setattr(_SyncWorker, "start", lambda self: self.run())


def _device(label="SWIM PRO", capacity=16_000_000_000, used=3_200_000_000):
    return MountedDevice(
        drive_label=label,
        mount_point=f"/Volumes/{label}",
        capacity_bytes=capacity,
        used_bytes=used,
    )


def _profile(name="Kenneth"):
    return Profile(name=name)


def _plan(
    to_add=None,
    to_delete=None,
    to_redownload=None,
    device_label="SWIM PRO",
    device_path="/Volumes/SWIM PRO",
    capacity=16_000_000_000,
    used=3_200_000_000,
    desired=0,
    storage_warning=False,
    storage_warning_message=None,
):
    return SyncPlan(
        to_add=to_add or [],
        to_delete=to_delete or [],
        to_redownload=to_redownload or [],
        device_label=device_label,
        device_path=device_path,
        device_capacity_bytes=capacity,
        device_used_bytes=used,
        desired_total_bytes=desired,
        storage_warning=storage_warning,
        storage_warning_message=storage_warning_message,
        profile_name="Kenneth",
    )


def _action(title="Ep 1", filename="ep1.mp3", size=5_000_000):
    return SyncAction(
        filename=filename,
        title=title,
        source_label="My Podcast",
        source_url="http://example.com/ep1.mp3",
        file_size_bytes=size,
    )


def _dialog(
    device=None,
    profile=None,
    profiles=None,
    load_fn=None,
    fetch_fn=None,
    compute_fn=None,
    execute_fn=None,
):
    if device is None:
        device = _device()
    if profile is None:
        profile = _profile()
    if profiles is None:
        profiles = [profile.name]
    if load_fn is None:
        load_fn = MagicMock(side_effect=lambda n: _profile(n))
    if fetch_fn is None:
        fetch_fn = MagicMock(return_value={})
    if compute_fn is None:
        compute_fn = MagicMock(return_value=_plan())
    if execute_fn is None:
        execute_fn = MagicMock(return_value=(True, "Sync complete — 0 files synced."))

    return SyncDialog(
        device=device,
        active_profile=profile,
        list_profiles_fn=lambda: list(profiles),
        load_profile_fn=load_fn,
        fetch_feeds_fn=fetch_fn,
        compute_plan_fn=compute_fn,
        execute_sync_fn=execute_fn,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_initial_phase_is_ready(self, app):
        dlg = _dialog()
        assert dlg.phase == _Phase.READY

    def test_device_label_in_ui(self, app):
        dlg = _dialog(device=_device("SWIM PRO"))
        assert "SWIM PRO" in dlg._device_label.text()

    def test_device_capacity_in_ui(self, app):
        dlg = _dialog(device=_device(capacity=16_000_000_000))
        assert "16" in dlg._device_label.text() or "GB" in dlg._device_label.text()

    def test_profile_combo_populated(self, app):
        dlg = _dialog(profile=_profile("Alice"), profiles=["Alice", "Bob"])
        assert dlg._profile_combo.count() == 2

    def test_active_profile_pre_selected(self, app):
        dlg = _dialog(profile=_profile("Bob"), profiles=["Alice", "Bob"])
        assert dlg._profile_combo.currentText() == "Bob"

    def test_active_profile_inserted_if_not_in_list(self, app):
        dlg = _dialog(profile=_profile("Orphan"), profiles=["Alice"])
        items = [dlg._profile_combo.itemText(i)
                 for i in range(dlg._profile_combo.count())]
        assert "Orphan" in items

    def test_window_title(self, app):
        dlg = _dialog()
        assert "Sync" in dlg.windowTitle()

    def test_analyze_button_visible_and_enabled(self, app):
        dlg = _dialog()
        assert not dlg._primary_btn.isHidden()
        assert dlg._primary_btn.isEnabled()
        assert dlg._primary_btn.text() == "Analyze"

    def test_cancel_button_shows_cancel(self, app):
        dlg = _dialog()
        assert dlg._secondary_btn.text() == "Cancel"
        assert dlg._secondary_btn.isEnabled()

    def test_status_page_shown_initially(self, app):
        dlg = _dialog()
        assert dlg._stack.currentIndex() == 0

    def test_profile_combo_enabled_in_ready(self, app):
        dlg = _dialog()
        assert dlg._profile_combo.isEnabled()


# ---------------------------------------------------------------------------
# Profile combo
# ---------------------------------------------------------------------------

class TestProfileCombo:
    def test_profile_change_calls_load_fn(self, app):
        load_fn = MagicMock(side_effect=lambda n: _profile(n))
        dlg = _dialog(profiles=["Alice", "Bob"], profile=_profile("Alice"),
                      load_fn=load_fn)
        dlg._profile_combo.setCurrentText("Bob")
        load_fn.assert_called_with("Bob")

    def test_profile_change_updates_internal_profile(self, app):
        bob = _profile("Bob")
        load_fn = MagicMock(return_value=bob)
        dlg = _dialog(profiles=["Alice", "Bob"], profile=_profile("Alice"),
                      load_fn=load_fn)
        dlg._profile_combo.setCurrentText("Bob")
        assert dlg._profile is bob

    def test_profile_change_ignored_if_load_returns_none(self, app):
        original = _profile("Alice")
        load_fn = MagicMock(return_value=None)
        dlg = _dialog(profiles=["Alice", "Bob"], profile=original,
                      load_fn=load_fn)
        dlg._profile_combo.setCurrentText("Bob")
        assert dlg._profile is original

    def test_profile_change_in_preview_resets_to_ready(self, app):
        plan = _plan(to_add=[_action()])
        compute_fn = MagicMock(return_value=plan)
        load_fn = MagicMock(side_effect=lambda n: _profile(n))
        dlg = _dialog(profiles=["Alice", "Bob"], profile=_profile("Alice"),
                      compute_fn=compute_fn, load_fn=load_fn)
        dlg._primary_btn.click()          # analyze → PREVIEW
        assert dlg.phase == _Phase.PREVIEW
        dlg._profile_combo.setCurrentText("Bob")
        assert dlg.phase == _Phase.READY

    def test_profile_change_in_ready_stays_ready(self, app):
        load_fn = MagicMock(side_effect=lambda n: _profile(n))
        dlg = _dialog(profiles=["Alice", "Bob"], profile=_profile("Alice"),
                      load_fn=load_fn)
        dlg._profile_combo.setCurrentText("Bob")
        assert dlg.phase == _Phase.READY

    def test_profile_combo_disabled_during_analyzing(self, app):
        # Patch start to be a no-op (worker never emits) → stays ANALYZING
        with patch.object(_FetchWorker, "start", lambda self: None):
            dlg = _dialog()
            dlg._primary_btn.click()
        assert not dlg._profile_combo.isEnabled()


# ---------------------------------------------------------------------------
# Analyze phase
# ---------------------------------------------------------------------------

class TestAnalyzePhase:
    def test_analyze_button_triggers_analyzing_phase(self, app):
        # Patch start to no-op so we catch the mid-transition state
        with patch.object(_FetchWorker, "start", lambda self: None):
            dlg = _dialog()
            dlg._primary_btn.click()
        assert dlg.phase == _Phase.ANALYZING

    def test_analyze_calls_fetch_feeds_fn(self, app):
        fetch_fn = MagicMock(return_value={})
        dlg = _dialog(fetch_fn=fetch_fn)
        dlg._primary_btn.click()
        fetch_fn.assert_called_once()

    def test_analyze_calls_compute_plan_fn(self, app):
        compute_fn = MagicMock(return_value=_plan())
        dlg = _dialog(compute_fn=compute_fn)
        dlg._primary_btn.click()
        compute_fn.assert_called_once()

    def test_fetch_worker_receives_current_profile(self, app):
        captured = []
        original_init = _FetchWorker.__init__

        def patched_init(self, profile, device, fetch_feeds_fn, compute_plan_fn,
                         parent=None):
            captured.append(profile)
            original_init(self, profile, device, fetch_feeds_fn, compute_plan_fn,
                          parent)

        with patch.object(_FetchWorker, "__init__", patched_init):
            prof = _profile("Kenneth")
            dlg = _dialog(profile=prof)
            dlg._primary_btn.click()

        assert captured[0].name == "Kenneth"

    def test_non_empty_plan_transitions_to_preview(self, app):
        plan = _plan(to_add=[_action()])
        dlg = _dialog(compute_fn=MagicMock(return_value=plan))
        dlg._primary_btn.click()
        assert dlg.phase == _Phase.PREVIEW

    def test_empty_plan_transitions_to_done(self, app):
        dlg = _dialog(compute_fn=MagicMock(return_value=_plan()))
        dlg._primary_btn.click()
        assert dlg.phase == _Phase.DONE

    def test_empty_plan_result_message(self, app):
        dlg = _dialog(compute_fn=MagicMock(return_value=_plan()))
        dlg._primary_btn.click()
        assert "up to date" in dlg._result_label.text().lower()

    def test_analyze_error_transitions_to_error(self, app):
        def bad_fetch(profile):
            raise RuntimeError("network failure")

        dlg = _dialog(fetch_fn=bad_fetch)
        dlg._primary_btn.click()
        assert dlg.phase == _Phase.ERROR

    def test_analyze_error_message_shown(self, app):
        def bad_fetch(profile):
            raise RuntimeError("timeout")

        dlg = _dialog(fetch_fn=bad_fetch)
        dlg._primary_btn.click()
        assert "timeout" in dlg._result_label.text()

    def test_primary_btn_disabled_during_analyzing(self, app):
        with patch.object(_FetchWorker, "start", lambda self: None):
            dlg = _dialog()
            dlg._primary_btn.click()
        assert not dlg._primary_btn.isEnabled()
        assert dlg._primary_btn.text() == "Analyzing…"


# ---------------------------------------------------------------------------
# Preview panel content
# ---------------------------------------------------------------------------

class TestPreviewContent:
    def _preview_dialog(self, plan):
        dlg = _dialog(compute_fn=MagicMock(return_value=plan))
        dlg._primary_btn.click()
        return dlg

    def test_add_count_shown(self, app):
        plan = _plan(to_add=[_action(), _action("Ep 2", "ep2.mp3")])
        dlg = self._preview_dialog(plan)
        assert "2" in dlg._preview_add_label.text()

    def test_add_size_shown_when_known(self, app):
        plan = _plan(to_add=[_action(size=5_000_000)])
        dlg = self._preview_dialog(plan)
        assert "MB" in dlg._preview_add_label.text() or "5" in dlg._preview_add_label.text()

    def test_remove_count_shown(self, app):
        plan = _plan(to_add=[_action()], to_delete=["old.mp3", "older.mp3"])
        dlg = self._preview_dialog(plan)
        assert "2" in dlg._preview_remove_label.text()

    def test_redownload_label_visible_when_present(self, app):
        plan = _plan(to_add=[_action()], to_redownload=[_action("Ep X", "epx.mp3")])
        dlg = self._preview_dialog(plan)
        assert not dlg._preview_redownload_label.isHidden()

    def test_redownload_label_hidden_when_absent(self, app):
        plan = _plan(to_add=[_action()])
        dlg = self._preview_dialog(plan)
        assert dlg._preview_redownload_label.isHidden()

    def test_space_label_shown(self, app):
        plan = _plan(to_add=[_action()], capacity=16_000_000_000, desired=500_000_000)
        dlg = self._preview_dialog(plan)
        assert dlg._preview_space_label.text() != ""

    def test_space_label_no_capacity(self, app):
        plan = _plan(to_add=[_action()], capacity=0, desired=500_000_000)
        dlg = self._preview_dialog(plan)
        assert "used" in dlg._preview_space_label.text()

    def test_storage_warning_label_visible_on_warning(self, app):
        plan = _plan(
            to_add=[_action()],
            storage_warning=True,
            storage_warning_message="Exceeds 90%.",
        )
        dlg = self._preview_dialog(plan)
        assert not dlg._storage_warning_label.isHidden()

    def test_storage_warning_text_shown(self, app):
        plan = _plan(
            to_add=[_action()],
            storage_warning=True,
            storage_warning_message="Exceeds 90%.",
        )
        dlg = self._preview_dialog(plan)
        assert "Exceeds 90%" in dlg._storage_warning_label.text()

    def test_storage_warning_label_hidden_without_warning(self, app):
        plan = _plan(to_add=[_action()])
        dlg = self._preview_dialog(plan)
        assert dlg._storage_warning_label.isHidden()

    def test_sync_btn_disabled_on_storage_warning(self, app):
        plan = _plan(
            to_add=[_action()],
            storage_warning=True,
            storage_warning_message="Too big.",
        )
        dlg = self._preview_dialog(plan)
        assert not dlg._primary_btn.isEnabled()

    def test_sync_btn_enabled_without_storage_warning(self, app):
        plan = _plan(to_add=[_action()])
        dlg = self._preview_dialog(plan)
        assert dlg._primary_btn.isEnabled()
        assert dlg._primary_btn.text() == "Sync"


# ---------------------------------------------------------------------------
# Sync phase
# ---------------------------------------------------------------------------

class TestSyncPhase:
    def _synced_dialog(self, execute_fn=None, plan=None):
        if plan is None:
            plan = _plan(to_add=[_action()])
        if execute_fn is None:
            execute_fn = MagicMock(return_value=(True, "Sync complete — 1 file synced."))
        dlg = _dialog(
            compute_fn=MagicMock(return_value=plan),
            execute_fn=execute_fn,
        )
        dlg._primary_btn.click()   # → PREVIEW
        dlg._primary_btn.click()   # → SYNCING → DONE (worker synchronous)
        return dlg

    def test_success_transitions_to_done(self, app):
        dlg = self._synced_dialog()
        assert dlg.phase == _Phase.DONE

    def test_failure_transitions_to_error(self, app):
        execute_fn = MagicMock(return_value=(False, "Download failed for 'ep1.mp3': timeout"))
        dlg = self._synced_dialog(execute_fn=execute_fn)
        assert dlg.phase == _Phase.ERROR

    def test_success_result_message_shown(self, app):
        dlg = self._synced_dialog()
        assert dlg._result_label.text() != ""

    def test_failure_result_message_shown(self, app):
        execute_fn = MagicMock(return_value=(False, "Download failed"))
        dlg = self._synced_dialog(execute_fn=execute_fn)
        assert "Download failed" in dlg._result_label.text()

    def test_sync_completed_emitted_on_success(self, app):
        received = []
        plan = _plan(to_add=[_action()])
        dlg = _dialog(
            compute_fn=MagicMock(return_value=plan),
            execute_fn=MagicMock(return_value=(True, "Done.")),
        )
        dlg.sync_completed.connect(lambda: received.append(True))
        dlg._primary_btn.click()
        dlg._primary_btn.click()
        assert received == [True]

    def test_sync_completed_not_emitted_on_failure(self, app):
        received = []
        plan = _plan(to_add=[_action()])
        dlg = _dialog(
            compute_fn=MagicMock(return_value=plan),
            execute_fn=MagicMock(return_value=(False, "Error")),
        )
        dlg.sync_completed.connect(lambda: received.append(True))
        dlg._primary_btn.click()
        dlg._primary_btn.click()
        assert received == []

    def test_execute_fn_called_with_plan(self, app):
        plan = _plan(to_add=[_action()])
        execute_fn = MagicMock(return_value=(True, "Done."))
        dlg = _dialog(
            compute_fn=MagicMock(return_value=plan),
            execute_fn=execute_fn,
        )
        dlg._primary_btn.click()
        dlg._primary_btn.click()
        assert execute_fn.call_args[0][0] is plan

    def test_progress_updates_bar_and_label(self, app):
        plan = _plan(to_add=[_action()])

        def slow_execute(p, on_progress, is_cancelled):
            on_progress("Downloading…", 1, 3)
            return True, "Done."

        dlg = _dialog(
            compute_fn=MagicMock(return_value=plan),
            execute_fn=slow_execute,
        )
        dlg._primary_btn.click()  # → PREVIEW
        # Capture progress mid-sync by hooking into the worker
        progress_msgs = []
        original_on_progress = dlg._on_sync_progress

        def capturing_progress(msg, done, total):
            progress_msgs.append((msg, done, total))
            original_on_progress(msg, done, total)

        dlg._on_sync_progress = capturing_progress
        dlg._primary_btn.click()  # → SYNCING

        assert ("Downloading…", 1, 3) in progress_msgs

    def test_sync_cannot_start_without_plan(self, app):
        dlg = _dialog()
        dlg._plan = None
        dlg._phase = _Phase.PREVIEW  # force into preview without a plan
        dlg._start_sync()
        # Should not crash or create a worker
        assert dlg._sync_worker is None


# ---------------------------------------------------------------------------
# Button states per phase
# ---------------------------------------------------------------------------

class TestButtonStates:
    def _at_phase(self, phase: _Phase, plan=None):
        if plan is None:
            plan = _plan(to_add=[_action()])
        dlg = _dialog(compute_fn=MagicMock(return_value=plan))
        dlg._set_phase(phase)
        return dlg

    def test_ready_primary_text_and_enabled(self, app):
        dlg = self._at_phase(_Phase.READY)
        assert dlg._primary_btn.text() == "Analyze"
        assert dlg._primary_btn.isEnabled()
        assert not dlg._primary_btn.isHidden()

    def test_analyzing_primary_disabled(self, app):
        dlg = self._at_phase(_Phase.ANALYZING)
        assert not dlg._primary_btn.isEnabled()
        assert dlg._primary_btn.text() == "Analyzing…"

    def test_preview_primary_text_sync(self, app):
        dlg = self._at_phase(_Phase.PREVIEW)
        assert dlg._primary_btn.text() == "Sync"

    def test_syncing_primary_hidden(self, app):
        dlg = self._at_phase(_Phase.SYNCING)
        assert dlg._primary_btn.isHidden()

    def test_done_primary_hidden(self, app):
        dlg = self._at_phase(_Phase.DONE)
        assert dlg._primary_btn.isHidden()

    def test_error_primary_hidden(self, app):
        dlg = self._at_phase(_Phase.ERROR)
        assert dlg._primary_btn.isHidden()

    def test_interrupted_primary_hidden(self, app):
        dlg = self._at_phase(_Phase.INTERRUPTED)
        assert dlg._primary_btn.isHidden()

    def test_ready_secondary_cancel(self, app):
        dlg = self._at_phase(_Phase.READY)
        assert dlg._secondary_btn.text() == "Cancel"

    def test_analyzing_secondary_cancel(self, app):
        dlg = self._at_phase(_Phase.ANALYZING)
        assert dlg._secondary_btn.text() == "Cancel"

    def test_preview_secondary_cancel(self, app):
        dlg = self._at_phase(_Phase.PREVIEW)
        assert dlg._secondary_btn.text() == "Cancel"

    def test_syncing_secondary_stop(self, app):
        dlg = self._at_phase(_Phase.SYNCING)
        assert dlg._secondary_btn.text() == "Stop"

    def test_done_secondary_close(self, app):
        dlg = self._at_phase(_Phase.DONE)
        assert dlg._secondary_btn.text() == "Close"

    def test_error_secondary_close(self, app):
        dlg = self._at_phase(_Phase.ERROR)
        assert dlg._secondary_btn.text() == "Close"

    def test_interrupted_secondary_close(self, app):
        dlg = self._at_phase(_Phase.INTERRUPTED)
        assert dlg._secondary_btn.text() == "Close"

    def test_profile_combo_disabled_in_analyzing(self, app):
        dlg = self._at_phase(_Phase.ANALYZING)
        assert not dlg._profile_combo.isEnabled()

    def test_profile_combo_disabled_in_syncing(self, app):
        dlg = self._at_phase(_Phase.SYNCING)
        assert not dlg._profile_combo.isEnabled()

    def test_profile_combo_enabled_in_ready(self, app):
        dlg = self._at_phase(_Phase.READY)
        assert dlg._profile_combo.isEnabled()


# ---------------------------------------------------------------------------
# Device disconnection
# ---------------------------------------------------------------------------

class TestDeviceDisconnection:
    def test_matching_label_transitions_to_interrupted(self, app):
        dlg = _dialog(device=_device("SWIM PRO"))
        dlg.notify_device_disconnected("SWIM PRO")
        assert dlg.phase == _Phase.INTERRUPTED

    def test_wrong_label_ignored(self, app):
        dlg = _dialog(device=_device("SWIM PRO"))
        dlg.notify_device_disconnected("OpenSwim")
        assert dlg.phase == _Phase.READY

    def test_interrupted_message_shown(self, app):
        dlg = _dialog(device=_device("SWIM PRO"))
        dlg.notify_device_disconnected("SWIM PRO")
        assert "SWIM PRO" in dlg._result_label.text()
        assert "disconnected" in dlg._result_label.text().lower()

    def test_sync_interruption_adds_suffix(self, app):
        dlg = _dialog(device=_device("SWIM PRO"))
        dlg._phase = _Phase.SYNCING  # simulate mid-sync
        dlg.notify_device_disconnected("SWIM PRO")
        assert "interrupted" in dlg._result_label.text().lower()

    def test_non_syncing_interruption_has_no_sync_suffix(self, app):
        dlg = _dialog(device=_device("SWIM PRO"))
        dlg._phase = _Phase.ANALYZING
        dlg.notify_device_disconnected("SWIM PRO")
        assert "Sync was interrupted" not in dlg._result_label.text()

    def test_done_phase_not_overridden(self, app):
        dlg = _dialog(device=_device("SWIM PRO"))
        dlg._set_phase(_Phase.DONE)
        dlg.notify_device_disconnected("SWIM PRO")
        assert dlg.phase == _Phase.DONE

    def test_error_phase_not_overridden(self, app):
        dlg = _dialog(device=_device("SWIM PRO"))
        dlg._set_phase(_Phase.ERROR)
        dlg.notify_device_disconnected("SWIM PRO")
        assert dlg.phase == _Phase.ERROR

    def test_cancel_called_on_sync_worker(self, app):
        dlg = _dialog(device=_device("SWIM PRO"))
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        dlg._sync_worker = mock_worker
        dlg._phase = _Phase.SYNCING
        dlg.notify_device_disconnected("SWIM PRO")
        mock_worker.cancel.assert_called_once()

    def test_fetch_worker_terminated_if_running(self, app):
        dlg = _dialog(device=_device("SWIM PRO"))
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        dlg._fetch_worker = mock_worker
        dlg._phase = _Phase.ANALYZING
        dlg.notify_device_disconnected("SWIM PRO")
        mock_worker.terminate.assert_called_once()


# ---------------------------------------------------------------------------
# _FetchWorker
# ---------------------------------------------------------------------------

class TestFetchWorker:
    def test_run_calls_fetch_feeds_fn(self, app):
        fetch_fn = MagicMock(return_value={})
        compute_fn = MagicMock(return_value=_plan())
        w = _FetchWorker(
            profile=_profile(),
            device=_device(),
            fetch_feeds_fn=fetch_fn,
            compute_plan_fn=compute_fn,
        )
        w.run()
        fetch_fn.assert_called_once()

    def test_run_passes_cache_to_compute(self, app):
        cache = {"http://rss": []}
        fetch_fn = MagicMock(return_value=cache)
        compute_fn = MagicMock(return_value=_plan())
        w = _FetchWorker(
            profile=_profile(),
            device=_device(),
            fetch_feeds_fn=fetch_fn,
            compute_plan_fn=compute_fn,
        )
        w.run()
        assert compute_fn.call_args[0][3] is cache

    def test_emits_plan_ready_on_success(self, app):
        received = []
        plan = _plan()
        w = _FetchWorker(
            profile=_profile(),
            device=_device(),
            fetch_feeds_fn=MagicMock(return_value={}),
            compute_plan_fn=MagicMock(return_value=plan),
        )
        w.plan_ready.connect(received.append)
        w.run()
        assert received == [plan]

    def test_emits_error_on_exception(self, app):
        received = []

        def bad_fetch(p):
            raise RuntimeError("boom")

        w = _FetchWorker(
            profile=_profile(),
            device=_device(),
            fetch_feeds_fn=bad_fetch,
            compute_plan_fn=MagicMock(),
        )
        w.error.connect(received.append)
        w.run()
        assert len(received) == 1
        assert "boom" in received[0]

    def test_compute_not_called_on_fetch_error(self, app):
        compute_fn = MagicMock()

        def bad_fetch(p):
            raise RuntimeError("boom")

        w = _FetchWorker(
            profile=_profile(),
            device=_device(),
            fetch_feeds_fn=bad_fetch,
            compute_plan_fn=compute_fn,
        )
        w.run()
        compute_fn.assert_not_called()

    def test_device_mount_point_passed_to_compute(self, app):
        compute_fn = MagicMock(return_value=_plan())
        dev = _device("SWIM PRO")
        w = _FetchWorker(
            profile=_profile(),
            device=dev,
            fetch_feeds_fn=MagicMock(return_value={}),
            compute_plan_fn=compute_fn,
        )
        w.run()
        assert compute_fn.call_args[0][1] == dev.mount_point
        assert compute_fn.call_args[0][2] == dev.drive_label


# ---------------------------------------------------------------------------
# _SyncWorker
# ---------------------------------------------------------------------------

class TestSyncWorker:
    def test_run_calls_execute_fn(self, app):
        execute_fn = MagicMock(return_value=(True, "done"))
        w = _SyncWorker(plan=_plan(), execute_fn=execute_fn)
        w.run()
        execute_fn.assert_called_once()

    def test_execute_fn_receives_plan(self, app):
        plan = _plan()
        captured = []

        def fake_exec(p, on_progress, is_cancelled):
            captured.append(p)
            return True, "done"

        w = _SyncWorker(plan=plan, execute_fn=fake_exec)
        w.run()
        assert captured[0] is plan

    def test_emits_progress(self, app):
        received = []

        def fake_exec(plan, on_progress, is_cancelled):
            on_progress("Copying ep.mp3", 1, 3)
            return True, "done"

        w = _SyncWorker(plan=_plan(), execute_fn=fake_exec)
        w.progress.connect(lambda msg, done, total: received.append((msg, done, total)))
        w.run()
        assert ("Copying ep.mp3", 1, 3) in received

    def test_emits_finished_true_on_success(self, app):
        received = []
        w = _SyncWorker(
            plan=_plan(),
            execute_fn=MagicMock(return_value=(True, "Done.")),
        )
        w.finished.connect(lambda ok, msg: received.append((ok, msg)))
        w.run()
        assert received == [(True, "Done.")]

    def test_emits_finished_false_on_failure(self, app):
        received = []
        w = _SyncWorker(
            plan=_plan(),
            execute_fn=MagicMock(return_value=(False, "Failed.")),
        )
        w.finished.connect(lambda ok, msg: received.append((ok, msg)))
        w.run()
        assert received == [(False, "Failed.")]

    def test_cancel_sets_flag(self, app):
        w = _SyncWorker(plan=_plan(), execute_fn=MagicMock(return_value=(True, "")))
        assert not w._cancelled
        w.cancel()
        assert w._cancelled

    def test_is_cancelled_callable_reflects_cancel(self, app):
        cancel_results = []

        def fake_exec(plan, on_progress, is_cancelled):
            cancel_results.append(is_cancelled())
            return True, "done"

        w = _SyncWorker(plan=_plan(), execute_fn=fake_exec)
        w.cancel()
        w.run()
        assert cancel_results == [True]

    def test_is_cancelled_false_before_cancel(self, app):
        cancel_results = []

        def fake_exec(plan, on_progress, is_cancelled):
            cancel_results.append(is_cancelled())
            return True, "done"

        w = _SyncWorker(plan=_plan(), execute_fn=fake_exec)
        w.run()
        assert cancel_results == [False]


# ---------------------------------------------------------------------------
# _fmt_bytes helper
# ---------------------------------------------------------------------------

class TestFmtBytes:
    def test_bytes(self):
        assert _fmt_bytes(512) == "512.0 B"

    def test_kilobytes(self):
        assert _fmt_bytes(2048) == "2.0 KB"

    def test_megabytes(self):
        assert _fmt_bytes(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self):
        assert _fmt_bytes(3 * 1024 ** 3) == "3.0 GB"

    def test_terabytes(self):
        assert _fmt_bytes(2 * 1024 ** 4) == "2.0 TB"


# ---------------------------------------------------------------------------
# _default_fetch_feeds
# ---------------------------------------------------------------------------

class TestDefaultFetchFeeds:
    def _episode(self):
        return Episode(
            title="Ep 1", url="http://x.com/ep1.mp3",
            publish_date="2026-06-01", duration_seconds=1800,
            file_size_bytes=5000000, guid="guid-1",
        )

    def test_calls_fetch_feed_for_each_flow(self):
        profile = Profile(name="X")
        profile.flows = [
            Flow(podcast_rss_url="http://rss1.com"),
            Flow(podcast_rss_url="http://rss2.com"),
        ]
        from swimsync.core.rss_client import FeedResult
        ok_result = FeedResult(ok=True, episodes=[self._episode()])
        with patch("swimsync.ui.sync_dialog.fetch_feed", return_value=ok_result) as mock_ff:
            _default_fetch_feeds(profile)
        assert mock_ff.call_count == 2

    def test_deduplicates_duplicate_rss_urls(self):
        profile = Profile(name="X")
        profile.flows = [
            Flow(podcast_rss_url="http://rss.com"),
            Flow(podcast_rss_url="http://rss.com"),
        ]
        from swimsync.core.rss_client import FeedResult
        with patch("swimsync.ui.sync_dialog.fetch_feed",
                   return_value=FeedResult(ok=True, episodes=[])) as mock_ff:
            _default_fetch_feeds(profile)
        assert mock_ff.call_count == 1

    def test_returns_episodes_for_successful_feed(self):
        ep = self._episode()
        profile = Profile(name="X")
        profile.flows = [Flow(podcast_rss_url="http://rss.com")]
        from swimsync.core.rss_client import FeedResult
        with patch("swimsync.ui.sync_dialog.fetch_feed",
                   return_value=FeedResult(ok=True, episodes=[ep])):
            result = _default_fetch_feeds(profile)
        assert result["http://rss.com"] == [ep]

    def test_returns_empty_list_for_failed_feed(self):
        profile = Profile(name="X")
        profile.flows = [Flow(podcast_rss_url="http://rss.com")]
        from swimsync.core.rss_client import FeedResult
        with patch("swimsync.ui.sync_dialog.fetch_feed",
                   return_value=FeedResult(ok=False, episodes=[], error="timeout")):
            result = _default_fetch_feeds(profile)
        assert result["http://rss.com"] == []

    def test_empty_flows_returns_empty_dict(self):
        profile = Profile(name="X")
        result = _default_fetch_feeds(profile)
        assert result == {}
