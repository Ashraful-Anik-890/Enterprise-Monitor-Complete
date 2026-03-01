"""
data_cleaner.py
7-day data retention cleanup service.

Pure Python — no platform-specific code. Identical to backend-windows version.
Runs as a background daemon thread that fires once per hour.
"""

import threading
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

RETENTION_DAYS = 7
CLEANUP_INTERVAL_SECONDS = 3600  # run once per hour


class CleanupService:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.is_running = False
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._cleanup_loop, daemon=True, name="CleanupService")
        self.thread.start()
        logger.info("CleanupService started (retention: %d days)", RETENTION_DAYS)

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
        cutoff = (datetime.utcnow() - timedelta(days=RETENTION_DAYS)).isoformat()
        tables = [
            "screenshots",
            "app_activity",
            "browser_activity",
            "clipboard_events",
            "text_logs",
        ]
        for table in tables:
            try:
                deleted = self.db_manager.delete_old_records(table, cutoff)
                if deleted:
                    logger.info("Cleaned %d records from %s (older than %s)", deleted, table, cutoff[:10])
            except Exception as e:
                logger.error("Failed to clean table %s: %s", table, e)
