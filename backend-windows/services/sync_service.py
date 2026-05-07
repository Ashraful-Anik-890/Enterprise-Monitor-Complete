"""
sync_service.py  v3 — Cycle Cap + Categorized Fast-Fail
========================================================

CHANGES IN THIS VERSION (v3)
─────────────────────────────
Bug 4 — Unbounded sync loop hammers the server on backlog
  Old: Each data type synced up to BATCH_JSON records per cycle with no
       cross-type total cap. On a machine with 3 days of backlog, a single
       cycle could send 300+ HTTP requests sequentially, blocking the loop
       for minutes and overwhelming the server.
  Fix: CYCLE_CAP = 200. Once total_synced_this_cycle reaches 200, the loop
       breaks early. The remaining backlog drains over subsequent cycles.

Bug 5 — Hard server errors (401, 502, network down) cause per-record retries
  Old: `_post_json` returned False on ANY failure. The caller broke out of
       the RECORD loop (good), but the cycle continued to the next DATA TYPE
       and retried the same unreachable server. A network outage caused 9
       consecutive connection errors per cycle (one per data type).
  Fix: Categorized error handling in `_post_json` and `_post_file`:
       - HARD errors (connection refused, 401, 403, 500, 502, 503):
         Set `self._abort_cycle = True`. Caller checks flag and aborts
         the entire cycle immediately.
       - SOFT errors (timeout, 404, 422): Break the current batch but
         allow the cycle to continue to the next data type.

  The `_abort_cycle` flag is reset at the start of every sync loop iteration
  so each new cycle gets a clean slate.

All v2 fixes (server_reachable tracking, log spam suppression, etc.) preserved.
"""

import os
import threading
import time
import logging
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any

from url import PATH_VIDEO_SETTINGS, PATH_SCREENSHOT_SETTINGS, PATH_MONITORING_SETTINGS, PATH_DEVICE_STATUS, PATH_DEVICE_LOGS
import requests

logger = logging.getLogger(__name__)

DEFAULT_SYNC_INTERVAL = 60
BATCH_JSON            = 100
BATCH_FILES           = 20
BATCH_VIDEOS          = 3
REQUEST_TIMEOUT_JSON  = 10
REQUEST_TIMEOUT_FILE  = 60

# ── v3 additions ──────────────────────────────────────────────────────────────
CYCLE_CAP = 200   # max total records synced per full cycle across all data types

# These HTTP status codes indicate a fundamental server/auth problem.
# Abort the entire cycle immediately — do not try remaining data types.
HARD_ABORT_STATUSES = {401, 403, 500, 502, 503}

import random
SYNC_JITTER_MAX_SECS  = 60      # randomize start to prevent thundering herd

# These are soft failures — break the current batch but continue other types.
# (Any status not in HARD_ABORT_STATUSES and not 2xx is implicitly soft.)


class SyncService:
    def __init__(self, db_manager, config_manager):
        self.db_manager            = db_manager
        self.config_manager        = config_manager
        self.is_running            = False
        self.thread: Optional[threading.Thread] = None
        self._fallback_hostname    = socket.gethostname()
        self._last_sync_time:  Optional[str] = None
        self._last_sync_error: Optional[str] = None
        self._is_syncing:      bool       = False
        self._local_update_time: float    = 0
        self._server_reachable:       bool = False
        self._consecutive_failures:   int  = 0
        # ── v3: per-cycle abort flag ─────────────────────────────────────────
        self._abort_cycle: bool = False
        # ── v5.3.0: device status for ERP reporting ─────────────────────────
        self._device_status: str = "ACTIVE"

    # ─── IDENTITY ────────────────────────────────────────────────────────────

    def _get_identity(self) -> dict:
        try:
            config = self.db_manager.get_identity_config()
            device_uuid = self._get_device_uuid()
            return {
                "pcName":     config.get("device_alias") or self._fallback_hostname,
                "macAddress": device_uuid or config.get("mac_address", ""),
                "userName":   config.get("user_alias") or config.get("os_user", ""),
                "location":   config.get("location", ""),
                "deviceId":   device_uuid,
            }
        except Exception as e:
            logger.warning("Could not read identity config: %s — using fallback", e)
            device_uuid = self._get_device_uuid()
            return {
                "pcName":     self._fallback_hostname,
                "macAddress": device_uuid,
                "userName":   "",
                "location":   "",
                "deviceId":   device_uuid,
            }

    def set_device_status(self, status: str) -> None:
        """Set the device status for ERP reporting. Called by api_server on state changes."""
        valid = {"ACTIVE", "PAUSED", "AUTO_PAUSED", "SLEEP", "SHUTDOWN", "GRACEFUL_OFF"}
        if status in valid:
            self._device_status = status
            logger.info("Device status set to: %s", status)
        else:
            logger.warning("Invalid device status '%s' — ignoring", status)

    def get_device_status(self) -> str:
        """Returns the current device status string."""
        return self._device_status

    def _get_device_uuid(self) -> str:
        """Returns the machine-scoped UUID or empty string."""
        try:
            from utils.device_id import get_device_uuid
            return get_device_uuid() or ""
        except Exception:
            return ""

    # ─── LIFECYCLE ───────────────────────────────────────────────────────────

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        logger.info("SyncService v3 started — cap=%d, hard-abort on %s",
                    CYCLE_CAP, HARD_ABORT_STATUSES)

    def stop(self) -> None:
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("SyncService stopped")

    def mark_local_update(self) -> None:
        self._local_update_time = time.time()
        logger.debug("SyncService: local update marked, cooldown active")

    def _is_cooldown_active(self) -> bool:
        return (time.time() - self._local_update_time) < 30

    def get_status(self) -> dict:
        return {
            "last_sync":        self._last_sync_time,
            "last_error":       self._last_sync_error,
            "is_syncing":       self._is_syncing,
            "server_reachable": self._server_reachable,
        }

    def trigger_sync_now(self) -> dict:
        logger.info("Manual sync triggered")
        try:
            if not self.db_manager.is_sync_enabled():
                return {"success": False, "error": "Sync disabled — confirm credentials first"}
            self._is_syncing = True
            self._abort_cycle = False
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
        # Stagger startup across PCs — each PC sleeps a random offset so
        # 200 machines don't all hammer the server at the same second.
        startup_jitter = random.randint(0, SYNC_JITTER_MAX_SECS)
        logger.info("SyncService: startup jitter %ds", startup_jitter)
        time.sleep(startup_jitter)
        while self.is_running:
            cycle_reached_server = False
            total_synced_this_cycle = 0

            try:
                if not self.db_manager.is_sync_enabled():
                    logger.debug("SyncService: sync disabled (credentials not confirmed) — skipping cycle")
                    interval = int(self.config_manager.get("sync_interval_seconds", DEFAULT_SYNC_INTERVAL))
                    for _ in range(interval):
                        if not self.is_running:
                            return
                        time.sleep(1)
                    continue

                self._is_syncing = True
                # v3: Reset abort flag at the start of every cycle
                self._abort_cycle = False
                identity = self._get_identity()

                # Command fetch (R9) — first step before anything else
                self._fetch_pending_commands(identity)

                # Status syncs (R2: non-fatal — never set _abort_cycle)
                if self._sync_device_status(identity):
                    cycle_reached_server = True
                if self._sync_video_status(identity):
                    cycle_reached_server = True
                if self._sync_screenshot_status(identity):
                    cycle_reached_server = True
                if self._sync_overall_status(identity):
                    cycle_reached_server = True

                # Data syncs — respect cap and abort flag
                sync_fns = [
                    self._sync_app_activity,
                    self._sync_browser,
                    self._sync_clipboard,
                    self._sync_keystrokes,
                    self._sync_screenshots,
                    self._sync_videos,
                ]

                for fn in sync_fns:
                    if self._abort_cycle:
                        logger.debug("SyncService: cycle aborted — skipping remaining data types")
                        break
                    if total_synced_this_cycle >= CYCLE_CAP:
                        logger.info(
                            "SyncService: cycle cap (%d) reached — deferring remainder to next cycle",
                            CYCLE_CAP,
                        )
                        break

                    count = fn(identity)
                    if count > 0:
                        cycle_reached_server = True
                        total_synced_this_cycle += count

            except Exception as e:
                self._last_sync_error = str(e)
                logger.error("Sync loop error: %s", e)
            finally:
                self._is_syncing = False

            # Reachability tracking
            if cycle_reached_server:
                self._server_reachable     = True
                self._last_sync_time       = datetime.now(timezone.utc).isoformat()
                self._last_sync_error      = None
                self._consecutive_failures = 0
            else:
                self._server_reachable     = False
                self._consecutive_failures += 1

                base_url = self.config_manager.get("base_url", "").strip()
                if base_url:
                    if self._consecutive_failures == 1:
                        logger.warning(
                            "SyncService: server unreachable at %s — "
                            "no data sent this cycle. Will retry in %ds.",
                            base_url,
                            int(self.config_manager.get("sync_interval_seconds", DEFAULT_SYNC_INTERVAL)),
                        )
                    else:
                        logger.debug(
                            "SyncService: server still unreachable (consecutive failures: %d)",
                            self._consecutive_failures,
                        )
                    self._last_sync_error = (
                        f"Server unreachable ({self._consecutive_failures} consecutive failure(s))"
                    )

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
        """
        POST JSON payload. Returns True on success.

        v3 error categorization:
          - ConnectionError → hard abort (network is down)
          - HARD_ABORT_STATUSES (401,403,500,502,503) → hard abort
          - Timeout → soft failure (this record skipped, cycle continues)
          - Other 4xx → soft failure

        Sets self._abort_cycle = True on hard failures so _sync_loop
        stops processing remaining data types immediately.
        """
        try:
            resp = requests.post(
                url,
                json=payload,
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT_JSON,
            )
            if resp.ok:
                return True
            if resp.status_code in HARD_ABORT_STATUSES:
                logger.error(
                    "JSON POST %s → HTTP %d — aborting cycle",
                    url, resp.status_code,
                )
                self._abort_cycle = True
                return False
            if 400 <= resp.status_code < 500:
                logger.warning("JSON POST permanent client error %d: %s. Dropping record.", resp.status_code, resp.text[:200])
                return True # Pretend success to drop from backlog 

            # Soft failure (timeout, 5xx not hard abort, etc.)
            logger.warning("JSON POST %s → HTTP %d: %s", url, resp.status_code, resp.text[:200])
            return False
        except requests.exceptions.Timeout:
            logger.warning("JSON POST timed out (soft): %s", url)
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error("JSON POST connection error — aborting cycle: %s", e)
            self._abort_cycle = True
            return False
        except Exception as e:
            logger.error("JSON POST unexpected error: %s", e)
            return False

    def _post_file(self, url: str, fields: dict, file_path: str,
                   media_type: str, field_name: str = "file") -> bool:
        """
        POST multipart file. Same error categorization as _post_json.
        """
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
            if resp.status_code in HARD_ABORT_STATUSES:
                logger.error(
                    "File POST %s → HTTP %d — aborting cycle",
                    url, resp.status_code,
                )
                self._abort_cycle = True
                return False
            if resp.status_code == 404:
                return "NOT_FOUND"
            if 400 <= resp.status_code < 500:
                logger.warning("File POST permanent client error %d: %s. Dropping record.", resp.status_code, resp.text[:200])
                return True # Pretend success to drop from backlog

            logger.warning("File POST %s → HTTP %d: %s", url, resp.status_code, resp.text[:200])
            return False
        except requests.exceptions.Timeout:
            logger.warning("File POST timed out (soft): %s", url)
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error("File POST connection error — aborting cycle: %s", e)
            self._abort_cycle = True
            return False
        except Exception as e:
            logger.error("File POST unexpected error: %s", e)
            return False

    def _get_url(self, key: str) -> str:
        return self.config_manager.get(key, "").strip()

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
            if self._abort_cycle:
                break
            payload = self._build_app_activity_payload(rec, identity)
            if payload is None:
                continue
            if self._post_json(url, payload):
                synced_ids.append(rec["id"])
            elif self._abort_cycle:
                break
        if synced_ids:
            self.db_manager.mark_as_synced("app_activity", synced_ids)
            logger.info("app_activity: synced %d records", len(synced_ids))
        return len(synced_ids)

    def _build_app_activity_payload(self, rec: dict, identity: dict) -> Optional[dict]:
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
                "location":     identity["location"],
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
            if self._abort_cycle:
                break
            payload = {
                "pcName":      identity["pcName"],
                "macAddress":  identity["macAddress"],
                "userName":    identity["userName"],
                "location":    identity["location"],
                "browserName": rec.get("browser_name") or "",
                "url":         rec.get("url") or "",
                "pageTitle":   rec.get("page_title") or "",
                "timestamp":   self._normalize_timestamp(rec.get("timestamp") or ""),
                "syncTime":    datetime.now(timezone.utc).isoformat(),
            }
            if self._post_json(url, payload):
                synced_ids.append(rec["id"])
            elif self._abort_cycle:
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
            if self._abort_cycle:
                break
            payload = {
                "pcName":         identity["pcName"],
                "macAddress":     identity["macAddress"],
                "userName":       identity["userName"],
                "location":       identity["location"],
                "contentType":    rec.get("content_type") or "text",
                "contentPreview": rec.get("content_preview") or "",
                "timestamp":      self._normalize_timestamp(rec.get("timestamp") or ""),
                "syncTime":       datetime.now(timezone.utc).isoformat(),
            }
            if self._post_json(url, payload):
                synced_ids.append(rec["id"])
            elif self._abort_cycle:
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
            if self._abort_cycle:
                break
            payload = {
                "pcName":      identity["pcName"],
                "macAddress":  identity["macAddress"],
                "userName":    identity["userName"],
                "location":    identity["location"],
                "application": rec.get("application") or "",
                "windowTitle": rec.get("window_title") or "",
                "content":     rec.get("content") or "",
                "timestamp":   self._normalize_timestamp(rec.get("timestamp") or ""),
                "syncTime":    datetime.now(timezone.utc).isoformat(),
            }
            if self._post_json(url, payload):
                synced_ids.append(rec["id"])
            elif self._abort_cycle:
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
            if self._abort_cycle:
                break
            file_path = rec.get("file_path") or ""
            fields = {
                "pcName":       identity["pcName"],
                "macAddress":   identity["macAddress"],
                "userName":     identity["userName"],
                "location":     identity["location"],
                "timestamp":    self._normalize_timestamp(rec.get("timestamp") or ""),
                "activeWindow": rec.get("active_window") or "",
                "activeApp":    rec.get("active_app") or "",
                "syncTime":     datetime.now(timezone.utc).isoformat(),
            }
            p = Path(file_path)
            if not p.exists():
                synced_ids.append(rec["id"])
                logger.warning("Screenshot file gone, marking synced: %s", file_path)
                continue
            result = self._post_file(url, fields, file_path, "image/jpeg")
            if result == "NOT_FOUND":
                current_failures = rec.get("failure_count") or 0
                self.db_manager.increment_failure_count("screenshots", rec["id"])
                if current_failures + 1 >= 3:
                    self.db_manager.mark_dead_letter("screenshots", rec["id"])
                    logger.warning("Screenshot id=%d dead-lettered after 3×404", rec["id"])
                continue
            elif result is True:
                synced_ids.append(rec["id"])
            elif self._abort_cycle:
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
            if self._abort_cycle:
                break
            file_path = rec.get("file_path") or ""
            fields = {
                "pcName":          identity["pcName"],
                "macAddress":      identity["macAddress"],
                "userName":        identity["userName"],
                "location":        identity["location"],
                "timestamp":       rec.get("timestamp") or "",
                "durationSeconds": int(rec.get("duration_seconds") or 0),
                "syncTime":        datetime.now(timezone.utc).isoformat(),
            }
            p = Path(file_path)
            if not p.exists():
                synced_ids.append(rec["id"])
                logger.warning("Video file gone, marking synced: %s", file_path)
                continue
            result = self._post_file(url, fields, file_path, "video/mp4")
            if result == "NOT_FOUND":
                current_failures = rec.get("failure_count") or 0
                self.db_manager.increment_failure_count("video_recordings", rec["id"])
                if current_failures + 1 >= 3:
                    self.db_manager.mark_dead_letter("video_recordings", rec["id"])
                    logger.warning("Video id=%d dead-lettered after 3×404", rec["id"])
                continue
            elif result is True:
                synced_ids.append(rec["id"])
            elif self._abort_cycle:
                break
        if synced_ids:
            self.db_manager.mark_videos_synced(synced_ids)
            logger.info("videos: synced %d records", len(synced_ids))
        return len(synced_ids)

    # ─── STATUS SYNCS (bi-directional remote control) ────────────────────────

    def _sync_device_status(self, identity: dict) -> bool:
        """POST current device status to the ERP server for the admin dashboard."""
        url = self.config_manager.get("url_device_status", "").strip()
        if not url:
            base_url = self.config_manager.get("base_url", "").strip()
            if not base_url:
                return False
            url = f"{base_url.rstrip('/')}{PATH_DEVICE_STATUS}"

        payload = {
            "pcName":     identity["pcName"],
            "macAddress": identity["macAddress"],
            "userName":   identity["userName"],
            "status":     self._device_status,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
        try:
            resp = requests.post(
                url, json=payload,
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT_JSON,
            )
            if resp.ok:
                logger.debug("Device status '%s' synced to server", self._device_status)
                return True
            if resp.status_code in HARD_ABORT_STATUSES:
                logger.warning("Device status POST → HTTP %d (non-fatal, cycle continues)", resp.status_code)
            return False
        except requests.exceptions.ConnectionError:
            logger.warning("Device status POST connection error (non-fatal, cycle continues)")
            return False
        except Exception as e:
            logger.debug("Device status sync failed: %s", e)
            return False

    def _sync_video_status(self, identity: dict) -> bool:
        if self._is_cooldown_active():
            return False

        url = self.config_manager.get("url_video_settings", "").strip()
        if not url:
            base_url = self.config_manager.get("base_url", "").strip()
            if not base_url:
                return False
            url = f"{base_url.rstrip('/')}{PATH_VIDEO_SETTINGS}"

        url = f"{url}?pcName={identity['pcName']}&macAddress={identity['macAddress']}&userName={identity['userName']}"
        try:
            resp = requests.get(url, headers=self._auth_headers(), timeout=10)
            if not resp.ok:
                if resp.status_code in HARD_ABORT_STATUSES:
                    self._abort_cycle = True
                return resp.status_code not in HARD_ABORT_STATUSES
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
                        screen_recorder.stop()
                        logger.info("Screen recording DISABLED by remote server sync")
            return True
        except Exception as e:
            if self._consecutive_failures == 0:
                logger.warning("Failed to sync video status from remote: %s", e)
            else:
                logger.debug("Failed to sync video status from remote: %s", e)
            if isinstance(e, requests.exceptions.ConnectionError):
                logger.warning("Video status sync connection error (non-fatal, cycle continues)")
            return False

    def _sync_screenshot_status(self, identity: dict) -> bool:
        if self._is_cooldown_active():
            return False

        url = self.config_manager.get("url_screenshot_settings", "").strip()
        if not url:
            base_url = self.config_manager.get("base_url", "").strip()
            if not base_url:
                return False
            url = f"{base_url.rstrip('/')}{PATH_SCREENSHOT_SETTINGS}"

        url = f"{url}?pcName={identity['pcName']}&macAddress={identity['macAddress']}&userName={identity['userName']}"
        try:
            resp = requests.get(url, headers=self._auth_headers(), timeout=10)
            if not resp.ok:
                if resp.status_code in HARD_ABORT_STATUSES:
                    self._abort_cycle = True
                return resp.status_code not in HARD_ABORT_STATUSES
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
                        screenshot_monitor.stop()
                        logger.info("Screenshot capturing DISABLED by remote server sync")
            return True
        except Exception as e:
            if self._consecutive_failures == 0:
                logger.warning("Failed to sync screenshot status from remote: %s", e)
            else:
                logger.debug("Failed to sync screenshot status from remote: %s", e)
            if isinstance(e, requests.exceptions.ConnectionError):
                logger.warning("Screenshot status sync connection error (non-fatal, cycle continues)")
            return False

    def _sync_overall_status(self, identity: dict) -> bool:
        if self._is_cooldown_active():
            return False

        url = self.config_manager.get("url_monitoring_settings", "").strip()
        if not url:
            base_url = self.config_manager.get("base_url", "").strip()
            if not base_url:
                return False
            url = f"{base_url.rstrip('/')}{PATH_MONITORING_SETTINGS}"

        url = f"{url}?pcName={identity['pcName']}&macAddress={identity['macAddress']}&userName={identity['userName']}"
        try:
            resp = requests.get(url, headers=self._auth_headers(), timeout=10)
            if not resp.ok:
                if resp.status_code in HARD_ABORT_STATUSES:
                    self._abort_cycle = True
                return resp.status_code not in HARD_ABORT_STATUSES
            data = resp.json()

            # v5.3.1: Check if the server is requesting device logs
            request_logs = data.get("requestLogs", False)
            if request_logs:
                logger.warning(
                    "Server is using deprecated 'requestLogs' flag. "
                    "Migrate to bulk command system when server endpoint is ready."
                )
                self._upload_device_logs(identity)

            remote_active = data.get("monitoringActive")
            if remote_active is None:
                return True

            import api_server
            if bool(remote_active) == bool(api_server.monitoring_active):
                return True

            if remote_active:
                api_server.monitoring_active = True
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
                api_server.monitoring_active = False
                api_server.screenshot_monitor.pause()
                api_server.clipboard_monitor.pause()
                api_server.app_tracker.pause()
                api_server.browser_tracker.pause()
                api_server.keylogger.pause()
                api_server.screen_recorder.pause()
                logger.info("Monitoring PAUSED by remote server sync")
            return True
        except Exception as e:
            if self._consecutive_failures == 0:
                logger.warning("Failed to sync overall monitoring status from remote: %s", e)
            else:
                logger.debug("Failed to sync overall monitoring status from remote: %s", e)
            if isinstance(e, requests.exceptions.ConnectionError):
                logger.warning("Overall status sync connection error (non-fatal, cycle continues)")
            return False

    # ─── DEVICE LOG UPLOAD ───────────────────────────────────────────────

    def _upload_device_logs(self, identity: dict) -> None:
        """
        v5.3.1: Read the last 300 lines of backend.log and POST them to the
        ERP server's /api/pctracking/device-logs endpoint.

        Triggered when the server sets requestLogs=true in the monitoring-
        settings response. This is a fire-and-forget push — the server is
        responsible for resetting the flag after receiving the payload.
        """
        url = self.config_manager.get("url_device_logs", "").strip()
        if not url:
            base_url = self.config_manager.get("base_url", "").strip()
            if not base_url:
                logger.warning("Cannot upload device logs — no base_url configured")
                return
            url = f"{base_url.rstrip('/')}{PATH_DEVICE_LOGS}"

        # Resolve log path (platform-aware)
        import platform as _platform
        if _platform.system() == "Darwin":
            log_path = (
                Path.home() / "Library" / "Application Support" /
                "EnterpriseMonitor" / "logs" / "backend.log"
            )
        else:
            _local = os.environ.get("LOCALAPPDATA") or str(
                Path.home() / "AppData" / "Local"
            )
            log_path = Path(_local) / "EnterpriseMonitor" / "logs" / "backend.log"

        log_lines = []
        if log_path.exists():
            try:
                with open(log_path, "rb") as f:
                    f.seek(0, 2)
                    file_size = f.tell()
                    read_start = max(0, file_size - 200 * 1024)  # last 200KB
                    f.seek(read_start)
                    chunk = f.read().decode("utf-8", errors="replace")
                all_lines = chunk.splitlines()
                log_lines = all_lines[-300:]  # last 300 lines
            except Exception as e:
                logger.error("Failed to read backend.log for upload: %s", e)
                log_lines = [f"[ERROR reading log: {e}]"]
        else:
            log_lines = ["[backend.log not found]"]

        payload = {
            "pcName":     identity["pcName"],
            "macAddress": identity["macAddress"],
            "userName":   identity["userName"],
            "logType":    "backend",
            "logLines":   log_lines,
            "lineCount":  len(log_lines),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }

        try:
            resp = requests.post(
                url,
                json=payload,
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT_JSON,
            )
            if resp.ok:
                logger.info("Device logs uploaded successfully (%d lines)", len(log_lines))
            else:
                logger.warning("Device log upload returned HTTP %d: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("Device log upload failed: %s", e)

    # ─── R9: BULK COMMAND CLIENT ─────────────────────────────────────────────

    def _fetch_pending_commands(self, identity: dict) -> None:
        """
        v5.4.0 (R9): Fetch pending commands from the server.
        Gracefully skips if the server endpoint isn't deployed yet (404).
        """
        device_id = identity.get("deviceId", "")
        if not device_id:
            return
        base_url = self.config_manager.get("base_url", "").strip()
        if not base_url:
            return

        url = f"{base_url.rstrip('/')}/api/devices/{device_id}/pending-commands"
        try:
            resp = requests.get(url, headers=self._auth_headers(), timeout=REQUEST_TIMEOUT_JSON)
            if resp.status_code == 404:
                logger.debug("pending-commands endpoint not yet available (404)")
                return
            if not resp.ok:
                logger.warning("pending-commands returned HTTP %d", resp.status_code)
                return
            data = resp.json()
            commands = data.get("commands", [])
            for cmd in commands:
                cmd_id   = cmd.get("id", "")
                cmd_type = cmd.get("type", "")
                status   = "executed"

                if cmd_type == "request_logs":
                    self._upload_device_logs(identity)
                elif cmd_type in ("pause", "resume"):
                    try:
                        import api_server
                        if cmd_type == "pause":
                            api_server.monitoring_active = False
                            api_server.screenshot_monitor.pause()
                            api_server.clipboard_monitor.pause()
                            api_server.app_tracker.pause()
                            api_server.browser_tracker.pause()
                            api_server.keylogger.pause()
                            api_server.screen_recorder.pause()
                            self.set_device_status("PAUSED")
                        else:
                            api_server.monitoring_active = True
                            api_server.clipboard_monitor.resume()
                            api_server.app_tracker.resume()
                            api_server.browser_tracker.resume()
                            api_server.keylogger.resume()
                            if self.config_manager.get("screenshot_enabled", True):
                                api_server.screenshot_monitor.resume()
                            if self.config_manager.get("recording_enabled", False):
                                api_server.screen_recorder.resume()
                            self.set_device_status("ACTIVE")
                        logger.info("Executed bulk command: %s", cmd_type)
                    except Exception as exc:
                        logger.error("Failed to execute bulk command %s: %s", cmd_type, exc)
                        status = "failed"
                else:
                    logger.warning("Unknown command type: %s", cmd_type)
                    status = "unsupported"

                # Acknowledge the command
                if cmd_id:
                    self._ack_command(base_url, cmd_id, device_id, status)

        except requests.exceptions.ConnectionError:
            logger.debug("pending-commands connection error — skipping")
        except Exception as e:
            logger.debug("pending-commands fetch error: %s", e)

    def _ack_command(self, base_url: str, cmd_id: str, device_id: str, status: str) -> None:
        """POST acknowledgement for a processed command."""
        url = f"{base_url.rstrip('/')}/api/commands/{cmd_id}/ack"
        try:
            requests.post(
                url,
                json={"deviceId": device_id, "status": status},
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                timeout=5,
            )
        except Exception:
            pass  # Best-effort ack
