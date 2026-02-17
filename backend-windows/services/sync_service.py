"""
sync_service.py
Service to synchronize local app_activity data with the ERP server.

ERP API Contract:
  URL:    POST https://api.erp.skillerszone.com/api/pctracking/appuseage
  Fields: pcName, appName, windowsTitle, startTime, endTime, duration, syncTime

Field mapping from local DB (app_activity table):
  pcName       ← socket.gethostname()
  appName      ← app_name
  windowsTitle ← window_title
  startTime    ← timestamp (ISO-8601)
  endTime      ← timestamp + duration_seconds (calculated)
  duration     ← str(duration_seconds)
  syncTime     ← current UTC time at point of sync
"""

import threading
import time
import logging
import socket
import requests
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ERP endpoint — hardcoded per the API contract
ERP_ENDPOINT = "https://api.erp.skillerszone.com/api/pctracking/appuseage"

# Sync interval in seconds (configurable via config_manager)
DEFAULT_SYNC_INTERVAL = 300  # 5 minutes

# Number of records to sync per batch
BATCH_SIZE = 50


class SyncService:
    def __init__(self, db_manager, config_manager):
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.is_running = False
        self.thread = None
        self._pc_name = socket.gethostname()

    # ─── LIFECYCLE ───────────────────────────────────────────────────────────
    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        logger.info("Sync service started (ERP: %s)", ERP_ENDPOINT)

    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Sync service stopped")

    # ─── MAIN LOOP ───────────────────────────────────────────────────────────
    def _sync_loop(self):
        """Periodic sync loop. Runs in a background daemon thread."""
        # Initial delay — let the rest of the app start first
        time.sleep(30)

        while self.is_running:
            try:
                self._sync_app_activity()
            except Exception as e:
                logger.error("Sync loop error: %s", e)

            interval = int(self.config_manager.get("sync_interval_seconds", DEFAULT_SYNC_INTERVAL))
            # Interruptible sleep — checks every second so stop() is responsive
            for _ in range(interval):
                if not self.is_running:
                    return
                time.sleep(1)

    # ─── SYNC LOGIC ──────────────────────────────────────────────────────────
    def _sync_app_activity(self):
        """
        Read unsynced app_activity records, POST each to the ERP endpoint,
        and mark them as synced on success.
        """
        data = self.db_manager.get_unsynced_data(limit=BATCH_SIZE)
        activities = data.get("app_activity", [])

        if not activities:
            logger.debug("No unsynced app_activity records — skipping")
            return

        logger.info("Syncing %d app_activity records to ERP", len(activities))

        synced_ids = []

        for record in activities:
            payload = self._build_payload(record)
            if payload is None:
                # Skip malformed records but don't block others
                continue

            success = self._post_to_erp(payload)
            if success:
                synced_ids.append(record["id"])
            else:
                # Stop batch on first failure — will retry next cycle
                logger.warning(
                    "ERP POST failed for record id=%s — stopping batch, will retry",
                    record["id"]
                )
                break

        if synced_ids:
            self.db_manager.mark_as_synced("app_activity", synced_ids)
            logger.info("Marked %d records as synced", len(synced_ids))

    def _build_payload(self, record: dict) -> dict | None:
        """
        Transform a local app_activity row into the ERP JSON format.

        Local row shape:
            id, timestamp (ISO), app_name, window_title, duration_seconds, synced

        ERP shape:
            pcName, appName, windowsTitle, startTime, endTime, duration, syncTime
        """
        try:
            # Parse the stored timestamp (assumed UTC, no timezone info stored)
            start_dt = datetime.fromisoformat(record["timestamp"])
            if start_dt.tzinfo is None:
                # Treat naive timestamps as UTC
                start_dt = start_dt.replace(tzinfo=timezone.utc)

            duration_seconds = int(record.get("duration_seconds") or 0)
            end_dt = start_dt + timedelta(seconds=duration_seconds)

            # syncTime = moment this batch is being sent
            sync_dt = datetime.now(timezone.utc)

            return {
                "pcName":       self._pc_name,
                "appName":      record.get("app_name") or "Unknown",
                "windowsTitle": record.get("window_title") or "",
                "startTime":    start_dt.isoformat(),
                "endTime":      end_dt.isoformat(),
                "duration":     str(duration_seconds),   # ERP expects string
                "syncTime":     sync_dt.isoformat()
            }
        except Exception as e:
            logger.error("Failed to build payload for record %s: %s", record.get("id"), e)
            return None

    def _post_to_erp(self, payload: dict) -> bool:
        """
        POST a single record to the ERP endpoint.
        Returns True on HTTP 2xx, False on any error.
        Timeout: 10s — don't block the sync thread.
        """
        try:
            response = requests.post(
                ERP_ENDPOINT,
                json=payload,
                timeout=10,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
            )

            if response.ok:  # 2xx
                logger.debug("ERP POST OK — app=%s duration=%ss",
                             payload["appName"], payload["duration"])
                return True
            else:
                logger.warning(
                    "ERP POST returned HTTP %d for app=%s: %s",
                    response.status_code, payload["appName"], response.text[:200]
                )
                return False

        except requests.exceptions.Timeout:
            logger.error("ERP POST timed out for app=%s", payload["appName"])
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error("ERP connection error: %s", e)
            return False
        except Exception as e:
            logger.error("ERP POST unexpected error: %s", e)
            return False

    # ─── MANUAL TRIGGER ──────────────────────────────────────────────────────
    def trigger_sync_now(self):
        """
        Manually trigger a sync outside the scheduled interval.
        Called from the API if needed (e.g., /api/sync/trigger endpoint).
        """
        logger.info("Manual sync triggered")
        try:
            self._sync_app_activity()
            return {"success": True, "message": "Sync completed"}
        except Exception as e:
            logger.error("Manual sync failed: %s", e)
            return {"success": False, "error": str(e)}
