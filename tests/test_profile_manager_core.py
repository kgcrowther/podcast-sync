"""
Tests for SwimSync profile manager (core/profile_manager.py).

Run with: pytest tests/test_profile_manager.py -v

Note: These tests patch the profile manager's directory constants so that
all file operations happen in a temporary directory rather than touching
~/Library/Application Support/SwimSync.
"""

import json
from pathlib import Path

import pytest

import swimsync.core.profile_manager as pm
from swimsync.models.profile import Profile, Podcast, Flow, DEFAULT_DEVICES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """
    Redirect all profile manager file I/O to a temporary directory.
    Runs automatically for every test in this file.
    """
    profiles_dir = tmp_path / "profiles"
    last_profile_file = tmp_path / "last_profile.txt"

    monkeypatch.setattr(pm, "PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(pm, "LAST_PROFILE_FILE", last_profile_file)


def make_profile(name: str = "TestUser") -> Profile:
    """Return a simple Profile for use in tests."""
    return Profile(
        name=name,
        podcasts=[
            Podcast(
                title="Test Podcast",
                rss_url="https://example.com/feed.xml",
                author="Author",
                description="Description",
                artwork_url=None,
                last_checked=None,
            )
        ],
        flows=[
            Flow(podcast_rss_url="https://example.com/feed.xml", most_recent_count=3)
        ],
        playlist=[],
        device_configs=list(DEFAULT_DEVICES),
    )


# ---------------------------------------------------------------------------
# list_profiles
# ---------------------------------------------------------------------------

def test_list_profiles_empty():
    """list_profiles returns an empty list when no profiles exist."""
    assert pm.list_profiles() == []


def test_list_profiles_after_save():
    """list_profiles returns the names of saved profiles."""
    pm.save_profile(make_profile("Alice"))
    pm.save_profile(make_profile("Bob"))
    assert pm.list_profiles() == ["Alice", "Bob"]


def test_list_profiles_sorted():
    """list_profiles returns names in alphabetical order."""
    pm.save_profile(make_profile("Zebra"))
    pm.save_profile(make_profile("Alpha"))
    assert pm.list_profiles() == ["Alpha", "Zebra"]


# ---------------------------------------------------------------------------
# save_profile / load_profile
# ---------------------------------------------------------------------------

def test_save_and_load_profile():
    """A saved profile can be loaded back with the same data."""
    profile = make_profile("Kenneth")
    pm.save_profile(profile)
    loaded = pm.load_profile("Kenneth")

    assert loaded is not None
    assert loaded.name == "Kenneth"
    assert len(loaded.podcasts) == 1
    assert loaded.podcasts[0].title == "Test Podcast"


def test_load_nonexistent_profile():
    """load_profile returns None for a profile that does not exist."""
    assert pm.load_profile("DoesNotExist") is None


def test_save_overwrites_existing():
    """Saving a profile with the same name overwrites the previous version."""
    profile = make_profile("Kenneth")
    pm.save_profile(profile)

    profile.podcasts = []
    pm.save_profile(profile)

    loaded = pm.load_profile("Kenneth")
    assert loaded is not None
    assert len(loaded.podcasts) == 0


def test_load_corrupted_profile_returns_none(tmp_path, monkeypatch):
    """load_profile returns None if the JSON file is corrupted."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    monkeypatch.setattr(pm, "PROFILES_DIR", profiles_dir)

    bad_file = profiles_dir / "Bad.json"
    bad_file.write_text("this is not valid json", encoding="utf-8")

    assert pm.load_profile("Bad") is None


# ---------------------------------------------------------------------------
# delete_profile
# ---------------------------------------------------------------------------

def test_delete_existing_profile():
    """delete_profile removes a profile from disk."""
    pm.save_profile(make_profile("ToDelete"))
    assert pm.delete_profile("ToDelete") is True
    assert pm.load_profile("ToDelete") is None


def test_delete_nonexistent_profile():
    """delete_profile returns True gracefully when profile does not exist."""
    assert pm.delete_profile("Ghost") is True


# ---------------------------------------------------------------------------
# create_default_profile
# ---------------------------------------------------------------------------

def test_create_default_profile():
    """create_default_profile creates and saves a new empty profile."""
    profile = pm.create_default_profile("NewUser")
    assert profile.name == "NewUser"
    assert len(profile.podcasts) == 0
    assert len(profile.flows) == 0
    assert len(profile.playlist) == 0

    labels = [d.drive_label for d in profile.device_configs]
    assert "SWIM PRO" in labels
    assert "OpenSwim" in labels


def test_create_default_profile_persisted():
    """create_default_profile saves the profile so it can be loaded."""
    pm.create_default_profile("Persisted")
    assert pm.load_profile("Persisted") is not None


# ---------------------------------------------------------------------------
# last profile
# ---------------------------------------------------------------------------

def test_get_last_profile_name_none_initially():
    """get_last_profile_name returns None when no last profile is recorded."""
    assert pm.get_last_profile_name() is None


def test_set_and_get_last_profile_name():
    """set_last_profile_name records a name that get_last_profile_name returns."""
    pm.set_last_profile_name("Kenneth")
    assert pm.get_last_profile_name() == "Kenneth"


def test_load_last_profile():
    """load_last_profile loads the profile recorded as last used."""
    pm.save_profile(make_profile("Kenneth"))
    pm.set_last_profile_name("Kenneth")

    loaded = pm.load_last_profile()
    assert loaded is not None
    assert loaded.name == "Kenneth"


def test_load_last_profile_none_when_not_set():
    """load_last_profile returns None when no last profile is set."""
    assert pm.load_last_profile() is None


def test_load_last_profile_none_when_missing_from_disk():
    """load_last_profile returns None if the recorded profile no longer exists."""
    pm.set_last_profile_name("Deleted")
    assert pm.load_last_profile() is None


# ---------------------------------------------------------------------------
# export_profile
# ---------------------------------------------------------------------------

def test_export_creates_file(tmp_path):
    """export_profile writes a .swimsync file at the given path."""
    profile = make_profile("Kenneth")
    dest = tmp_path / "exports" / "Kenneth.swimsync"

    assert pm.export_profile(profile, dest) is True
    assert dest.exists()


def test_export_file_is_valid_json(tmp_path):
    """The exported .swimsync file contains valid JSON."""
    profile = make_profile("Kenneth")
    dest = tmp_path / "Kenneth.swimsync"
    pm.export_profile(profile, dest)

    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["name"] == "Kenneth"


def test_export_contains_podcasts_and_flows(tmp_path):
    """Exported file includes podcasts, flows, playlist, and device configs."""
    profile = make_profile("Kenneth")
    dest = tmp_path / "Kenneth.swimsync"
    pm.export_profile(profile, dest)

    data = json.loads(dest.read_text(encoding="utf-8"))
    assert "podcasts" in data
    assert "flows" in data
    assert "playlist" in data
    assert "device_configs" in data


# ---------------------------------------------------------------------------
# import_profile
# ---------------------------------------------------------------------------

def test_import_profile(tmp_path):
    """import_profile loads a profile from a .swimsync file."""
    profile = make_profile("Kenneth")
    dest = tmp_path / "Kenneth.swimsync"
    pm.export_profile(profile, dest)

    imported = pm.import_profile(dest)
    assert imported is not None
    assert imported.name == "Kenneth"
    assert len(imported.podcasts) == 1


def test_import_profile_persisted(tmp_path):
    """import_profile saves the profile so it appears in list_profiles."""
    profile = make_profile("Kenneth")
    dest = tmp_path / "Kenneth.swimsync"
    pm.export_profile(profile, dest)
    pm.import_profile(dest)

    assert "Kenneth" in pm.list_profiles()


def test_import_profile_no_overwrite(tmp_path):
    """import_profile returns None if profile exists and overwrite=False."""
    profile = make_profile("Kenneth")
    dest = tmp_path / "Kenneth.swimsync"
    pm.export_profile(profile, dest)

    pm.import_profile(dest)
    result = pm.import_profile(dest, overwrite=False)
    assert result is None


def test_import_profile_with_overwrite(tmp_path):
    """import_profile succeeds when overwrite=True and profile already exists."""
    profile = make_profile("Kenneth")
    dest = tmp_path / "Kenneth.swimsync"
    pm.export_profile(profile, dest)

    pm.import_profile(dest)
    result = pm.import_profile(dest, overwrite=True)
    assert result is not None


def test_import_missing_file(tmp_path):
    """import_profile returns None if the source file does not exist."""
    assert pm.import_profile(tmp_path / "missing.swimsync") is None


def test_import_corrupted_file(tmp_path):
    """import_profile returns None if the file contains invalid JSON."""
    bad = tmp_path / "bad.swimsync"
    bad.write_text("not json", encoding="utf-8")
    assert pm.import_profile(bad) is None
