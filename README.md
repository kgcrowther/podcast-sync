# SwimSync

SwimSync is a macOS desktop application that keeps your Shokz OpenSwim device loaded with the podcasts you want to hear — automatically. When you plug in your device, SwimSync compares what is on it against your configured flows and playlist, removes anything that no longer belongs, and downloads and copies everything that should be there.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Running SwimSync](#running-swimsync)
- [Using SwimSync](#using-swimsync)
  - [Podcasts](#podcasts)
  - [Flows](#flows)
  - [Playlist](#playlist)
  - [Devices](#devices)
  - [Profiles](#profiles)
  - [Log](#log)
  - [Syncing your device](#syncing-your-device)
- [Data & file locations](#data--file-locations)
- [Running the tests](#running-the-tests)
- [Troubleshooting](#troubleshooting)

---

## Features

- **Automatic sync on plug-in** — mount a supported Shokz device and a sync dialog opens immediately.
- **Flows** — rule-based rules that keep the N most recent episodes (or all episodes from the last X days) on your device, updated automatically at every sync.
- **Playlist** — a manually curated, ordered list of specific episodes or local audio files.
- **Podcast search** — find podcasts by name or keyword using the Apple Podcasts / iTunes Search API, or paste any RSS feed URL directly.
- **Multiple profiles** — each household member maintains an independent library, flow configuration, and device setup. Profiles are exportable as a single `.swimsync` file and importable on any Mac running SwimSync.
- **Storage-aware** — if your desired content would exceed 90 % of the device's capacity, SwimSync warns you before touching the device.
- **Activity log** — every sync, download, deletion, and error is recorded and browsable inside the app.

---

## Requirements

| Requirement | Minimum |
|---|---|
| macOS | Monterey (12.0) or later |
| Python | 3.12 or later |
| Disk space | ~50 MB for the app + space for downloaded episodes |
| Shokz device | OpenSwim (legacy) or OpenSwim Pro (S710) |

> **No Shokz device required to install or explore the app.** The sync dialog only appears when a supported device is physically connected.

---

## Installation

All steps are performed in **Terminal** (`/Applications/Utilities/Terminal.app`).

### Step 1 — Verify Python 3.12

Open Terminal and run:

```bash
python3 --version
```

You need `Python 3.12.x` or later. If your output shows an older version (e.g. `Python 3.9.x`) or `command not found`, install Python from the official installer at [python.org/downloads](https://www.python.org/downloads/). Download the macOS universal installer, open the `.pkg` file, and follow the prompts. When the installer finishes, open a new Terminal window and re-run `python3 --version` to confirm.

### Step 2 — Download SwimSync

If you have Git installed:

```bash
git clone https://github.com/your-username/podcast-sync.git
cd podcast-sync
```

If you do not have Git, click **Code → Download ZIP** on the GitHub page, double-click the downloaded `.zip` to expand it, then in Terminal:

```bash
cd ~/Downloads/podcast-sync-main
```

> Adjust the path above if macOS expanded the ZIP to a different folder name.

### Step 3 — Create a virtual environment

A virtual environment keeps SwimSync's dependencies isolated from the rest of your Mac.

```bash
python3 -m venv venv
```

Activate it:

```bash
source venv/bin/activate
```

Your Terminal prompt will change to show `(venv)` at the start — this is expected and confirms the environment is active.

### Step 4 — Install dependencies

```bash
pip install -r requirements.txt
```

This installs PyQt6, feedparser, requests, psutil, and the other libraries SwimSync needs. It takes about 30–60 seconds on a typical broadband connection. You will see a series of `Successfully installed …` lines when it finishes.

> You only need to run this once. On future sessions, activating the virtual environment (`source venv/bin/activate`) is sufficient.

---

## Running SwimSync

Every time you want to launch the app:

1. Open Terminal.
2. Navigate to the SwimSync folder:
   ```bash
   cd ~/Downloads/podcast-sync
   ```
   (Replace the path with wherever you placed the folder.)
3. Activate the virtual environment:
   ```bash
   source venv/bin/activate
   ```
4. Launch the app:
   ```bash
   python -m swimsync
   ```

The SwimSync window will open. You can leave the Terminal window in the background — closing it will also close SwimSync.

---

## Using SwimSync

SwimSync has a left sidebar with six sections. Click any section name to switch to it.

---

### Podcasts

The **Podcasts** section shows all the podcasts you are currently following as a scrollable list of tiles.

**Following a podcast**

Click **+ Follow Podcast** in the top-right corner. A dialog opens with two tabs:

- **Search tab** — type a podcast name or keyword and press Return (or click **Search**). Results appear as a list. Click **Details** on any result to expand an inline panel showing the artwork, full description, episode count, and most recent episode title. Click **Follow** inside the expanded panel, or select a result row and click **Follow Selected** at the bottom of the dialog.
- **RSS URL tab** — paste a direct RSS feed URL and click **Validate**. SwimSync fetches the feed and displays the podcast title, episode count, and most recent episode title as confirmation. Click **Follow** to add it.

Following a podcast does not add anything to your device. It makes the podcast available for use in Flows and the Playlist.

**Browsing episodes**

Click **View Episodes** on any tile to open the episode browser. The browser shows the podcast's description and artwork followed by the 10 most recent episodes. Use **Show 10 more** or **Show 50 more** at the bottom to load additional episodes.

Each episode row shows the title, publish date, duration, and file size. Two buttons appear on each row:

- **▶ Preview** — opens the episode in your Mac's default audio player (e.g. QuickTime) so you can sample it before adding it.
- **+ Add to Playlist** — adds this specific episode to your Playlist. The button changes to **In Playlist** if the episode is already there.

Click **← Back** at the top to return to the Podcasts list.

**Indicators on tiles**

- A **red dot** ( ● ) means no new episode has been published in 45 or more days. The feed is still reachable; the podcast is just inactive.
- A **warning icon** means the RSS feed could not be reached the last time SwimSync tried. This will be retried at the next sync.

**Unfollowing a podcast**

Right-click any tile and choose **Unfollow**. If the podcast has a flow or episodes in your Playlist, SwimSync warns you that those will also be removed. Confirm to proceed.

---

### Flows

A **flow** is a rule that automatically determines which episodes from a followed podcast should be on your device. Flows are re-evaluated at every sync using fresh RSS data, so your device stays current without any manual effort.

**Adding a flow**

Click **+ Add Flow**. A picker shows all your followed podcasts that do not already have a flow. Select one. In the configuration panel you can set:

- **Most recent N episodes** — keep the N most recently published episodes (default: 3).
- **Last X days** — keep all episodes published within the past X days.

Both settings can be active at the same time. SwimSync uses the union — any episode matching either rule is included.

Click **Save** to create the flow. The flow appears in the list with a summary of its rule.

**Editing or deleting a flow**

Click any flow row to open its configuration panel. Change the settings and click **Save**, or click **Delete Flow** to remove it.

**Indicators**

- A **red dot** on a flow row means the associated podcast has not published a new episode in 45 or more days.
- A **warning icon** means the RSS feed was unreachable at the last sync.

---

### Playlist

The **Playlist** is a manually curated, ordered list of specific episodes or local audio files you want on your device. Unlike flows, the playlist gives you exact control over which files are present.

**Adding episodes from the episode browser**

Browse to a podcast's episodes (Podcasts → View Episodes) and click **+ Add to Playlist** on any episode row. The episode is appended to the bottom of your playlist.

**Adding a local audio file**

In the Playlist section, click **+ Add File** to open a file picker, or drag any supported audio file from Finder and drop it onto the playlist. Supported formats are MP3, FLAC, WMA, WAV, AAC, and M4A. If you drop a file type that your configured device does not support, SwimSync shows a warning.

**Reordering items**

Drag any item in the list up or down to reorder it. The order here is the order files will appear in the device's root directory.

**Previewing an item**

Click **▶ Preview** on any item to open it in your Mac's default audio player.

**Removing an item**

Click **Remove from Playlist** on the item you want to remove. Removed items will be deleted from your device at the next sync.

The total size of all playlist items is shown at the bottom of the list.

---

### Devices

The **Devices** section lists the drive labels that trigger a sync when a matching USB volume is mounted. Two devices are configured by default:

| Drive Label | Device |
|---|---|
| `SWIM PRO` | Shokz OpenSwim Pro (S710) |
| `OpenSwim` | Shokz OpenSwim (legacy) |

When you plug in your Shokz device, macOS mounts it with one of these labels. SwimSync's background monitor detects the mount and opens the sync dialog automatically.

**Adding a custom device**

Click **+ Add Device**. Enter the exact drive label (this is the volume name that appears in Finder when you plug in the device) and select the file types the device supports. Click **Save**.

**Editing or removing a device**

Click the edit icon on any device row to change its label or supported file types. Click the delete icon to remove it. You cannot delete the last remaining device.

> **Finding your device's drive label:** Plug in the device and look in the Finder sidebar under **Locations**. The name shown there (e.g. `SWIM PRO`) is the drive label.

---

### Profiles

A **profile** bundles your followed podcasts, flows, playlist, and device configuration together under a single name. Multiple profiles let different people on the same Mac maintain completely independent setups.

**Creating a profile**

Click **+ New Profile**, enter a name, and click **Create**. The new profile starts empty.

**Switching profiles**

Each profile is listed with its name. Click **Switch to** next to any profile to make it active. All views immediately update to show that profile's content.

**Exporting a profile**

With your profile active, click **Export Profile**. Choose a save location. SwimSync saves a `.swimsync` file containing your followed podcasts, flows, playlist, and device configuration. This file does not contain downloaded audio files or logs.

**Importing a profile**

Click **Import Profile** and select a `.swimsync` file. If a profile with the same name already exists, SwimSync asks whether you want to overwrite it.

**Deleting a profile**

Click **Delete** next to any profile that is not the currently active one. You cannot delete the last remaining profile.

---

### Log

The **Log** section shows a scrollable, timestamped record of everything SwimSync has done: device connections, downloads, file copies and deletions, RSS feed errors, storage warnings, and sync completions.

**Filter buttons**

- **All** — shows every log line (default).
- **Errors** — shows only WARNING, ERROR, and CRITICAL lines.
- **Sync Events** — shows only lines related to device activity, downloads, and sync operations.

**Refresh**

Click **Refresh** to reload the log from disk and display any entries that were added since you last opened the Log section.

**Open Log File**

Click **Open Log File** to reveal the log file in Finder. The file is a plain text file at:

```
~/Library/Application Support/SwimSync/logs/swimsync.log
```

This file is never automatically deleted, so you can keep a long-running history or share it when reporting issues.

---

### Syncing your device

1. Make sure your Shokz device is charged.
2. Connect it to your Mac using its USB cable.
3. macOS will mount it as a USB drive. Within a few seconds, SwimSync detects the mount and the **Sync Dialog** opens automatically.

**Inside the Sync Dialog:**

1. The dialog shows the device name and its reported storage capacity.
2. A **profile selector** is pre-populated with your currently active profile. You can switch profiles here if needed.
3. Click **Analyze** to begin. SwimSync fetches the latest episodes for all your flows and computes the desired state of the device.
4. A **preview** appears showing:
   - How many files will be added and their total size.
   - How many files will be removed.
   - The resulting used space on the device after sync.
5. If the desired content would exceed 90 % of the device's capacity, a storage warning appears and the **Sync** button is disabled. Remove items from your Playlist or reduce flow episode counts and click **Analyze** again.
6. Click **Sync** to proceed. SwimSync deletes stale files, downloads new episodes, and copies them to the device.
7. A completion message confirms the sync is finished. Click **Close**.

**If you unplug the device during sync:**

SwimSync detects the disconnection immediately, cancels any in-progress download, and shows an interrupted state with the timestamp of the last completed action. Partial files on the device will be detected by byte-size mismatch at the next sync and re-written automatically.

---

## Data & file locations

| Purpose | Location |
|---|---|
| Profile data | `~/Library/Application Support/SwimSync/profiles/` |
| Temporary downloads | `~/Library/Application Support/SwimSync/downloads/` |
| Log file | `~/Library/Application Support/SwimSync/logs/swimsync.log` |

SwimSync creates these directories automatically on first launch. Temporary downloads are deleted after a successful sync. They are intentionally kept if a sync is interrupted, so they can be reused on the next attempt.

---

## Running the tests

SwimSync has 915 automated tests covering all core logic and UI behaviour. To run them:

```bash
# Make sure your virtual environment is active
source venv/bin/activate

# Run the full suite
python -m pytest

# Run with verbose output
python -m pytest -v

# Run a single file
python -m pytest tests/test_downloader.py -v

# Skip tests that require a real internet connection
python -m pytest -m "not network"
```

---

## Troubleshooting

**The sync dialog does not open when I plug in my device.**

- Check the **Devices** section. The drive label listed there must exactly match the volume name macOS assigns to your device. Open Finder and look under **Locations** in the sidebar — the name shown is the label SwimSync needs to see.
- Make sure SwimSync is running before you plug in the device. The background monitor starts when the app opens.

**I get a 403 Forbidden error when downloading an episode.**

This should be handled automatically — SwimSync sends a `User-Agent` header that podcast hosts recognise. If you see this error, the episode URL may have changed or the feed may require authentication. Try refreshing the podcast's feed by viewing its episodes and then re-syncing.

**I get a "command not found" error when running `python -m swimsync`.**

Your virtual environment is probably not active. Run `source venv/bin/activate` from inside the `podcast-sync` folder and try again.

**SwimSync opens but the window is blank or shows placeholder text.**

This is normal on first launch — the app creates a default profile and loads each view. If a section still shows placeholder text after a few seconds, try quitting and restarting.

**My followed podcasts show a warning indicator.**

The RSS feed for that podcast could not be reached. This can happen when a podcast host is temporarily unavailable. SwimSync will retry at the next sync. The warning does not affect other podcasts or your ability to sync the rest of your library.

**I want to start fresh / reset the app.**

Delete the SwimSync data directory:

```bash
rm -rf ~/Library/Application\ Support/SwimSync
```

The next launch will recreate it with a fresh default profile. This also clears your log history.

**Running on Apple Silicon (M1/M2/M3/M4)?**

The Python installer from [python.org](https://www.python.org/downloads/) ships a universal binary that runs natively on Apple Silicon. PyQt6 6.7.1 (the version pinned in `requirements.txt`) supports Monterey and later on both Intel and Apple Silicon Macs. No Rosetta is required.
