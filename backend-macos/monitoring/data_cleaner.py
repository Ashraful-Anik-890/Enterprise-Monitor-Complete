"""
data_cleaner.py
Background service to automatically clean up old data.

v5.2.6 — HEARTBEAT TIMER REFACTOR
  Problem: The previous implementation used time.sleep(interval_seconds) inside
  a loop. On machines that restart the backend daily (e.g. via auto-update or
  system reboot), the sleep timer reset to zero each time. Cleanup never ran on
  any machine where the backend uptime was shorter than the 24-hour interval.

  Fix: Persistent timestamp file (.last_cleanup) in the EM data directory.
  A 15-minute heartbeat wakes up and checks how long ago cleanup last ran.
  If elapsed time >= cleanup_interval_hours, it runs. This survives restarts.

  The stop() method responds within 1 second because the heartbeat sleeps
  in 1-second increments rather than one long sleep call.

Retention policy (v5.2.7):
  - Synced records   → deleted after 2 hours (SYNCED_RETENTION_HOURS=2).
    Mac storage is limited; synced data is purged aggressively once on server.
    Orphan files on disk (no DB record) are also swept — see db_manager Step 6.
  - Unsynced records → deleted after 7 days (UNSYNCED_RETENTION_DAYS=7).
  - Physical .jpg / .png / .mp4 files are removed from disk during cleanup.

NOTE: WAL mode is already configured in db_manager.py. No change needed here.
"""

import threading
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SYNCED_RETENTION_HOURS  = 2    # records already on the server
UNSYNCED_RETENTION_DAYS = 7    # records not yet synced

HEARTBEAT_SECONDS   = 300      # wake up every 15 minutes to check
CLEANUP_INTERVAL_H  = 2        # run actual cleanup every 2 hours


class CleanupService:
    def __init__(self, db_manager,
                 interval_hours: int = CLEANUP_INTERVAL_H,
                 synced_hours: int   = SYNCED_RETENTION_HOURS,
                 unsynced_days: int  = UNSYNCED_RETENTION_DAYS):
        """
        :param db_manager:     DatabaseManager instance (must expose .db_dir Path)
        :param interval_hours: Minimum hours between cleanup runs (default 2)
        :param synced_hours:   Hours before synced records are deleted (default 2)
        :param unsynced_days:  Days before unsynced records are deleted (default 7)
        """
        self.db_manager       = db_manager
        self.interval_seconds = interval_hours * 3600
        self.synced_hours     = synced_hours
        self.unsynced_days    = unsynced_days
        self.is_running       = False
        self.thread: Optional[threading.Thread] = None

        # Persistent timestamp file: survives backend restarts.
        # Written in the same directory as the database.
        self._ts_file = Path(db_manager.db_dir) / ".last_cleanup"

    # ─── LIFECYCLE ───────────────────────────────────────────────────────────

    def start(self):
        if self.is_running:
            logger.warning("Cleanup service already running")
            return
        self.is_running = True
        self.thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="CleanupService",
        )
        self.thread.start()
        logger.info(
            "Cleanup service started "
            "(heartbeat=%ds, interval=%dh, synced=%dh, unsynced=%dd)",
            HEARTBEAT_SECONDS,
            self.interval_seconds // 3600,
            self.synced_hours,
            self.unsynced_days,
        )

    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=2)   # responds within 1s due to incremental sleep
        logger.info("Cleanup service stopped")

    # ─── TIMESTAMP PERSISTENCE ───────────────────────────────────────────────

    def _get_last_run(self) -> float:
        """Read last-run epoch from disk. Returns 0.0 if file missing or corrupt."""
        try:
            return float(self._ts_file.read_text(encoding="utf-8").strip())
        except Exception:
            return 0.0

    def _save_last_run(self) -> None:
        """Atomically persist the current time as the last-run timestamp."""
        try:
            tmp = self._ts_file.with_suffix(".tmp")
            tmp.write_text(str(time.time()), encoding="utf-8")
            tmp.replace(self._ts_file)   # atomic on NTFS and POSIX
        except Exception as e:
            logger.warning("CleanupService: could not write timestamp file: %s", e)

    # ─── MAIN LOOP ───────────────────────────────────────────────────────────

    def _cleanup_loop(self):
        """
        Heartbeat loop. Wakes every HEARTBEAT_SECONDS to check whether
        enough time has elapsed since the last cleanup run. Uses 1-second
        incremental sleep so stop() is responsive.
        """
        logger.info("Cleanup heartbeat loop started")

        while self.is_running:
            elapsed = time.time() - self._get_last_run()
            if elapsed >= self.interval_seconds:
                self._run_cleanup()
                self._save_last_run()

            # Sleep in 1-second ticks so stop() takes effect quickly
            for _ in range(HEARTBEAT_SECONDS):
                if not self.is_running:
                    break
                time.sleep(1)

        logger.info("Cleanup heartbeat loop ended")

    # ─── CLEANUP EXECUTION ───────────────────────────────────────────────────

    def _run_cleanup(self):
        """Execute the actual data deletion via db_manager."""
        try:
            logger.info(
                "Running scheduled data cleanup (synced >%dh, unsynced >%dd)…",
                self.synced_hours,
                self.unsynced_days,
            )
            self.db_manager.cleanup_old_data(
                synced_hours=self.synced_hours,
                unsynced_days=self.unsynced_days,
            )
        except Exception as e:
            logger.error("Failed to run data cleanup: %s", e)
