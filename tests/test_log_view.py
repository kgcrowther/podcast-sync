"""
Behavior tests for swimsync/ui/log_view.py.

Covers:
  - _parse_line: valid lines, short/empty lines, various log levels
  - _is_sync_event: logger-name match, keyword match, no match
  - LogView construction: reads log on init, shows all entries
  - Empty log: shows "No log entries."
  - Filter All: shows all entries, All button disabled
  - Filter Errors: shows ERROR/WARNING/CRITICAL only, hides INFO/DEBUG
  - Filter Sync Events: shows sync-related entries only
  - Filter with no matches: shows "No matching log entries."
  - Switching filters: re-applies without re-reading file
  - Refresh button: re-reads log (detects new entries)
  - refresh() public method: same
  - Entry count label: correct count per filter
  - Open Log File button: calls open_log_fn with path
  - Unparseable / continuation lines: stored, shown in All
  - Filter buttons: active one disabled, others enabled
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from PyQt6.QtWidgets import QApplication

from swimsync.ui.log_view import (
    LogView,
    _Filter,
    _LogEntry,
    _is_sync_event,
    _parse_line,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


# ── Sample log lines ────────────────────────────────────────────────────────

_INFO_LINE = (
    "2026-06-30 20:42:44  INFO      swimsync.ui.profiles_view  "
    "Created new profile: 'Bob'"
)
_WARN_LINE = (
    "2026-06-30 20:43:00  WARNING   swimsync.core.rss_client  "
    "Feed stale: http://example.com/rss"
)
_ERROR_LINE = (
    "2026-06-30 20:43:01  ERROR     swimsync.core.downloader  "
    "Download failed for 'ep1.mp3': timeout"
)
_CRITICAL_LINE = (
    "2026-06-30 20:43:05  CRITICAL  swimsync.ui.sync_dialog  "
    "Unexpected error"
)
_DEBUG_LINE = (
    "2026-06-30 20:43:10  DEBUG     swimsync.core.sync_engine  "
    "Computing sync plan"
)
_SYNC_ENGINE_LINE = (
    "2026-06-30 20:44:00  INFO      swimsync.core.sync_engine  "
    "Sync plan complete: 3 to add"
)
_DEVICE_MONITOR_LINE = (
    "2026-06-30 20:44:10  INFO      swimsync.core.device_monitor  "
    "Device connected: 'SWIM PRO'"
)
_SYNC_DIALOG_LINE = (
    "2026-06-30 20:44:20  INFO      swimsync.ui.sync_dialog  "
    "Sync complete — 3 files synced."
)
_DOWNLOADER_LINE = (
    "2026-06-30 20:44:30  INFO      swimsync.core.downloader  "
    "Downloaded ep1.mp3: 5000000 bytes"
)

ALL_LINES = [
    _INFO_LINE,
    _WARN_LINE,
    _ERROR_LINE,
    _CRITICAL_LINE,
    _DEBUG_LINE,
    _SYNC_ENGINE_LINE,
    _DEVICE_MONITOR_LINE,
    _SYNC_DIALOG_LINE,
    _DOWNLOADER_LINE,
]


def _log_content(*lines) -> str:
    return "\n".join(lines)


def _view(content="", open_fn=None, log_path=None):
    if open_fn is None:
        open_fn = MagicMock()
    return LogView(
        read_log_fn=lambda: content,
        open_log_fn=open_fn,
        log_file_path=log_path or Path("/tmp/test.log"),
    )


# ---------------------------------------------------------------------------
# _parse_line
# ---------------------------------------------------------------------------

class TestParseLine:
    def test_parses_info_line(self):
        e = _parse_line(_INFO_LINE)
        assert e is not None
        assert e.timestamp == "2026-06-30 20:42:44"
        assert e.level == "INFO"
        assert e.logger_name == "swimsync.ui.profiles_view"
        assert "Created new profile" in e.message

    def test_parses_warning_line(self):
        e = _parse_line(_WARN_LINE)
        assert e is not None
        assert e.level == "WARNING"

    def test_parses_error_line(self):
        e = _parse_line(_ERROR_LINE)
        assert e is not None
        assert e.level == "ERROR"
        assert "timeout" in e.message

    def test_parses_critical_line(self):
        e = _parse_line(_CRITICAL_LINE)
        assert e is not None
        assert e.level == "CRITICAL"

    def test_parses_debug_line(self):
        e = _parse_line(_DEBUG_LINE)
        assert e is not None
        assert e.level == "DEBUG"

    def test_raw_field_preserved(self):
        e = _parse_line(_INFO_LINE)
        assert e.raw == _INFO_LINE

    def test_returns_none_for_short_line(self):
        assert _parse_line("2026-06-30") is None

    def test_returns_none_for_empty_string(self):
        assert _parse_line("") is None

    def test_returns_none_for_blank_level(self):
        # Line long enough but level field is spaces
        line = "2026-06-30 20:42:44           swimsync.foo  msg"
        e = _parse_line(line)
        assert e is None

    def test_message_with_no_double_space_separator(self):
        # logger name but no double-space before message
        line = "2026-06-30 20:42:44  INFO      swimsync.foo"
        e = _parse_line(line)
        assert e is not None
        assert e.logger_name == "swimsync.foo"
        assert e.message == ""

    def test_message_can_contain_double_spaces(self):
        line = (
            "2026-06-30 20:42:44  INFO      swimsync.foo  "
            "value is  3.2 GB  used"
        )
        e = _parse_line(line)
        assert e is not None
        assert e.message.startswith("value is")


# ---------------------------------------------------------------------------
# _is_sync_event
# ---------------------------------------------------------------------------

class TestIsSyncEvent:
    def _entry(self, logger_name="swimsync.foo", message="hello"):
        return _LogEntry(
            raw="", timestamp="", level="INFO",
            logger_name=logger_name, message=message,
        )

    def test_sync_engine_logger_is_sync_event(self):
        assert _is_sync_event(self._entry("swimsync.core.sync_engine"))

    def test_device_monitor_logger_is_sync_event(self):
        assert _is_sync_event(self._entry("swimsync.core.device_monitor"))

    def test_sync_dialog_logger_is_sync_event(self):
        assert _is_sync_event(self._entry("swimsync.ui.sync_dialog"))

    def test_downloader_logger_is_sync_event(self):
        assert _is_sync_event(self._entry("swimsync.core.downloader"))

    def test_message_containing_sync_keyword(self):
        assert _is_sync_event(self._entry(message="Sync complete."))

    def test_message_containing_device_keyword(self):
        assert _is_sync_event(self._entry(message="Device mounted."))

    def test_sync_keyword_case_insensitive(self):
        assert _is_sync_event(self._entry(message="SYNC STARTED"))

    def test_device_keyword_case_insensitive(self):
        assert _is_sync_event(self._entry(message="DEVICE detected"))

    def test_unrelated_logger_unrelated_message_not_sync_event(self):
        assert not _is_sync_event(
            self._entry("swimsync.ui.profiles_view", "Created new profile: 'Bob'")
        )

    def test_profiles_view_not_sync_event(self):
        assert not _is_sync_event(self._entry("swimsync.ui.profiles_view"))

    def test_podcasts_view_not_sync_event(self):
        assert not _is_sync_event(self._entry("swimsync.ui.podcasts_view", "Followed."))


# ---------------------------------------------------------------------------
# LogView construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_reads_log_on_init(self, app):
        read_fn = MagicMock(return_value=_log_content(_INFO_LINE))
        LogView(read_log_fn=read_fn, open_log_fn=MagicMock(),
                log_file_path=Path("/tmp/x.log"))
        read_fn.assert_called_once()

    def test_empty_log_shows_no_entries_message(self, app):
        view = _view("")
        assert "No log entries" in view._text.toPlainText()

    def test_populated_log_shows_content(self, app):
        view = _view(_log_content(_INFO_LINE, _ERROR_LINE))
        text = view._text.toPlainText()
        assert "profiles_view" in text
        assert "downloader" in text

    def test_initial_filter_is_all(self, app):
        view = _view(_log_content(_INFO_LINE))
        assert view._filter == _Filter.ALL

    def test_all_button_disabled_initially(self, app):
        view = _view()
        assert not view._all_btn.isEnabled()

    def test_errors_and_sync_buttons_enabled_initially(self, app):
        view = _view()
        assert view._errors_btn.isEnabled()
        assert view._sync_btn.isEnabled()

    def test_filter_button_labels(self, app):
        view = _view()
        assert view._all_btn.text() == "All"
        assert view._errors_btn.text() == "Errors"
        assert view._sync_btn.text() == "Sync Events"

    def test_refresh_and_open_buttons_present(self, app):
        view = _view()
        assert view._refresh_btn.text() == "Refresh"
        assert view._open_btn.text() == "Open Log File"

    def test_text_area_is_read_only(self, app):
        view = _view()
        assert view._text.isReadOnly()

    def test_count_label_shows_zero_for_empty_log(self, app):
        view = _view("")
        assert "0" in view._count_label.text()

    def test_count_label_shows_total_for_populated_log(self, app):
        view = _view(_log_content(*ALL_LINES))
        count = len(ALL_LINES)
        assert str(count) in view._count_label.text()

    def test_count_label_singular_for_one_entry(self, app):
        view = _view(_log_content(_INFO_LINE))
        assert "entry" in view._count_label.text()

    def test_count_label_plural_for_multiple_entries(self, app):
        view = _view(_log_content(_INFO_LINE, _ERROR_LINE))
        assert "entries" in view._count_label.text()


# ---------------------------------------------------------------------------
# Filter: All
# ---------------------------------------------------------------------------

class TestFilterAll:
    def test_all_shows_every_line(self, app):
        view = _view(_log_content(*ALL_LINES))
        text = view._text.toPlainText()
        for line in ALL_LINES:
            assert line in text

    def test_switching_to_all_re_enables_errors_button(self, app):
        view = _view(_log_content(_ERROR_LINE, _INFO_LINE))
        view._on_filter_errors()
        view._on_filter_all()
        assert view._errors_btn.isEnabled()

    def test_switching_to_all_re_enables_sync_button(self, app):
        view = _view(_log_content(_SYNC_ENGINE_LINE, _INFO_LINE))
        view._on_filter_sync()
        view._on_filter_all()
        assert view._sync_btn.isEnabled()

    def test_all_button_disabled_when_all_active(self, app):
        view = _view(_log_content(_INFO_LINE))
        view._on_filter_all()
        assert not view._all_btn.isEnabled()


# ---------------------------------------------------------------------------
# Filter: Errors
# ---------------------------------------------------------------------------

class TestFilterErrors:
    def test_errors_shows_error_lines(self, app):
        view = _view(_log_content(_INFO_LINE, _ERROR_LINE, _WARN_LINE))
        view._on_filter_errors()
        text = view._text.toPlainText()
        assert _ERROR_LINE in text
        assert _WARN_LINE in text

    def test_errors_hides_info_lines(self, app):
        view = _view(_log_content(_INFO_LINE, _ERROR_LINE))
        view._on_filter_errors()
        assert _INFO_LINE not in view._text.toPlainText()

    def test_errors_hides_debug_lines(self, app):
        view = _view(_log_content(_DEBUG_LINE, _ERROR_LINE))
        view._on_filter_errors()
        assert _DEBUG_LINE not in view._text.toPlainText()

    def test_errors_includes_critical(self, app):
        view = _view(_log_content(_INFO_LINE, _CRITICAL_LINE))
        view._on_filter_errors()
        assert _CRITICAL_LINE in view._text.toPlainText()

    def test_errors_button_disabled_when_active(self, app):
        view = _view(_log_content(_ERROR_LINE))
        view._on_filter_errors()
        assert not view._errors_btn.isEnabled()

    def test_all_and_sync_enabled_when_errors_active(self, app):
        view = _view(_log_content(_ERROR_LINE))
        view._on_filter_errors()
        assert view._all_btn.isEnabled()
        assert view._sync_btn.isEnabled()

    def test_errors_filter_no_matches_shows_message(self, app):
        view = _view(_log_content(_INFO_LINE, _DEBUG_LINE))
        view._on_filter_errors()
        assert "No matching" in view._text.toPlainText()

    def test_errors_count_label_reflects_filtered_count(self, app):
        view = _view(_log_content(_INFO_LINE, _ERROR_LINE, _WARN_LINE))
        view._on_filter_errors()
        assert "2" in view._count_label.text()

    def test_errors_count_zero_when_no_matches(self, app):
        view = _view(_log_content(_INFO_LINE))
        view._on_filter_errors()
        assert "0" in view._count_label.text()


# ---------------------------------------------------------------------------
# Filter: Sync Events
# ---------------------------------------------------------------------------

class TestFilterSyncEvents:
    def test_sync_shows_sync_engine_lines(self, app):
        view = _view(_log_content(_INFO_LINE, _SYNC_ENGINE_LINE))
        view._on_filter_sync()
        assert _SYNC_ENGINE_LINE in view._text.toPlainText()

    def test_sync_shows_device_monitor_lines(self, app):
        view = _view(_log_content(_INFO_LINE, _DEVICE_MONITOR_LINE))
        view._on_filter_sync()
        assert _DEVICE_MONITOR_LINE in view._text.toPlainText()

    def test_sync_shows_sync_dialog_lines(self, app):
        view = _view(_log_content(_INFO_LINE, _SYNC_DIALOG_LINE))
        view._on_filter_sync()
        assert _SYNC_DIALOG_LINE in view._text.toPlainText()

    def test_sync_shows_downloader_lines(self, app):
        view = _view(_log_content(_INFO_LINE, _DOWNLOADER_LINE))
        view._on_filter_sync()
        assert _DOWNLOADER_LINE in view._text.toPlainText()

    def test_sync_hides_unrelated_info_lines(self, app):
        view = _view(_log_content(_INFO_LINE, _SYNC_ENGINE_LINE))
        view._on_filter_sync()
        assert _INFO_LINE not in view._text.toPlainText()

    def test_sync_button_disabled_when_active(self, app):
        view = _view(_log_content(_SYNC_ENGINE_LINE))
        view._on_filter_sync()
        assert not view._sync_btn.isEnabled()

    def test_all_and_errors_enabled_when_sync_active(self, app):
        view = _view(_log_content(_SYNC_ENGINE_LINE))
        view._on_filter_sync()
        assert view._all_btn.isEnabled()
        assert view._errors_btn.isEnabled()

    def test_sync_filter_no_matches_shows_message(self, app):
        view = _view(_log_content(_INFO_LINE))
        view._on_filter_sync()
        assert "No matching" in view._text.toPlainText()

    def test_sync_count_reflects_filtered_count(self, app):
        view = _view(_log_content(
            _SYNC_ENGINE_LINE, _DEVICE_MONITOR_LINE, _INFO_LINE
        ))
        view._on_filter_sync()
        assert "2" in view._count_label.text()

    def test_sync_includes_message_keyword_match(self, app):
        keyword_line = (
            "2026-06-30 20:45:00  INFO      swimsync.ui.main_window  "
            "All views refreshed for sync profile"
        )
        view = _view(_log_content(keyword_line, _INFO_LINE))
        view._on_filter_sync()
        assert keyword_line in view._text.toPlainText()


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

class TestRefresh:
    def test_refresh_re_reads_log(self, app):
        call_count = [0]
        lines = [_INFO_LINE]

        def read_fn():
            call_count[0] += 1
            return _log_content(*lines)

        view = LogView(read_log_fn=read_fn, open_log_fn=MagicMock(),
                       log_file_path=Path("/tmp/x.log"))
        assert call_count[0] == 1

        lines.append(_ERROR_LINE)
        view.refresh()
        assert call_count[0] == 2

    def test_refresh_picks_up_new_entries(self, app):
        lines = [_INFO_LINE]
        view = _view(_log_content(*lines))
        assert _ERROR_LINE not in view._text.toPlainText()

        lines.append(_ERROR_LINE)
        view._read_log_fn = lambda: _log_content(*lines)
        view.refresh()
        assert _ERROR_LINE in view._text.toPlainText()

    def test_refresh_button_updates_display(self, app):
        lines = [_INFO_LINE]
        view = _view(_log_content(*lines))
        assert _ERROR_LINE not in view._text.toPlainText()

        view._read_log_fn = lambda: _log_content(*lines, _ERROR_LINE)
        view._refresh_btn.click()
        assert _ERROR_LINE in view._text.toPlainText()

    def test_refresh_preserves_current_filter(self, app):
        lines = [_INFO_LINE, _ERROR_LINE]
        view = _view(_log_content(*lines))
        view._on_filter_errors()
        assert view._filter == _Filter.ERRORS

        lines.append(_WARN_LINE)
        view._read_log_fn = lambda: _log_content(*lines)
        view.refresh()

        assert view._filter == _Filter.ERRORS
        assert _WARN_LINE in view._text.toPlainText()
        assert _INFO_LINE not in view._text.toPlainText()

    def test_refresh_with_empty_log_shows_no_entries(self, app):
        view = _view(_log_content(_INFO_LINE))
        view._read_log_fn = lambda: ""
        view.refresh()
        assert "No log entries" in view._text.toPlainText()


# ---------------------------------------------------------------------------
# Open Log File
# ---------------------------------------------------------------------------

class TestOpenLogFile:
    def test_open_btn_calls_open_fn(self, app):
        open_fn = MagicMock()
        view = LogView(read_log_fn=lambda: "", open_log_fn=open_fn,
                       log_file_path=Path("/logs/swimsync.log"))
        view._open_btn.click()
        open_fn.assert_called_once()

    def test_open_fn_receives_log_file_path(self, app):
        open_fn = MagicMock()
        log_path = Path("/logs/swimsync.log")
        view = LogView(read_log_fn=lambda: "", open_log_fn=open_fn,
                       log_file_path=log_path)
        view._open_btn.click()
        open_fn.assert_called_once_with(log_path)

    def test_custom_log_path_used(self, app):
        open_fn = MagicMock()
        custom = Path("/custom/path.log")
        view = LogView(read_log_fn=lambda: "", open_log_fn=open_fn,
                       log_file_path=custom)
        view._open_btn.click()
        assert open_fn.call_args[0][0] == custom


# ---------------------------------------------------------------------------
# Unparseable / continuation lines
# ---------------------------------------------------------------------------

class TestUnparseableLines:
    def test_short_line_stored_as_raw(self, app):
        short = "short"
        view = _view(short)
        assert short in view._text.toPlainText()

    def test_blank_lines_ignored(self, app):
        content = f"{_INFO_LINE}\n\n{_ERROR_LINE}"
        view = _view(content)
        # Should have 2 entries (the blank line is skipped)
        assert len(view._entries) == 2

    def test_unparseable_line_shown_in_all_filter(self, app):
        raw = "Traceback (most recent call last):"
        view = _view(f"{_INFO_LINE}\n{raw}")
        assert raw in view._text.toPlainText()

    def test_unparseable_line_hidden_in_errors_filter(self, app):
        raw = "Traceback (most recent call last):"
        view = _view(f"{_INFO_LINE}\n{raw}")
        view._on_filter_errors()
        # raw has no level, not an error — should not appear
        assert raw not in view._text.toPlainText()

    def test_multiple_unparseable_lines(self, app):
        content = "\n".join(["bad line 1", "bad line 2", _INFO_LINE])
        view = _view(content)
        assert len(view._entries) == 3
