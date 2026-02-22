"""
sync_service.py  v2 — All-6-Type ERP Sync
==========================================
Synchronises all 6 monitoring data types to their respective ERP endpoints.

Config keys (saved via GUI "Config Server API" modal):
  url_app_activity  — POST JSON        — app usage sessions
  url_browser       — POST JSON        — browser URL visits
  url_clipboard     — POST JSON        — clipboard events
  url_keystrokes    — POST JSON        — keystroke / text logs
  url_screenshots   — POST multipart   — PNG screenshot files + metadata
  url_videos        — POST multipart   — MP4 recording chunks + metadata

Global settings (also in config):
  api_key               — optional X-API-Key header (shared by all 6 endpoints)
  sync_interval_seconds — how often the loop wakes (default: 300)

Retry policy (per-type):
  Stop current batch on first failure.
  Mark successes, leave failures with synced=0 → picked up next cycle.

DB prerequisites:
  browser_activity and text_logs need a synced INTEGER DEFAULT 0 column.
  Run the migration in db_manager._run_migrations() (see db_manager_additions.py).
"""

import os
import threading
import time
import logging
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DEFAULT_SYNC_INTERVAL = 300
BATCH_JSON            = 50   # records per cycle for JSON types
BATCH_FILES           = 10   # records per cycle for screenshot uploads
BATCH_VIDEOS          = 3    # records per cycle for video uploads (large files)
REQUEST_TIMEOUT_JSON  = 10   # seconds
REQUEST_TIMEOUT_FILE  = 60   # seconds (files take longer)


class SyncService:
    def __init__(self, db_manager, config_manager):
        self.db_manager     = db_manager
        self.config_manager = config_manager
        self.is_running     = False
        self.thread         = None
        self._fallback_hostname = socket.gethostname()

    # ─── IDENTITY ────────────────────────────────────────────────────────────

    def _get_pc_name(self) -> str:
        try:
            config = self.db_manager.get_identity_config()
            return config.get("device_alias") or self._fallback_hostname
        except Exception as e:
            logger.warning("Could not read device_alias: %s — using hostname", e)
            return self._fallback_hostname

    # ─── LIFECYCLE ───────────────────────────────────────────────────────────

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        logger.info("SyncService v2 started — 6 data types enabled")

    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("SyncService stopped")

    def trigger_sync_now(self):
        """Manually trigger a full sync cycle from the API."""
        logger.info("Manual sync triggered")
        try:
            pc_name = self._get_pc_name()
            results = {
                "app_activity": self._sync_app_activity(pc_name),
                "browser":      self._sync_browser(pc_name),
                "clipboard":    self._sync_clipboard(pc_name),
                "keystrokes":   self._sync_keystrokes(pc_name),
                "screenshots":  self._sync_screenshots(pc_name),
                "videos":       self._sync_videos(pc_name),
            }
            return {"success": True, "synced": results}
        except Exception as e:
            logger.error("Manual sync failed: %s", e)
            return {"success": False, "error": str(e)}

    # ─── MAIN LOOP ───────────────────────────────────────────────────────────

    def _sync_loop(self):
        time.sleep(30)  # let the rest of the app initialise first
        while self.is_running:
            try:
                pc_name = self._get_pc_name()
                self._sync_app_activity(pc_name)
                self._sync_browser(pc_name)
                self._sync_clipboard(pc_name)
                self._sync_keystrokes(pc_name)
                self._sync_screenshots(pc_name)
                self._sync_videos(pc_name)
            except Exception as e:
                logger.error("Sync loop error: %s", e)

            interval = int(self.config_manager.get("sync_interval_seconds", DEFAULT_SYNC_INTERVAL))
            for _ in range(interval):
                if not self.is_running:
                    return
                time.sleep(1)

    # ─── SHARED HTTP HELPERS ─────────────────────────────────────────────────

    def _auth_headers(self) -> dict:
        api_key = self.config_manager.get("api_key", "").strip()
        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        return headers

    def _post_json(self, url: str, payload: dict) -> bool:
        """POST a single JSON record. Returns True on HTTP 2xx."""
        try:
            resp = requests.post(
                url,
                json=payload,
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT_JSON,
            )
            if resp.ok:
                return True
            logger.warning("JSON POST %s → HTTP %d: %s", url, resp.status_code, resp.text[:200])
            return False
        except requests.exceptions.Timeout:
            logger.error("JSON POST timed out: %s", url)
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error("JSON POST connection error: %s", e)
            return False
        except Exception as e:
            logger.error("JSON POST unexpected error: %s", e)
            return False

    def _post_file(self, url: str, fields: dict, file_path: str,
                   media_type: str, field_name: str = "file") -> bool:
        """
        POST a file as multipart/form-data.
        fields   — extra form fields sent alongside the file
        file_path — absolute path to the file on disk
        Returns True on HTTP 2xx, False on any error or missing file.
        """
        p = Path(file_path)
        if not p.exists():
            logger.warning("File not found, skipping: %s", file_path)
            return False  # don't retry a missing file — mark it synced below
        try:
            with open(p, "rb") as fh:
                resp = requests.post(
                    url,
                    data=fields,
                    files={field_name: (p.name, fh, media_type)},
                    headers=self._auth_headers(),
                    timeout=REQUEST_TIMEOUT_FILE,
                )
            if resp.ok:
                return True
            logger.warning("File POST %s → HTTP %d: %s", url, resp.status_code, resp.text[:200])
            return False
        except requests.exceptions.Timeout:
            logger.error("File POST timed out: %s", url)
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error("File POST connection error: %s", e)
            return False
        except Exception as e:
            logger.error("File POST unexpected error: %s", e)
            return False

    def _get_url(self, key: str) -> str:
        """Return configured URL for this type, or '' if not set."""
        return self.config_manager.get(key, "").strip()

    # ─── TYPE 1 — APP ACTIVITY ───────────────────────────────────────────────

    def _sync_app_activity(self, pc_name: str) -> int:
        url = self._get_url("url_app_activity")
        if not url:
            return 0

        records = self.db_manager.get_unsynced_data(limit=BATCH_JSON).get("app_activity", [])
        if not records:
            return 0

        synced_ids = []
        for rec in records:
            payload = self._build_app_activity_payload(rec, pc_name)
            if payload is None:
                continue
            if self._post_json(url, payload):
                synced_ids.append(rec["id"])
            else:
                break  # stop batch, retry next cycle

        if synced_ids:
            self.db_manager.mark_as_synced("app_activity", synced_ids)
            logger.info("app_activity: synced %d records", len(synced_ids))
        return len(synced_ids)

    def _build_app_activity_payload(self, rec: dict, pc_name: str) -> dict | None:
        try:
            start_dt = datetime.fromisoformat(rec["timestamp"])
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            duration  = int(rec.get("duration_seconds") or 0)
            end_dt    = start_dt + timedelta(seconds=duration)
            return {
                "pcName":       pc_name,
                "appName":      rec.get("app_name") or "Unknown",
                "windowsTitle": rec.get("window_title") or "",
                "startTime":    start_dt.isoformat(),
                "endTime":      end_dt.isoformat(),
                "duration":     duration,
                "syncTime":     datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error("build_app_activity_payload id=%s: %s", rec.get("id"), e)
            return None

    # ─── TYPE 2 — BROWSER ACTIVITY ───────────────────────────────────────────

    def _sync_browser(self, pc_name: str) -> int:
        url = self._get_url("url_browser")
        if not url:
            return 0

        records = self.db_manager.get_unsynced_browser(limit=BATCH_JSON)
        if not records:
            return 0

        synced_ids = []
        for rec in records:
            payload = {
                "pcName":     pc_name,
                "browserName": rec.get("browser_name") or "",
                "url":         rec.get("url") or "",
                "pageTitle":   rec.get("page_title") or "",
                "timestamp":   rec.get("timestamp") or "",
                "syncTime":    datetime.now(timezone.utc).isoformat(),
            }
            if self._post_json(url, payload):
                synced_ids.append(rec["id"])
            else:
                break

        if synced_ids:
            self.db_manager.mark_as_synced("browser_activity", synced_ids)
            logger.info("browser_activity: synced %d records", len(synced_ids))
        return len(synced_ids)

    # ─── TYPE 3 — CLIPBOARD ──────────────────────────────────────────────────

    def _sync_clipboard(self, pc_name: str) -> int:
        url = self._get_url("url_clipboard")
        if not url:
            return 0

        records = self.db_manager.get_unsynced_clipboard(limit=BATCH_JSON)
        if not records:
            return 0

        synced_ids = []
        for rec in records:
            payload = {
                "pcName":         pc_name,
                "contentType":    rec.get("content_type") or "text",
                "contentPreview": rec.get("content_preview") or "",
                "timestamp":      rec.get("timestamp") or "",
                "syncTime":       datetime.now(timezone.utc).isoformat(),
            }
            if self._post_json(url, payload):
                synced_ids.append(rec["id"])
            else:
                break

        if synced_ids:
            self.db_manager.mark_as_synced("clipboard_events", synced_ids)
            logger.info("clipboard_events: synced %d records", len(synced_ids))
        return len(synced_ids)

    # ─── TYPE 4 — KEYSTROKES ─────────────────────────────────────────────────

    def _sync_keystrokes(self, pc_name: str) -> int:
        url = self._get_url("url_keystrokes")
        if not url:
            return 0

        records = self.db_manager.get_unsynced_keystrokes(limit=BATCH_JSON)
        if not records:
            return 0

        synced_ids = []
        for rec in records:
            payload = {
                "pcName":      pc_name,
                "application": rec.get("application") or "",
                "windowTitle": rec.get("window_title") or "",
                "content":     rec.get("content") or "",
                "timestamp":   rec.get("timestamp") or "",
                "syncTime":    datetime.now(timezone.utc).isoformat(),
            }
            if self._post_json(url, payload):
                synced_ids.append(rec["id"])
            else:
                break

        if synced_ids:
            self.db_manager.mark_as_synced("text_logs", synced_ids)
            logger.info("text_logs: synced %d records", len(synced_ids))
        return len(synced_ids)

    # ─── TYPE 5 — SCREENSHOTS ────────────────────────────────────────────────

    def _sync_screenshots(self, pc_name: str) -> int:
        """
        Sends each screenshot as multipart/form-data.
        If the PNG file no longer exists on disk, the record is marked synced
        anyway (it was already cleaned up by data_cleaner) — no point retrying.
        """
        url = self._get_url("url_screenshots")
        if not url:
            return 0

        records = self.db_manager.get_unsynced_screenshots(limit=BATCH_FILES)
        if not records:
            return 0

        synced_ids = []
        for rec in records:
            file_path = rec.get("file_path") or ""
            fields = {
                "pcName":       pc_name,
                "timestamp":    rec.get("timestamp") or "",
                "activeWindow": rec.get("active_window") or "",
                "activeApp":    rec.get("active_app") or "",
                "syncTime":     datetime.now(timezone.utc).isoformat(),
            }

            p = Path(file_path)
            if not p.exists():
                # File deleted by data_cleaner — mark synced to stop infinite retry
                synced_ids.append(rec["id"])
                logger.warning("Screenshot file gone, marking synced: %s", file_path)
                continue

            if self._post_file(url, fields, file_path, "image/png"):
                synced_ids.append(rec["id"])
            else:
                break  # network issue — stop batch

        if synced_ids:
            self.db_manager.mark_as_synced("screenshots", synced_ids)
            logger.info("screenshots: synced %d records", len(synced_ids))
        return len(synced_ids)

    # ─── TYPE 6 — VIDEOS ─────────────────────────────────────────────────────

    def _sync_videos(self, pc_name: str) -> int:
        """
        Sends each video chunk as multipart/form-data.
        Same missing-file logic as screenshots.
        """
        url = self._get_url("url_videos")
        if not url:
            return 0

        records = self.db_manager.get_unsynced_videos(limit=BATCH_VIDEOS)
        if not records:
            return 0

        synced_ids = []
        for rec in records:
            file_path = rec.get("file_path") or ""
            fields = {
                "pcName":          pc_name,
                "timestamp":       rec.get("timestamp") or "",
                "durationSeconds": str(rec.get("duration_seconds") or 0),
                "syncTime":        datetime.now(timezone.utc).isoformat(),
            }

            p = Path(file_path)
            if not p.exists():
                synced_ids.append(rec["id"])
                logger.warning("Video file gone, marking synced: %s", file_path)
                continue

            if self._post_file(url, fields, file_path, "video/mp4"):
                synced_ids.append(rec["id"])
            else:
                break

        if synced_ids:
            self.db_manager.mark_videos_synced(synced_ids)
            logger.info("videos: synced %d records", len(synced_ids))
        return len(synced_ids)
