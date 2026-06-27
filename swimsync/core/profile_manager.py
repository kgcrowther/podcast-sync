"""
SwimSync profile manager.

Handles loading, saving, creating, and deleting profiles on disk.
Also handles export to and import from .swimsync files.

Profiles are stored as JSON files in:
    ~/Library/Application Support/SwimSync/profiles/

Each profile is saved as:
    ~/Library/Application Support/SwimSync/profiles/<profile_name>.json

The name of the last used profile is stored in:
    ~/Library/Application Support/SwimSync/last_profile.txt
"""

import json
import shutil
from pathlib import Path
from typing import Optional

from swimsync.models.profile import Profile, DEFAULT_DEVICES
from swimsync.utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "SwimSync"
PROFILES_DIR = APP_SUPPORT_DIR / "profiles"
LAST_PROFILE_FILE = APP_SUPPORT_DIR / "last_profile.txt"


def _ensure_dirs() -> None:
    """Create the profiles directory if it does not exist."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def _profile_path(name: str) -> Path:
    """Return the path to a profile's JSON file."""
    return PROFILES_DIR / f"{name}.json"


# ---------------------------------------------------------------------------
# Core CRUD operations
# ---------------------------------------------------------------------------

def list_profiles() -> list[str]:
    """
    Return a sorted list of all saved profile names.

    Returns:
        List of profile name strings (without .json extension).
    """
    _ensure_dirs()
    return sorted(p.stem for p in PROFILES_DIR.glob("*.json"))


def load_profile(name: str) -> Optional[Profile]:
    """
    Load a profile by name from disk.

    Args:
        name: The profile name (must match a saved profile).

    Returns:
        A Profile instance, or None if the profile does not exist.
    """
    path = _profile_path(name)
    if not path.exists():
        log.warning(f"Profile not found: {name}")
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        profile = Profile.from_dict(data)
        log.info(f"Loaded profile: {name}")
        return profile
    except (json.JSONDecodeError, KeyError) as exc:
        log.error(f"Failed to load profile '{name}': {exc}")
        return None


def save_profile(profile: Profile) -> bool:
    """
    Save a profile to disk, overwriting any existing file with the same name.

    Args:
        profile: The Profile instance to save.

    Returns:
        True if saved successfully, False on error.
    """
    _ensure_dirs()
    path = _profile_path(profile.name)

    try:
        path.write_text(
            json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info(f"Saved profile: {profile.name}")
        return True
    except OSError as exc:
        log.error(f"Failed to save profile '{profile.name}': {exc}")
        return False


def delete_profile(name: str) -> bool:
    """
    Delete a saved profile by name.

    Args:
        name: The profile name to delete.

    Returns:
        True if deleted (or did not exist), False on error.
    """
    path = _profile_path(name)
    if not path.exists():
        log.warning(f"Cannot delete — profile not found: {name}")
        return True

    try:
        path.unlink()
        log.info(f"Deleted profile: {name}")
        return True
    except OSError as exc:
        log.error(f"Failed to delete profile '{name}': {exc}")
        return False


def create_default_profile(name: str) -> Profile:
    """
    Create a new empty profile with the given name and save it to disk.

    Args:
        name: The name for the new profile.

    Returns:
        The newly created Profile instance.
    """
    profile = Profile(name=name, device_configs=list(DEFAULT_DEVICES))
    save_profile(profile)
    log.info(f"Created new profile: {name}")
    return profile


# ---------------------------------------------------------------------------
# Last used profile
# ---------------------------------------------------------------------------

def get_last_profile_name() -> Optional[str]:
    """
    Return the name of the most recently used profile, or None.

    Returns:
        Profile name string, or None if no last profile has been recorded.
    """
    if not LAST_PROFILE_FILE.exists():
        return None
    name = LAST_PROFILE_FILE.read_text(encoding="utf-8").strip()
    return name if name else None


def set_last_profile_name(name: str) -> None:
    """
    Record the most recently used profile name.

    Args:
        name: The profile name to record.
    """
    _ensure_dirs()
    LAST_PROFILE_FILE.write_text(name, encoding="utf-8")
    log.info(f"Last profile set to: {name}")


def load_last_profile() -> Optional[Profile]:
    """
    Load the most recently used profile, if one exists.

    Returns:
        The last used Profile, or None if no last profile is recorded
        or it can no longer be found on disk.
    """
    name = get_last_profile_name()
    if name is None:
        return None
    return load_profile(name)


# ---------------------------------------------------------------------------
# Export and import
# ---------------------------------------------------------------------------

def export_profile(profile: Profile, destination: Path) -> bool:
    """
    Export a profile to a .swimsync file at the given destination path.

    The exported file contains: profile name, followed podcasts, flows,
    playlist, and device trigger settings. It does NOT contain downloaded
    files or logs.

    Args:
        profile: The Profile to export.
        destination: Full path where the .swimsync file should be written,
                     e.g. Path("/Users/kenneth/Desktop/Kenneth.swimsync")

    Returns:
        True if exported successfully, False on error.
    """
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info(f"Exported profile '{profile.name}' to {destination}")
        return True
    except OSError as exc:
        log.error(f"Failed to export profile '{profile.name}': {exc}")
        return False


def import_profile(source: Path, overwrite: bool = False) -> Optional[Profile]:
    """
    Import a profile from a .swimsync file.

    If a profile with the same name already exists on disk, the import
    will fail unless overwrite=True.

    Args:
        source: Path to the .swimsync file to import.
        overwrite: If True, overwrite an existing profile with the same name.

    Returns:
        The imported Profile instance, or None if import failed.
    """
    if not source.exists():
        log.error(f"Import failed — file not found: {source}")
        return None

    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        profile = Profile.from_dict(data)
    except (json.JSONDecodeError, KeyError) as exc:
        log.error(f"Import failed — could not parse {source}: {exc}")
        return None

    existing = _profile_path(profile.name)
    if existing.exists() and not overwrite:
        log.warning(
            f"Import aborted — profile '{profile.name}' already exists. "
            f"Use overwrite=True to replace it."
        )
        return None

    if save_profile(profile):
        log.info(f"Imported profile '{profile.name}' from {source}")
        return profile

    return None
