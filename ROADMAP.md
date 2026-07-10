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

As long as Shokz devices only expose bulk file storage over USB, some device with a USB host port must physically connect to them to sync files. A cloud server cannot detect a USB mount, so the desktop daemon in Option A below is unavoidable for a *cloud* architecture.

A mobile app is not limited the same way, though: modern iOS and Android devices can mount and write to a USB mass-storage volume directly over a cable — confirmed feasible below. So a mobile app genuinely can eliminate the desktop/Mac requirement, with no change needed from Shokz, provided a wired connection is used. See **[Mobile companion app — wired sync, no Mac required](#mobile-companion-app-iosandroid--wired-sync-no-mac-required)** below.

Neither Bluetooth nor WiFi offers a wireless shortcut to the same goal. The OpenSwim Pro is confirmed to have a Bluetooth radio (used for live audio streaming in its dual-mode design), but Shokz explicitly states file transfer is not supported over that connection — see **[Wireless (Bluetooth) file sync](#wireless-bluetooth-file-sync--not-supported-by-the-hardwarefirmware)** below. And the device's FCC filing confirms it has no WiFi radio at all — see **[WiFi connectivity](#wifi-connectivity--no-radio-present-confirmed-via-fcc-filing)** below. A fully cable-free mobile sync therefore remains out of reach unless Shokz changes either of these in future hardware.

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

### Device battery status ("time to charge" indicator)

**Concept:** When a device is mounted and the profile-selection dialog appears, show the device's current battery charge alongside a recommendation of how long to charge it. Extend the idea to a general capability so that other MP3-player devices users add as custom device profiles could eventually support the same indicator.

**Feasibility findings (empirically tested 2026-07-08 against a physical Shokz OpenSwim Pro, mounted as `SWIM PRO`):**
- The charging/sync cable is a proprietary 4-pin magnetic connector, but once connected it presents to macOS as a plain USB mass-storage device — same as any flash drive.
- `system_profiler SPUSBDataType -detailLevel full` and `ioreg -p IOUSB -l` both show the storage interface identifying only as a generic **Genesys Logic, Inc. "USB Storage"** bridge chip (`idVendor` 0x05E3 / `idProduct` 0x0761, `iProduct` = `"USB Storage"`) — a commodity USB-to-flash bridge used in countless unrelated flash drives and card readers, not a Shokz-custom controller. There is no Shokz-branded string anywhere in the descriptor, no vendor-specific interface, and no battery/capacity-related key anywhere in the IORegistry node for this device.
- No hidden status/config file exists at the root of the mounted volume — `ls -la "/Volumes/SWIM PRO"` shows only the audio files SwimSync placed there plus standard FAT32/macOS housekeeping entries (`.Spotlight-V100`, `.fseventsd`, `System Volume Information`).
- **Correction after further testing:** the OpenSwim Pro is a confirmed dual-mode device — it has a Bluetooth 5.4 radio for live audio streaming (switchable to standalone MP3 mode via a 2-second Volume+/Volume− hold, or the Shokz app), and the Shokz companion app *does* show a battery reading, over that Bluetooth connection. This does not change the conclusion below for SwimSync's current integration path — the USB-mounted-drive path and the Bluetooth path are architecturally separate (see [Wireless (Bluetooth) file sync](#wireless-bluetooth-file-sync--not-supported-by-the-hardwarefirmware) below) — but it does mean battery telemetry isn't absent from the device entirely, only absent from the specific access path SwimSync uses today.
- macOS's `IOPowerSources` / `ioreg BatteryPercent` mechanism is populated for Bluetooth accessories and internal battery hardware, not for USB mass-storage devices — there is no OS-level hook a userspace app could read via the mounted-drive path, even though the same battery value is reachable over Bluetooth by Shokz's own app.
- **Conclusion:** a real battery percentage is not obtainable from the OpenSwim Pro through the mounted-USB-drive path any macOS application (including SwimSync) uses today. The storage bridge chip is off-the-shelf with no vendor-added command, and a raw-SCSI-passthrough approach would require an undocumented vendor command with no evidence it exists. Bluetooth is a real, working alternative path to the same data (proven by Shokz's own app), but reading it would require reverse-engineering Shokz's proprietary GATT service/characteristic (no public SDK exists) — a project on the scale of the mobile companion app analysis below, not a small addition to the current desktop sync flow.

**Implementation approach — reframed around the "device stays silent" constraint:**

1. **Self-reported charge state (ships immediately, no hardware dependency)**
   - Add a lightweight control to the Sync Dialog's `READY` phase (`sync_dialog.py`): "Full / Partial / Low — not sure," defaulting to "not sure."
   - Session-only state — not persisted into the `Profile`/`.swimsync` file, since it's a momentary fact about hardware, not portable profile data.
   - If the user picks "Low," show a one-line, non-blocking reminder: "Consider charging before your next swim."

2. **Usage-based heuristic estimate (soft-state, still no hardware dependency)**
   - Two new optional fields on `DeviceConfig`: `last_charged_at: Optional[str]` (ISO-8601, user-confirmed) and `rated_playback_hours: Optional[float]` (from the device manual — OpenSwim Pro is rated ~10 hours).
   - Sync Dialog asks "Did you just charge this device?" the first time it connects after a sync; answering Yes stamps `last_charged_at = now`.
   - On later connects, show an estimate ("~X hours of playback likely remaining") derived from elapsed time vs. `rated_playback_hours`, clearly labeled as an estimate. Confidence should decay with time: past roughly 1.5× the rated window with no reconfirmation, fall back to "Unknown — check the device's LED indicator" rather than asserting a number that's probably wrong.

3. **True hardware probe — a documented stretch path, not planned work**
   - If a future device (or firmware revision) does expose battery telemetry, the architecture shouldn't need to change to add it: a `battery_probe.py` module defining a `BatteryProbe` protocol (`read(mount_point) -> Optional[BatteryStatus]`), registered by **USB vendor/product ID**, not drive label. This distinction matters for correctness, not just tidiness — `drive_label` is user-editable text (Requirements §3 allows typing it manually), so two unrelated devices could share a label, while VID/PID is the one reliable hardware fingerprint. Capturing VID/PID is new work: `device_monitor.get_mounted_devices()` currently only reads `psutil.disk_partitions()`, which exposes mount point and filesystem type but not the parent USB device — mapping a BSD disk node back to its USB descriptor needs a `system_profiler SPUSBDataType` shell-out or an IOKit registry walk keyed by `IOBSDName`.
   - Any device without a registered VID/PID (every device today) silently falls back to the self-report/heuristic path above — the same graceful-degradation pattern already used for the missing-ffmpeg case in the playback-speed entry above.

**Key tradeoffs:**
- The headline ask (a real battery percentage) cannot be delivered for the OpenSwim Pro; this needs to be set as an expectation up front rather than discovered after building UI around it.
- The self-report control adds a small amount of friction to every sync's `READY` phase; keeping the default non-committal and never blocking keeps this cheap.
- The heuristic estimate is only as good as its inputs (rated hours, honesty of the "just charged" confirmation) and will visibly diverge from reality in edge cases (partial charges, device left powered on between syncs) — hence the explicit decay-to-"Unknown" behavior rather than a persistently confident number.
- Generalizing via VID/PID adds a new detection dependency to `device_monitor.py` that doesn't exist today; it's a small addition, but it's still a new external-process/IOKit call in a module that currently only calls `psutil`.

**Estimated scope:** Low for the self-report + heuristic path — roughly half a development session: one new Sync Dialog control, two new optional `DeviceConfig` fields, no new modules. The hardware-probe extension point is a few hours to scaffold but isn't worth building until a specific device with a real, working battery-read mechanism is identified; a registry with zero working probes in it is speculative work with no payoff.

**Prerequisites:** None for the self-report/heuristic path. The hardware-probe path needs a specific device confirmed (via vendor documentation or successful reverse engineering) to expose battery telemetry over the mounted-drive path — none qualify today. A Bluetooth-based probe is known to be *possible* in principle (Shokz's own app does it for the OpenSwim Pro) but is a separate, much larger project — see the mobile companion app analysis below, since it would need the same GATT reverse-engineering effort as any other Bluetooth capability on this device.

---

### Wireless (Bluetooth) file sync — not supported by the hardware/firmware

**Concept prompting this analysis:** The OpenSwim Pro is a confirmed dual-mode device: a Bluetooth 5.4 radio streams live audio from a phone during normal use, and a 2-second Volume+/Volume− hold (or the Shokz app) switches it to standalone MP3 mode, playing files from onboard flash — which is what makes it usable underwater, where Bluetooth can't propagate. Because both modes live on one device, it's natural to ask whether SwimSync could sync podcast files onto the device's onboard storage over the existing Bluetooth connection instead of the physical cable — which would let a mobile app sync while out on a run, ready for the pool later without ever touching a Mac.

**Findings:**
- Shokz's own documentation states directly: *"OpenSwim Pro does not support Bluetooth music transfer. Instead, to import songs to OpenSwim Pro, connect the headphones to your computer using the magnetic charging cable."* This is a stated limitation, not an undocumented gap — on a product whose companion app already implements a fairly capable Bluetooth control surface (mode switching, EQ, multipoint pairing, battery status, firmware OTA updates).
- The two playback modes are architecturally separate pipelines, not two writers sharing one storage buffer: Bluetooth mode streams audio live from the phone straight to the DAC, never touching flash; MP3 mode has the device's own MCU read files directly off onboard flash. The flash is exposed externally only through the physical cable, as a plain USB mass-storage volume via a commodity Genesys Logic bridge chip (the same chip identified in the battery investigation above) — nothing suggests that chip is reachable from the Bluetooth radio at the hardware-bus level.
- Firmware OTA over Bluetooth does prove *some* write path exists from the Bluetooth SoC into flash — but that's a narrow, vendor-controlled binary update mechanism aimed at a dedicated firmware partition, not a general filesystem write API, and Shokz's statement confirms they did not repurpose or expose it for user audio content.

**Why this isn't worth pursuing:** Unlike the battery investigation — where "not reachable over USB" turned out to mean "reachable over a different, working channel instead" — this is a vendor-stated, deliberate absence on a device where Shokz has clearly already invested in Bluetooth tooling. Working around it would require confirming bus-level hardware access from the Bluetooth SoC to the flash chip (realistically needs a teardown/datasheet — destructive, and not available for hardware in daily use), reverse-engineering a protocol that doesn't currently exist in the firmware (not merely discovering a hidden-but-present one), and quite possibly flashing custom firmware to add the capability — closer to jailbreaking the device than writing an app, with real risk of bricking hardware and no guarantee of success.

**Conclusion:** Not feasible, and not worth treating as a research spike. Revisit only if Shokz ships an SDK or firmware update that adds Bluetooth file transfer.

---

### WiFi connectivity — no radio present, confirmed via FCC filing

**Concept prompting this analysis:** Some SoCs that provide Bluetooth also bundle WiFi on the same die, with the antenna and RF front-end already present for other reasons. A Garmin Forerunner 245 Music auto-connects to a previously-configured WiFi network when plugged in to charge, syncing podcasts in the background with no phone needed — the question is whether the OpenSwim Pro has similar (even if undocumented) WiFi hardware and a CLI or protocol to configure it.

**Findings:**
- The OpenSwim Pro's FCC filing (**FCC ID 2BCD6-S710**, Shokz Singapore Pte. Ltd. — the only FCC filing for this product) lists exactly two radio grants, both operating solely in the 2402–2480 MHz band (the Bluetooth ISM band) at 5.6 mW and 6.9 mW conducted output. **There is no 802.11/WiFi equipment-class grant anywhere in the filing.** Since intentional radiators sold in the US are legally required to be FCC-certified, the absence of a WiFi grant is about as close to definitive as public evidence gets: this device does not contain a legally-operating WiFi radio. (Source: [fccid.io/2BCD6-S710](https://fccid.io/2BCD6-S710).)
- Cross-checked every Shokz filing under grantee code 2BCD6 (OpenRun, OpenRun Pro, OpenRun Pro 2, OpenComm, OpenComm2, OpenFit 2, OpenDots One, OpenMeet) — every Shokz product is Bluetooth-only. This isn't a one-off omission on the OpenSwim Pro; Shokz has no WiFi hardware, firmware, or cloud-sync infrastructure anywhere in its product line.
- Empirical test performed live against the physical device (connected and charging): a WiFi scan (`airport -s`) from the Mac showed only pre-existing household/neighbor networks — no new SSID or access point associated with the device appeared. This rules out the device broadcasting a setup/provisioning AP the way some IoT devices do during pairing, which would show up in a scan even without the device being paired to anything.
- The 5.6–6.9 mW conducted output levels are consistent with a Bluetooth Low Energy/Classic radio; even low-power WiFi implementations typically transmit at higher power, and would in any case need their own distinct FCC grant.

**On the "unpublished CLI" idea specifically:** Setting the FCC finding aside, "an unpublished CLI to configure WiFi" presupposes a WiFi stack (network manager, DHCP client, credential storage) already exists in firmware and is merely undocumented — the way undocumented diagnostic shells sometimes exist on routers or NAS boxes. That's not this situation: there's no radio hardware to drive such a stack in the first place. This isn't a hidden-feature question; it would require Shokz to have populated an antenna and RF front-end for a radio class they never certified this product for — new hardware, not hidden firmware.

**Comparison with the Garmin Forerunner 245 Music:** Garmin's charge-and-sync behavior rides on infrastructure built for reasons that have nothing to do with music — Garmin Connect (a cloud platform), and WiFi hardware already justified by GPS-heavy product needs (activity upload, maps, software updates) across a large, diverse catalog. Shokz has no equivalent on any product: no cloud platform, no other WiFi hardware anywhere in the lineup, and — per the FCC filing — no WiFi silicon on this specific device. There's no existing infrastructure here to extend.

**Conclusion:** Not feasible on current OpenSwim Pro hardware, and unlike the Bluetooth file-transfer question, this isn't a reverse-engineering problem — it's a confirmed hardware absence from a primary regulatory source, corroborated by a live scan. There is no unpublished WiFi CLI to find, because there is no WiFi radio to configure. Revisit only if a future OpenSwim Pro hardware revision ships with a new FCC filing that includes an 802.11 grant.

**Estimated scope:** Not applicable — no engineering work can substitute for missing radio hardware; this closes the WiFi avenue for the current device generation.

**Prerequisites:** None. To verify independently, the primary source is the grant table and exhibits at [fccid.io/2BCD6-S710](https://fccid.io/2BCD6-S710).

---

### Mobile companion app (iOS/Android) — wired sync, no Mac required

**Concept:** Since Bluetooth transfer is ruled out, the practical way to free the sync workflow from requiring a Mac is a native mobile app implementing the same feature set as the desktop app (follow podcasts, configure flows, curate a playlist, sync) that talks to the device over the *same physical cable*, plugged into the phone instead of a computer — reusing the identical USB mass-storage protocol already in use today, just with a different host.

**Why this is newly worth taking seriously:** The "Cloud / mobile architecture" analysis above originally framed USB as an *irreducible constraint requiring a desktop*, assuming "mobile app" meant a configuration-only companion talking to a cloud or desktop backend. That framing was too strong. Modern phones can genuinely mount and read/write a FAT32 USB mass-storage device directly:
- **Android**: native support via the Storage Access Framework (`ACTION_OPEN_DOCUMENT_TREE` grants a persistent URI to an attached USB drive; `DocumentFile`/`ContentResolver` then read/write it) and the USB Host API (`UsbManager`, with `ACTION_USB_DEVICE_ATTACHED` broadcast intents for attach detection) — this is how Android file-manager apps already browse USB flash drives over an OTG cable/adapter, no root required.
- **iOS**: supported since iOS 13's "USB drives in Files app" feature. USB-C iPhones (iPhone 15 and later) mount a FAT32 drive directly; Lightning iPhones need Apple's Lightning-to-USB 3 Camera Adapter in addition to the Shokz cable. Third-party apps get read/write access via `UIDocumentPickerViewController` — the same document-provider mechanism the Files app itself uses — with no MFi certification required.

**Implementation approach:**
- The current architecture's separation of UI-free core logic (`sync_engine.py`, `downloader.py`, `profile_manager.py`) from the PyQt6 UI pays off here as an *algorithm to port*, not literal shared code — Python isn't a first-class citizen in iOS/Android app-store distribution, so this would be a ground-up native implementation (Swift/SwiftUI + Kotlin/Jetpack Compose, or one Flutter/React Native codebase with platform channels for the USB/file-picker integration) that reimplements the same logic: flow evaluation (most-recent-N ∪ last-X-days union), filename+byte-size comparison, the 90% storage-threshold check, RSS fetching, iTunes search.
- Profile storage should stay `.swimsync`-compatible JSON, so a profile exported from the desktop app imports cleanly into the mobile app and vice versa — this was already flagged as a strength of the current data model in the cloud/mobile analysis's "how v1 decisions affect future options" table, and it applies just as well here.
- Device-attach detection differs meaningfully by platform: Android can listen for `ACTION_USB_DEVICE_ATTACHED`, similar in spirit to how `device_monitor.py` polls for a mount today; iOS has no equivalent background-attach API for third-party apps, so the user must explicitly open the document picker to connect the device each time rather than getting the Mac app's automatic "device just got plugged in" dialog. This is a real UX regression specific to iOS, not a limitation of the concept.
- No cloud, no authentication, no Bluetooth reverse-engineering — this sidesteps essentially every hard problem raised in the cloud/mobile analysis's "upfront decisions" section, because sync stays entirely local and device-initiated, exactly like the desktop app today.

**Key tradeoffs:**
- Substantial engineering project — two native codebases, or one cross-platform app with platform-specific USB/file-provider glue — comparable in scope to cloud Option A's "web/mobile UI is ground-up new work," but without Option A's authentication/infrastructure burden.
- iOS's lack of background USB-attach detection means sync is always user-initiated there (open app, tap "connect device"), never automatic like the desktop app's polling.
- Needs the right cable/adapter on the phone side: USB-C-to-USB-C for USB-C iPhones and most modern Android phones, or the Lightning Camera Adapter for older iPhones — no new adapter needed for the OpenSwim Pro's own cable, since it already terminates in a standard USB connector today.
- Doesn't preclude a future cloud layer — compatible with the local-first Option D/E paths in the cloud/mobile analysis; a Mac becomes optional rather than required, which is the actual goal here.

**Estimated scope:** High — a full mobile port of the podcast/flow/playlist/sync feature set, in a new language/platform, is comparable to building the desktop app's core and UI a second time. Meaningfully smaller than cloud Option A, though, since there's no backend, no auth, and no multi-device conflict resolution to design.

**Prerequisites:** A USB-C-to-USB-C cable (most Android phones, iPhone 15+) or a Lightning-to-USB 3 Camera Adapter (older iPhones) to connect the OpenSwim Pro's existing cable to the phone — no new hardware dependency beyond what's already used with the Mac.

---

## Deferred to v2

Items from the original requirements document deferred out of v1 scope:

- **Compiled `.app` / `.exe` distribution** — code-signed, distributable app bundle (currently run from source via Python)
- **Launch at login / menu bar presence** — background daemon with menu bar icon
- **iCloud profile sync** — sync profiles across multiple Macs automatically
- **Smart playlists** — rule-based playlists (e.g. "unlistened episodes under 30 minutes")
- **Audiobook support** — chapter-aware handling for audiobooks
- **Automatic episode marking** — treat a file deleted from the device as "listened"
