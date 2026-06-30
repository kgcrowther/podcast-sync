"""
Tests for swimsync.ui.podcasts_view.

Behavioral tests only: tile population, filter bar, status indicators,
signal emission, follow/unfollow flows, and dialog interactions.
Visual layout and styling are not tested here.

Run with: pytest tests/test_podcasts_view.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from swimsync.core.podcast_search import (
    FeedValidationResult,
    PodcastSearchResult,
    SearchOutcome,
)
from swimsync.models.profile import Flow, PlaylistItem, Podcast, Profile
from swimsync.ui.podcasts_view import (
    FollowPodcastDialog,
    PodcastStatus,
    PodcastTileWidget,
    PodcastsView,
    _ArtworkLoader,
    _SearchResultRow,
    _Worker,
)


# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _podcast(title: str, rss_url: str = "", author: str = "Some Author",
             description: str = "") -> Podcast:
    url = rss_url or f"https://feeds.example.com/{title.lower().replace(' ', '-')}"
    return Podcast(
        title=title, rss_url=url, author=author,
        description=description, artwork_url=None, last_checked=None,
    )


def _search_result(title: str = "Result", author: str = "Author",
                   rss_url: str = "https://feeds.example.com/result",
                   episode_count: int = 10,
                   description: str = "") -> PodcastSearchResult:
    return PodcastSearchResult(
        title=title, author=author, artwork_url=None,
        rss_url=rss_url, itunes_id=1, genre="Tech",
        episode_count=episode_count, description=description,
    )


@pytest.fixture
def three_podcasts():
    return [
        _podcast("Tech Talk", "https://feeds.example.com/tech", description="A tech show about things"),
        _podcast("Science Hour", "https://feeds.example.com/science"),
        _podcast("History Today", "https://feeds.example.com/history"),
    ]


@pytest.fixture
def profile(three_podcasts):
    return Profile(name="TestUser", podcasts=list(three_podcasts))


# Replace background workers with synchronous stubs for all tests.
@pytest.fixture(autouse=True)
def sync_workers(monkeypatch):
    class _SyncWorker(_Worker):
        def start(self, priority=None):
            self.run()

    class _NoOpArtworkLoader(_ArtworkLoader):
        def start(self, priority=None):
            pass  # do not fetch artwork in tests

    monkeypatch.setattr("swimsync.ui.podcasts_view._Worker", _SyncWorker)
    monkeypatch.setattr("swimsync.ui.podcasts_view._ArtworkLoader", _NoOpArtworkLoader)


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


def _tiles(v: PodcastsView) -> list[PodcastTileWidget]:
    return list(v._tile_widgets)


# ---------------------------------------------------------------------------
# Tile population
# ---------------------------------------------------------------------------

class TestTilePopulation:
    def test_tile_count_matches_podcasts(self, view, three_podcasts):
        assert len(_tiles(view)) == len(three_podcasts)

    def test_empty_profile_has_no_tiles(self, qapp):
        v = PodcastsView(profile=Profile(name="Empty"), on_profile_changed=lambda _: None)
        assert len(_tiles(v)) == 0
        v.close()

    def test_tile_podcast_property(self, view, three_podcasts):
        urls = {t.podcast.rss_url for t in _tiles(view)}
        assert urls == {p.rss_url for p in three_podcasts}

    def test_tile_title_label_text(self, view, three_podcasts):
        for tile, podcast in zip(_tiles(view), three_podcasts):
            assert tile._title_label.text() == podcast.title

    def test_tile_author_label_text(self, view, three_podcasts):
        for tile, podcast in zip(_tiles(view), three_podcasts):
            assert tile._author_label.text() == podcast.author

    def test_tile_description_excerpt_truncates_at_20_words(self, qapp):
        long_desc = " ".join(f"word{i}" for i in range(40))
        p = _podcast("P", description=long_desc)
        v = PodcastsView(profile=Profile(name="U", podcasts=[p]),
                         on_profile_changed=lambda _: None)
        tile = _tiles(v)[0]
        words_shown = tile._desc_label.text().rstrip("…").split()
        assert len(words_shown) == 20
        assert tile._desc_label.text().endswith("…")
        v.close()

    def test_tile_description_no_ellipsis_when_short(self, qapp):
        p = _podcast("P", description="Short description.")
        v = PodcastsView(profile=Profile(name="U", podcasts=[p]),
                         on_profile_changed=lambda _: None)
        assert not _tiles(v)[0]._desc_label.text().endswith("…")
        v.close()

    def test_refresh_profile_rebuilds_tiles(self, view):
        new_profile = Profile(name="Other", podcasts=[_podcast("Only Show")])
        view.refresh_profile(new_profile)
        assert len(_tiles(view)) == 1
        assert _tiles(view)[0].podcast.title == "Only Show"

    def test_title_font_is_bold(self, view):
        tile = _tiles(view)[0]
        assert tile._title_label.font().bold()

    def test_author_font_is_italic(self, view):
        tile = _tiles(view)[0]
        assert tile._author_label.font().italic()


# ---------------------------------------------------------------------------
# Filter bar
# ---------------------------------------------------------------------------

class TestFilterBar:
    # isHidden() checks whether setVisible(False) was called on the widget
    # itself, independently of whether any ancestor window is shown.
    # isVisible() returns False for everything when the parent is not shown,
    # which would make the "visible" and "hidden" cases indistinguishable.
    def _visible(self, view):
        return [t for t in _tiles(view) if not t.isHidden()]

    def test_filter_by_title(self, view):
        view._filter_edit.setText("tech")
        assert len(self._visible(view)) == 1
        assert self._visible(view)[0].podcast.title == "Tech Talk"

    def test_filter_by_author(self, qapp):
        podcasts = [_podcast("Show A", author="Alice"), _podcast("Show B", author="Bob")]
        v = PodcastsView(profile=Profile(name="U", podcasts=podcasts),
                         on_profile_changed=lambda _: None)
        v._filter_edit.setText("alice")
        visible = [t for t in _tiles(v) if not t.isHidden()]
        assert len(visible) == 1
        assert visible[0].podcast.author == "Alice"
        v.close()

    def test_filter_is_case_insensitive(self, view):
        view._filter_edit.setText("TECH")
        assert len(self._visible(view)) == 1

    def test_clearing_filter_restores_all(self, view, three_podcasts):
        view._filter_edit.setText("tech")
        view._filter_edit.setText("")
        assert len(self._visible(view)) == len(three_podcasts)

    def test_no_match_hides_all(self, view):
        view._filter_edit.setText("xyzzy")
        assert len(self._visible(view)) == 0

    def test_filter_persists_after_refresh_statuses(self, view):
        view._filter_edit.setText("tech")
        view.refresh_statuses({})
        visible = self._visible(view)
        assert len(visible) == 1
        assert visible[0].podcast.title == "Tech Talk"


# ---------------------------------------------------------------------------
# Status indicators
# ---------------------------------------------------------------------------

class TestStatusIndicators:
    def test_stale_indicator_text(self, view, three_podcasts):
        url = three_podcasts[0].rss_url
        view.refresh_statuses({url: PodcastStatus(is_stale=True)})
        assert _tiles(view)[0]._indicator_label.text() == "● No new episodes in 45+ days"

    def test_error_indicator_text(self, view, three_podcasts):
        url = three_podcasts[1].rss_url
        view.refresh_statuses({url: PodcastStatus(has_error=True)})
        assert _tiles(view)[1]._indicator_label.text() == "⚠ Feed unavailable"

    def test_no_indicator_on_normal_podcast(self, view):
        view.refresh_statuses({})
        assert _tiles(view)[0]._indicator_label.text() == ""

    def test_refresh_statuses_updates_in_place(self, view, three_podcasts):
        count_before = len(_tiles(view))
        view.refresh_statuses({three_podcasts[0].rss_url: PodcastStatus(is_stale=True)})
        assert len(_tiles(view)) == count_before  # no rebuild

    def test_both_stale_and_error_prefer_stale(self, view, three_podcasts):
        url = three_podcasts[0].rss_url
        view.refresh_statuses({url: PodcastStatus(is_stale=True, has_error=True)})
        assert "45+ days" in _tiles(view)[0]._indicator_label.text()


# ---------------------------------------------------------------------------
# Flow button state
# ---------------------------------------------------------------------------

class TestFlowButton:
    def test_add_flow_btn_text_when_no_flow(self, view):
        assert _tiles(view)[0]._flow_btn.text() == "Add Flow"

    def test_edit_flow_btn_text_when_flow_exists(self, view, three_podcasts):
        target = three_podcasts[0]
        view._profile.flows.append(Flow(podcast_rss_url=target.rss_url, most_recent_count=3))
        view._populate_tiles()
        assert _tiles(view)[0]._flow_btn.text() == "Edit Flow"

    def test_flow_btn_emits_add_flow_requested(self, view):
        received = []
        view.add_flow_requested.connect(received.append)
        _tiles(view)[0]._flow_btn.click()
        assert len(received) == 1
        assert isinstance(received[0], Podcast)

    def test_flow_btn_emits_edit_flow_requested_when_flow_exists(self, view, three_podcasts):
        target = three_podcasts[0]
        view._profile.flows.append(Flow(podcast_rss_url=target.rss_url, most_recent_count=3))
        view._populate_tiles()
        received = []
        view.edit_flow_requested.connect(received.append)
        _tiles(view)[0]._flow_btn.click()
        assert len(received) == 1
        assert received[0].rss_url == target.rss_url

    def test_add_flow_signal_carries_correct_podcast(self, view, three_podcasts):
        received = []
        view.add_flow_requested.connect(received.append)
        _tiles(view)[1]._flow_btn.click()
        assert received[0].rss_url == three_podcasts[1].rss_url


# ---------------------------------------------------------------------------
# Podcast selection (View Episodes)
# ---------------------------------------------------------------------------

class TestPodcastSelection:
    def test_view_episodes_btn_emits_podcast_selected(self, view):
        received = []
        view.podcast_selected.connect(received.append)
        _tiles(view)[0]._view_episodes_btn.click()
        assert len(received) == 1

    def test_emitted_podcast_matches_tile(self, view, three_podcasts):
        received = []
        view.podcast_selected.connect(received.append)
        for i, tile in enumerate(_tiles(view)):
            tile._view_episodes_btn.click()
        assert [p.rss_url for p in received] == [p.rss_url for p in three_podcasts]

    def test_emitted_object_is_podcast_instance(self, view):
        received = []
        view.podcast_selected.connect(received.append)
        _tiles(view)[0]._view_episodes_btn.click()
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

    def test_add_podcast_creates_new_tile(self, view):
        before = len(_tiles(view))
        view._add_podcast(_podcast("New Show", "https://feeds.example.com/new"))
        assert len(_tiles(view)) == before + 1

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

    def test_unfollow_removes_tile(self, view, three_podcasts):
        before = len(_tiles(view))
        view._unfollow(three_podcasts[0])
        assert len(_tiles(view)) == before - 1

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
            title="Ep", source_label=target.title, file_size_bytes=None,
            duration_seconds=None, podcast_rss_url=target.rss_url,
            episode_guid="g1", episode_url="https://example.com/ep.mp3",
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
        details = []
        monkeypatch.setattr(view, "_confirm_unfollow", lambda p, d: details.append(d) or True)
        view._unfollow(target)
        assert details and "flow" in details[0]

    def test_unfollow_warns_if_playlist_items_exist(self, view, three_podcasts, monkeypatch):
        target = three_podcasts[0]
        view._profile.playlist.append(PlaylistItem(
            title="Ep", source_label=target.title, file_size_bytes=None,
            duration_seconds=None, podcast_rss_url=target.rss_url,
            episode_guid="g1", episode_url="https://example.com/ep.mp3",
        ))
        details = []
        monkeypatch.setattr(view, "_confirm_unfollow", lambda p, d: details.append(d) or True)
        view._unfollow(target)
        assert details and "playlist" in details[0]

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
            title="Ep", source_label=target.title, file_size_bytes=None,
            duration_seconds=None, podcast_rss_url=target.rss_url,
            episode_guid="g1", episode_url="https://example.com/ep.mp3",
        ))
        details = []
        monkeypatch.setattr(view, "_confirm_unfollow", lambda p, d: details.append(d) or True)
        view._unfollow(target)
        assert "flow" in details[0] and "playlist" in details[0]

    def test_unfollow_plural_playlist_items(self, view, three_podcasts, monkeypatch):
        target = three_podcasts[0]
        for i in range(3):
            view._profile.playlist.append(PlaylistItem(
                title=f"Ep{i}", source_label=target.title, file_size_bytes=None,
                duration_seconds=None, podcast_rss_url=target.rss_url,
                episode_guid=f"g{i}", episode_url=f"https://example.com/ep{i}.mp3",
            ))
        details = []
        monkeypatch.setattr(view, "_confirm_unfollow", lambda p, d: details.append(d) or True)
        view._unfollow(target)
        assert "3 playlist items" in details[0]

    def test_unfollow_singular_playlist_item(self, view, three_podcasts, monkeypatch):
        target = three_podcasts[0]
        view._profile.playlist.append(PlaylistItem(
            title="Ep", source_label=target.title, file_size_bytes=None,
            duration_seconds=None, podcast_rss_url=target.rss_url,
            episode_guid="g1", episode_url="https://example.com/ep.mp3",
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
        _search_result("Tech Podcast", "Tech Author",
                       "https://feeds.example.com/tech-pod", 100, "A tech show."),
        _search_result("Science Podcast", "Science Author",
                       "https://feeds.example.com/sci-pod", 50, "A science show."),
    ]


@pytest.fixture
def search_dialog(qapp, search_results):
    dlg = FollowPodcastDialog(
        search_fn=MagicMock(return_value=SearchOutcome(ok=True, results=search_results)),
        validate_fn=MagicMock(return_value=FeedValidationResult(ok=False, error="stub")),
    )
    yield dlg
    dlg.close()


def _rows(dlg: FollowPodcastDialog) -> list[_SearchResultRow]:
    return list(dlg._search_rows)


class TestFollowDialogSearch:
    def test_search_calls_search_fn(self, search_dialog):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        search_dialog._search_fn.assert_called_once_with("tech")

    def test_result_rows_created(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        assert len(_rows(search_dialog)) == len(search_results)

    def test_row_title_label(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        assert _rows(search_dialog)[0]._title_label.text() == search_results[0].title

    def test_row_author_label(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        assert _rows(search_dialog)[0]._author_label.text() == search_results[0].author

    def test_row_title_font_is_bold(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        assert _rows(search_dialog)[0]._title_label.font().bold()

    def test_row_author_font_is_italic(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        assert _rows(search_dialog)[0]._author_label.font().italic()

    def test_result_count_shown_in_status(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        assert str(len(search_results)) in search_dialog._search_status.text()

    def test_empty_query_does_not_call_search_fn(self, search_dialog):
        search_dialog._search_edit.setText("")
        search_dialog._search_btn.click()
        search_dialog._search_fn.assert_not_called()

    def test_search_error_shows_error_message(self, qapp):
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

    def test_return_key_triggers_search(self, search_dialog):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_edit.returnPressed.emit()
        search_dialog._search_fn.assert_called_once_with("tech")

    def test_follow_btn_disabled_before_selection(self, search_dialog):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        assert not search_dialog._follow_search_btn.isEnabled()

    def test_follow_btn_enabled_after_row_selected(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        # Simulate clicking a row
        _rows(search_dialog)[0].selected.emit(search_results[0])
        assert search_dialog._follow_search_btn.isEnabled()

    def test_follow_selected_emits_podcast(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        _rows(search_dialog)[0].selected.emit(search_results[0])
        received = []
        search_dialog.podcast_followed.connect(received.append)
        search_dialog._follow_selected()
        assert len(received) == 1
        assert received[0].rss_url == search_results[0].rss_url

    def test_follow_selected_carries_description(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        _rows(search_dialog)[0].selected.emit(search_results[0])
        received = []
        search_dialog.podcast_followed.connect(received.append)
        search_dialog._follow_selected()
        assert received[0].description == search_results[0].description


# ---------------------------------------------------------------------------
# FollowPodcastDialog — Details expand panel
# ---------------------------------------------------------------------------

class TestSearchResultDetails:
    def test_expand_panel_hidden_by_default(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        assert _rows(search_dialog)[0]._expand_panel.isHidden()

    def test_details_btn_expands_panel(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        row = _rows(search_dialog)[0]
        row._details_btn.click()
        assert not row._expand_panel.isHidden()

    def test_details_btn_text_changes_when_expanded(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        row = _rows(search_dialog)[0]
        row._details_btn.click()
        assert row._details_btn.text() == "Hide"

    def test_details_btn_collapses_on_second_click(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        row = _rows(search_dialog)[0]
        row._details_btn.click()
        row._details_btn.click()
        assert row._expand_panel.isHidden()

    def test_expanding_second_row_collapses_first(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        rows = _rows(search_dialog)
        rows[0]._details_btn.click()
        rows[1]._details_btn.click()
        assert rows[0]._expand_panel.isHidden()
        assert not rows[1]._expand_panel.isHidden()

    def test_expand_panel_shows_episode_count(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        row = _rows(search_dialog)[0]
        row._details_btn.click()
        assert str(search_results[0].episode_count) in row._expand_meta.text()

    def test_expand_panel_shows_description(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        row = _rows(search_dialog)[0]
        row._details_btn.click()
        assert search_results[0].description in row._expand_desc.text()

    def test_expand_panel_follow_btn_emits_podcast(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        row = _rows(search_dialog)[0]
        row._details_btn.click()
        received = []
        search_dialog.podcast_followed.connect(received.append)
        row._expand_follow_btn.click()
        assert len(received) == 1
        assert received[0].rss_url == search_results[0].rss_url

    def test_details_click_also_selects_row(self, search_dialog, search_results):
        search_dialog._search_edit.setText("tech")
        search_dialog._search_btn.click()
        row = _rows(search_dialog)[0]
        row._details_btn.click()
        assert search_dialog._selected_result is search_results[0]


# ---------------------------------------------------------------------------
# FollowPodcastDialog — RSS URL tab
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_feed_result():
    return FeedValidationResult(
        ok=True, title="My Podcast", author="Podcast Author",
        episode_count=42, most_recent_episode="Episode 42: The Finale",
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

    def test_error_message_shown(self, qapp):
        dlg = FollowPodcastDialog(
            search_fn=MagicMock(),
            validate_fn=MagicMock(return_value=FeedValidationResult(ok=False, error="Connection failed")),
        )
        dlg._tabs.setCurrentIndex(1)
        dlg._rss_edit.setText("https://bad.example.com/feed.rss")
        dlg._validate_btn.click()
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

    def test_url_change_resets_follow_button(self, rss_dialog):
        rss_dialog._rss_edit.setText("https://example.com/feed.rss")
        rss_dialog._validate_btn.click()
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
