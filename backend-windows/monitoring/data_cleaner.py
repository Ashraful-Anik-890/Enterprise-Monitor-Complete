"""
data_cleaner.py
Background service to automatically clean up old data.

Retention policy:
  - Synced records  → deleted from device after 1 day.
  - Unsynced records → deleted from device after 7 days.
  - Physical .png / .mp4 files are removed from disk during cleanup.
"""

import threading
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SYNCED_RETENTION_DAYS   = 1   # records already on the server
UNSYNCED_RETENTION_DAYS = 7   # records not yet synced


class CleanupService:
    def __init__(self, db_manager, interval_hours: int = 24,
                 synced_days: int = SYNCED_RETENTION_DAYS,
                 unsynced_days: int = UNSYNCED_RETENTION_DAYS):
        """
        :param db_manager:     DatabaseManager instance
        :param interval_hours: How often to run cleanup (default every 24 h)
        :param synced_days:    Days before synced records are deleted (default 1)
        :param unsynced_days:  Days before unsynced records are deleted (default 7)
        """
        self.db_manager       = db_manager
        self.interval_seconds = interval_hours * 3600
        self.synced_days      = synced_days
        self.unsynced_days    = unsynced_days
        self.is_running       = False
        self.thread: Optional[threading.Thread] = None

    def start(self):
        """Start the cleanup service."""
        if self.is_running:
            logger.warning("Cleanup service already running")
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._cleanup_loop, daemon=True,
                                       name="CleanupService")
        self.thread.start()
        logger.info(
            "Cleanup service started (synced: %dd, unsynced: %dd)",
            self.synced_days, self.unsynced_days,
        )

    def stop(self):
        """Stop the cleanup service."""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=1)
        logger.info("Cleanup service stopped")

    def _cleanup_loop(self):
        """Main cleanup loop — runs immediately then on every interval."""
        logger.info("Cleanup loop started")
        self._run_cleanup()

        while self.is_running:
            try:
                for _ in range(self.interval_seconds):
                    if not self.is_running:
                        break
                    time.sleep(1)
                if self.is_running:
                    self._run_cleanup()
            except Exception as e:
                logger.error("Error in cleanup loop: %s", e)
                time.sleep(300)

        logger.info("Cleanup loop ended")

    def _run_cleanup(self):
        """Execute the cleanup logic."""
        try:
            logger.info("Running scheduled data cleanup...")
            self.db_manager.cleanup_old_data(
                synced_days=self.synced_days,
                unsynced_days=self.unsynced_days,
            )
        except Exception as e:
            logger.error("Failed to run data cleanup: %s", e)
