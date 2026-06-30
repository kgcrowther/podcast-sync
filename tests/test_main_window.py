"""
Tests for swimsync.ui.main_window — navigation behavior only.

Visual layout and styling are excluded; those are reviewed by running the app.

Run with: pytest tests/test_main_window.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from swimsync.core.device_monitor import DeviceMonitor
from swimsync.models.profile import DEFAULT_DEVICES, DeviceConfig, Profile
from swimsync.ui.main_window import NAV_SECTIONS, MainWindow


# ---------------------------------------------------------------------------
# QApplication — one instance for the whole test session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Per-test window fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_monitor():
    return MagicMock(spec=DeviceMonitor)


@pytest.fixture
def window(qapp, mock_monitor, monkeypatch):
    monkeypatch.setattr("swimsync.ui.main_window.load_last_profile", lambda: None)
    monkeypatch.setattr(
        "swimsync.ui.main_window.create_default_profile",
        lambda name: Profile(name=name),
    )
    monkeypatch.setattr("swimsync.ui.main_window.save_profile", lambda p: None)
    monkeypatch.setattr("swimsync.ui.main_window.set_last_profile_name", lambda n: None)

    profile = Profile(name="TestUser", device_configs=list(DEFAULT_DEVICES))
    win = MainWindow(profile=profile, device_monitor=mock_monitor)
    yield win
    win.close()


# ---------------------------------------------------------------------------
# NAV_SECTIONS constant
# ---------------------------------------------------------------------------

class TestNavSections:
    def test_six_sections(self):
        assert len(NAV_SECTIONS) == 6

    def test_section_names_in_order(self):
        assert NAV_SECTIONS == [
            "Podcasts", "Flows", "Playlist", "Devices", "Profiles", "Log",
        ]


# ---------------------------------------------------------------------------
# Sidebar contents
# ---------------------------------------------------------------------------

class TestSidebar:
    def test_sidebar_item_count(self, window):
        assert window._nav.count() == 6

    def test_sidebar_item_labels(self, window):
        labels = [window._nav.item(i).text() for i in range(window._nav.count())]
        assert labels == NAV_SECTIONS

    def test_default_row_is_podcasts(self, window):
        assert window._nav.currentRow() == 0

    def test_stack_page_count_matches_sections(self, window):
        assert window._stack.count() == 6


# ---------------------------------------------------------------------------
# current_section
# ---------------------------------------------------------------------------

class TestCurrentSection:
    def test_default_current_section(self, window):
        assert window.current_section() == "Podcasts"

    @pytest.mark.parametrize("idx, name", list(enumerate(NAV_SECTIONS)))
    def test_current_section_after_row_change(self, window, idx, name):
        window._nav.setCurrentRow(idx)
        assert window.current_section() == name


# ---------------------------------------------------------------------------
# navigate_to
# ---------------------------------------------------------------------------

class TestNavigateTo:
    @pytest.mark.parametrize("section", NAV_SECTIONS)
    def test_navigate_to_updates_current_section(self, window, section):
        window.navigate_to(section)
        assert window.current_section() == section

    @pytest.mark.parametrize("section, expected_idx", [
        ("Podcasts", 0), ("Flows", 1), ("Playlist", 2),
        ("Devices", 3), ("Profiles", 4), ("Log", 5),
    ])
    def test_navigate_to_sets_correct_sidebar_row(self, window, section, expected_idx):
        window.navigate_to(section)
        assert window._nav.currentRow() == expected_idx

    @pytest.mark.parametrize("section, expected_idx", [
        ("Podcasts", 0), ("Flows", 1), ("Playlist", 2),
        ("Devices", 3), ("Profiles", 4), ("Log", 5),
    ])
    def test_navigate_to_sets_correct_stack_index(self, window, section, expected_idx):
        window.navigate_to(section)
        assert window._stack.currentIndex() == expected_idx

    def test_navigate_to_unknown_section_raises(self, window):
        with pytest.raises(ValueError):
            window.navigate_to("Unknown")


# ---------------------------------------------------------------------------
# Sidebar click drives stack (the signal connection)
# ---------------------------------------------------------------------------

class TestSidebarClickDrivesStack:
    @pytest.mark.parametrize("idx", range(len(NAV_SECTIONS)))
    def test_clicking_sidebar_row_switches_stack_page(self, window, idx):
        window._nav.setCurrentRow(idx)
        assert window._stack.currentIndex() == idx

    def test_sidebar_and_stack_stay_in_sync(self, window):
        for idx in [3, 0, 5, 2, 4, 1]:
            window._nav.setCurrentRow(idx)
            assert window._stack.currentIndex() == idx
            assert window.current_section() == NAV_SECTIONS[idx]


# ---------------------------------------------------------------------------
# replace_view
# ---------------------------------------------------------------------------

class TestReplaceView:
    def test_replace_view_installs_widget_at_correct_index(self, window):
        real_view = QLabel("Real Podcasts View")
        window.replace_view("Podcasts", real_view)
        assert window._stack.widget(0) is real_view

    def test_replace_view_does_not_change_page_count(self, window):
        window.replace_view("Flows", QLabel("Real Flows"))
        assert window._stack.count() == 6

    def test_replace_active_section_shows_new_widget_immediately(self, window):
        window.navigate_to("Log")
        new_widget = QLabel("Real Log View")
        window.replace_view("Log", new_widget)
        assert window._stack.currentWidget() is new_widget

    def test_replace_inactive_section_does_not_change_current(self, window):
        window.navigate_to("Podcasts")
        window.replace_view("Log", QLabel("Real Log"))
        assert window.current_section() == "Podcasts"
        assert window._stack.currentIndex() == 0

    @pytest.mark.parametrize("section, idx", [
        ("Flows", 1), ("Playlist", 2), ("Devices", 3), ("Profiles", 4),
    ])
    def test_replace_view_installs_at_right_index_for_each_section(
        self, window, section, idx
    ):
        widget = QLabel(f"Real {section}")
        window.replace_view(section, widget)
        assert window._stack.widget(idx) is widget

    def test_replace_view_unknown_section_raises(self, window):
        with pytest.raises(ValueError):
            window.replace_view("Unknown", QLabel("Oops"))
