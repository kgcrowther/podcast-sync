"""
Tests for swimsync.ui.podcasts_view.

Behavioral tests only: list population, filter bar, status indicators,
signal emission, follow/unfollow flows, and dialog interactions.
Visual layout and styling are not tested here.

Run with: pytest tests/test_podcasts_view.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from swimsync.core.podcast_search import (
    FeedValidationResult,
    PodcastSearchResult,
    SearchOutcome,
)
from swimsync.models.profile import Flow, PlaylistItem, Podcast, Profile
from swimsync.ui.podcasts_view import (
    FollowPodcastDialog,
    PodcastStatus,
    PodcastsView,
    _Worker,
)


# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _podcast(title: str, rss_url: str = "", author: str = "Some Author") -> Podcast:
    url = rss_url or f"https://feeds.example.com/{title.lower().replace(' ', '-')}"
    return Podcast(
        title=title,
        rss_url=url,
        author=author,
        description="",
        artwork_url=None,
        last_checked=None,
    )


@pytest.fixture
def three_podcasts():
    return [
        _podcast("Tech Talk", "https://feeds.example.com/tech"),
        _podcast("Science Hour", "https://feeds.example.com/science"),
        _podcast("History Today", "https://feeds.example.com/history"),
    ]


@pytest.fixture
def profile(three_podcasts):
    return Profile(name="TestUser", podcasts=list(three_podcasts))


# Replace the background worker with a synchronous version for all tests.
@pytest.fixture(autouse=True)
def sync_worker(monkeypatch):
    class _SyncWorker(_Worker):
        def start(self, priority=None):
            self.run()   # executes fn + emits finished synchronously

    monkeypatch.setattr("swimsync.ui.podcasts_view._Worker", _SyncWorker)


@pytest.fixture
def view(qapp, profile):
    saved = []
    v = PodcastsView(
        profile=profile,
        on_profile_changed=saved.append,
        search_fn=MagicMock(return_value=SearchOutcome(ok=True, results=[])),
        validate_fn=MagicMock(return_value=FeedValidationResult(ok=False, error="stub")),
    )
    v._saved = saved
    yield v
    v.close()


# ---------------------------------------------------------------------------
# List population
# ---------------------------------------------------------------------------

class TestListPopulation:
    def test_podcasts_appear_in_list(self, view, three_podcasts):
        assert view._list.count() == len(three_podcasts)

    def test_empty_profile_shows_no_items(self, qapp):
        v = PodcastsView(profile=Profile(name="Empty"), on_profile_changed=lambda _: None)
        assert v._list.count() == 0
        v.close()

    def test_podcast_stored_as_user_role_data(self, view, three_podcasts):
        stored_urls = {
            view._list.item(i).data(Qt.ItemDataRole.UserRole).rss_url
            for i in range(view._list.count())
        }
        assert stored_urls == {p.rss_url for p in three_podcasts}

    def test_item_text_contains_title(self, view, three_podcasts):
        for i, podcast in enumerate(three_podcasts):
            assert podcast.title in view._list.item(i).text()

    def test_item_text_contains_author(self, view, three_podcasts):
        for i, podcast in enumerate(three_podcasts):
            assert podcast.author in view._list.item(i).text()

    def test_refresh_profile_updates_list(self, view):
        new_profile = Profile(name="Other", podcasts=[_podcast("Only Show")])
        view.refresh_profile(new_profile)
        assert view._list.count() == 1
        assert view._list.item(0).data(Qt.ItemDataRole.UserRole).title == "Only Show"


# ---------------------------------------------------------------------------
# Filter bar
# ---------------------------------------------------------------------------

class TestFilterBar:
    def _visible(self, view):
        return [
            view._list.item(i)
            for i in range(view._list.count())
            if not view._list.item(i).isHidden()
        ]

    def test_filter_by_title(self, view):
        view._filter_edit.setText("tech")
        assert len(self._visible(view)) == 1
        assert self._visible(view)[0].data(Qt.ItemDataRole.UserRole).title == "Tech Talk"

    def test_filter_by_author(self, qapp):
        podcasts = [_podcast("Show A", author="Alice"), _podcast("Show B", author="Bob")]
        v = PodcastsView(
            profile=Profile(name="U", podcasts=podcasts),
            on_profile_changed=lambda _: None,
        )
        v._filter_edit.setText("alice")
        visible = [v._list.item(i) for i in range(v._list.count()) if not v._list.item(i).isHidden()]
        assert len(visible) == 1
        assert visible[0].data(Qt.ItemDataRole.UserRole).author == "Alice"
        v.close()

    def test_filter_is_case_insensitive(self, view):
        view._filter_edit.setText("TECH")
        assert len(self._visible(view)) == 1

    def test_clearing_filter_restores_all(self, view, three_podcasts):
        view._filter_edit.setText("tech")
        view._filter_edit.setText("")
        assert len(self._visible(view)) == len(three_podcasts)

    def test_no_match_hides_all(self, view, three_podcasts):
        view._filter_edit.setText("xyzzy")
        assert len(self._visible(view)) == 0

    def test_filter_persists_after_refresh_statuses(self, view, three_podcasts):
        view._filter_edit.setText("tech")
        view.refresh_statuses({})
        visible = self._visible(view)
        assert len(visible) == 1
        assert visible[0].data(Qt.ItemDataRole.UserRole).title == "Tech Talk"


# ---------------------------------------------------------------------------
# Status indicators
# ---------------------------------------------------------------------------

class TestStatusIndicators:
    def test_stale_prefix_on_item(self, view, three_podcasts):
        url = three_podcasts[0].rss_url
        view.refresh_statuses({url: PodcastStatus(is_stale=True)})
        assert view._list.item(0).text().startswith("● ")

    def test_error_prefix_on_item(self, view, three_podcasts):
        url = three_podcasts[1].rss_url
        view.refresh_statuses({url: PodcastStatus(has_error=True)})
        assert view._list.item(1).text().startswith("⚠ ")

    def test_normal_podcast_has_no_prefix(self, view):
        view.refresh_statuses({})
        item = view._list.item(0)
        assert not item.text().startswith("● ")
        assert not item.text().startswith("⚠ ")

    def test_stale_flag_in_status_role(self, view, three_podcasts):
        url = three_podcasts[0].rss_url
        view.refresh_statuses({url: PodcastStatus(is_stale=True)})
        assert view._list.item(0).data(Qt.ItemDataRole.UserRole + 1) == "stale"

    def test_error_flag_in_status_role(self, view, three_podcasts):
        url = three_podcasts[1].rss_url
        view.refresh_statuses({url: PodcastStatus(has_error=True)})
        assert view._list.item(1).data(Qt.ItemDataRole.UserRole + 1) == "error"

    def test_normal_flag_is_none(self, view):
        view.refresh_statuses({})
        assert view._list.item(0).data(Qt.ItemDataRole.UserRole + 1) is None

    def test_refresh_statuses_does_not_change_count(self, view, three_podcasts):
        view.refresh_statuses({})
        assert view._list.count() == len(three_podcasts)


# ---------------------------------------------------------------------------
# Podcast selection signal
# ---------------------------------------------------------------------------

class TestPodcastSelection:
    def test_clicking_item_emits_podcast_selected(self, view, three_podcasts):
        received = []
        view.podcast_selected.connect(received.append)
        view._on_item_clicked(view._list.item(0))
        assert len(received) == 1

    def test_emitted_podcast_matches_clicked_item(self, view, three_podcasts):
        received = []
        view.podcast_selected.connect(received.append)
        for i in range(view._list.count()):
            view._on_item_clicked(view._list.item(i))
        assert [p.title for p in received] == [p.title for p in three_podcasts]

    def test_emitted_object_is_podcast_instance(self, view):
        received = []
        view.podcast_selected.connect(received.append)
        view._on_item_clicked(view._list.item(0))
        assert isinstance(received[0], Podcast)


# ---------------------------------------------------------------------------
# Follow podcast
# ---------------------------------------------------------------------------

class TestFollowPodcast:
    def test_add_podcast_appends_to_profile(self, view):
        new = _podcast("New Show", "https://feeds.example.com/new")
        view._add_podcast(new)
        assert any(p.rss_url == new.rss_url for p in view._profile.podcasts)

    def test_add_podcast_calls_on_profile_changed(self, view):
        view._add_podcast(_podcast("New Show", "https://feeds.example.com/new"))
        assert len(view._saved) == 1

    def test_add_podcast_updates_list(self, view):
        before = view._list.count()
        view._add_podcast(_podcast("New Show", "https://feeds.example.com/new"))
        assert view._list.count() == before + 1

    def test_duplicate_url_not_added(self, view, three_podcasts):
        before = len(view._profile.podcasts)
        view._add_podcast(three_podcasts[0])
        assert len(view._profile.podcasts) == before

    def test_duplicate_does_not_call_on_profile_changed(self, view, three_podcasts):
        view._add_podcast(three_podcasts[0])
        assert len(view._saved) == 0


# ---------------------------------------------------------------------------
# Unfollow podcast
# ---------------------------------------------------------------------------

class TestUnfollowPodcast:
    def test_unfollow_removes_podcast(self, view, three_podcasts):
        target = three_podcasts[0]
        view._unfollow(target)
        assert not any(p.rss_url == target.rss_url for p in view._profile.podcasts)

    def test_unfollow_decrements_list(self, view, three_podcasts):
        before = view._list.count()
        view._unfollow(three_podcasts[0])
        assert view._list.count() == before - 1

    def test_unfollow_calls_on_profile_changed(self, view, three_podcasts):
        view._unfollow(three_podcasts[0])
        assert len(view._saved) == 1

    def test_unfollow_removes_associated_flow(self, view, three_podcasts):
        target = three_podcasts[0]
        view._profile.flows.append(Flow(podcast_rss_url=target.rss_url, most_recent_count=3))
        view._unfollow(target)
        assert not any(f.podcast_rss_url == target.rss_url for f in view._profile.flows)

    def test_unfollow_removes_playlist_items(self, view, three_podcasts):
        target = three_podcasts[0]
        view._profile.playlist.append(PlaylistItem(
            title="Ep 1", source_label=target.title,
            file_size_bytes=None, duration_seconds=None,
            podcast_rss_url=target.rss_url, episode_guid="g1",
            episode_url="https://example.com/ep1.mp3",
        ))
        view._unfollow(target)
        assert not any(i.podcast_rss_url == target.rss_url for i in view._profile.playlist)

    def test_unfollow_no_warning_if_clean(self, view, three_podcasts, monkeypatch):
        calls = []
        monkeypatch.setattr(view, "_confirm_unfollow", lambda p, d: calls.append(True) or True)
        view._unfollow(three_podcasts[0])
        assert not calls

    def test_unfollow_warns_if_flow_exists(self, view, three_podcasts, monkeypatch):
        target = three_podcasts[0]
        view._profile.flows.append(Flow(podcast_rss_url=target.rss_url))
        calls = []
        monkeypatch.setattr(view, "_confirm_unfollow", lambda p, d: calls.append(d) or True)
        view._unfollow(target)
        assert calls
        assert "flow" in calls[0]

    def test_unfollow_warns_if_playlist_items_exist(self, view, three_podcasts, monkeypatch):
        target = three_podcasts[0]
        view._profile.playlist.append(PlaylistItem(
            title="Ep", source_label=target.title,
            file_size_bytes=None, duration_seconds=None,
            podcast_rss_url=target.rss_url, episode_guid="g1",
            episode_url="https://example.com/ep.mp3",
        ))
        calls = []
        monkeypatch.setattr(view, "_confirm_unfollow", lambda p, d: calls.append(d) or True)
        view._unfollow(target)
        assert calls
        assert "playlist" in calls[0]

    def test_unfollow_cancelled_keeps_podcast(self, view, three_podcasts, monkeypatch):
        target = three_podcasts[0]
        view._profile.flows.append(Flow(podcast_rss_url=target.rss_url))
        monkeypatch.setattr(view, "_confirm_unfollow", lambda p, d: False)
        before = len(view._profile.podcasts)
        view._unfollow(target)
        assert len(view._profile.podcasts) == before

    def test_unfollow_detail_mentions_both_flow_and_playlist(self, view, three_podcasts, monkeypatch):
        target = three_podcasts[0]
        view._profile.flows.append(Flow(podcast_rss_url=target.rss_url))
        view._profile.playlist.append(PlaylistItem(
            title="Ep", source_label=target.title,
            file_size_bytes=None, duration_seconds=None,
            podcast_rss_url=target.rss_url, episode_guid="g1",
            episode_url="https://example.com/ep.mp3",
        ))
        details = []
        monkeypatch.setattr(view, "_confirm_unfollow", lambda p, d: details.append(d) or True)
        view._unfollow(target)
        assert "flow" in details[0] and "playlist" in details[0]

    def test_unfollow_plural_playlist_items(self, view, three_podcasts, monkeypatch):
        target = three_podcasts[0]
        for i in range(3):
            view._profile.playlist.append(PlaylistItem(
                title=f"Ep {i}", source_label=target.title,
                file_size_bytes=None, duration_seconds=None,
                podcast_rss_url=target.rss_url, episode_guid=f"g{i}",
                episode_url=f"https://example.com/ep{i}.mp3",
            ))
        details = []
        monkeypatch.setattr(view, "_confirm_unfollow", lambda p, d: details.append(d) or True)
        view._unfollow(target)
        assert "3 playlist items" in details[0]

    def test_unfollow_singular_playlist_item(self, view, three_podcasts, monkeypatch):
        target = three_podcasts[0]
        view._profile.playlist.append(PlaylistItem(
            title="Ep", source_label=target.title,
            file_size_bytes=None, duration_seconds=None,
            podcast_rss_url=target.rss_url, episode_guid="g1",
            episode_url="https://example.com/ep.mp3",
        ))
        details = []
        monkeypatch.setattr(view, "_confirm_unfollow", lambda p, d: details.append(d) or True)
        view._unfollow(target)
        assert "1 playlist item" in details[0]


# ---------------------------------------------------------------------------
# FollowPodcastDialog — Search tab
# ---------------------------------------------------------------------------

@pytest.fixture
def search_results():
    return [
        PodcastSearchResult(
            title="Tech Podcast", author="Tech Author",
            artwork_url=None, rss_url="https://feeds.example.com/tech-pod",
            itunes_id=1, genre="Technology", episode_count=100,
        ),
        PodcastSearchResult(
            title="Science Podcast", author="Science Author",
            artwork_url=None, rss_url="https://feeds.example.com/sci-pod",
            itunes_id=2, genre="Science", episode_count=50,
        ),
    ]


@pytest.fixture
def search_dialog(qapp, search_results):
    dlg = FollowPodcastDialog(
        search_fn=MagicMock(return_value=SearchOutcome(ok=True, results=search_results)),
        validate_fn=MagicMock(return_value=FeedValidationResult(ok=False, error="stub")),
    )
    yield dlg
    dlg.close()


class TestFollowDialogSearch:
    def test_search_calls_search_fn(self, search_dialog):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        search_dialog._search_fn.assert_called_once_with("tech")

    def test_results_appear_in_list(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        assert search_dialog._results_list.count() == len(search_results)

    def test_result_data_stored_correctly(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        stored = search_dialog._results_list.item(0).data(Qt.ItemDataRole.UserRole)
        assert stored.rss_url == search_results[0].rss_url

    def test_result_count_shown_in_status(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        assert str(len(search_results)) in search_dialog._search_status.text()

    def test_empty_query_does_not_call_search_fn(self, search_dialog):
        search_dialog._search_edit.setText("")
        search_dialog._search_btn.click()
        search_dialog._search_fn.assert_not_called()

    def test_search_error_shows_error_in_status(self, qapp):
        dlg = FollowPodcastDialog(
            search_fn=MagicMock(return_value=SearchOutcome(ok=False, results=[], error="Net error")),
            validate_fn=MagicMock(),
        )
        dlg._search_edit.setText("anything")
        dlg._search_btn.click()
        assert "Error" in dlg._search_status.text()
        assert "Net error" in dlg._search_status.text()
        dlg.close()

    def test_no_results_shows_message(self, qapp):
        dlg = FollowPodcastDialog(
            search_fn=MagicMock(return_value=SearchOutcome(ok=True, results=[])),
            validate_fn=MagicMock(),
        )
        dlg._search_edit.setText("nothing")
        dlg._search_btn.click()
        assert "No results" in dlg._search_status.text()
        dlg.close()

    def test_follow_btn_disabled_before_selection(self, search_dialog):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        assert not search_dialog._follow_search_btn.isEnabled()

    def test_follow_btn_enabled_after_selection(self, search_dialog):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        search_dialog._results_list.setCurrentRow(0)
        assert search_dialog._follow_search_btn.isEnabled()

    def test_follow_from_search_emits_podcast(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        search_dialog._results_list.setCurrentRow(0)
        received = []
        search_dialog.podcast_followed.connect(received.append)
        search_dialog._follow_from_search()
        assert len(received) == 1
        assert received[0].rss_url == search_results[0].rss_url
        assert received[0].title == search_results[0].title
        assert received[0].author == search_results[0].author

    def test_follow_from_search_is_podcast_instance(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        search_dialog._results_list.setCurrentRow(0)
        received = []
        search_dialog.podcast_followed.connect(received.append)
        search_dialog._follow_from_search()
        assert isinstance(received[0], Podcast)

    def test_return_key_triggers_search(self, search_dialog):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_edit.returnPressed.emit()
        search_dialog._search_fn.assert_called_once_with("tech")


# ---------------------------------------------------------------------------
# FollowPodcastDialog — RSS URL tab
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_feed_result():
    return FeedValidationResult(
        ok=True,
        title="My Podcast",
        author="Podcast Author",
        episode_count=42,
        most_recent_episode="Episode 42: The Finale",
    )


@pytest.fixture
def rss_dialog(qapp, valid_feed_result):
    dlg = FollowPodcastDialog(
        search_fn=MagicMock(return_value=SearchOutcome(ok=True, results=[])),
        validate_fn=MagicMock(return_value=valid_feed_result),
    )
    dlg._tabs.setCurrentIndex(1)
    yield dlg
    dlg.close()


class TestFollowDialogRss:
    def test_validate_btn_disabled_with_empty_url(self, rss_dialog):
        assert not rss_dialog._validate_btn.isEnabled()

    def test_validate_btn_enabled_when_url_entered(self, rss_dialog):
        rss_dialog._rss_edit.setText("https://example.com/feed.rss")
        assert rss_dialog._validate_btn.isEnabled()

    def test_validate_btn_disabled_with_whitespace(self, rss_dialog):
        rss_dialog._rss_edit.setText("   ")
        assert not rss_dialog._validate_btn.isEnabled()

    def test_validate_calls_validate_fn(self, rss_dialog):
        url = "https://example.com/feed.rss"
        rss_dialog._rss_edit.setText(url)
        rss_dialog._validate_btn.click()
        rss_dialog._validate_fn.assert_called_once_with(url)

    def test_valid_feed_shows_title(self, rss_dialog, valid_feed_result):
        rss_dialog._rss_edit.setText("https://example.com/feed.rss")
        rss_dialog._validate_btn.click()
        assert valid_feed_result.title in rss_dialog._rss_status.text()

    def test_valid_feed_shows_episode_count(self, rss_dialog, valid_feed_result):
        rss_dialog._rss_edit.setText("https://example.com/feed.rss")
        rss_dialog._validate_btn.click()
        assert str(valid_feed_result.episode_count) in rss_dialog._rss_status.text()

    def test_valid_feed_shows_most_recent_episode(self, rss_dialog, valid_feed_result):
        rss_dialog._rss_edit.setText("https://example.com/feed.rss")
        rss_dialog._validate_btn.click()
        assert valid_feed_result.most_recent_episode in rss_dialog._rss_status.text()

    def test_follow_btn_disabled_before_validation(self, rss_dialog):
        rss_dialog._rss_edit.setText("https://example.com/feed.rss")
        assert not rss_dialog._follow_rss_btn.isEnabled()

    def test_follow_btn_enabled_after_valid_feed(self, rss_dialog):
        rss_dialog._rss_edit.setText("https://example.com/feed.rss")
        rss_dialog._validate_btn.click()
        assert rss_dialog._follow_rss_btn.isEnabled()

    def test_follow_btn_disabled_after_error(self, qapp):
        dlg = FollowPodcastDialog(
            search_fn=MagicMock(),
            validate_fn=MagicMock(return_value=FeedValidationResult(ok=False, error="Bad URL")),
        )
        dlg._tabs.setCurrentIndex(1)
        dlg._rss_edit.setText("https://bad.example.com/feed.rss")
        dlg._validate_btn.click()
        assert not dlg._follow_rss_btn.isEnabled()
        dlg.close()

    def test_error_message_shown_on_invalid_feed(self, qapp):
        dlg = FollowPodcastDialog(
            search_fn=MagicMock(),
            validate_fn=MagicMock(return_value=FeedValidationResult(ok=False, error="Connection failed")),
        )
        dlg._tabs.setCurrentIndex(1)
        dlg._rss_edit.setText("https://bad.example.com/feed.rss")
        dlg._validate_btn.click()
        assert "Error" in dlg._rss_status.text()
        assert "Connection failed" in dlg._rss_status.text()
        dlg.close()

    def test_follow_from_rss_emits_podcast(self, rss_dialog, valid_feed_result):
        url = "https://example.com/feed.rss"
        rss_dialog._rss_edit.setText(url)
        rss_dialog._validate_btn.click()
        received = []
        rss_dialog.podcast_followed.connect(received.append)
        rss_dialog._follow_from_rss()
        assert len(received) == 1
        assert received[0].rss_url == url
        assert received[0].title == valid_feed_result.title
        assert received[0].author == valid_feed_result.author

    def test_follow_from_rss_is_podcast_instance(self, rss_dialog):
        rss_dialog._rss_edit.setText("https://example.com/feed.rss")
        rss_dialog._validate_btn.click()
        received = []
        rss_dialog.podcast_followed.connect(received.append)
        rss_dialog._follow_from_rss()
        assert isinstance(received[0], Podcast)

    def test_url_change_resets_follow_button(self, rss_dialog):
        rss_dialog._rss_edit.setText("https://example.com/feed.rss")
        rss_dialog._validate_btn.click()
        assert rss_dialog._follow_rss_btn.isEnabled()
        rss_dialog._rss_edit.setText("https://different.com/feed.rss")
        assert not rss_dialog._follow_rss_btn.isEnabled()

    def test_url_change_clears_status_label(self, rss_dialog):
        rss_dialog._rss_edit.setText("https://example.com/feed.rss")
        rss_dialog._validate_btn.click()
        rss_dialog._rss_edit.setText("https://different.com/feed.rss")
        assert rss_dialog._rss_status.text() == ""

    def test_follow_without_validation_does_nothing(self, rss_dialog):
        received = []
        rss_dialog.podcast_followed.connect(received.append)
        rss_dialog._follow_from_rss()
        assert len(received) == 0
