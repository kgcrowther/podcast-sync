"""
Behavior tests for swimsync/ui/playlist_view.py.

Covers:
  - _fmt_duration, _fmt_size, _total_size_str helpers
  - _is_supported_type: supported ext, unsupported ext, no device configs
  - PlaylistView empty state (empty label, scroll visibility, total label)
  - PlaylistView with items: row count, labels, total size
  - refresh_profile: adds and removes rows, updates total
  - Remove item: updates profile, calls on_changed, row disappears
  - _add_file: creates PlaylistItem, uses os.path.getsize, sets correct fields
  - _add_file unsupported type: shows QMessageBox warning but still adds item
  - _open_file_picker: calls QFileDialog, delegates to _add_file when path given
  - _open_file_picker: no-op when dialog cancelled
  - dragEnterEvent: accepts local-file URLs, ignores non-URL data
  - dropEvent: calls _add_file for each local file URL
  - _PlaylistItemRowWidget: title, source, meta labels; preview (local file and
    podcast episode); remove signal
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call, patch

from PyQt6.QtWidgets import QApplication

from swimsync.models.profile import DeviceConfig, PlaylistItem, Profile
from swimsync.ui.playlist_view import (
    PlaylistView,
    _PlaylistItemRowWidget,
    _fmt_duration,
    _fmt_size,
    _is_supported_type,
    _total_size_str,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _item(
    title="Episode 1",
    source="My Podcast",
    size=10_000_000,
    duration=3600,
    guid="ep1",
    episode_url="https://pod.com/ep1.mp3",
    local_file_path=None,
) -> PlaylistItem:
    return PlaylistItem(
        title=title,
        source_label=source,
        file_size_bytes=size,
        duration_seconds=duration,
        podcast_rss_url="https://pod.com/feed" if not local_file_path else None,
        episode_guid=guid if not local_file_path else None,
        episode_url=episode_url if not local_file_path else None,
        local_file_path=local_file_path,
    )


def _local_item(path="/music/track.mp3", size=5_000_000) -> PlaylistItem:
    import os
    filename = os.path.basename(path)
    stem = os.path.splitext(filename)[0]
    return PlaylistItem(
        title=stem,
        source_label=filename,
        file_size_bytes=size,
        duration_seconds=None,
        local_file_path=path,
    )


def _profile(*items: PlaylistItem) -> Profile:
    return Profile(name="Test", playlist=list(items))


def _view(profile=None, on_changed=None) -> PlaylistView:
    if profile is None:
        profile = Profile(name="Test")
    if on_changed is None:
        on_changed = MagicMock()
    return PlaylistView(profile=profile, on_profile_changed=on_changed)


def _rows(view: PlaylistView) -> list[_PlaylistItemRowWidget]:
    return list(view._row_widgets)


# ---------------------------------------------------------------------------
# _fmt_duration
# ---------------------------------------------------------------------------

class TestFmtDuration:
    def test_none_returns_empty(self):
        assert _fmt_duration(None) == ""

    def test_zero_seconds(self):
        assert _fmt_duration(0) == "0:00"

    def test_seconds_only(self):
        assert _fmt_duration(45) == "0:45"

    def test_minutes_and_seconds(self):
        assert _fmt_duration(90) == "1:30"

    def test_exactly_one_hour(self):
        assert _fmt_duration(3600) == "1:00:00"

    def test_hours_minutes_seconds(self):
        assert _fmt_duration(3723) == "1:02:03"

    def test_large_hours(self):
        assert _fmt_duration(7261) == "2:01:01"

    def test_pads_seconds(self):
        assert _fmt_duration(65) == "1:05"


# ---------------------------------------------------------------------------
# _fmt_size
# ---------------------------------------------------------------------------

class TestFmtSize:
    def test_none_returns_empty(self):
        assert _fmt_size(None) == ""

    def test_zero_bytes(self):
        assert _fmt_size(0) == "0.0 MB"

    def test_one_mb(self):
        assert _fmt_size(1024 * 1024) == "1.0 MB"

    def test_fractional_mb(self):
        result = _fmt_size(1_500_000)
        assert "MB" in result
        assert "1." in result

    def test_large_file(self):
        result = _fmt_size(50 * 1024 * 1024)
        assert "50.0 MB" in result


# ---------------------------------------------------------------------------
# _total_size_str
# ---------------------------------------------------------------------------

class TestTotalSizeStr:
    def test_empty_list(self):
        assert "0.0 MB" in _total_size_str([])

    def test_all_none_sizes(self):
        items = [_item(size=None), _item(size=None)]
        assert "0.0 MB" in _total_size_str(items)

    def test_sums_non_none_sizes(self):
        items = [_item(size=10 * 1024 * 1024), _item(size=10 * 1024 * 1024)]
        assert "20.0 MB" in _total_size_str(items)

    def test_skips_none_size(self):
        items = [_item(size=10 * 1024 * 1024), _item(size=None)]
        assert "10.0 MB" in _total_size_str(items)

    def test_gb_threshold(self):
        items = [_item(size=2 * 1024 ** 3)]
        result = _total_size_str(items)
        assert "GB" in result

    def test_total_prefix(self):
        assert _total_size_str([]).startswith("Total:")


# ---------------------------------------------------------------------------
# _is_supported_type
# ---------------------------------------------------------------------------

class TestIsSupportedType:
    def setup_method(self):
        self.profile = Profile(
            name="T",
            device_configs=[
                DeviceConfig("SWIM PRO", ["mp3", "flac", "wma", "wav", "aac", "m4a", "ape"]),
            ],
        )
        self.empty_profile = Profile(name="T", device_configs=[])

    def test_mp3_supported(self):
        assert _is_supported_type("/music/track.mp3", self.profile)

    def test_flac_supported(self):
        assert _is_supported_type("/music/track.FLAC", self.profile)

    def test_case_insensitive(self):
        assert _is_supported_type("/music/track.MP3", self.profile)

    def test_unsupported_extension(self):
        assert not _is_supported_type("/music/track.ogg", self.profile)

    def test_no_extension(self):
        assert not _is_supported_type("/music/track", self.profile)

    def test_no_device_configs_returns_true(self):
        assert _is_supported_type("/music/track.ogg", self.empty_profile)

    def test_supported_by_second_device_only(self):
        profile = Profile(
            name="T",
            device_configs=[
                DeviceConfig("Dev A", ["mp3"]),
                DeviceConfig("Dev B", ["flac"]),
            ],
        )
        assert _is_supported_type("/music/track.flac", profile)


# ---------------------------------------------------------------------------
# PlaylistView — empty state
# ---------------------------------------------------------------------------

class TestPlaylistViewEmpty:
    def test_empty_label_visible_when_no_items(self, app):
        view = _view()
        assert not view._empty_label.isHidden()

    def test_scroll_hidden_when_no_items(self, app):
        view = _view()
        assert view._scroll.isHidden()

    def test_no_row_widgets(self, app):
        view = _view()
        assert _rows(view) == []

    def test_total_label_shows_zero(self, app):
        view = _view()
        assert "0.0 MB" in view._total_label.text()

    def test_total_label_has_total_prefix(self, app):
        view = _view()
        assert view._total_label.text().startswith("Total:")

    def test_add_file_btn_always_enabled(self, app):
        view = _view()
        assert view._add_file_btn.isEnabled()


# ---------------------------------------------------------------------------
# PlaylistView — with items
# ---------------------------------------------------------------------------

class TestPlaylistViewWithItems:
    def setup_method(self):
        self.i1 = _item("Episode 1", "Pod A", size=10 * 1024 * 1024, duration=1800)
        self.i2 = _item("Episode 2", "Pod B", size=20 * 1024 * 1024, duration=3600)

    def test_row_count_matches_item_count(self, app):
        view = _view(profile=_profile(self.i1, self.i2))
        assert len(_rows(view)) == 2

    def test_empty_label_hidden_when_items_present(self, app):
        view = _view(profile=_profile(self.i1))
        assert view._empty_label.isHidden()

    def test_scroll_visible_when_items_present(self, app):
        view = _view(profile=_profile(self.i1))
        assert not view._scroll.isHidden()

    def test_total_label_sums_sizes(self, app):
        view = _view(profile=_profile(self.i1, self.i2))
        assert "30.0 MB" in view._total_label.text()

    def test_order_preserved(self, app):
        view = _view(profile=_profile(self.i1, self.i2))
        rows = _rows(view)
        assert rows[0].item is self.i1
        assert rows[1].item is self.i2


# ---------------------------------------------------------------------------
# PlaylistView — refresh_profile
# ---------------------------------------------------------------------------

class TestRefreshProfile:
    def test_refresh_adds_new_item(self, app):
        profile = _profile()
        view = _view(profile=profile)
        assert len(_rows(view)) == 0

        new_item = _item("New Ep")
        profile.playlist.append(new_item)
        view.refresh_profile(profile)
        assert len(_rows(view)) == 1

    def test_refresh_removes_deleted_item(self, app):
        i = _item()
        profile = _profile(i)
        view = _view(profile=profile)
        assert len(_rows(view)) == 1

        profile.playlist.clear()
        view.refresh_profile(profile)
        assert len(_rows(view)) == 0

    def test_refresh_updates_total(self, app):
        profile = _profile()
        view = _view(profile=profile)
        assert "0.0 MB" in view._total_label.text()

        profile.playlist.append(_item(size=50 * 1024 * 1024))
        view.refresh_profile(profile)
        assert "50.0 MB" in view._total_label.text()

    def test_refresh_shows_empty_label_when_emptied(self, app):
        i = _item()
        profile = _profile(i)
        view = _view(profile=profile)
        profile.playlist.clear()
        view.refresh_profile(profile)
        assert not view._empty_label.isHidden()


# ---------------------------------------------------------------------------
# PlaylistView — remove item
# ---------------------------------------------------------------------------

class TestRemoveItem:
    def test_remove_calls_on_changed(self, app):
        i = _item()
        on_changed = MagicMock()
        view = _view(profile=_profile(i), on_changed=on_changed)
        view._on_remove(i)
        on_changed.assert_called_once()

    def test_remove_deletes_item_from_profile(self, app):
        i = _item()
        profile = _profile(i)
        view = _view(profile=profile)
        view._on_remove(i)
        assert i not in profile.playlist

    def test_remove_removes_row(self, app):
        i = _item()
        view = _view(profile=_profile(i))
        assert len(_rows(view)) == 1
        view._on_remove(i)
        assert len(_rows(view)) == 0

    def test_remove_only_target_item(self, app):
        i1 = _item("Ep1")
        i2 = _item("Ep2")
        profile = _profile(i1, i2)
        view = _view(profile=profile)
        view._on_remove(i1)
        assert i2 in profile.playlist
        assert i1 not in profile.playlist

    def test_remove_shows_empty_label_when_last_item(self, app):
        i = _item()
        view = _view(profile=_profile(i))
        view._on_remove(i)
        assert not view._empty_label.isHidden()

    def test_remove_updates_total_label(self, app):
        i = _item(size=10 * 1024 * 1024)
        view = _view(profile=_profile(i))
        view._on_remove(i)
        assert "0.0 MB" in view._total_label.text()

    def test_remove_btn_on_row_triggers_on_remove(self, app):
        i = _item()
        profile = _profile(i)
        on_changed = MagicMock()
        view = _view(profile=profile, on_changed=on_changed)
        row = _rows(view)[0]
        row._remove_btn.click()
        on_changed.assert_called_once()
        assert len(_rows(view)) == 0


# ---------------------------------------------------------------------------
# PlaylistView — _add_file
# ---------------------------------------------------------------------------

class TestAddFile:
    def test_add_file_creates_playlist_item(self, app):
        profile = _profile()
        view = _view(profile=profile)
        with patch("swimsync.ui.playlist_view.os.path.getsize", return_value=5_000_000):
            view._add_file("/music/track.mp3")
        assert len(profile.playlist) == 1
        added = profile.playlist[0]
        assert added.local_file_path == "/music/track.mp3"

    def test_add_file_uses_stem_as_title(self, app):
        view = _view()
        with patch("swimsync.ui.playlist_view.os.path.getsize", return_value=1):
            view._add_file("/music/my_track.mp3")
        assert view._profile.playlist[0].title == "my_track"

    def test_add_file_uses_filename_as_source_label(self, app):
        view = _view()
        with patch("swimsync.ui.playlist_view.os.path.getsize", return_value=1):
            view._add_file("/music/my_track.mp3")
        assert view._profile.playlist[0].source_label == "my_track.mp3"

    def test_add_file_uses_getsize(self, app):
        view = _view()
        with patch("swimsync.ui.playlist_view.os.path.getsize", return_value=12_345_678):
            view._add_file("/music/track.mp3")
        assert view._profile.playlist[0].file_size_bytes == 12_345_678

    def test_add_file_size_none_on_oserror(self, app):
        view = _view()
        with patch("swimsync.ui.playlist_view.os.path.getsize", side_effect=OSError):
            view._add_file("/missing/track.mp3")
        assert view._profile.playlist[0].file_size_bytes is None

    def test_add_file_duration_is_none(self, app):
        view = _view()
        with patch("swimsync.ui.playlist_view.os.path.getsize", return_value=1):
            view._add_file("/music/track.mp3")
        assert view._profile.playlist[0].duration_seconds is None

    def test_add_file_calls_on_changed(self, app):
        on_changed = MagicMock()
        view = _view(on_changed=on_changed)
        with patch("swimsync.ui.playlist_view.os.path.getsize", return_value=1):
            view._add_file("/music/track.mp3")
        on_changed.assert_called_once()

    def test_add_file_creates_row(self, app):
        view = _view()
        with patch("swimsync.ui.playlist_view.os.path.getsize", return_value=1):
            view._add_file("/music/track.mp3")
        assert len(_rows(view)) == 1

    def test_add_file_unsupported_shows_warning(self, app):
        profile = Profile(
            name="T",
            device_configs=[DeviceConfig("Dev", ["mp3"])],
        )
        view = _view(profile=profile)
        with patch("swimsync.ui.playlist_view.os.path.getsize", return_value=1):
            with patch("swimsync.ui.playlist_view.QMessageBox.warning") as mock_warn:
                view._add_file("/music/track.ogg")
        mock_warn.assert_called_once()
        warning_text = mock_warn.call_args[0][2]
        assert "not be supported" in warning_text

    def test_add_file_unsupported_still_adds_item(self, app):
        profile = Profile(
            name="T",
            device_configs=[DeviceConfig("Dev", ["mp3"])],
        )
        view = _view(profile=profile)
        with patch("swimsync.ui.playlist_view.os.path.getsize", return_value=1):
            with patch("swimsync.ui.playlist_view.QMessageBox.warning"):
                view._add_file("/music/track.ogg")
        assert len(profile.playlist) == 1

    def test_add_file_supported_no_warning(self, app):
        profile = Profile(
            name="T",
            device_configs=[DeviceConfig("Dev", ["mp3"])],
        )
        view = _view(profile=profile)
        with patch("swimsync.ui.playlist_view.os.path.getsize", return_value=1):
            with patch("swimsync.ui.playlist_view.QMessageBox.warning") as mock_warn:
                view._add_file("/music/track.mp3")
        mock_warn.assert_not_called()


# ---------------------------------------------------------------------------
# PlaylistView — file picker
# ---------------------------------------------------------------------------

class TestFilePicker:
    def test_picker_calls_add_file_when_path_selected(self, app):
        view = _view()
        with patch("swimsync.ui.playlist_view.QFileDialog.getOpenFileName",
                   return_value=("/music/track.mp3", "")):
            with patch.object(view, "_add_file") as mock_add:
                view._open_file_picker()
        mock_add.assert_called_once_with("/music/track.mp3")

    def test_picker_no_op_when_cancelled(self, app):
        view = _view()
        with patch("swimsync.ui.playlist_view.QFileDialog.getOpenFileName",
                   return_value=("", "")):
            with patch.object(view, "_add_file") as mock_add:
                view._open_file_picker()
        mock_add.assert_not_called()

    def test_add_file_btn_click_opens_picker(self, app):
        view = _view()
        with patch("swimsync.ui.playlist_view.QFileDialog.getOpenFileName",
                   return_value=("", "")) as mock_dlg:
            view._add_file_btn.click()
        mock_dlg.assert_called_once()


# ---------------------------------------------------------------------------
# PlaylistView — drag-and-drop
# ---------------------------------------------------------------------------

class TestDragAndDrop:
    def _url(self, path: str):
        url = MagicMock()
        url.isLocalFile.return_value = True
        url.toLocalFile.return_value = path
        return url

    def _non_local_url(self):
        url = MagicMock()
        url.isLocalFile.return_value = False
        url.toLocalFile.return_value = ""
        return url

    def test_drag_enter_accepted_for_local_file_url(self, app):
        view = _view()
        event = MagicMock()
        event.mimeData.return_value.hasUrls.return_value = True
        event.mimeData.return_value.urls.return_value = [self._url("/music/track.mp3")]
        view.dragEnterEvent(event)
        event.acceptProposedAction.assert_called_once()

    def test_drag_enter_ignored_for_non_url_data(self, app):
        view = _view()
        event = MagicMock()
        event.mimeData.return_value.hasUrls.return_value = False
        view.dragEnterEvent(event)
        event.ignore.assert_called_once()

    def test_drag_enter_ignored_when_no_local_urls(self, app):
        view = _view()
        event = MagicMock()
        event.mimeData.return_value.hasUrls.return_value = True
        event.mimeData.return_value.urls.return_value = [self._non_local_url()]
        view.dragEnterEvent(event)
        event.ignore.assert_called_once()

    def test_drop_calls_add_file_for_each_local_url(self, app):
        view = _view()
        event = MagicMock()
        event.mimeData.return_value.urls.return_value = [
            self._url("/music/a.mp3"),
            self._url("/music/b.mp3"),
        ]
        with patch.object(view, "_add_file") as mock_add:
            view.dropEvent(event)
        assert mock_add.call_count == 2
        mock_add.assert_any_call("/music/a.mp3")
        mock_add.assert_any_call("/music/b.mp3")

    def test_drop_skips_non_local_urls(self, app):
        view = _view()
        event = MagicMock()
        event.mimeData.return_value.urls.return_value = [
            self._url("/music/a.mp3"),
            self._non_local_url(),
        ]
        with patch.object(view, "_add_file") as mock_add:
            view.dropEvent(event)
        assert mock_add.call_count == 1

    def test_drop_accepts_proposed_action(self, app):
        view = _view()
        event = MagicMock()
        event.mimeData.return_value.urls.return_value = []
        with patch.object(view, "_add_file"):
            view.dropEvent(event)
        event.acceptProposedAction.assert_called_once()


# ---------------------------------------------------------------------------
# _PlaylistItemRowWidget
# ---------------------------------------------------------------------------

class TestPlaylistItemRowWidget:
    def test_title_label(self, app):
        row = _PlaylistItemRowWidget(_item("My Episode"))
        assert row._title_label.text() == "My Episode"

    def test_source_label(self, app):
        row = _PlaylistItemRowWidget(_item(source="My Podcast"))
        assert row._source_label.text() == "My Podcast"

    def test_meta_shows_duration_and_size(self, app):
        row = _PlaylistItemRowWidget(_item(size=10 * 1024 * 1024, duration=3661))
        meta = row._meta_label.text()
        assert "1:01:01" in meta
        assert "10.0 MB" in meta

    def test_meta_empty_when_no_duration_or_size(self, app):
        row = _PlaylistItemRowWidget(_item(size=None, duration=None))
        assert row._meta_label.text() == ""

    def test_meta_shows_only_duration_when_no_size(self, app):
        row = _PlaylistItemRowWidget(_item(size=None, duration=90))
        assert "1:30" in row._meta_label.text()
        assert "MB" not in row._meta_label.text()

    def test_meta_shows_only_size_when_no_duration(self, app):
        row = _PlaylistItemRowWidget(_item(size=5 * 1024 * 1024, duration=None))
        assert "5.0 MB" in row._meta_label.text()
        assert ":" not in row._meta_label.text().split("MB")[0]

    def test_preview_btn_label(self, app):
        row = _PlaylistItemRowWidget(_item())
        assert "Preview" in row._preview_btn.text()

    def test_remove_btn_label(self, app):
        row = _PlaylistItemRowWidget(_item())
        assert "Remove" in row._remove_btn.text()

    def test_remove_btn_emits_signal(self, app):
        i = _item()
        row = _PlaylistItemRowWidget(i)
        received: list[PlaylistItem] = []
        row.remove_requested.connect(received.append)
        row._remove_btn.click()
        assert len(received) == 1
        assert received[0] is i

    def test_item_property(self, app):
        i = _item()
        row = _PlaylistItemRowWidget(i)
        assert row.item is i

    def test_preview_opens_url_for_podcast_episode(self, app):
        i = _item(episode_url="https://pod.com/ep1.mp3", local_file_path=None)
        row = _PlaylistItemRowWidget(i)
        with patch("swimsync.ui.playlist_view.QDesktopServices.openUrl") as mock_open:
            row._preview_btn.click()
        mock_open.assert_called_once()
        url_arg = mock_open.call_args[0][0]
        assert "https://pod.com/ep1.mp3" in url_arg.toString()

    def test_preview_opens_local_file(self, app):
        i = _local_item("/music/track.mp3")
        row = _PlaylistItemRowWidget(i)
        with patch("swimsync.ui.playlist_view.QDesktopServices.openUrl") as mock_open:
            row._preview_btn.click()
        mock_open.assert_called_once()
        url_arg = mock_open.call_args[0][0]
        assert "track.mp3" in url_arg.toString()

    def test_preview_no_op_when_no_url(self, app):
        i = PlaylistItem(
            title="No URL",
            source_label="none",
            file_size_bytes=None,
            duration_seconds=None,
        )
        row = _PlaylistItemRowWidget(i)
        with patch("swimsync.ui.playlist_view.QDesktopServices.openUrl") as mock_open:
            row._preview_btn.click()
        mock_open.assert_not_called()

    def test_local_file_preview_takes_precedence(self, app):
        i = PlaylistItem(
            title="Both",
            source_label="both",
            file_size_bytes=None,
            duration_seconds=None,
            episode_url="https://pod.com/ep.mp3",
            local_file_path="/music/track.mp3",
        )
        row = _PlaylistItemRowWidget(i)
        with patch("swimsync.ui.playlist_view.QDesktopServices.openUrl") as mock_open:
            row._preview_btn.click()
        url_arg = mock_open.call_args[0][0]
        assert "track.mp3" in url_arg.toString()
