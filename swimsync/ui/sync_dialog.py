"""
SwimSync Sync Dialog.

Shown when a supported device is mounted. Guides the user through:
  1. Profile selection
  2. Feed refresh + sync plan computation (background)
  3. Sync preview (files to add, remove, storage warning)
  4. Sync execution (background, with progress)
  5. Completion or error summary

All network/filesystem operations run on background QThread workers so the
UI remains responsive throughout.

Requirements §8: Sync Execution Order
"""

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from swimsync.core.device_monitor import MountedDevice
from swimsync.core.downloader import cleanup_downloads, download_action
from swimsync.core.profile_manager import list_profiles, load_profile
from swimsync.core.rss_client import fetch_feed
from swimsync.core.sync_engine import compute_sync_plan
from swimsync.models.profile import Episode, Profile
from swimsync.models.sync_plan import SyncPlan
from swimsync.utils.file_utils import safe_copy, safe_delete
from swimsync.utils.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------

class _Phase(Enum):
    READY = auto()        # profile selected, ready to analyze
    ANALYZING = auto()    # fetch + compute running in background
    PREVIEW = auto()      # plan computed, waiting for user confirmation
    SYNCING = auto()      # sync executing in background
    DONE = auto()         # sync finished successfully (or device up to date)
    ERROR = auto()        # analysis or sync failed
    INTERRUPTED = auto()  # device disconnected mid-operation


# Stacked widget page indices
_PAGE_STATUS = 0   # READY / ANALYZING
_PAGE_PREVIEW = 1  # PREVIEW
_PAGE_SYNCING = 2  # SYNCING
_PAGE_RESULT = 3   # DONE / ERROR / INTERRUPTED


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    """Format a byte count as a human-readable string (e.g. '3.2 GB')."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"


def _default_fetch_feeds(profile: Profile) -> dict[str, list[Episode]]:
    """Fetch latest RSS episodes for all podcasts that have active flows."""
    cache: dict[str, list[Episode]] = {}
    for flow in profile.flows:
        rss_url = flow.podcast_rss_url
        if rss_url in cache:
            continue
        result = fetch_feed(rss_url)
        if result.ok:
            cache[rss_url] = result.episodes
        else:
            cache[rss_url] = []
            log.warning(f"Feed unavailable during sync: {rss_url}: {result.error}")
    return cache


def _default_execute_sync(
    plan: SyncPlan,
    on_progress: Callable[[str, int, int], None],
    is_cancelled: Callable[[], bool],
) -> tuple[bool, str]:
    """
    Execute a sync plan: delete stale files, download/copy new files, clean up.

    Args:
        plan: The sync plan to execute.
        on_progress: Called with (message, done, total) after each step.
        is_cancelled: Returns True if the user requested cancellation.

    Returns:
        (True, success_message) or (False, error_message).
    """
    device_root = Path(plan.device_path)
    adds = plan.to_add + plan.to_redownload
    total = len(plan.to_delete) + len(adds)
    done = 0

    # Step 1: delete stale files from device
    for filename in plan.to_delete:
        if is_cancelled():
            return False, "Sync cancelled."
        on_progress(f"Removing: {filename}", done, total)
        safe_delete(device_root / filename)
        done += 1
        on_progress(f"Removed: {filename}", done, total)
        log.info(f"Deleted from device: {filename}")

    # Step 2: download and copy new files
    for action in adds:
        if is_cancelled():
            return False, "Sync cancelled."
        on_progress(f"Downloading: {action.title}", done, total)
        result = download_action(action)
        if not result.ok:
            return False, f"Download failed for '{action.title}': {result.error}"
        if result.local_path:
            dest = device_root / action.filename
            on_progress(f"Copying: {action.filename}", done, total)
            if not safe_copy(result.local_path, dest):
                return False, f"Failed to copy '{action.filename}' to device."
            log.info(f"Copied to device: {action.filename}")
        done += 1
        on_progress(f"Copied: {action.filename}", done, total)

    # Step 3: clean up local downloads directory
    cleanup_downloads()

    files_synced = len(plan.to_delete) + len(adds)
    noun = "file" if files_synced == 1 else "files"
    msg = f"Sync complete — {files_synced} {noun} synced."
    log.info(f"Sync complete on '{plan.device_label}': {plan.summary()}")
    return True, msg


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _FetchWorker(QThread):
    """Fetches RSS feeds and computes the sync plan on a background thread."""

    plan_ready = pyqtSignal(object)  # SyncPlan
    error = pyqtSignal(str)

    def __init__(
        self,
        profile: Profile,
        device: MountedDevice,
        fetch_feeds_fn: Callable[[Profile], dict[str, list[Episode]]],
        compute_plan_fn: Callable,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._profile = profile
        self._device = device
        self._fetch_feeds_fn = fetch_feeds_fn
        self._compute_plan_fn = compute_plan_fn

    def run(self) -> None:
        try:
            episode_cache = self._fetch_feeds_fn(self._profile)
            plan = self._compute_plan_fn(
                self._profile,
                self._device.mount_point,
                self._device.drive_label,
                episode_cache,
            )
            self.plan_ready.emit(plan)
        except Exception as exc:
            log.error(f"Sync analysis error: {exc}")
            self.error.emit(str(exc))


class _SyncWorker(QThread):
    """Executes a sync plan on a background thread."""

    progress = pyqtSignal(str, int, int)  # message, done, total
    finished = pyqtSignal(bool, str)      # success, message

    def __init__(
        self,
        plan: SyncPlan,
        execute_fn: Callable,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._plan = plan
        self._execute_fn = execute_fn
        self._cancelled = False

    def cancel(self) -> None:
        """Signal the worker to stop after the current action finishes."""
        self._cancelled = True

    def run(self) -> None:
        def on_progress(msg: str, done: int, total: int) -> None:
            self.progress.emit(msg, done, total)

        def is_cancelled() -> bool:
            return self._cancelled

        ok, msg = self._execute_fn(self._plan, on_progress, is_cancelled)
        self.finished.emit(ok, msg)


# ---------------------------------------------------------------------------
# Sync dialog
# ---------------------------------------------------------------------------

class SyncDialog(QDialog):
    """
    Multi-phase dialog that guides the user through a device sync.

    Each argument ending in ``_fn`` is an injectable seam defaulting to the
    real implementation. Pass mocks in tests to avoid network/filesystem access.

    Phases: READY → ANALYZING → PREVIEW → SYNCING → DONE/ERROR/INTERRUPTED
    """

    sync_completed = pyqtSignal()  # emitted on successful sync

    def __init__(
        self,
        device: MountedDevice,
        active_profile: Profile,
        list_profiles_fn: Callable[[], list[str]] = list_profiles,
        load_profile_fn: Callable[[str], Optional[Profile]] = load_profile,
        fetch_feeds_fn: Callable[[Profile], dict[str, list[Episode]]] = _default_fetch_feeds,
        compute_plan_fn: Callable = compute_sync_plan,
        execute_sync_fn: Callable = _default_execute_sync,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._device = device
        self._profile = active_profile
        self._list_profiles_fn = list_profiles_fn
        self._load_profile_fn = load_profile_fn
        self._fetch_feeds_fn = fetch_feeds_fn
        self._compute_plan_fn = compute_plan_fn
        self._execute_sync_fn = execute_sync_fn

        self._plan: Optional[SyncPlan] = None
        self._fetch_worker: Optional[_FetchWorker] = None
        self._sync_worker: Optional[_SyncWorker] = None
        self._phase = _Phase.READY

        self.setWindowTitle("Sync Device")
        self.setMinimumWidth(460)
        self.setModal(True)

        self._build_ui()
        self._set_phase(_Phase.READY)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(12)
        outer.setContentsMargins(20, 20, 20, 20)

        # Device info
        self._device_label = QLabel(
            f"<b>{self._device.drive_label}</b>  —  "
            f"{_fmt_bytes(self._device.capacity_bytes)} capacity, "
            f"{_fmt_bytes(self._device.used_bytes)} used"
        )
        self._device_label.setObjectName("sync_device_label")
        outer.addWidget(self._device_label)

        # Profile selector
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self._profile_combo = QComboBox()
        self._profile_combo.setObjectName("sync_profile_combo")
        profiles = self._list_profiles_fn()
        for name in profiles:
            self._profile_combo.addItem(name)
        if self._profile.name in profiles:
            self._profile_combo.setCurrentText(self._profile.name)
        else:
            # Active profile not in stored list — insert it at the top
            self._profile_combo.insertItem(0, self._profile.name)
            self._profile_combo.setCurrentIndex(0)
        profile_row.addWidget(self._profile_combo, stretch=1)
        outer.addLayout(profile_row)

        # Variable content area
        self._stack = QStackedWidget()
        self._stack.setObjectName("sync_stack")
        self._stack.addWidget(self._make_status_page())
        self._stack.addWidget(self._make_preview_page())
        self._stack.addWidget(self._make_syncing_page())
        self._stack.addWidget(self._make_result_page())
        outer.addWidget(self._stack)

        # Button row — built BEFORE connecting signals that reference these buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._secondary_btn = QPushButton("Cancel")
        self._secondary_btn.setObjectName("sync_secondary_btn")
        self._secondary_btn.clicked.connect(self._on_secondary_clicked)
        btn_row.addWidget(self._secondary_btn)

        self._primary_btn = QPushButton("Analyze")
        self._primary_btn.setObjectName("sync_primary_btn")
        self._primary_btn.setDefault(True)
        self._primary_btn.clicked.connect(self._on_primary_clicked)
        btn_row.addWidget(self._primary_btn)

        outer.addLayout(btn_row)

        # Connect profile combo after all widgets exist
        self._profile_combo.currentTextChanged.connect(self._on_profile_changed)

    def _make_status_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("sync_status_page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 8, 0, 8)
        self._status_label = QLabel("Click Analyze to check what needs to sync.")
        self._status_label.setObjectName("sync_status_label")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._status_label)
        return page

    def _make_preview_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("sync_preview_page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(4)

        self._preview_add_label = QLabel()
        self._preview_add_label.setObjectName("sync_preview_add")
        lay.addWidget(self._preview_add_label)

        self._preview_redownload_label = QLabel()
        self._preview_redownload_label.setObjectName("sync_preview_redownload")
        lay.addWidget(self._preview_redownload_label)

        self._preview_remove_label = QLabel()
        self._preview_remove_label.setObjectName("sync_preview_remove")
        lay.addWidget(self._preview_remove_label)

        self._preview_space_label = QLabel()
        self._preview_space_label.setObjectName("sync_preview_space")
        lay.addWidget(self._preview_space_label)

        self._storage_warning_label = QLabel()
        self._storage_warning_label.setObjectName("sync_storage_warning")
        self._storage_warning_label.setWordWrap(True)
        self._storage_warning_label.setVisible(False)
        lay.addWidget(self._storage_warning_label)

        return page

    def _make_syncing_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("sync_syncing_page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(8)

        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("sync_progress_bar")
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(0)
        self._progress_bar.setValue(0)
        lay.addWidget(self._progress_bar)

        self._progress_label = QLabel("Preparing…")
        self._progress_label.setObjectName("sync_progress_label")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._progress_label)

        return page

    def _make_result_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("sync_result_page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 8, 0, 8)
        self._result_label = QLabel()
        self._result_label.setObjectName("sync_result_label")
        self._result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_label.setWordWrap(True)
        lay.addWidget(self._result_label)
        return page

    # ------------------------------------------------------------------
    # Phase management
    # ------------------------------------------------------------------

    def _set_phase(self, phase: _Phase) -> None:
        self._phase = phase

        # Stack page
        if phase in (_Phase.READY, _Phase.ANALYZING):
            self._stack.setCurrentIndex(_PAGE_STATUS)
            self._status_label.setText(
                "Click Analyze to check what needs to sync."
                if phase == _Phase.READY
                else "Analyzing…"
            )
        elif phase == _Phase.PREVIEW:
            self._stack.setCurrentIndex(_PAGE_PREVIEW)
        elif phase == _Phase.SYNCING:
            self._stack.setCurrentIndex(_PAGE_SYNCING)
        else:  # DONE, ERROR, INTERRUPTED
            self._stack.setCurrentIndex(_PAGE_RESULT)

        # Profile combo: only editable when idle
        self._profile_combo.setEnabled(phase == _Phase.READY)

        # Primary button
        if phase == _Phase.READY:
            self._primary_btn.setVisible(True)
            self._primary_btn.setEnabled(True)
            self._primary_btn.setText("Analyze")
        elif phase == _Phase.ANALYZING:
            self._primary_btn.setVisible(True)
            self._primary_btn.setEnabled(False)
            self._primary_btn.setText("Analyzing…")
        elif phase == _Phase.PREVIEW:
            self._primary_btn.setVisible(True)
            self._primary_btn.setText("Sync")
            self._primary_btn.setEnabled(
                self._plan is None or not self._plan.storage_warning
            )
        else:  # SYNCING, DONE, ERROR, INTERRUPTED
            self._primary_btn.setVisible(False)

        # Secondary button (Cancel / Stop / Close)
        if phase == _Phase.SYNCING:
            self._secondary_btn.setText("Stop")
        elif phase in (_Phase.DONE, _Phase.ERROR, _Phase.INTERRUPTED):
            self._secondary_btn.setText("Close")
        else:
            self._secondary_btn.setText("Cancel")
        self._secondary_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def phase(self) -> _Phase:
        return self._phase

    def notify_device_disconnected(self, label: str) -> None:
        """
        Called by main_window when a USB volume disconnects.

        If the label matches this dialog's device and the dialog is not
        already in a terminal phase (DONE/ERROR/INTERRUPTED), cancels any
        running worker and transitions to INTERRUPTED.
        """
        if label != self._device.drive_label:
            return
        if self._phase in (_Phase.DONE, _Phase.ERROR, _Phase.INTERRUPTED):
            return
        if self._sync_worker and self._sync_worker.isRunning():
            self._sync_worker.cancel()
        if self._fetch_worker and self._fetch_worker.isRunning():
            self._fetch_worker.terminate()
        suffix = " Sync was interrupted." if self._phase == _Phase.SYNCING else ""
        self._result_label.setText(f"Device '{label}' was disconnected.{suffix}")
        self._set_phase(_Phase.INTERRUPTED)
        log.warning(f"Device '{label}' disconnected during sync dialog")

    # ------------------------------------------------------------------
    # Profile change
    # ------------------------------------------------------------------

    def _on_profile_changed(self, name: str) -> None:
        profile = self._load_profile_fn(name)
        if profile is None:
            return
        self._profile = profile
        # Invalidate any existing analysis when the user switches profile
        if self._phase == _Phase.PREVIEW:
            self._plan = None
            self._set_phase(_Phase.READY)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_primary_clicked(self) -> None:
        if self._phase == _Phase.READY:
            self._start_analyze()
        elif self._phase == _Phase.PREVIEW:
            self._start_sync()

    def _on_secondary_clicked(self) -> None:
        if self._phase == _Phase.SYNCING:
            if self._sync_worker:
                self._sync_worker.cancel()
            # _on_sync_finished will fire from the worker thread when it exits
        elif self._phase in (_Phase.DONE, _Phase.ERROR, _Phase.INTERRUPTED):
            self.accept()
        else:  # READY, ANALYZING, PREVIEW
            self.reject()

    # ------------------------------------------------------------------
    # Analyze phase
    # ------------------------------------------------------------------

    def _start_analyze(self) -> None:
        self._set_phase(_Phase.ANALYZING)
        self._fetch_worker = _FetchWorker(
            profile=self._profile,
            device=self._device,
            fetch_feeds_fn=self._fetch_feeds_fn,
            compute_plan_fn=self._compute_plan_fn,
            parent=self,
        )
        self._fetch_worker.plan_ready.connect(self._on_plan_ready)
        self._fetch_worker.error.connect(self._on_analyze_error)
        self._fetch_worker.start()

    def _on_plan_ready(self, plan: SyncPlan) -> None:
        self._plan = plan

        if plan.is_empty:
            self._result_label.setText(
                "Device is already up to date — no changes needed."
            )
            self._set_phase(_Phase.DONE)
            return

        # Populate preview panel
        add_size = sum(a.file_size_bytes for a in plan.to_add if a.file_size_bytes)
        rdl_size = sum(a.file_size_bytes for a in plan.to_redownload if a.file_size_bytes)

        self._preview_add_label.setText(
            f"Files to add:  {len(plan.to_add)}"
            + (f"  ({_fmt_bytes(add_size)})" if add_size else "")
        )
        self._preview_redownload_label.setText(
            f"Files to re-download:  {len(plan.to_redownload)}"
            + (f"  ({_fmt_bytes(rdl_size)})" if rdl_size else "")
        )
        self._preview_redownload_label.setVisible(bool(plan.to_redownload))
        self._preview_remove_label.setText(
            f"Files to remove:  {len(plan.to_delete)}"
        )

        after_bytes = plan.desired_total_bytes
        cap = plan.device_capacity_bytes
        if cap > 0:
            pct = after_bytes / cap * 100
            self._preview_space_label.setText(
                f"After sync:  {_fmt_bytes(after_bytes)} used  "
                f"({pct:.0f}% of {_fmt_bytes(cap)})"
            )
        else:
            self._preview_space_label.setText(
                f"After sync:  {_fmt_bytes(after_bytes)} used"
            )

        if plan.storage_warning and plan.storage_warning_message:
            self._storage_warning_label.setText(f"⚠ {plan.storage_warning_message}")
            self._storage_warning_label.setVisible(True)
        else:
            self._storage_warning_label.setVisible(False)

        self._set_phase(_Phase.PREVIEW)

    def _on_analyze_error(self, error: str) -> None:
        self._result_label.setText(f"Analysis failed: {error}")
        self._set_phase(_Phase.ERROR)

    # ------------------------------------------------------------------
    # Sync phase
    # ------------------------------------------------------------------

    def _start_sync(self) -> None:
        if self._plan is None:
            return
        self._progress_bar.setMaximum(max(self._plan.total_actions, 1))
        self._progress_bar.setValue(0)
        self._progress_label.setText("Starting sync…")
        self._set_phase(_Phase.SYNCING)

        self._sync_worker = _SyncWorker(
            plan=self._plan,
            execute_fn=self._execute_sync_fn,
            parent=self,
        )
        self._sync_worker.progress.connect(self._on_sync_progress)
        self._sync_worker.finished.connect(self._on_sync_finished)
        self._sync_worker.start()

    def _on_sync_progress(self, message: str, done: int, total: int) -> None:
        self._progress_bar.setMaximum(max(total, 1))
        self._progress_bar.setValue(done)
        self._progress_label.setText(message)

    def _on_sync_finished(self, ok: bool, message: str) -> None:
        self._result_label.setText(message)
        if ok:
            self.sync_completed.emit()
            self._set_phase(_Phase.DONE)
        else:
            self._set_phase(_Phase.ERROR)
        log.info(f"Sync dialog finished: ok={ok} — {message!r}")
