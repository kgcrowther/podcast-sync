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

## Deferred to v2

Items from the original requirements document deferred out of v1 scope:

- **Compiled `.app` distribution** — code-signed, distributable macOS app bundle (currently run from source via Python)
- **Launch at login / menu bar presence** — background daemon with menu bar icon
- **iCloud profile sync** — sync profiles across multiple Macs automatically
- **Smart playlists** — rule-based playlists (e.g. "unlistened episodes under 30 minutes")
- **Audiobook support** — chapter-aware handling for audiobooks
- **Automatic episode marking** — treat a file deleted from the device as "listened"
- **Windows / Linux support**
