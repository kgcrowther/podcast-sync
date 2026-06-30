"""
Tests for swimsync.ui.episode_browser.

Behavioral tests only: feed loading, header content, pagination,
add-to-playlist flow, back navigation, and stale/error indicators.

Run with: pytest tests/test_episode_browser.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication

from swimsync.core.rss_client import FeedResult
from swimsync.models.profile import Episode, PlaylistItem, Podcast, Profile
from swimsync.ui.episode_browser import (
    EpisodeBrowser,
    _ArtworkLoader,
    _EpisodeRowWidget,
    _Worker,
    _fmt_duration,
    _fmt_size,
)


# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _episode(
    title: str = "Episode 1",
    guid: str = "g1",
    url: str = "https://example.com/ep1.mp3",
    publish_date: str = "2026-01-01",
    duration_seconds: int | None = 3661,
    file_size_bytes: int | None = 10_485_760,
) -> Episode:
    return Episode(
        title=title,
        url=url,
        publish_date=publish_date,
        duration_seconds=duration_seconds,
        file_size_bytes=file_size_bytes,
        guid=guid,
    )


def _make_episodes(n: int) -> list[Episode]:
    return [_episode(title=f"Episode {i+1}", guid=f"g{i+1}",
                     url=f"https://example.com/ep{i+1}.mp3") for i in range(n)]


def _podcast(title: str = "My Podcast", artwork_url: str | None = None) -> Podcast:
    return Podcast(
        title=title, rss_url="https://feeds.example.com/pod",
        author="Test Author", description="A test podcast about testing.",
        artwork_url=artwork_url, last_checked=None,
    )


def _ok_result(episodes: list[Episode], is_stale: bool = False) -> FeedResult:
    return FeedResult(ok=True, episodes=episodes, is_stale=is_stale)


def _err_result(error: str = "Connection refused") -> FeedResult:
    return FeedResult(ok=False, episodes=[], error=error)


@pytest.fixture(autouse=True)
def sync_workers(monkeypatch):
    class _SyncWorker(_Worker):
        def start(self, priority=None):
            self.run()

    class _NoOpArtwork(_ArtworkLoader):
        def start(self, priority=None):
            pass

    monkeypatch.setattr("swimsync.ui.episode_browser._Worker", _SyncWorker)
    monkeypatch.setattr("swimsync.ui.episode_browser._ArtworkLoader", _NoOpArtwork)


@pytest.fixture
def profile():
    return Profile(name="Tester")


def _browser(qapp, podcast=None, episodes=None, profile=None,
             is_stale=False, feed_ok=True, feed_error="Feed error"):
    podcast = podcast or _podcast()
    profile = profile or Profile(name="T")
    if feed_ok:
        result = _ok_result(episodes if episodes is not None else _make_episodes(5),
                            is_stale=is_stale)
    else:
        result = _err_result(feed_error)
    saved = []
    b = EpisodeBrowser(
        podcast=podcast,
        profile=profile,
        on_profile_changed=saved.append,
        fetch_fn=MagicMock(return_value=result),
    )
    b._saved = saved
    return b


def _rows(browser: EpisodeBrowser) -> list[_EpisodeRowWidget]:
    rows = []
    for i in range(browser._episodes_layout.count()):
        w = browser._episodes_layout.itemAt(i).widget()
        if isinstance(w, _EpisodeRowWidget):
            rows.append(w)
    return rows


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

class TestFmtDuration:
    def test_none_returns_empty(self):
        assert _fmt_duration(None) == ""

    def test_zero(self):
        assert _fmt_duration(0) == "0:00"

    def test_seconds_only(self):
        assert _fmt_duration(65) == "1:05"

    def test_minutes_and_seconds(self):
        assert _fmt_duration(3600) == "1:00:00"

    def test_hours_minutes_seconds(self):
        assert _fmt_duration(3661) == "1:01:01"

    def test_sub_minute(self):
        assert _fmt_duration(45) == "0:45"


class TestFmtSize:
    def test_none_returns_empty(self):
        assert _fmt_size(None) == ""

    def test_one_mb(self):
        assert _fmt_size(1_048_576) == "1.0 MB"

    def test_half_mb(self):
        assert _fmt_size(524_288) == "0.5 MB"

    def test_ten_mb(self):
        assert _fmt_size(10_485_760) == "10.0 MB"


# ---------------------------------------------------------------------------
# Header content
# ---------------------------------------------------------------------------

class TestHeader:
    def test_title_label_text(self, qapp):
        b = _browser(qapp, podcast=_podcast("Awesome Pod"))
        assert b._title_label.text() == "Awesome Pod"

    def test_author_label_text(self, qapp):
        pod = Podcast(title="P", rss_url="u", author="Jane Smith",
                      description="", artwork_url=None, last_checked=None)
        b = _browser(qapp, podcast=pod)
        assert b._author_label.text() == "Jane Smith"

    def test_description_label_text(self, qapp):
        pod = Podcast(title="P", rss_url="u", author="A",
                      description="A deep dive into things.",
                      artwork_url=None, last_checked=None)
        b = _browser(qapp, podcast=pod)
        assert b._desc_label.text() == "A deep dive into things."

    def test_artwork_placeholder_when_no_url(self, qapp):
        b = _browser(qapp, podcast=_podcast(artwork_url=None))
        assert b._artwork_label.text() == "♪"

    def test_title_font_is_bold(self, qapp):
        b = _browser(qapp)
        assert b._title_label.font().bold()

    def test_author_font_is_italic(self, qapp):
        b = _browser(qapp)
        assert b._author_label.font().italic()

    def test_back_btn_text(self, qapp):
        b = _browser(qapp)
        assert "Podcasts" in b._back_btn.text()

    def test_back_btn_emits_signal(self, qapp):
        b = _browser(qapp)
        received = []
        b.back_requested.connect(lambda: received.append(True))
        b._back_btn.click()
        assert received


# ---------------------------------------------------------------------------
# Feed loading state
# ---------------------------------------------------------------------------

class TestFeedLoading:
    def test_status_clears_after_successful_load(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(5))
        assert b._status_label.text() == ""

    def test_status_shows_no_episodes_when_feed_empty(self, qapp):
        b = _browser(qapp, episodes=[])
        assert "No episodes" in b._status_label.text()

    def test_status_shows_error_when_feed_fails(self, qapp):
        b = _browser(qapp, feed_ok=False, feed_error="Timeout")
        assert "Timeout" in b._status_label.text()

    def test_error_indicator_shown_when_feed_fails(self, qapp):
        b = _browser(qapp, feed_ok=False)
        assert b._indicator_label.text() == "⚠ Feed unavailable"

    def test_stale_indicator_shown_when_stale(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(3), is_stale=True)
        assert b._indicator_label.text() == "● No new episodes in 45+ days"

    def test_no_indicator_on_healthy_feed(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(3), is_stale=False)
        assert b._indicator_label.text() == ""

    def test_fetch_fn_called_with_rss_url(self, qapp, profile):
        fetch = MagicMock(return_value=_ok_result([]))
        pod = _podcast()
        EpisodeBrowser(podcast=pod, profile=profile,
                       on_profile_changed=lambda _: None, fetch_fn=fetch)
        fetch.assert_called_once_with(pod.rss_url)


# ---------------------------------------------------------------------------
# Episode row content
# ---------------------------------------------------------------------------

class TestEpisodeRowContent:
    def test_row_title_text(self, qapp):
        b = _browser(qapp, episodes=[_episode("My Episode")])
        assert _rows(b)[0]._title_label.text() == "My Episode"

    def test_row_title_font_bold(self, qapp):
        b = _browser(qapp, episodes=[_episode()])
        assert _rows(b)[0]._title_label.font().bold()

    def test_row_meta_contains_date(self, qapp):
        ep = _episode(publish_date="2026-03-15")
        b = _browser(qapp, episodes=[ep])
        assert "2026-03-15" in _rows(b)[0]._meta_label.text()

    def test_row_meta_contains_duration(self, qapp):
        ep = _episode(duration_seconds=3661)
        b = _browser(qapp, episodes=[ep])
        assert "1:01:01" in _rows(b)[0]._meta_label.text()

    def test_row_meta_contains_file_size(self, qapp):
        ep = _episode(file_size_bytes=10_485_760)
        b = _browser(qapp, episodes=[ep])
        assert "10.0 MB" in _rows(b)[0]._meta_label.text()

    def test_row_meta_omits_none_duration(self, qapp):
        ep = _episode(duration_seconds=None)
        b = _browser(qapp, episodes=[ep])
        meta = _rows(b)[0]._meta_label.text()
        assert ":" not in meta

    def test_row_meta_omits_none_size(self, qapp):
        ep = _episode(file_size_bytes=None)
        b = _browser(qapp, episodes=[ep])
        assert "MB" not in _rows(b)[0]._meta_label.text()

    def test_row_meta_empty_when_all_none(self, qapp):
        ep = _episode(publish_date="", duration_seconds=None, file_size_bytes=None)
        b = _browser(qapp, episodes=[ep])
        assert _rows(b)[0]._meta_label.text() == ""

    def test_add_btn_text_default(self, qapp):
        b = _browser(qapp, episodes=[_episode()])
        assert _rows(b)[0]._add_btn.text() == "+ Add to Playlist"

    def test_add_btn_enabled_by_default(self, qapp):
        b = _browser(qapp, episodes=[_episode()])
        assert _rows(b)[0]._add_btn.isEnabled()

    def test_preview_btn_present(self, qapp):
        b = _browser(qapp, episodes=[_episode()])
        assert _rows(b)[0]._preview_btn.text() == "▶ Preview"


# ---------------------------------------------------------------------------
# Initial episode count
# ---------------------------------------------------------------------------

class TestInitialEpisodeCount:
    def test_ten_episodes_shown_when_feed_has_ten(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(10))
        assert len(_rows(b)) == 10

    def test_ten_episodes_shown_when_feed_has_more(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(25))
        assert len(_rows(b)) == 10

    def test_all_shown_when_fewer_than_ten(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(6))
        assert len(_rows(b)) == 6

    def test_no_rows_when_feed_empty(self, qapp):
        b = _browser(qapp, episodes=[])
        assert len(_rows(b)) == 0


# ---------------------------------------------------------------------------
# Pagination (Show more)
# ---------------------------------------------------------------------------

class TestPagination:
    def test_show10_btn_disabled_when_all_shown(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(10))
        assert not b._show10_btn.isEnabled()

    def test_show10_btn_enabled_when_more_remain(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(15))
        assert b._show10_btn.isEnabled()

    def test_show50_btn_disabled_when_all_shown(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(5))
        assert not b._show50_btn.isEnabled()

    def test_show50_btn_enabled_when_more_remain(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(60))
        assert b._show50_btn.isEnabled()

    def test_show10_adds_ten_rows(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(25))
        b._show10_btn.click()
        assert len(_rows(b)) == 20

    def test_show50_adds_fifty_rows(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(65))
        b._show50_btn.click()
        assert len(_rows(b)) == 60

    def test_show10_clamps_to_available(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(13))
        b._show10_btn.click()
        assert len(_rows(b)) == 13

    def test_show50_clamps_to_available(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(55))
        b._show50_btn.click()
        assert len(_rows(b)) == 55

    def test_buttons_disabled_after_all_shown(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(15))
        b._show10_btn.click()
        assert not b._show10_btn.isEnabled()
        assert not b._show50_btn.isEnabled()

    def test_show10_disabled_when_feed_empty(self, qapp):
        b = _browser(qapp, episodes=[])
        assert not b._show10_btn.isEnabled()

    def test_shown_count_tracks_correctly(self, qapp):
        b = _browser(qapp, episodes=_make_episodes(30))
        assert b._shown_count == 10
        b._show10_btn.click()
        assert b._shown_count == 20
        b._show10_btn.click()
        assert b._shown_count == 30

    def test_row_order_is_feed_order(self, qapp):
        eps = _make_episodes(15)
        b = _browser(qapp, episodes=eps)
        b._show10_btn.click()
        titles = [r._title_label.text() for r in _rows(b)]
        assert titles == [e.title for e in eps]


# ---------------------------------------------------------------------------
# Add to Playlist
# ---------------------------------------------------------------------------

class TestAddToPlaylist:
    def test_add_appends_to_profile_playlist(self, qapp, profile):
        ep = _episode()
        b = _browser(qapp, episodes=[ep], profile=profile)
        _rows(b)[0]._add_btn.click()
        assert len(profile.playlist) == 1

    def test_add_calls_on_profile_changed(self, qapp):
        b = _browser(qapp, episodes=[_episode()])
        _rows(b)[0]._add_btn.click()
        assert len(b._saved) == 1

    def test_added_item_has_correct_title(self, qapp, profile):
        ep = _episode("Special Episode")
        b = _browser(qapp, episodes=[ep], profile=profile)
        _rows(b)[0]._add_btn.click()
        assert profile.playlist[0].title == "Special Episode"

    def test_added_item_has_correct_podcast_rss_url(self, qapp, profile):
        pod = _podcast()
        ep = _episode()
        b = _browser(qapp, podcast=pod, episodes=[ep], profile=profile)
        _rows(b)[0]._add_btn.click()
        assert profile.playlist[0].podcast_rss_url == pod.rss_url

    def test_added_item_source_label_is_podcast_title(self, qapp, profile):
        pod = _podcast("Great Podcast")
        ep = _episode()
        b = _browser(qapp, podcast=pod, episodes=[ep], profile=profile)
        _rows(b)[0]._add_btn.click()
        assert profile.playlist[0].source_label == "Great Podcast"

    def test_added_item_preserves_episode_guid(self, qapp, profile):
        ep = _episode(guid="abc-123")
        b = _browser(qapp, episodes=[ep], profile=profile)
        _rows(b)[0]._add_btn.click()
        assert profile.playlist[0].episode_guid == "abc-123"

    def test_added_item_preserves_episode_url(self, qapp, profile):
        ep = _episode(url="https://cdn.example.com/ep.mp3")
        b = _browser(qapp, episodes=[ep], profile=profile)
        _rows(b)[0]._add_btn.click()
        assert profile.playlist[0].episode_url == "https://cdn.example.com/ep.mp3"

    def test_added_item_preserves_duration(self, qapp, profile):
        ep = _episode(duration_seconds=1234)
        b = _browser(qapp, episodes=[ep], profile=profile)
        _rows(b)[0]._add_btn.click()
        assert profile.playlist[0].duration_seconds == 1234

    def test_added_item_preserves_file_size(self, qapp, profile):
        ep = _episode(file_size_bytes=5_000_000)
        b = _browser(qapp, episodes=[ep], profile=profile)
        _rows(b)[0]._add_btn.click()
        assert profile.playlist[0].file_size_bytes == 5_000_000

    def test_btn_changes_to_in_playlist_after_add(self, qapp):
        b = _browser(qapp, episodes=[_episode()])
        _rows(b)[0]._add_btn.click()
        assert _rows(b)[0]._add_btn.text() == "✓ In Playlist"

    def test_btn_disabled_after_add(self, qapp):
        b = _browser(qapp, episodes=[_episode()])
        _rows(b)[0]._add_btn.click()
        assert not _rows(b)[0]._add_btn.isEnabled()

    def test_duplicate_not_added(self, qapp, profile):
        ep = _episode()
        b = _browser(qapp, episodes=[ep], profile=profile)
        _rows(b)[0]._add_btn.click()
        _rows(b)[0]._add_btn.click()  # should be a no-op (btn disabled)
        assert len(profile.playlist) == 1

    def test_episode_already_in_playlist_shown_as_in_playlist(self, qapp):
        ep = _episode(guid="existing")
        profile = Profile(name="T")
        profile.playlist.append(PlaylistItem(
            title=ep.title, source_label="Pod",
            file_size_bytes=None, duration_seconds=None,
            podcast_rss_url="https://feeds.example.com/pod",
            episode_guid="existing", episode_url=ep.url,
        ))
        b = _browser(qapp, episodes=[ep], profile=profile)
        row = _rows(b)[0]
        assert row._add_btn.text() == "✓ In Playlist"
        assert not row._add_btn.isEnabled()

    def test_add_does_not_affect_other_rows(self, qapp, profile):
        eps = _make_episodes(3)
        b = _browser(qapp, episodes=eps, profile=profile)
        _rows(b)[0]._add_btn.click()
        assert _rows(b)[1]._add_btn.text() == "+ Add to Playlist"
        assert _rows(b)[2]._add_btn.text() == "+ Add to Playlist"


# ---------------------------------------------------------------------------
# Preview button
# ---------------------------------------------------------------------------

class TestPreviewButton:
    def test_preview_opens_url(self, qapp):
        ep = _episode(url="https://cdn.example.com/episode.mp3")
        b = _browser(qapp, episodes=[ep])
        with patch("swimsync.ui.episode_browser.QDesktopServices.openUrl") as mock_open:
            _rows(b)[0]._preview_btn.click()
            mock_open.assert_called_once()
            called_url = mock_open.call_args[0][0]
            assert called_url.toString() == ep.url

    def test_preview_uses_correct_episode_url(self, qapp):
        eps = [
            _episode("Ep A", guid="a", url="https://cdn.example.com/a.mp3"),
            _episode("Ep B", guid="b", url="https://cdn.example.com/b.mp3"),
        ]
        b = _browser(qapp, episodes=eps)
        with patch("swimsync.ui.episode_browser.QDesktopServices.openUrl") as mock_open:
            _rows(b)[1]._preview_btn.click()
            called_url = mock_open.call_args[0][0].toString()
            assert called_url == "https://cdn.example.com/b.mp3"


# ---------------------------------------------------------------------------
# Back navigation
# ---------------------------------------------------------------------------

class TestBackNavigation:
    def test_back_btn_emits_back_requested(self, qapp):
        b = _browser(qapp)
        received = []
        b.back_requested.connect(lambda: received.append(True))
        b._back_btn.click()
        assert len(received) == 1

    def test_back_does_not_affect_playlist(self, qapp, profile):
        b = _browser(qapp, episodes=[_episode()], profile=profile)
        _rows(b)[0]._add_btn.click()
        b._back_btn.click()
        assert len(profile.playlist) == 1


# ---------------------------------------------------------------------------
# _EpisodeRowWidget standalone
# ---------------------------------------------------------------------------

class TestEpisodeRowWidget:
    def test_mark_in_playlist_updates_btn_text(self, qapp):
        row = _EpisodeRowWidget(_episode())
        row.mark_in_playlist(True)
        assert row._add_btn.text() == "✓ In Playlist"

    def test_mark_not_in_playlist_restores_btn(self, qapp):
        row = _EpisodeRowWidget(_episode(), in_playlist=True)
        row.mark_in_playlist(False)
        assert row._add_btn.text() == "+ Add to Playlist"
        assert row._add_btn.isEnabled()

    def test_in_playlist_on_construction(self, qapp):
        row = _EpisodeRowWidget(_episode(), in_playlist=True)
        assert row._add_btn.text() == "✓ In Playlist"
        assert not row._add_btn.isEnabled()

    def test_add_btn_click_emits_episode(self, qapp):
        ep = _episode()
        row = _EpisodeRowWidget(ep)
        received = []
        row.add_to_playlist_requested.connect(received.append)
        row._add_btn.click()
        assert len(received) == 1
        assert received[0] is ep

    def test_episode_property(self, qapp):
        ep = _episode("Unique")
        row = _EpisodeRowWidget(ep)
        assert row.episode is ep
