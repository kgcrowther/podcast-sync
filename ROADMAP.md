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

### Cloud / mobile architecture

**Concept:** Shift SwimSync from a standalone desktop application to a cloud-coordinated service with browser and mobile configuration, while retaining a thin desktop client for USB device detection and file transfer.

---

#### The irreducible constraint

As long as Shokz uses USB, some agent must run on the machine that physically connects the device. A cloud server or mobile app cannot detect a USB mount. The desktop client is therefore never fully eliminated under any architecture — it becomes a background daemon with no UI rather than a full application. If Shokz ever adds Bluetooth or WiFi transfer, this constraint disappears and a mobile app could sync directly to the device without any desktop involvement. That would be a genuinely transformative shift worth watching.

---

#### The single most important upfront decision

**Does audio ever pass through your cloud infrastructure?**

The answer should almost certainly be **no**. Podcast episodes are 20–100 MB each. Cloud egress is the most expensive line item in most cloud bills, and storing audio adds cost with no benefit — the files are ephemeral, podcast hosts are already serving them reliably, and routing them through your cloud makes the sync slower and more expensive. The correct data flow is:

```
Podcast host → Desktop daemon → Device (USB)
```

The cloud provides the *plan* (what to sync, for which user); the desktop *executes* it. This decision affects every architecture variant below. Settling it early prevents designs that accidentally route audio through expensive infrastructure.

---

#### Upfront decisions that constrain future options

These choices interact. Making one without considering the others can close off paths that seem unrelated today.

**1. Who are the users?**
- *You and a small circle of known people* → self-hosted or local-first. No public auth, no infrastructure to operate, no GDPR exposure.
- *Strangers using a public service* → cloud-hosted with managed authentication, data isolation, account deletion flows, privacy policy.

Choosing "strangers" later after building for "known people" means retrofitting authentication and data isolation into a system not designed for it — one of the most expensive rewrites possible.

**2. Is the desktop app kept, reduced to a daemon, or eliminated?**
- *Kept* (local-first + optional sync): smallest change from today, offline always works, mobile is companion-only.
- *Reduced to daemon*: PyQt6 and all current UI is discarded; web/mobile replaces it entirely. The 3,984 lines of UI code become dead weight.
- *Eliminated*: only possible if USB dependency goes away (WiFi/Bluetooth device).

Choosing "reduce to daemon" without having the web/mobile replacement ready creates a gap where users have no UI. The transition must be atomic or the daemon must ship with a minimal UI fallback.

**3. Where does RSS fetching live?**
- *Desktop at sync time* (current): simple, no cloud dependency, but episodes only refresh when you plug in the device.
- *Cloud on a schedule*: enables push notifications ("new episode from X"), keeps episode lists fresh in the mobile app, but adds a background job infrastructure requirement.

Moving RSS fetching to the cloud is a prerequisite for push notifications and for keeping the mobile app's episode lists current. If push notifications are a goal, this must be decided and designed in before the cloud backend is built — retrofitting scheduled jobs into a system not designed for them is painful.

**4. Are profiles merged or replaced across devices?**
- *Last write wins*: simple to implement, occasionally surprising (editing flows on mobile and desktop simultaneously loses one set of changes).
- *CRDT-based merge*: complex to implement correctly, but changes from different devices are never lost.

This decision is invisible in a single-user local app but becomes critical the moment profiles live in the cloud and are editable from multiple surfaces simultaneously.

---

#### Architecture options

**Option A — Cloud-coordinated, desktop-executes** *(the proposed approach)*

```
Browser / Mobile App
        ↕  HTTPS
   Cloud API + Database  ←  Background RSS jobs
        ↕  HTTPS
  Desktop Daemon  →  Podcast hosts (audio download, direct)
        ↓
     Device (USB)
```

Cloud holds: user accounts, profiles, podcast subscriptions, flows, playlist metadata, device configs, sync logs, fresh episode data (fetched on a schedule). Desktop daemon holds: nothing persistent — it pulls its sync plan from the cloud on each device mount.

*Gains:* Mobile configuration, multi-user isolation, fresh episodes without plugging in the device, push notifications, no data loss on Mac reinstall, Windows daemon is trivial to ship alongside macOS.

*Costs:* Authentication is significant new scope (email verification, password reset, session management, account deletion, GDPR compliance). The entire PyQt6 UI (8 views, ~4,000 lines) is discarded and rewritten as a web app in React or Vue and optionally as native mobile apps. Infrastructure to operate even at small scale. Sync does not work when the cloud is unreachable. Privacy commitment — user podcast preferences and listening habits now live in your infrastructure.

*Estimated scope:* Very high. The desktop daemon reuses the existing Python core (`sync_engine`, `downloader`, `device_monitor`) but the web UI and authentication are ground-up new work.

---

**Option B — Self-hosted / home server**

```
Browser / Mobile App (local network or via Tailscale)
        ↕
  Local Server (runs on Mac mini / NAS / Raspberry Pi)
        ↕
  Desktop Daemon (may be the same machine)
        ↓  USB
     Device
```

The "cloud" is a server the user controls. No data ever leaves the home. Works offline on the local network. Familiar model — Plex, Jellyfin, and Nextcloud all operate this way.

*Gains:* No ongoing cost, no privacy exposure, no infrastructure to operate, no GDPR surface.

*Costs:* Setup complexity shifts to the user. Port forwarding or Tailscale required for remote access. No push notifications without an internet relay. Not viable as a multi-user public service.

*Best fit for:* Technical users managing their own setup, or a personal/family tool where you are effectively the only operator.

---

**Option C — Backend as a Service (BaaS)**

Use **Supabase** or **Firebase** to eliminate building and operating authentication, a database, and a server entirely.

```
Browser / Mobile App
        ↕  Supabase/Firebase SDK
   Supabase (Auth + Postgres + Row-Level Security + Realtime)
        ↕  WebSocket or REST
  Desktop Daemon
        ↓  USB
     Device
```

Supabase's row-level security means each user's data is isolated at the database layer without writing custom authorization code. The real-time layer can push a sync plan to the desktop daemon the moment a device is detected. At "dozens of users," the free tier is sufficient.

*Gains:* Authentication and data isolation are handled for you. No servers to patch or scale. Time-to-working product is dramatically shorter than Option A. Supabase is open-source and self-hostable if you later want to move off the managed service.

*Costs:* Dependency on a third-party platform — pricing changes and outages are outside your control. Some users may have privacy concerns about data on a third-party service. The web/mobile UI still needs to be built regardless.

*This is the recommended starting point for a cloud version at the current scale.* The operational burden is near zero.

---

**Option D — Local-first with cloud sync** *(smallest change from today)*

```
Desktop App (full PyQt6 UI — unchanged from v1)
        ↕  background sync (profiles only, tiny data)
   Cloud sync layer
        ↕
Mobile App (configuration only — no device sync on mobile)
```

The current desktop app stays intact. Profile data syncs to the cloud in the background when available — similar to how Apple Notes or Obsidian Sync work. The mobile app is a companion for configuring podcasts, flows, and playlists; device sync still happens from the desktop.

*Gains:* The app works perfectly offline — no regression from today. Cloud is additive, not required. Profile data is small (a few KB of JSON), so sync is fast and cheap. The desktop UI investment is preserved. Conflict resolution is the main technical challenge; "last write wins" is usually acceptable for this data type.

*Costs:* No push notifications. Mobile has no device sync capability. Does not support multiple independent users — this is still a personal tool. The PyQt6 UI remains the primary interface.

*Best fit for:* "Same profile across all my own machines" without building a full cloud service. Substantially smaller scope than Options A–C.

---

**Option E — No cloud, use existing sync infrastructure**

The simplest possible answer: SwimSync already exports and imports `.swimsync` profile files. Add a "sync folder" setting that auto-reads and auto-writes profiles to a user-chosen directory — which could be their iCloud Drive or Dropbox folder. Profiles follow the user across their own Macs automatically with zero new infrastructure.

*Gains:* Zero new infrastructure, zero authentication, works immediately for personal multi-machine use.

*Costs:* No mobile configuration. No multi-user support. No push notifications. Not a step toward the cloud/mobile vision — a workaround within the current architecture.

---

#### How current v1 decisions affect future options

| v1 decision | Keeps open | Closes off |
|---|---|---|
| Core logic separated from UI (`sync_engine`, `downloader` are UI-free) | Desktop daemon reuse in any option | Nothing — this is already done well |
| Profiles as self-contained JSON (`.swimsync` export/import) | Option D and E without schema migration | Nothing |
| No authentication surface | Simple to add later | Multi-user requires auth retrofit — design data model for multi-tenancy from the start if Option A/C is chosen |
| Local file paths hardcoded (`~/Library/...`) | Fine for Options D and E | Must be centralized and made platform-aware before Options A–C (cloud needs a concept of "user storage," not a local path) |
| RSS fetching at sync time only | Fine for all options initially | Push notifications require moving RSS to a cloud-side background job — this is a design change, not just an addition |
| Profiles stored as flat JSON files | Easy migration to a database (flat structure maps cleanly to rows) | Nothing — the data model is simple enough to port without redesign |

---

#### Recommended path if moving forward

1. **Decide the user scope first** (known users vs. public service) — this is the fork that determines everything else and cannot easily be reversed.
2. **If proceeding with cloud:** start with **Option C (Supabase)** and keep audio out of the cloud entirely. Build the desktop daemon first (reusing existing Python core), then the web UI, then mobile if needed.
3. **If staying personal/small circle:** **Option D** (local-first + sync) is substantially less work, preserves the current investment, and can be shipped much sooner. It does not preclude moving to Option C later — the data model is compatible.
4. **Do not build authentication from scratch** under any scenario. Use a managed identity provider (Supabase Auth, Firebase Auth, Auth0, or Apple/Google Sign-In). Authentication security is a specialist domain and the failure modes are severe.

---

## Deferred to v2

Items from the original requirements document deferred out of v1 scope:

- **Compiled `.app` / `.exe` distribution** — code-signed, distributable app bundle (currently run from source via Python)
- **Launch at login / menu bar presence** — background daemon with menu bar icon
- **iCloud profile sync** — sync profiles across multiple Macs automatically
- **Smart playlists** — rule-based playlists (e.g. "unlistened episodes under 30 minutes")
- **Audiobook support** — chapter-aware handling for audiobooks
- **Automatic episode marking** — treat a file deleted from the device as "listened"
