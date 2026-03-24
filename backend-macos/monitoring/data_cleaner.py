"""
data_cleaner.py
7-day / 1-day data retention cleanup service — macOS backend.

Retention policy:
  - Synced records  → deleted from device after 1 day.
  - Unsynced records → deleted from device after 7 days.
  - Physical .png / .mp4 files are removed from disk during cleanup.

Identical behaviour to the Windows backend; delegates all logic to db_manager.
"""

import threading
import time
import logging

logger = logging.getLogger(__name__)

SYNCED_RETENTION_DAYS   = 1   # records already on the server
UNSYNCED_RETENTION_DAYS = 7   # records not yet synced
CLEANUP_INTERVAL_SECONDS = 3600  # run once per hour


class CleanupService:
    def __init__(self, db_manager,
                 synced_days: int = SYNCED_RETENTION_DAYS,
                 unsynced_days: int = UNSYNCED_RETENTION_DAYS):
        self.db_manager    = db_manager
        self.synced_days   = synced_days
        self.unsynced_days = unsynced_days
        self.is_running    = False
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="CleanupService",
        )
        self.thread.start()
        logger.info(
            "CleanupService started (synced: %dd, unsynced: %dd)",
            self.synced_days, self.unsynced_days,
        )

    def stop(self) -> None:
        self.is_running = False
        logger.info("CleanupService stopped")

    def _cleanup_loop(self) -> None:
        while self.is_running:
            try:
                self._run_cleanup()
            except Exception as e:
                logger.error("Cleanup error: %s", e)
            for _ in range(CLEANUP_INTERVAL_SECONDS):
                if not self.is_running:
                    return
                time.sleep(1)

    def _run_cleanup(self) -> None:
        logger.info("Running scheduled data cleanup...")
        try:
            self.db_manager.cleanup_old_data(
                synced_days=self.synced_days,
                unsynced_days=self.unsynced_days,
            )
        except Exception as e:
            logger.error("Failed to run data cleanup: %s", e)
