"""
sync_service.py
Service to synchronize local app_activity data with the ERP server.

ERP API Contract:
  URL:    POST https://api.erp.skillerszone.com/api/pctracking/appuseage
  Fields: pcName, appName, windowsTitle, startTime, endTime, duration, syncTime

Field mapping from local DB (app_activity table):
  pcName       ← device_alias (custom name) — falls back to socket.gethostname()
  appName      ← app_name
  windowsTitle ← window_title
  startTime    ← timestamp (ISO-8601)
  endTime      ← timestamp + duration_seconds (calculated)
  duration     ← duration_seconds (integer)
  syncTime     ← current UTC time at point of sync

CHANGES:
- IDENTITY: pcName now reads device_alias from device_config table per sync cycle.
            If no alias is set, falls back to raw hostname. This means alias
            changes take effect on the very next sync without restarting the agent.
"""

import threading
import getpass
import time
import logging
import socket
import requests
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

DEFAULT_SYNC_INTERVAL = 300   # 5 minutes
BATCH_SIZE            = 50


class SyncService:
    def __init__(self, db_manager, config_manager):
        self.db_manager     = db_manager
        self.config_manager = config_manager
        self.is_running     = False
        self.thread         = None
        # _fallback_hostname is used only when DB is unreachable
        self._fallback_hostname = socket.gethostname()

    def _get_pc_name(self) -> str:
        """
        Resolve the effective PC name to send to the ERP.
        Reads device_alias from device_config; falls back to raw hostname.
        Called fresh each sync cycle so alias changes are picked up immediately.
        """
        try:
            config = self.db_manager.get_identity_config()
            return config.get("device_alias") or self._fallback_hostname
        except Exception as e:
            logger.warning("Could not read device_alias from DB (%s) — using hostname", e)
            return self._fallback_hostname

    # ─── LIFECYCLE ───────────────────────────────────────────────────────────
    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        logger.info("Sync service started — endpoint resolved from config at sync time")

    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Sync service stopped")

    # ─── MAIN LOOP ───────────────────────────────────────────────────────────
    def _sync_loop(self):
        """Periodic sync loop. Runs in a background daemon thread."""
        time.sleep(30)   # Let the rest of the app start first

        while self.is_running:
            try:
                self._sync_app_activity()
            except Exception as e:
                logger.error("Sync loop error: %s", e)

            interval = int(self.config_manager.get("sync_interval_seconds", DEFAULT_SYNC_INTERVAL))
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
        data       = self.db_manager.get_unsynced_data(limit=BATCH_SIZE)
        activities = data.get("app_activity", [])

        if not activities:
            logger.debug("No unsynced app_activity records — skipping")
            return

        logger.info("Syncing %d app_activity records to ERP", len(activities))

        # Resolve alias once per batch (consistent within a batch)
        pc_name    = self._get_pc_name()
        synced_ids = []

        for record in activities:
            payload = self._build_payload(record, pc_name)
            if payload is None:
                continue

            success = self._post_to_erp(payload)
            if success:
                synced_ids.append(record["id"])
            else:
                logger.warning(
                    "ERP POST failed for record id=%s — stopping batch, will retry",
                    record["id"]
                )
                break

        if synced_ids:
            self.db_manager.mark_as_synced("app_activity", synced_ids)
            logger.info("Marked %d records as synced", len(synced_ids))

    def _build_payload(self, record: dict, pc_name: str) -> dict | None:
        """
        Transform a local app_activity row into the ERP JSON format.
        pc_name is passed in (resolved once per batch) rather than re-fetched per record.
        """
        try:
            start_dt = datetime.fromisoformat(record["timestamp"])
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)

            duration_seconds = int(record.get("duration_seconds") or 0)
            end_dt  = start_dt + timedelta(seconds=duration_seconds)
            sync_dt = datetime.now(timezone.utc)

            return {
                "pcName":       pc_name,
                "appName":      record.get("app_name") or "Unknown",
                "windowsTitle": record.get("window_title") or "",
                "startTime":    start_dt.isoformat(),
                "endTime":      end_dt.isoformat(),
                "duration":     duration_seconds,
                "syncTime":     sync_dt.isoformat(),
            }
        except Exception as e:
            logger.error("Failed to build payload for record %s: %s", record.get("id"), e)
            return None

    def _post_to_erp(self, payload: dict) -> bool:
        """
        POST a single record to the configured ERP endpoint.
        Reads server_url and api_key fresh from config_manager on every call
        so that GUI changes take effect without a service restart.
        Returns True on HTTP 2xx, False on any error or missing config.
        """
        server_url = self.config_manager.get("server_url", "").strip()
        if not server_url:
            logger.warning("ERP server_url is not configured — skipping sync. "
                           "Set it via the 'Config Server API' button in the dashboard.")
            return False

        api_key = self.config_manager.get("api_key", "").strip()

        headers = {
            "Content-Type": "application/json",
            "Accept":       "application/json",
        }
        if api_key:
            headers["X-API-Key"] = api_key

        try:
            response = requests.post(
                server_url,
                json=payload,
                timeout=10,
                headers=headers,
            )
            if response.ok:
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
        """Manually trigger a sync outside the scheduled interval."""
        logger.info("Manual sync triggered")
        try:
            self._sync_app_activity()
            return {"success": True, "message": "Sync completed"}
        except Exception as e:
            logger.error("Manual sync failed: %s", e)
            return {"success": False, "error": str(e)}

    def push_credentials_to_erp(self, username: str):
        """Placeholder — implement when ERP credential API is available."""
        logger.info("Credential sync placeholder called for user: %s", username)

    
