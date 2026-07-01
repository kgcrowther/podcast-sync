# SwimSync Roadmap

Items already committed to the requirements document as **v2+ future considerations** are listed in the [Deferred to v2](#deferred-to-v2) section. Items below that line are feature ideas under active consideration for inclusion in a future release.

---

## Released

### v1.0.0 — June 2026
Full v1 feature set as specified in SwimSync_Requirements.md:
- Podcast management (iTunes search + RSS URL, episode browser, stale/error indicators)
- Flows (most-recent-N and last-X-days rules, evaluated fresh at each sync)
- Playlist (manual curation, drag-and-drop, file picker, preview)
- Devices (Shokz OpenSwim + OpenSwim Pro defaults, custom device support)
- Profiles (multi-user, export/import as `.swimsync`)
- Sync dialog (7-phase, storage-aware, mid-sync disconnect handling)
- Log viewer (All / Errors / Sync Events filters, Finder reveal)
- 923 automated tests

---

## Under consideration

### Per-podcast playback speed (time-stretching)

**Concept:** Each followed podcast can be assigned a playback speed (e.g. 1.0×, 1.25×, 1.5×, 2.0×). When an episode from that podcast is synced to the device, SwimSync downloads the original file and re-encodes it at the target speed using pitch-preserving time-stretching before copying it to the device. If the speed setting changes between syncs, the file size on the device changes and the existing filename + byte-size comparison logic automatically triggers a re-download and re-process.

**Implementation approach:**
- New `playback_speed: float = 1.0` field on the `Podcast` model (serialized in profile export/import)
- Audio processing via **ffmpeg `atempo` filter** — pitch-corrected time-stretch, widely used by podcast apps, good speech quality, no heavy Python dependency
- New `audio_processor.py` module (`apply_speed(input, output, speed)`) inserted in the sync pipeline between download and copy
- Speed selector UI on each podcast tile (dropdown: 1.0×, 1.1×, 1.25×, 1.5×, 1.75×, 2.0×)
- Sync dialog progress updated to show a "Processing" step alongside Download and Copy

**Key tradeoffs:**
- **ffmpeg is a system dependency** — must be installed separately (`brew install ffmpeg`, ~300 MB). The app needs runtime detection and graceful degradation (fall back to 1.0× with a log warning if ffmpeg is absent).
- Processed files are proportionally smaller on the device (a 1.5× file is ~67% the size of the original at the same bitrate), which is a net storage benefit.
- Peak downloads-directory usage during sync temporarily holds both the original and processed file (~167% of original size at 1.5×).
- Re-encoding MP3 → MP3 introduces minor generational quality loss; imperceptible for speech.
- Processing time is negligible (~1–2 seconds per 45-minute episode on modern hardware).

**Estimated scope:** Medium. ~2 focused development sessions. The sync detection logic requires no changes; the main complexity is the ffmpeg dependency management and the graceful-degradation UX.

**Prerequisites:** ffmpeg installed via Homebrew. README and in-app messaging would need to document this.

---

### Windows 11 support

**Concept:** Extend SwimSync to run on Windows 11 with full feature parity. The Python and PyQt6 stack is already cross-platform; the work is confined to four specific areas where the code is currently macOS-specific.

**What needs no changes:**
PyQt6 (UI, dialogs, signals), feedparser, requests, psutil, certifi, pathlib, shutil, FAT32 filename sanitization, file picker and drag-and-drop, `QDesktopServices.openUrl()` for episode preview, profile export/import, RSS fetching, and the `python -m swimsync` entry point all work on Windows without modification.

**Required changes:**

1. **Device label detection** — The only non-trivial change. On macOS, the drive label is the last component of the mount point path (`/Volumes/SWIM PRO` → `"SWIM PRO"`). On Windows, USB volumes mount at a drive letter (`D:\`) and the volume label is stored in FAT32 metadata, retrieved separately. Confirmed via hardware testing: a Shokz OpenSwim Pro appears as `"SWIM PRO (D:)"` in Windows File Explorer, meaning the underlying volume label is `"SWIM PRO"` — identical to what macOS reports. The fix is a Windows branch in `get_mounted_devices()` that calls `ctypes.windll.kernel32.GetVolumeInformationW` for each drive letter to retrieve the label, then compares against watched labels as normal. No changes to the user-facing Devices configuration; users still enter `"SWIM PRO"` as the drive label on both platforms.

2. **Application data paths** — `~/Library/Application Support/SwimSync/` is hardcoded in `file_utils.py`, `logger.py`, and `profile_manager.py`. On Windows the correct location is `%APPDATA%\SwimSync\`. Fix: centralize the path into a single platform-aware helper (using `sys.platform` + `os.environ["APPDATA"]`, or the `platformdirs` library) and have all three files import from it. This also resolves the existing structural issue of the same path being defined in three places.

3. **`os.statvfs()` for device storage** — `sync_engine.py` uses `os.statvfs()` to read device capacity, which is POSIX-only and raises `AttributeError` on Windows. Replace with `shutil.disk_usage()`, which is cross-platform stdlib and already used elsewhere in the codebase via psutil.

4. **"Open Log File" button** — `log_view.py` runs `subprocess.run(["open", "-R", path])` (macOS Finder). Windows equivalent is `subprocess.run(["explorer", "/select,", path])`. Needs a `sys.platform` check; without it the button silently does nothing on Windows.

**Minor:**
- User-Agent string `"SwimSync/1.0 (Podcast sync; macOS)"` in `rss_client.py` and `downloader.py` — change to `"SwimSync/1.0 (Podcast sync)"` for platform neutrality.
- README installation instructions — add Windows venv activation (`venv\Scripts\activate`) and note that the command may be `python` rather than `python3` on Windows.

**Estimated scope:** Low–Medium. ~1 focused development session for the code changes. The device label detection requires a Windows machine or VM for end-to-end testing; all other changes can be verified in the test suite by mocking `sys.platform` and the ctypes call.

**Prerequisites:** A Windows 11 machine or VM for integration testing. No new runtime dependencies required if using ctypes (Windows built-in) for volume label lookup.

---

## Deferred to v2

Items from the original requirements document deferred out of v1 scope:

- **Compiled `.app` / `.exe` distribution** — code-signed, distributable app bundle (currently run from source via Python)
- **Launch at login / menu bar presence** — background daemon with menu bar icon
- **iCloud profile sync** — sync profiles across multiple Macs automatically
- **Smart playlists** — rule-based playlists (e.g. "unlistened episodes under 30 minutes")
- **Audiobook support** — chapter-aware handling for audiobooks
- **Automatic episode marking** — treat a file deleted from the device as "listened"
