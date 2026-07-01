"""
Behavior tests for swimsync/ui/flows_view.py.

Covers:
  - _rule_summary() formatting
  - FlowsView row population, empty state, scroll visibility
  - + Add Flow button enable/disable
  - refresh_statuses() indicator updates
  - refresh_profile() rebuilds rows
  - open_add_flow() / open_edit_flow() — dialog wiring via monkeypatching exec
  - _FlowRowWidget: label content, Edit button emits edit_requested
  - _FlowConfigDialog: add mode defaults, edit mode pre-fill, save/cancel/delete
  - _PodcastPickerDialog: list population, Add Flow enable, podcast_picked
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication

from swimsync.models.profile import Flow, Podcast, Profile
from swimsync.ui.flows_view import (
    FlowsView,
    _FlowConfigDialog,
    _FlowRowWidget,
    _PodcastPickerDialog,
    _rule_summary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _podcast(title="Pod A", rss_url="https://example.com/a.rss", author="Author A") -> Podcast:
    return Podcast(
        title=title,
        rss_url=rss_url,
        author=author,
        description="A test podcast.",
        artwork_url=None,
        last_checked=None,
    )


def _flow(rss_url="https://example.com/a.rss", most_recent=3, last_days=None) -> Flow:
    return Flow(
        podcast_rss_url=rss_url,
        most_recent_count=most_recent,
        last_x_days=last_days,
    )


def _profile_with(*podcasts_and_flows) -> Profile:
    """Convenience factory — pass Podcast and Flow objects freely."""
    podcasts = [x for x in podcasts_and_flows if isinstance(x, Podcast)]
    flows = [x for x in podcasts_and_flows if isinstance(x, Flow)]
    return Profile(name="Test", podcasts=podcasts, flows=flows)


def _view(profile=None, on_changed=None) -> FlowsView:
    if profile is None:
        profile = Profile(name="Test")
    if on_changed is None:
        on_changed = MagicMock()
    return FlowsView(profile=profile, on_profile_changed=on_changed)


def _rows(view: FlowsView) -> list[_FlowRowWidget]:
    return list(view._row_widgets)


# ---------------------------------------------------------------------------
# _rule_summary
# ---------------------------------------------------------------------------

class TestRuleSummary:
    def test_most_recent_only_plural(self):
        f = _flow(most_recent=3, last_days=None)
        assert _rule_summary(f) == "3 most recent episodes"

    def test_most_recent_singular(self):
        f = _flow(most_recent=1, last_days=None)
        assert _rule_summary(f) == "1 most recent episode"

    def test_last_days_only(self):
        f = Flow(podcast_rss_url="x", most_recent_count=None, last_x_days=7)
        assert _rule_summary(f) == "Last 7 days"

    def test_both_criteria(self):
        f = Flow(podcast_rss_url="x", most_recent_count=5, last_x_days=30)
        assert _rule_summary(f) == "5 most recent episodes · Last 30 days"

    def test_no_criteria(self):
        f = Flow(podcast_rss_url="x", most_recent_count=None, last_x_days=None)
        assert _rule_summary(f) == "No criteria set"

    def test_most_recent_large_number(self):
        f = _flow(most_recent=100, last_days=None)
        assert "100 most recent episodes" in _rule_summary(f)

    def test_last_days_large_number(self):
        f = Flow(podcast_rss_url="x", most_recent_count=None, last_x_days=365)
        assert "Last 365 days" in _rule_summary(f)


# ---------------------------------------------------------------------------
# FlowsView — empty state
# ---------------------------------------------------------------------------

class TestFlowsViewEmpty:
    def test_empty_label_visible_when_no_flows(self, app):
        view = _view()
        assert not view._empty_label.isHidden()

    def test_scroll_hidden_when_no_flows(self, app):
        view = _view()
        assert view._scroll.isHidden()

    def test_no_row_widgets_when_no_flows(self, app):
        view = _view()
        assert _rows(view) == []

    def test_add_flow_btn_disabled_when_no_podcasts(self, app):
        view = _view()
        assert not view._add_flow_btn.isEnabled()

    def test_add_flow_btn_enabled_when_podcast_without_flow(self, app):
        p = _podcast()
        profile = _profile_with(p)
        view = _view(profile=profile)
        assert view._add_flow_btn.isEnabled()

    def test_add_flow_btn_disabled_when_all_podcasts_have_flows(self, app):
        p = _podcast()
        f = _flow(rss_url=p.rss_url)
        profile = _profile_with(p, f)
        view = _view(profile=profile)
        assert not view._add_flow_btn.isEnabled()

    def test_empty_label_text(self, app):
        view = _view()
        assert "No flows configured" in view._empty_label.text()


# ---------------------------------------------------------------------------
# FlowsView — rows present
# ---------------------------------------------------------------------------

class TestFlowsViewWithRows:
    def setup_method(self):
        self.p1 = _podcast("Pod A", "https://a.com/feed")
        self.p2 = _podcast("Pod B", "https://b.com/feed")
        self.f1 = _flow(rss_url="https://a.com/feed", most_recent=3)
        self.f2 = _flow(rss_url="https://b.com/feed", most_recent=5, last_days=14)

    def test_row_count_matches_flow_count(self, app):
        profile = _profile_with(self.p1, self.p2, self.f1, self.f2)
        view = _view(profile=profile)
        assert len(_rows(view)) == 2

    def test_empty_label_hidden_when_rows_present(self, app):
        profile = _profile_with(self.p1, self.f1)
        view = _view(profile=profile)
        assert view._empty_label.isHidden()

    def test_scroll_visible_when_rows_present(self, app):
        profile = _profile_with(self.p1, self.f1)
        view = _view(profile=profile)
        assert not view._scroll.isHidden()

    def test_row_shows_podcast_title(self, app):
        profile = _profile_with(self.p1, self.f1)
        view = _view(profile=profile)
        row = _rows(view)[0]
        assert row._podcast_label.text() == "Pod A"

    def test_row_shows_rule_summary(self, app):
        profile = _profile_with(self.p1, self.f1)
        view = _view(profile=profile)
        row = _rows(view)[0]
        assert "3 most recent episodes" in row._summary_label.text()

    def test_row_shows_both_criteria_in_summary(self, app):
        profile = _profile_with(self.p2, self.f2)
        view = _view(profile=profile)
        row = _rows(view)[0]
        assert "5 most recent episodes" in row._summary_label.text()
        assert "Last 14 days" in row._summary_label.text()

    def test_orphan_flow_skipped_when_podcast_missing(self, app):
        # Flow references a podcast not in the profile
        orphan = _flow(rss_url="https://missing.com/feed")
        profile = Profile(name="T", flows=[orphan])
        view = _view(profile=profile)
        assert _rows(view) == []

    def test_add_flow_enabled_when_podcast_missing_a_flow(self, app):
        profile = _profile_with(self.p1, self.p2, self.f1)
        view = _view(profile=profile)
        assert view._add_flow_btn.isEnabled()


# ---------------------------------------------------------------------------
# FlowsView — refresh_statuses
# ---------------------------------------------------------------------------

class TestRefreshStatuses:
    def setup_method(self):
        self.p = _podcast("Pod", "https://pod.com/feed")
        self.f = _flow(rss_url="https://pod.com/feed")
        self.profile = _profile_with(self.p, self.f)

    def test_stale_indicator_set(self, app):
        view = _view(profile=self.profile)
        view.refresh_statuses({"https://pod.com/feed": (True, False)})
        row = _rows(view)[0]
        assert "45+ days" in row._indicator_label.text()

    def test_error_indicator_set(self, app):
        view = _view(profile=self.profile)
        view.refresh_statuses({"https://pod.com/feed": (False, True)})
        row = _rows(view)[0]
        assert "unavailable" in row._indicator_label.text()

    def test_no_indicator_when_healthy(self, app):
        view = _view(profile=self.profile)
        view.refresh_statuses({"https://pod.com/feed": (False, False)})
        row = _rows(view)[0]
        assert row._indicator_label.text() == ""

    def test_stale_takes_precedence_over_error(self, app):
        view = _view(profile=self.profile)
        view.refresh_statuses({"https://pod.com/feed": (True, True)})
        row = _rows(view)[0]
        assert "45+ days" in row._indicator_label.text()

    def test_unknown_url_does_not_crash(self, app):
        view = _view(profile=self.profile)
        view.refresh_statuses({"https://other.com/feed": (True, False)})
        row = _rows(view)[0]
        assert row._indicator_label.text() == ""

    def test_statuses_applied_on_construction(self, app):
        view = FlowsView(
            profile=self.profile,
            on_profile_changed=MagicMock(),
        )
        # Confirm indicator starts blank (no statuses passed yet)
        row = _rows(view)[0]
        assert row._indicator_label.text() == ""


# ---------------------------------------------------------------------------
# FlowsView — refresh_profile
# ---------------------------------------------------------------------------

class TestRefreshProfile:
    def test_refresh_adds_new_row(self, app):
        p1 = _podcast("Pod A", "https://a.com/feed")
        f1 = _flow(rss_url="https://a.com/feed")
        profile = _profile_with(p1, f1)
        view = _view(profile=profile)
        assert len(_rows(view)) == 1

        p2 = _podcast("Pod B", "https://b.com/feed")
        f2 = _flow(rss_url="https://b.com/feed")
        profile.podcasts.append(p2)
        profile.flows.append(f2)
        view.refresh_profile(profile)
        assert len(_rows(view)) == 2

    def test_refresh_removes_deleted_flow(self, app):
        p = _podcast()
        f = _flow(rss_url=p.rss_url)
        profile = _profile_with(p, f)
        view = _view(profile=profile)
        assert len(_rows(view)) == 1

        profile.flows.clear()
        view.refresh_profile(profile)
        assert len(_rows(view)) == 0

    def test_refresh_shows_empty_label_when_no_flows(self, app):
        p = _podcast()
        f = _flow(rss_url=p.rss_url)
        profile = _profile_with(p, f)
        view = _view(profile=profile)
        profile.flows.clear()
        view.refresh_profile(profile)
        assert not view._empty_label.isHidden()


# ---------------------------------------------------------------------------
# FlowsView — open_add_flow / open_edit_flow
# ---------------------------------------------------------------------------

class TestOpenAddEditFlow:
    def _captured_dialog(self) -> tuple[list, list]:
        saved: list[Flow] = []
        deleted: list[Flow] = []
        return saved, deleted

    def test_open_add_flow_opens_dialog(self, app):
        profile = _profile_with(_podcast())
        view = _view(profile=profile)
        with patch.object(_FlowConfigDialog, "exec", return_value=None):
            view.open_add_flow(_podcast())
            # No exception = dialog opened correctly

    def test_open_edit_flow_opens_dialog(self, app):
        p = _podcast()
        f = _flow(rss_url=p.rss_url)
        profile = _profile_with(p, f)
        view = _view(profile=profile)
        with patch.object(_FlowConfigDialog, "exec", return_value=None):
            view.open_edit_flow(p)

    def test_add_flow_saves_new_flow_to_profile(self, app):
        p = _podcast()
        profile = _profile_with(p)
        on_changed = MagicMock()
        view = _view(profile=profile, on_changed=on_changed)

        new_flow = Flow(podcast_rss_url=p.rss_url, most_recent_count=5)

        def fake_exec(self):
            self.flow_saved.emit(new_flow)

        with patch.object(_FlowConfigDialog, "exec", fake_exec):
            view.open_add_flow(p)

        assert any(f.podcast_rss_url == p.rss_url for f in profile.flows)
        on_changed.assert_called_once()

    def test_add_flow_creates_row(self, app):
        p = _podcast()
        profile = _profile_with(p)
        view = _view(profile=profile)
        assert len(_rows(view)) == 0

        new_flow = Flow(podcast_rss_url=p.rss_url, most_recent_count=3)

        def fake_exec(self):
            self.flow_saved.emit(new_flow)

        with patch.object(_FlowConfigDialog, "exec", fake_exec):
            view.open_add_flow(p)

        assert len(_rows(view)) == 1

    def test_edit_flow_updates_existing_flow(self, app):
        p = _podcast()
        f = _flow(rss_url=p.rss_url, most_recent=3)
        profile = _profile_with(p, f)
        view = _view(profile=profile)

        updated_flow = Flow(podcast_rss_url=p.rss_url, most_recent_count=10, last_x_days=30)

        def fake_exec(self):
            self.flow_saved.emit(updated_flow)

        with patch.object(_FlowConfigDialog, "exec", fake_exec):
            view.open_edit_flow(p)

        saved = profile.get_flow(p.rss_url)
        assert saved is not None
        assert saved.most_recent_count == 10
        assert saved.last_x_days == 30

    def test_delete_flow_removes_from_profile(self, app):
        p = _podcast()
        f = _flow(rss_url=p.rss_url)
        profile = _profile_with(p, f)
        on_changed = MagicMock()
        view = _view(profile=profile, on_changed=on_changed)
        assert len(_rows(view)) == 1

        def fake_exec(self):
            self.flow_deleted.emit(f)

        with patch.object(_FlowConfigDialog, "exec", fake_exec):
            view.open_edit_flow(p)

        assert profile.get_flow(p.rss_url) is None
        assert len(_rows(view)) == 0
        on_changed.assert_called_once()

    def test_cancel_does_not_save(self, app):
        p = _podcast()
        profile = _profile_with(p)
        on_changed = MagicMock()
        view = _view(profile=profile, on_changed=on_changed)

        with patch.object(_FlowConfigDialog, "exec", return_value=None):
            view.open_add_flow(p)

        on_changed.assert_not_called()
        assert len(_rows(view)) == 0


# ---------------------------------------------------------------------------
# FlowsView — picker button opens picker then dialog
# ---------------------------------------------------------------------------

class TestPickerButton:
    def test_picker_disabled_when_no_candidates(self, app):
        p = _podcast()
        f = _flow(rss_url=p.rss_url)
        profile = _profile_with(p, f)
        view = _view(profile=profile)
        assert not view._add_flow_btn.isEnabled()

    def test_picker_enabled_when_candidates_exist(self, app):
        p = _podcast()
        profile = _profile_with(p)
        view = _view(profile=profile)
        assert view._add_flow_btn.isEnabled()

    def test_picker_dialog_receives_candidates(self, app):
        p1 = _podcast("Pod A", "https://a.com")
        p2 = _podcast("Pod B", "https://b.com")
        f1 = _flow(rss_url="https://a.com")
        profile = _profile_with(p1, p2, f1)
        view = _view(profile=profile)

        opened_with: list[list[Podcast]] = []

        original_init = _PodcastPickerDialog.__init__

        def patched_init(self, podcasts, parent=None):
            opened_with.append(list(podcasts))
            original_init(self, podcasts, parent)

        with patch.object(_PodcastPickerDialog, "__init__", patched_init):
            with patch.object(_PodcastPickerDialog, "exec", return_value=None):
                view._add_flow_btn.click()

        assert len(opened_with) == 1
        titles = [p.title for p in opened_with[0]]
        assert "Pod B" in titles
        assert "Pod A" not in titles  # already has a flow

    def test_no_picker_when_all_podcasts_have_flows(self, app):
        p = _podcast()
        f = _flow(rss_url=p.rss_url)
        profile = _profile_with(p, f)
        view = _view(profile=profile)
        # Button is disabled so _open_picker would return early anyway
        candidates = view._podcasts_without_flows()
        assert candidates == []


# ---------------------------------------------------------------------------
# _FlowRowWidget
# ---------------------------------------------------------------------------

class TestFlowRowWidget:
    def setup_method(self):
        self.p = _podcast("My Show", "https://show.com/feed", "Author X")
        self.f = Flow(podcast_rss_url="https://show.com/feed", most_recent_count=5)

    def test_podcast_label_shows_title(self, app):
        row = _FlowRowWidget(self.p, self.f)
        assert row._podcast_label.text() == "My Show"

    def test_summary_label_shows_rule(self, app):
        row = _FlowRowWidget(self.p, self.f)
        assert "5 most recent episodes" in row._summary_label.text()

    def test_indicator_blank_by_default(self, app):
        row = _FlowRowWidget(self.p, self.f)
        assert row._indicator_label.text() == ""

    def test_stale_indicator(self, app):
        row = _FlowRowWidget(self.p, self.f, is_stale=True)
        assert "45+ days" in row._indicator_label.text()

    def test_error_indicator(self, app):
        row = _FlowRowWidget(self.p, self.f, has_error=True)
        assert "unavailable" in row._indicator_label.text()

    def test_stale_overrides_error(self, app):
        row = _FlowRowWidget(self.p, self.f, is_stale=True, has_error=True)
        assert "45+ days" in row._indicator_label.text()

    def test_update_status_to_stale(self, app):
        row = _FlowRowWidget(self.p, self.f)
        row.update_status(is_stale=True, has_error=False)
        assert "45+ days" in row._indicator_label.text()

    def test_update_status_to_error(self, app):
        row = _FlowRowWidget(self.p, self.f)
        row.update_status(is_stale=False, has_error=True)
        assert "unavailable" in row._indicator_label.text()

    def test_update_status_clear(self, app):
        row = _FlowRowWidget(self.p, self.f, is_stale=True)
        row.update_status(is_stale=False, has_error=False)
        assert row._indicator_label.text() == ""

    def test_rss_url_property(self, app):
        row = _FlowRowWidget(self.p, self.f)
        assert row.rss_url == "https://show.com/feed"

    def test_edit_btn_emits_edit_requested(self, app):
        row = _FlowRowWidget(self.p, self.f)
        received: list[Podcast] = []
        row.edit_requested.connect(received.append)
        row._edit_btn.click()
        assert len(received) == 1
        assert received[0] is self.p

    def test_edit_btn_label(self, app):
        row = _FlowRowWidget(self.p, self.f)
        assert row._edit_btn.text() == "Edit"


# ---------------------------------------------------------------------------
# _FlowConfigDialog — add mode
# ---------------------------------------------------------------------------

class TestFlowConfigDialogAddMode:
    def setup_method(self):
        self.p = _podcast("My Podcast", "https://pod.com/feed", "Author")

    def test_window_title_add_mode(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        assert "Add Flow" in dlg.windowTitle()
        assert "My Podcast" in dlg.windowTitle()

    def test_title_label_shows_podcast(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        assert dlg._title_label.text() == "My Podcast"

    def test_author_label_shows_author(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        assert dlg._author_label.text() == "Author"

    def test_most_recent_checked_by_default(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        assert dlg._most_recent_check.isChecked()

    def test_last_days_unchecked_by_default(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        assert not dlg._last_days_check.isChecked()

    def test_most_recent_default_value(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        assert dlg._most_recent_spin.value() == 3

    def test_last_days_default_value(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        assert dlg._last_days_spin.value() == 7

    def test_save_btn_enabled_when_most_recent_checked(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        assert dlg._save_btn.isEnabled()

    def test_save_btn_disabled_when_nothing_checked(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        dlg._most_recent_check.setChecked(False)
        assert not dlg._save_btn.isEnabled()

    def test_save_btn_enabled_when_only_days_checked(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        dlg._most_recent_check.setChecked(False)
        dlg._last_days_check.setChecked(True)
        assert dlg._save_btn.isEnabled()

    def test_save_btn_enabled_when_both_checked(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        dlg._last_days_check.setChecked(True)
        assert dlg._save_btn.isEnabled()

    def test_no_delete_btn_in_add_mode(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        assert not hasattr(dlg, "_delete_btn")

    def test_save_emits_flow_saved(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        received: list[Flow] = []
        dlg.flow_saved.connect(received.append)
        dlg._most_recent_spin.setValue(7)
        dlg._on_save()
        assert len(received) == 1
        assert received[0].most_recent_count == 7
        assert received[0].last_x_days is None

    def test_save_emits_correct_rss_url(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        received: list[Flow] = []
        dlg.flow_saved.connect(received.append)
        dlg._on_save()
        assert received[0].podcast_rss_url == "https://pod.com/feed"

    def test_save_both_criteria(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        dlg._most_recent_spin.setValue(5)
        dlg._last_days_check.setChecked(True)
        dlg._last_days_spin.setValue(14)
        received: list[Flow] = []
        dlg.flow_saved.connect(received.append)
        dlg._on_save()
        assert received[0].most_recent_count == 5
        assert received[0].last_x_days == 14

    def test_save_unchecked_criteria_produces_none(self, app):
        dlg = _FlowConfigDialog(self.p, existing_flow=None)
        dlg._most_recent_check.setChecked(False)
        dlg._last_days_check.setChecked(True)
        dlg._last_days_spin.setValue(30)
        received: list[Flow] = []
        dlg.flow_saved.connect(received.append)
        dlg._on_save()
        assert received[0].most_recent_count is None
        assert received[0].last_x_days == 30


# ---------------------------------------------------------------------------
# _FlowConfigDialog — edit mode
# ---------------------------------------------------------------------------

class TestFlowConfigDialogEditMode:
    def setup_method(self):
        self.p = _podcast("My Podcast", "https://pod.com/feed", "Author")

    def test_window_title_edit_mode(self, app):
        f = _flow(most_recent=5)
        dlg = _FlowConfigDialog(self.p, existing_flow=f)
        assert "Edit Flow" in dlg.windowTitle()

    def test_most_recent_prefilled_from_existing_flow(self, app):
        f = _flow(most_recent=10)
        dlg = _FlowConfigDialog(self.p, existing_flow=f)
        assert dlg._most_recent_check.isChecked()
        assert dlg._most_recent_spin.value() == 10

    def test_last_days_prefilled_from_existing_flow(self, app):
        f = Flow(podcast_rss_url=self.p.rss_url, most_recent_count=None, last_x_days=21)
        dlg = _FlowConfigDialog(self.p, existing_flow=f)
        assert dlg._last_days_check.isChecked()
        assert dlg._last_days_spin.value() == 21
        assert not dlg._most_recent_check.isChecked()

    def test_both_criteria_prefilled(self, app):
        f = Flow(podcast_rss_url=self.p.rss_url, most_recent_count=3, last_x_days=7)
        dlg = _FlowConfigDialog(self.p, existing_flow=f)
        assert dlg._most_recent_check.isChecked()
        assert dlg._last_days_check.isChecked()

    def test_delete_btn_present_in_edit_mode(self, app):
        f = _flow()
        dlg = _FlowConfigDialog(self.p, existing_flow=f)
        assert hasattr(dlg, "_delete_btn")

    def test_delete_emits_flow_deleted(self, app):
        f = _flow(most_recent=3)
        dlg = _FlowConfigDialog(self.p, existing_flow=f)
        received: list[Flow] = []
        dlg.flow_deleted.connect(received.append)
        dlg._on_delete()
        assert len(received) == 1
        assert received[0].podcast_rss_url == f.podcast_rss_url

    def test_edit_save_emits_updated_flow(self, app):
        f = _flow(most_recent=3)
        dlg = _FlowConfigDialog(self.p, existing_flow=f)
        dlg._most_recent_spin.setValue(8)
        received: list[Flow] = []
        dlg.flow_saved.connect(received.append)
        dlg._on_save()
        assert received[0].most_recent_count == 8

    def test_flow_none_criteria_unchecked_in_edit(self, app):
        f = Flow(podcast_rss_url=self.p.rss_url, most_recent_count=None, last_x_days=None)
        dlg = _FlowConfigDialog(self.p, existing_flow=f)
        assert not dlg._most_recent_check.isChecked()
        assert not dlg._last_days_check.isChecked()
        assert not dlg._save_btn.isEnabled()


# ---------------------------------------------------------------------------
# _PodcastPickerDialog
# ---------------------------------------------------------------------------

class TestPodcastPickerDialog:
    def setup_method(self):
        self.p1 = _podcast("Alpha", "https://a.com")
        self.p2 = _podcast("Beta", "https://b.com")
        self.p3 = _podcast("Gamma", "https://g.com")

    def test_list_shows_all_podcasts(self, app):
        dlg = _PodcastPickerDialog([self.p1, self.p2, self.p3])
        assert dlg._list.count() == 3

    def test_list_item_titles(self, app):
        dlg = _PodcastPickerDialog([self.p1, self.p2])
        titles = [dlg._list.item(i).text() for i in range(dlg._list.count())]
        assert "Alpha" in titles
        assert "Beta" in titles

    def test_add_flow_btn_disabled_initially(self, app):
        dlg = _PodcastPickerDialog([self.p1])
        assert not dlg._select_btn.isEnabled()

    def test_add_flow_btn_enabled_on_selection(self, app):
        dlg = _PodcastPickerDialog([self.p1, self.p2])
        dlg._list.setCurrentRow(0)
        assert dlg._select_btn.isEnabled()

    def test_add_flow_btn_disabled_when_selection_cleared(self, app):
        dlg = _PodcastPickerDialog([self.p1])
        dlg._list.setCurrentRow(0)
        dlg._list.setCurrentRow(-1)
        assert not dlg._select_btn.isEnabled()

    def test_podcast_picked_emitted_on_select(self, app):
        dlg = _PodcastPickerDialog([self.p1, self.p2])
        received: list[Podcast] = []
        dlg.podcast_picked.connect(received.append)
        dlg._list.setCurrentRow(1)
        dlg._on_select()
        assert len(received) == 1
        assert received[0] is self.p2

    def test_podcast_picked_first_item(self, app):
        dlg = _PodcastPickerDialog([self.p1, self.p2])
        received: list[Podcast] = []
        dlg.podcast_picked.connect(received.append)
        dlg._list.setCurrentRow(0)
        dlg._on_select()
        assert received[0] is self.p1

    def test_no_emit_when_no_selection(self, app):
        dlg = _PodcastPickerDialog([self.p1])
        received: list[Podcast] = []
        dlg.podcast_picked.connect(received.append)
        dlg._on_select()
        assert received == []

    def test_window_title(self, app):
        dlg = _PodcastPickerDialog([self.p1])
        assert "Add Flow" in dlg.windowTitle()

    def test_list_item_carries_podcast_data(self, app):
        dlg = _PodcastPickerDialog([self.p1, self.p2])
        from PyQt6.QtCore import Qt
        item = dlg._list.item(0)
        podcast = item.data(Qt.ItemDataRole.UserRole)
        assert isinstance(podcast, Podcast)
        assert podcast.rss_url in {self.p1.rss_url, self.p2.rss_url}


# ---------------------------------------------------------------------------
# FlowsView — podcasts_without_flows helper
# ---------------------------------------------------------------------------

class TestPodcastsWithoutFlows:
    def test_all_podcasts_returned_when_no_flows(self, app):
        p1 = _podcast("A", "https://a.com")
        p2 = _podcast("B", "https://b.com")
        profile = _profile_with(p1, p2)
        view = _view(profile=profile)
        result = view._podcasts_without_flows()
        assert len(result) == 2

    def test_podcast_with_flow_excluded(self, app):
        p1 = _podcast("A", "https://a.com")
        p2 = _podcast("B", "https://b.com")
        f1 = _flow(rss_url="https://a.com")
        profile = _profile_with(p1, p2, f1)
        view = _view(profile=profile)
        result = view._podcasts_without_flows()
        assert len(result) == 1
        assert result[0].rss_url == "https://b.com"

    def test_empty_when_all_have_flows(self, app):
        p1 = _podcast("A", "https://a.com")
        f1 = _flow(rss_url="https://a.com")
        profile = _profile_with(p1, f1)
        view = _view(profile=profile)
        assert view._podcasts_without_flows() == []

    def test_empty_when_no_podcasts(self, app):
        view = _view()
        assert view._podcasts_without_flows() == []
