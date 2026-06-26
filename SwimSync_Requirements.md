# SwimSync — Software Requirements Document
**Version:** 1.0  
**Date:** June 2026  
**Platform:** macOS (Monterey and later)  
**Language:** Python 3.12+

---

## 1. Overview

SwimSync is a macOS desktop application that manages podcast subscriptions and audio file synchronization to Shokz OpenSwim MP3 swimming devices. When a supported device is mounted as a drive, SwimSync automatically compares the device's current contents against the user's desired state (defined by flows and playlists) and performs the minimal set of additions and deletions required to bring the device into alignment.

SwimSync supports multiple user profiles on a single Mac, allowing different household members to maintain independent podcast libraries and device configurations.

---

## 2. Goals & Non-Goals

### Goals
- Allow users to follow podcasts via Apple Podcast directory search or RSS URL
- Configure flows (automatic rules) and playlists (manual curation) to define desired device state
- Automatically detect mounted Shokz devices and sync to the desired state
- Support multiple user profiles on one machine
- Allow profiles to be exported and imported across multiple Macs
- Maintain a persistent log of all app activity

### Non-Goals (v1)
- Playback position tracking or "resume where you left off" functionality
- Automatic background episode checking (only checks on app open or at sync time)
- Compiling to a distributable .app package (deferred to v2)
- Syncing to non-Shokz devices (configurable but not the primary focus)

---

## 3. Supported Devices

### Default Device Triggers
SwimSync monitors for the following drive names when any USB volume is mounted:

| Drive Label | Device | Supported File Types |
|---|---|---|
| `SWIM PRO` | Shokz OpenSwim Pro (S710) | MP3, FLAC, WMA, WAV, AAC, M4A, APE* |
| `OpenSwim` | Shokz OpenSwim (legacy) | MP3, WMA, FLAC, WAV, AAC |

*APE: OpenSwim Pro supports up to 16-bit depth, Fast/Normal format only.

### Custom Device Configuration
Users may add custom device profiles in Settings. Each custom device profile includes:
- Drive label (selected from a dropdown of previously seen drives, or typed manually)
- Supported file types (multi-select from the full list: MP3, FLAC, WMA, WAV, AAC, M4A, APE)

### File Type Warning
If a user attempts to add a file to a playlist whose type is outside the supported list for any known device, the app displays a warning:
> "This file type might not be supported or has limitations — please check the device's manual for details."

---

## 4. User Profiles

### Profile Structure
Each profile contains:
- Profile name
- Followed podcasts (list of RSS feed URLs + metadata)
- Configured flows (per podcast)
- Playlist (ordered list of specific episodes and audio files)
- Device trigger settings (which drive labels trigger sync for this profile)

### Profile Selection at Sync
When a supported device is detected:
1. The app displays a profile selection dialog, pre-selecting the most recently used profile
2. The user may confirm or change the profile
3. The user clicks **Sync** to begin synchronization

### Profile Export & Import
- Profiles can be exported as a single `.swimsync` file (JSON format internally)
- Exported profiles include: followed podcasts, flows, playlist, device trigger settings, and profile name
- Exported profiles do NOT include: downloaded audio files or logs
- Any SwimSync installation can import a `.swimsync` file via File → Import Profile
- This is the supported method for moving a profile to another Mac

---

## 5. Podcast Management

### Following Podcasts
Users can follow podcasts by:
1. **Search:** Searching the Apple Podcasts / iTunes Search API by name or keyword
2. **RSS URL:** Pasting a direct RSS feed URL, with the app validating the feed and displaying episode count and most recent episode title as confirmation

Following a podcast does NOT automatically add it to any flow or playlist. It only makes it available for those purposes.

### Unfollowing Podcasts
Users may unfollow a podcast at any time. If the podcast has an active flow or episodes in the playlist, the app warns the user before removing it. Unfollowing a podcast will automatically remove any flows associated with that podcast and any episodes associated with that podcast in the playlist.

### Episode Browsing
When viewing a followed podcast:
- Show the general podcast authors and description followed by some of the most recent episodes
- Default view: most recent 20 episodes
- **"Show 10 more"** button: loads 10 additional episodes
- **"Show 50 more"** button: loads 50 additional episodes
- Each episode shows: title, publish date, duration, and file size (if known)

### Stale Feed Detection
If a podcast has not published a new episode in over 45 days:
- It is marked with a red indicator in the Podcasts list view
- It is marked with a red indicator on any associated flow
- This is checked when the app is opened and when a sync is performed

### Feed Unavailability
If an RSS feed cannot be reached:
- A notice is shown on the podcast in the Podcasts list
- A notice is shown on any associated flow
- The event is written to the app log
- The app silently skips that podcast and continues

### Episode Refresh
New episodes are fetched from RSS feeds:
- When the user opens the episode browser for a podcast
- When a sync is about to be performed (to ensure flows use the latest episodes)
- NOT on a background schedule

---

## 6. Flows

A flow is a rule applied to a followed podcast that automatically determines which episodes should be on the device.

### Flow Configuration (per podcast)
| Setting | Default | Description |
|---|---|---|
| Most recent N episodes | 3 | Keep the N most recently published episodes |
| Last X days | Off | Keep all episodes published within X days |

Both settings may be active simultaneously; the union of matching episodes is used.

### Flow Behavior
- Flows are evaluated fresh at each sync using the latest RSS feed data
- Episodes included by a flow but not currently on the device are downloaded and added
- Episodes previously added by a flow that no longer match the flow criteria are automatically deleted from the device
- If no episodes match (e.g. all episodes are older than X days), the device will have zero episodes for that podcast from the flow

### Flow Priority
In the event of a storage conflict (approaching 90% capacity), playlist items take priority over flow items. Among flow items, more recent episodes take priority over older ones.

---

## 7. Playlist

The playlist is a manually curated, ordered list of specific episodes and audio files the user wants on the device.

### Adding Items
- From the episode browser: A **▶ Preview** button (plays the file in the system default audio player); A **+ Add to Playlist** button will add the episode to the playlist
- From the filesystem: drag and drop any supported audio file into the playlist; the system will store the file location instead of the episode location

### Playlist View
Each item in the playlist shows:
- Title
- Source (podcast name or filename)
- Duration
- File size
- A **▶ Preview** button (plays the file in the system default audio player)
- A **Remove from Playlist** button

### Removal Behavior
- Removing an item from the playlist marks it for deletion from the device at next sync
- Items are never silently removed from the playlist; only the user can remove them

---

## 8. Desired State & Sync Logic

### Desired State Definition
At sync time, the desired state of the device is computed as:
```
Desired State = Playlist items + Flow items (after conflict resolution)
```
Anything on the device that is NOT in the desired state is deleted. Nothing is ever left on the device that isn't explicitly in the desired state.

### File Comparison Method
SwimSync compares files using **filename + exact byte size** (`os.path.getsize()`):
- If a file exists on the device with the same filename and exact byte count as the desired file → it is considered current, no action taken
- If the filename matches but byte size differs (e.g. truncated from a previous interrupted sync) → the file is re-downloaded and overwritten
- If the file does not exist on the device → it is downloaded and copied
- If a file exists on the device but is not in the desired state → it is deleted

### Storage Warning
Before executing any sync:
- Calculate total size of all desired state files
- If this would exceed 90% of the device's reported capacity → alert the user with a summary and do not proceed until the user resolves the conflict (by removing items from the playlist or adjusting flows)

### Sync Execution Order
1. Detect mounted device and have user confirm profile
2. Fetch latest RSS data for any podcasts with active flows
3. Compute desired state
4. Check storage threshold — alert and halt if exceeded
5. Compare desired state against current device contents
6. Display sync preview summary to user (files to add, files to remove, total size delta)
7. User confirms or cancels
8. Delete files from device that are no longer in desired state
9. Download new files to temporary local directory (`~/Library/Application Support/SwimSync/downloads/`)
10. Copy new files to device
11. Delete temporary downloaded files
12. Write sync summary to log
13. Display completion notification

### Mid-Sync Disconnection
If the device is unplugged during sync:
- Log the interruption with timestamp and last completed action
- Alert the user that sync was interrupted
- When the device is next mounted, begin a fresh sync analysis from step 2 (any partially written files will be detected by byte size mismatch and re-written)

---

## 9. File Storage & Logging

### Temporary Downloads
- Location: `~/Library/Application Support/SwimSync/downloads/`
- Files are deleted immediately after a successful sync
- Files are NOT deleted if a sync is interrupted (they will be reused or overwritten on the next sync attempt)

### Log File
- Location: `~/Library/Application Support/SwimSync/logs/swimsync.log`
- The log file is never automatically deleted
- Log entries include:
  - Device mount detected (drive label, reported capacity, timestamp)
  - Profile selected
  - Sync analysis summary (files to add, files to remove, sizes)
  - Each file downloaded (filename, size, duration)
  - Each file copied to device (filename)
  - Each file deleted from device (filename)
  - Any RSS feed access failures (feed URL, error)
  - Storage threshold warnings
  - Sync completion (timestamp, total files on device, total size used)
  - Sync interruptions (timestamp, last completed action)

---

## 10. User Interface

### General
- Full window desktop application with a dock icon
- Minimal, utilitarian visual design with subtle swimming/OpenSwim iconography
- Follows macOS system appearance (light mode / dark mode)
- Built with a Python GUI framework (e.g. PyQt6 or Tkinter with ttk)

### Navigation
The app has a left sidebar with the following sections:
- **Podcasts** — browse and manage followed podcasts
- **Flows** — view and configure all active flows
- **Playlist** — view and manage the manual playlist
- **Devices** — configure device triggers and supported file types
- **Profiles** — switch, export, or import profiles
- **Log** — view the activity log within the app

### Podcasts View
- List of followed podcasts with name, artwork thumbnail, and most recent episode date
- Red indicator on podcasts with no new episode in 45+ days
- Warning indicator on podcasts with unreachable RSS feeds
- Search bar at the top to search followed podcasts
- **+ Follow Podcast** button opens a search/add dialog
- Clicking a podcast opens its episode browser

### Episode browser
- Description, author, imagry from the podcast followed by a list of the most recent episodes
- Red indicator at top for podcasts with no new episodes in 45+ days
- Warning indicator on podcasts with unreadable RSS feeds
- List of most recent 10 episodes
- A **▶ Preview** button (plays the file in the system default audio player); 
- A **+ Add to Playlist** button will add the episode to the playlist
- Buttons at the bottom of the list of episodes to show an additional 10 or an additional 50 episodes

### Flows View
- List of all configured flows
- Each flow shows: podcast name, rule summary (e.g. "3 most recent episodes"), red/warning indicators
- **+ Add Flow** button shows followed podcasts without a flow configured
- Clicking a flow opens the flow configuration panel

### Playlist View
- Ordered list of all playlist items
- Each item: title, source, duration, file size, ▶ Preview, Remove from Playlist
- **+ Add File** button for drag-and-drop or file picker
- Total playlist size shown at bottom

### Sync Dialog
Appears when a supported device is mounted:
- Device name and reported capacity
- Profile selector (pre-selects last used profile)
- Sync preview: files to add (count + size), files to remove (count), resulting used space
- Storage warning if approaching 90%
- **Sync** and **Cancel** buttons

### Settings / Devices View
- Table of device trigger configurations (default: SWIM PRO, OpenSwim)
- Each row: drive label, supported file types, edit/delete
- **+ Add Device** button

### Profiles View
- List of profiles on this machine
- **+ New Profile** button
- **Export Profile** button (saves `.swimsync` file)
- **Import Profile** button (loads `.swimsync` file)

### Log View
- Scrollable, timestamped log viewer within the app
- Filter by: All, Errors, Sync Events
- **Open Log File** button to reveal in Finder

---

## 11. Technical Stack (Recommended)

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| GUI Framework | PyQt6 |
| Podcast search | iTunes Search API (free, no key required) |
| RSS parsing | `feedparser` library |
| HTTP downloads | `requests` library |
| File operations | `os`, `shutil` (stdlib) |
| Device detection | `psutil` (monitors mounted volumes) |
| Profile storage | JSON (`.swimsync` files) |
| Logging | Python `logging` module to rotating file |

---

## 12. Out of Scope for v1

- Compiled `.app` distribution (run from source via Python)
- Background daemon / launch-at-login
- Playback position tracking
- Automatic episode refresh on a schedule
- Cloud sync of profiles
- Windows or Linux support

---

## 13. Future Considerations (v2+)

- Compile and sign as a distributable macOS `.app`
- Launch at login with menu bar presence
- iCloud profile sync
- Smart playlists (e.g. "unlistened episodes under 30 minutes")
- Support for audiobooks (with chapter awareness)
- Automatic episode marking when returned from device (file deleted from device = listened)

---

*Document prepared June 2026. To be used as the primary brief for SwimSync v1 development.*
