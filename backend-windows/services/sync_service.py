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

FIX — durationSeconds type:
  Old: "durationSeconds": str(rec.get("duration_seconds") or 0)
        → Explicit str() cast was semantically wrong. The API contract specifies
          durationSeconds as an integer (300, not "300").
  New: "durationSeconds": int(rec.get("duration_seconds") or 0)
        → Correct type. requests serialises it identically on the wire for
          multipart/form-data, but the intent is correct and future JSON
          transports will behave correctly without code changes.

  NOTE on HTTP multipart/form-data transport:
    All form fields are transported as text bytes — the receiving server is
    responsible for casting to integer. If your server framework has strict
    type validation (e.g. Laravel 'integer' rule, Django IntegerField), it
    will cast "300" → 300 automatically. If it does NOT cast, the server-side
    code must do: int(request.POST.get('durationSeconds', 0)).
"""

import os
import threading
import time
import logging
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from url import PATH_VIDEO_SETTINGS, PATH_SCREENSHOT_SETTINGS, PATH_MONITORING_SETTINGS
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
        self.db_manager          = db_manager
        self.config_manager      = config_manager
        self.is_running          = False
        self.thread              = None
        self._fallback_hostname  = socket.gethostname()
        self._last_sync_time:  str | None = None
        self._last_sync_error: str | None = None
        self._is_syncing:      bool       = False
        self._local_update_time: float    = 0

    # ─── IDENTITY ────────────────────────────────────────────────────────────

    def _get_identity(self) -> dict:
        try:
            config = self.db_manager.get_identity_config()
            return {
                "pcName":     config.get("device_alias") or self._fallback_hostname,
                "macAddress": config.get("mac_address", ""),
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

    def mark_local_update(self) -> None:
        """Called by api_server when a local toggle happens to prevent immediate override."""
        self._local_update_time = time.time()
        logger.debug("SyncService: local update marked, cooldown active")

    def _is_cooldown_active(self) -> bool:
        """Returns True if a local update happened recently (e.g. within 30s)."""
        return (time.time() - self._local_update_time) < 30

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
        time.sleep(30)   # let app fully initialise before first sync
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
        p = Path(file_path)
        if not p.exists():
            logger.warning("File not found, skipping: %s", file_path)
            return False
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
        return self.config_manager.get(key, "").strip()

    def _normalize_timestamp(self, ts: str) -> str:
        """Ensure timestamp includes UTC timezone suffix for ERP compatibility."""
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

    def _build_app_activity_payload(self, rec: dict, identity: dict) -> dict | None:
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
            logger.info("text_logs: synced %d records", len(synced_ids))
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
                "pcName":       identity["pcName"],
                "macAddress":   identity["macAddress"],
                "userName":     identity["userName"],
                "timestamp":    rec.get("timestamp") or "",
                "activeWindow": rec.get("active_window") or "",
                "activeApp":    rec.get("active_app") or "",
                "syncTime":     datetime.now(timezone.utc).isoformat(),
            }

            p = Path(file_path)
            if not p.exists():
                synced_ids.append(rec["id"])
                logger.warning("Screenshot file gone, marking synced: %s", file_path)
                continue

            if self._post_file(url, fields, file_path, "image/png"):
                synced_ids.append(rec["id"])
            else:
                break

        if synced_ids:
            self.db_manager.mark_as_synced("screenshots", synced_ids)
            logger.info("screenshots: synced %d records", len(synced_ids))
        return len(synced_ids)

    # ─── TYPE 6 — VIDEOS ─────────────────────────────────────────────────────

    def _sync_videos(self, identity: dict) -> int:
        """
        Sends each video chunk as multipart/form-data.

        FIX: durationSeconds field changed from str() → int().

        API contract:
          POST multipart/form-data to url_videos
          Form fields:
            pcName          = "DESKTOP-ABC123"       (str)
            timestamp       = "2026-02-22T08:00:00Z" (str, ISO-8601)
            durationSeconds = 300                    (int — NOT "300")
            syncTime        = "2026-02-22T08:35:01Z" (str, ISO-8601)
          File field:
            file            = <MP4 binary>

        Note: HTTP multipart/form-data transports all form fields as text bytes.
        The server must cast durationSeconds to int. Using int() here ensures
        the intent is correct; requests serialises it as "300" on the wire
        either way. If the receiving server does strict type validation, add
        parseInt() / int() on the server side.
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
                "pcName":          identity["pcName"],
                "macAddress":      identity["macAddress"],
                "userName":        identity["userName"],
                "timestamp":       rec.get("timestamp") or "",
                # ── FIX: was str(...), now int() — semantically correct ───────
                "durationSeconds": int(rec.get("duration_seconds") or 0),
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

    def _sync_video_status(self, identity: dict) -> None:
        if self._is_cooldown_active():
            return

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
                        from api_server import screen_recorder, monitoring_active
                        if remote_enabled:
                            if monitoring_active:
                                screen_recorder.start()
                                logger.info("Screen recording ENABLED by remote server sync")
                            else:
                                logger.info("Screen recording ENABLED in config by remote sync (but monitoring is paused)")
                        else:
                            screen_recorder.stop()
                            logger.info("Screen recording DISABLED by remote server sync")
        except Exception as e:
            logger.debug("Failed to sync video status from remote: %s", e)

    def _sync_screenshot_status(self, identity: dict) -> None:
        if self._is_cooldown_active():
            return

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
                        from api_server import screenshot_monitor, monitoring_active
                        if remote_enabled:
                            if monitoring_active:
                                screenshot_monitor.start()
                                logger.info("Screenshot capturing ENABLED by remote server sync")
                            else:
                                logger.info("Screenshot capturing ENABLED in config by remote sync (but monitoring is paused)")
                        else:
                            screenshot_monitor.stop()
                            logger.info("Screenshot capturing DISABLED by remote server sync")
        except Exception as e:
            logger.debug("Failed to sync screenshot status from remote: %s", e)

    def _sync_overall_status(self, identity: dict) -> None:
        if self._is_cooldown_active():
            return

        url = self.config_manager.get("url_monitoring_settings", "").strip()
        if not url:
            base_url = self.config_manager.get("base_url", "").strip()
            if not base_url:
                return
            url = f"{base_url.rstrip('/')}{PATH_MONITORING_SETTINGS}"

        url = f"{url}?pcName={identity['pcName']}&macAddress={identity['macAddress']}&userName={identity['userName']}"
        try:
            resp = requests.get(url, headers=self._auth_headers(), timeout=10)
            if not resp.ok:
                return
            data = resp.json()
            remote_active = data.get("monitoringActive")
            if remote_active is None:
                return

            import api_server  # import the module so we can read AND write the global
            if bool(remote_active) == bool(api_server.monitoring_active):
                return  # already in sync — nothing to do

            if remote_active:
                # ── RESUME ───────────────────────────────────────────────────
                api_server.monitoring_active = True
                # Mirror resume_monitoring() logic exactly — no HTTP round-trip
                if api_server.screenshot_monitor.is_running:
                    api_server.screenshot_monitor.resume()
                elif self.config_manager.get("screenshot_enabled", True):
                    api_server.screenshot_monitor.start()

                if api_server.screen_recorder.is_running:
                    api_server.screen_recorder.resume()
                elif self.config_manager.get("recording_enabled", False):
                    api_server.screen_recorder.start()

                api_server.clipboard_monitor.resume()
                api_server.app_tracker.resume()
                api_server.browser_tracker.resume()
                api_server.keylogger.resume()
                logger.info("Monitoring RESUMED by remote server sync")
            else:
                # ── PAUSE ────────────────────────────────────────────────────
                api_server.monitoring_active = False
                # Mirror pause_monitoring() logic exactly — no HTTP round-trip
                api_server.screenshot_monitor.pause()
                api_server.clipboard_monitor.pause()
                api_server.app_tracker.pause()
                api_server.browser_tracker.pause()
                api_server.keylogger.pause()
                api_server.screen_recorder.pause()
                logger.info("Monitoring PAUSED by remote server sync")

        except Exception as e:
            logger.debug("Failed to sync overall monitoring status from remote: %s", e)

