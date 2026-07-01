"""
SwimSync Log View.

Displays the contents of the app's log file in a scrollable, filterable
text area within the main window sidebar.

Requirements §10 (Log View):
  - Scrollable, timestamped log viewer
  - Filter by: All | Errors | Sync Events
  - "Open Log File" button to reveal in Finder
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from swimsync.utils.logger import get_log_file_path, get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Log format constants (must match logger.py LOG_FORMAT)
# ---------------------------------------------------------------------------

# "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
# 0         1         2
# 0123456789012345678901234567890
# <19 ts>  <8 level>  <name>  <message>
_TS_END = 19         # exclusive end of timestamp slice
_LEVEL_START = 21    # after two spaces
_LEVEL_END = 29      # 8-char field end
_REST_START = 31     # name starts here

_ERROR_LEVELS = {"ERROR", "WARNING", "CRITICAL"}

# Logger names whose output always counts as a Sync Event
_SYNC_EVENT_LOGGERS = {
    "swimsync.ui.sync_dialog",
    "swimsync.core.sync_engine",
    "swimsync.core.downloader",
    "swimsync.core.device_monitor",
}


# ---------------------------------------------------------------------------
# Filter enum
# ---------------------------------------------------------------------------

class _Filter(Enum):
    ALL = auto()
    ERRORS = auto()
    SYNC_EVENTS = auto()


# ---------------------------------------------------------------------------
# Log entry dataclass
# ---------------------------------------------------------------------------

@dataclass
class _LogEntry:
    raw: str
    timestamp: str
    level: str
    logger_name: str
    message: str
    is_sync_event: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_line(line: str) -> Optional[_LogEntry]:
    """
    Parse one log line into a _LogEntry, or return None if malformed.

    Expected format (from logger.LOG_FORMAT):
        2026-06-30 20:42:44  INFO      swimsync.ui.foo  Some message
    """
    if len(line) <= _REST_START:
        return None
    timestamp = line[:_TS_END]
    level = line[_LEVEL_START:_LEVEL_END].strip()
    if not level:
        return None
    rest = line[_REST_START:]
    if "  " in rest:
        logger_name, _, message = rest.partition("  ")
    else:
        logger_name = rest.strip()
        message = ""
    return _LogEntry(
        raw=line,
        timestamp=timestamp,
        level=level,
        logger_name=logger_name.strip(),
        message=message,
    )


def _is_sync_event(entry: _LogEntry) -> bool:
    """Return True if the entry is considered a Sync Event."""
    if entry.logger_name in _SYNC_EVENT_LOGGERS:
        return True
    lower_msg = entry.message.lower()
    return "sync" in lower_msg or "device" in lower_msg


def _default_read_log() -> str:
    """Read the log file; return empty string if it doesn't exist yet."""
    try:
        return get_log_file_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _default_open_log(path: Path) -> None:
    """Reveal the log file in macOS Finder."""
    import subprocess
    subprocess.run(["open", "-R", str(path)], check=False)


# ---------------------------------------------------------------------------
# Log view
# ---------------------------------------------------------------------------

class LogView(QWidget):
    """
    Log section of the main window.

    Args:
        read_log_fn: Returns the full log file content as a string.
            Defaults to reading LOG_FILE from disk.
        open_log_fn: Called with the log file Path to reveal it in Finder.
            Defaults to ``open -R <path>``.
        log_file_path: Override the path shown/passed to open_log_fn.
            Defaults to get_log_file_path().
    """

    def __init__(
        self,
        read_log_fn: Callable[[], str] = _default_read_log,
        open_log_fn: Callable[[Path], None] = _default_open_log,
        log_file_path: Optional[Path] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._read_log_fn = read_log_fn
        self._open_log_fn = open_log_fn
        self._log_file_path = log_file_path or get_log_file_path()
        self._entries: list[_LogEntry] = []
        self._filter = _Filter.ALL
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # Top bar: filter buttons + action buttons
        top = QHBoxLayout()
        top.setSpacing(6)

        top.addWidget(QLabel("Filter:"))

        self._all_btn = QPushButton("All")
        self._all_btn.setObjectName("log_filter_all")
        self._all_btn.clicked.connect(self._on_filter_all)
        top.addWidget(self._all_btn)

        self._errors_btn = QPushButton("Errors")
        self._errors_btn.setObjectName("log_filter_errors")
        self._errors_btn.clicked.connect(self._on_filter_errors)
        top.addWidget(self._errors_btn)

        self._sync_btn = QPushButton("Sync Events")
        self._sync_btn.setObjectName("log_filter_sync")
        self._sync_btn.clicked.connect(self._on_filter_sync)
        top.addWidget(self._sync_btn)

        top.addStretch()

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("log_refresh_btn")
        self._refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self._refresh_btn)

        self._open_btn = QPushButton("Open Log File")
        self._open_btn.setObjectName("log_open_btn")
        self._open_btn.clicked.connect(self._on_open)
        top.addWidget(self._open_btn)

        layout.addLayout(top)

        # Log text area
        self._text = QPlainTextEdit()
        self._text.setObjectName("log_text")
        self._text.setReadOnly(True)
        mono = QFont("Courier New")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(11)
        self._text.setFont(mono)
        layout.addWidget(self._text)

        # Status bar: entry count
        self._count_label = QLabel()
        self._count_label.setObjectName("log_count_label")
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._count_label)

        self._update_filter_buttons()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read the log file and repopulate the display."""
        content = self._read_log_fn()
        self._entries = []
        for raw_line in content.splitlines():
            raw_line = raw_line.rstrip()
            if not raw_line:
                continue
            entry = _parse_line(raw_line)
            if entry is not None:
                entry.is_sync_event = _is_sync_event(entry)
                self._entries.append(entry)
            else:
                # Continuation lines (e.g. multi-line exception tracebacks)
                self._entries.append(
                    _LogEntry(
                        raw=raw_line,
                        timestamp="",
                        level="",
                        logger_name="",
                        message=raw_line,
                    )
                )
        self._apply_filter()
        log.debug(f"Log view refreshed: {len(self._entries)} total entries")

    # ------------------------------------------------------------------
    # Filter handlers
    # ------------------------------------------------------------------

    def _on_filter_all(self) -> None:
        self._filter = _Filter.ALL
        self._update_filter_buttons()
        self._apply_filter()

    def _on_filter_errors(self) -> None:
        self._filter = _Filter.ERRORS
        self._update_filter_buttons()
        self._apply_filter()

    def _on_filter_sync(self) -> None:
        self._filter = _Filter.SYNC_EVENTS
        self._update_filter_buttons()
        self._apply_filter()

    def _update_filter_buttons(self) -> None:
        """Disable the active filter button; enable the others."""
        self._all_btn.setEnabled(self._filter != _Filter.ALL)
        self._errors_btn.setEnabled(self._filter != _Filter.ERRORS)
        self._sync_btn.setEnabled(self._filter != _Filter.SYNC_EVENTS)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        """Filter _entries by the current mode and update the text widget."""
        if not self._entries:
            self._text.setPlainText("No log entries.")
            self._count_label.setText("0 entries")
            return

        if self._filter == _Filter.ALL:
            visible = self._entries
        elif self._filter == _Filter.ERRORS:
            visible = [e for e in self._entries if e.level in _ERROR_LEVELS]
        else:  # SYNC_EVENTS
            visible = [e for e in self._entries if e.is_sync_event]

        if not visible:
            self._text.setPlainText("No matching log entries.")
            self._count_label.setText("0 entries")
        else:
            self._text.setPlainText("\n".join(e.raw for e in visible))
            noun = "entry" if len(visible) == 1 else "entries"
            self._count_label.setText(f"{len(visible)} {noun}")

        # Scroll to bottom so the most recent entry is visible
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    # Open log file
    # ------------------------------------------------------------------

    def _on_open(self) -> None:
        self._open_log_fn(self._log_file_path)
