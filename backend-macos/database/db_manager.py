"""
Database Manager — macOS version
Handles SQLite database operations for storing monitoring data.

CHANGES from Windows version:
- Path changed from LOCALAPPDATA → ~/Library/Application Support/EnterpriseMonitor

v5.2.7 PARITY PATCHES:
- get_identity_config() now returns mac_address (was always empty on Mac)
- cleanup_old_data() now runs orphan file sweep (Step 6) matching Windows behaviour

THREAD-SAFETY:
  - ONE persistent connection shared by the entire process lifetime.
  - check_same_thread=False — we own synchronisation via _lock.
  - WAL mode — allows readers to not block writers.
  - threading.Lock — serialises every cursor operation.
"""

import sqlite3
import threading
import logging
import socket
import getpass
import uuid
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import json

logger = logging.getLogger(__name__)


class DatabaseManager:

    def __init__(self):
        self.db_dir = Path.home() / 'Library' / 'Application Support' / 'EnterpriseMonitor'
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / "monitoring.db"

        # ── Thread safety primitives ──────────────────────────────────────────
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,   # We own the synchronisation via _lock
        )
        self._conn.row_factory = sqlite3.Row

        # WAL mode: readers never block writers; writers never block readers.
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")  # safe with WAL
            self._conn.commit()

        self._initialize_database()

    # ─── Public initialization (called by api_server lifespan) ────────────────

    def initialize(self) -> None:
        """Public wrapper — safe to call multiple times (CREATE IF NOT EXISTS)."""
        self._initialize_database()

    # ─── Connection accessor (returns the shared persistent connection) ───────

    def _get_connection(self) -> sqlite3.Connection:
        return self._conn

    # ─── Schema setup ─────────────────────────────────────────────────────────

    def _initialize_database(self):
        with self._lock:
            conn   = self._conn
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS screenshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    active_window TEXT,
                    active_app TEXT,
                    username TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    synced INTEGER DEFAULT 0
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS app_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    app_name TEXT NOT NULL,
                    window_title TEXT,
                    duration_seconds INTEGER DEFAULT 0,
                    username TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    synced INTEGER DEFAULT 0
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS clipboard_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    content_type TEXT,
                    content_preview TEXT,
                    username TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    synced INTEGER DEFAULT 0
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS browser_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    browser_name TEXT,
                    url TEXT,
                    page_title TEXT,
                    username TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    synced INTEGER DEFAULT 0
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS text_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    application TEXT,
                    window_title TEXT,
                    content TEXT,
                    username TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    synced INTEGER DEFAULT 0
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS video_recordings (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT NOT NULL,
                    file_path       TEXT NOT NULL,
                    duration_seconds INTEGER DEFAULT 0,
                    is_synced       INTEGER DEFAULT 0,
                    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS device_config (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')

            conn.commit()

        self._run_migrations()
        logger.info("Database initialised (WAL mode, shared connection, thread-safe lock).")

    def _run_migrations(self):
        with self._lock:
            conn   = self._conn
            cursor = conn.cursor()
            try:
                # ── synced column (legacy) ────────────────────────────────────
                cursor.execute("PRAGMA table_info(screenshots)")
                if "synced" not in [r[1] for r in cursor.fetchall()]:
                    cursor.execute("ALTER TABLE screenshots ADD COLUMN synced INTEGER DEFAULT 0")
                    cursor.execute("ALTER TABLE app_activity ADD COLUMN synced INTEGER DEFAULT 0")
                    conn.commit()
                    logger.info("Migration: added synced columns to screenshots/app_activity")

                # ── username column on all tracking tables ────────────────────
                for table in ("screenshots", "app_activity", "clipboard_events",
                               "browser_activity", "text_logs"):
                    cursor.execute(f"PRAGMA table_info({table})")
                    if "username" not in [r[1] for r in cursor.fetchall()]:
                        cursor.execute(
                            f"ALTER TABLE {table} ADD COLUMN username TEXT DEFAULT ''"
                        )
                        logger.info("Migration: added username to %s", table)

                # ── synced column on browser_activity + text_logs ─────────────
                for tbl in ("browser_activity", "text_logs"):
                    cursor.execute(f"PRAGMA table_info({tbl})")
                    if "synced" not in [r[1] for r in cursor.fetchall()]:
                        cursor.execute(
                            f"ALTER TABLE {tbl} ADD COLUMN synced INTEGER DEFAULT 0"
                        )
                        logger.info("Migration: added synced to %s", tbl)

                conn.commit()
            except Exception as exc:
                logger.error("Migration error: %s", exc)

    # ─── IDENTITY CONFIG ──────────────────────────────────────────────────────

    def get_identity_config(self) -> Dict[str, str]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT key, value FROM device_config")
            rows = {r["key"]: r["value"] for r in cursor.fetchall()}

        # v5.2.7: compute MAC address the same way as the Windows backend
        mac_address = ':'.join(
            '{:02x}'.format((uuid.getnode() >> ele) & 0xff)
            for ele in reversed(range(0, 8 * 6, 8))
        )

        return {
            "machine_id":     socket.gethostname(),
            "mac_address":    mac_address,
            "os_user":        getpass.getuser(),
            "device_alias":   rows.get("device_alias", ""),
            "user_alias":     rows.get("user_alias", ""),
            "login_username": rows.get("login_username", ""),
        }

    def update_identity_config(
        self,
        device_alias: Optional[str] = None,
        user_alias:   Optional[str] = None,
    ) -> bool:
        if not device_alias and not user_alias:
            return False
        with self._lock:
            cursor = self._conn.cursor()
            try:
                if device_alias is not None:
                    cursor.execute(
                        "INSERT INTO device_config (key, value) VALUES ('device_alias', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (device_alias,),
                    )
                if user_alias is not None:
                    cursor.execute(
                        "INSERT INTO device_config (key, value) VALUES ('user_alias', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (user_alias,),
                    )
                self._conn.commit()
                return True
            except Exception as exc:
                logger.error("update_identity_config: %s", exc)
                self._conn.rollback()
                return False

    def update_login_username(self, username: str) -> bool:
        """Persist the app-auth username after a successful login."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO device_config (key, value) VALUES ('login_username', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (username,),
                )
                self._conn.commit()
                return True
            except Exception as exc:
                logger.error("update_login_username: %s", exc)
                self._conn.rollback()
                return False

    # ─── INSERTS ──────────────────────────────────────────────────────────────

    def insert_screenshot(self, file_path: str, active_window: str, active_app: str,
                          username: str = '') -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO screenshots "
                    "(timestamp, file_path, active_window, active_app, username, synced) "
                    "VALUES (?, ?, ?, ?, ?, 0)",
                    (datetime.utcnow().isoformat(), file_path, active_window, active_app, username),
                )
                self._conn.commit()
            except Exception as exc:
                logger.error("insert_screenshot: %s", exc)
                self._conn.rollback()

    def insert_app_activity(self, app_name: str, window_title: str, duration_seconds: int,
                            username: str = '') -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO app_activity "
                    "(timestamp, app_name, window_title, duration_seconds, username, synced) "
                    "VALUES (?, ?, ?, ?, ?, 0)",
                    (datetime.utcnow().isoformat(), app_name, window_title, duration_seconds, username),
                )
                self._conn.commit()
            except Exception as exc:
                logger.error("insert_app_activity: %s", exc)
                self._conn.rollback()

    def insert_clipboard_event(self, content_type: str, content_preview: str,
                               username: str = '') -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO clipboard_events "
                    "(timestamp, content_type, content_preview, username, synced) "
                    "VALUES (?, ?, ?, ?, 0)",
                    (datetime.utcnow().isoformat(), content_type, content_preview, username),
                )
                self._conn.commit()
            except Exception as exc:
                logger.error("insert_clipboard_event: %s", exc)
                self._conn.rollback()

    def insert_browser_activity(self, browser_name: str, url: str, page_title: str,
                                username: str = '') -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO browser_activity "
                    "(timestamp, browser_name, url, page_title, username, synced) "
                    "VALUES (?, ?, ?, ?, ?, 0)",
                    (datetime.utcnow().isoformat(), browser_name, url, page_title, username),
                )
                self._conn.commit()
            except Exception as exc:
                logger.error("insert_browser_activity: %s", exc)
                self._conn.rollback()

    def insert_text_log(self, application: str, window_title: str, content: str,
                        username: str = '') -> None:
        if not content or not content.strip():
            return
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO text_logs "
                    "(timestamp, application, window_title, content, username, synced) "
                    "VALUES (?, ?, ?, ?, ?, 0)",
                    (datetime.utcnow().isoformat(), application, window_title, content, username),
                )
                self._conn.commit()
            except Exception as exc:
                logger.error("insert_text_log: %s", exc)
                self._conn.rollback()

    def insert_video_recording(self, timestamp: str, file_path: str,
                                duration_seconds: int) -> None:
        """Insert a completed recording chunk into video_recordings."""
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO video_recordings (timestamp, file_path, duration_seconds) "
                    "VALUES (?, ?, ?)",
                    (timestamp, file_path, duration_seconds),
                )
                self._conn.commit()
            except Exception as exc:
                logger.error("insert_video_recording: %s", exc)
                self._conn.rollback()

    # ─── QUERIES ──────────────────────────────────────────────────────────────

    def get_screenshots(self, limit: int = 20, offset: int = 0) -> List[Dict]:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT id, timestamp, file_path, active_window, active_app, username, synced "
                    "FROM screenshots ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
                return [
                    {
                        "id": r[0], "timestamp": r[1], "file_path": r[2],
                        "active_window": r[3], "active_app": r[4], "username": r[5],
                        "synced": bool(r[6]),
                    }
                    for r in cursor.fetchall()
                ]
            except Exception as exc:
                logger.error("get_screenshots: %s", exc)
                return []

    def get_app_activity_logs(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT id, timestamp, app_name, window_title, duration_seconds, username "
                    "FROM app_activity ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
                return [
                    {
                        "id": r[0], "timestamp": r[1], "app_name": r[2],
                        "window_title": r[3], "duration_seconds": r[4], "username": r[5],
                    }
                    for r in cursor.fetchall()
                ]
            except Exception as exc:
                logger.error("get_app_activity_logs: %s", exc)
                return []

    def get_clipboard_logs(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT id, timestamp, content_type, content_preview, username "
                    "FROM clipboard_events ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
                return [
                    {
                        "id": r[0], "timestamp": r[1], "content_type": r[2],
                        "content_preview": r[3], "username": r[4],
                    }
                    for r in cursor.fetchall()
                ]
            except Exception as exc:
                logger.error("get_clipboard_logs: %s", exc)
                return []

    def get_browser_activity(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT id, timestamp, browser_name, url, page_title, username "
                    "FROM browser_activity ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
                return [
                    {
                        "id": r[0], "timestamp": r[1], "browser_name": r[2],
                        "url": r[3], "page_title": r[4], "username": r[5],
                    }
                    for r in cursor.fetchall()
                ]
            except Exception as exc:
                logger.error("get_browser_activity: %s", exc)
                return []

    def get_text_logs(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT id, timestamp, application, window_title, content, username "
                    "FROM text_logs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
                return [
                    {
                        "id": r[0], "timestamp": r[1], "application": r[2],
                        "window_title": r[3], "content": r[4], "username": r[5],
                    }
                    for r in cursor.fetchall()
                ]
            except Exception as exc:
                logger.error("get_text_logs: %s", exc)
                return []

    def get_video_recordings(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT id, timestamp, file_path, duration_seconds, is_synced "
                    "FROM video_recordings ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
                return [
                    {
                        "id": r[0], "timestamp": r[1], "file_path": r[2],
                        "duration_seconds": r[3], "is_synced": bool(r[4]),
                    }
                    for r in cursor.fetchall()
                ]
            except Exception as exc:
                logger.error("get_video_recordings: %s", exc)
                return []

    def get_statistics(self, date: Optional[str] = None) -> Dict:
        target_date = date or datetime.utcnow().strftime("%Y-%m-%d")
        start_ts = f"{target_date}T00:00:00"
        end_ts   = f"{target_date}T23:59:59"

        with self._lock:
            try:
                c = self._conn
                screenshots = c.execute(
                    "SELECT COUNT(*) FROM screenshots WHERE timestamp BETWEEN ? AND ?",
                    (start_ts, end_ts),
                ).fetchone()[0]

                app_sessions = c.execute(
                    "SELECT COUNT(*) FROM app_activity WHERE timestamp BETWEEN ? AND ?",
                    (start_ts, end_ts),
                ).fetchone()[0]

                active_time = c.execute(
                    "SELECT COALESCE(SUM(duration_seconds), 0) FROM app_activity "
                    "WHERE timestamp BETWEEN ? AND ?",
                    (start_ts, end_ts),
                ).fetchone()[0]

                clipboard_events = c.execute(
                    "SELECT COUNT(*) FROM clipboard_events WHERE timestamp BETWEEN ? AND ?",
                    (start_ts, end_ts),
                ).fetchone()[0]

                browser_visits = c.execute(
                    "SELECT COUNT(*) FROM browser_activity WHERE timestamp BETWEEN ? AND ?",
                    (start_ts, end_ts),
                ).fetchone()[0]

                keystrokes = c.execute(
                    "SELECT COUNT(*) FROM text_logs WHERE timestamp BETWEEN ? AND ?",
                    (start_ts, end_ts),
                ).fetchone()[0]

                return {
                    "date":             target_date,
                    "screenshots":      screenshots,
                    "app_sessions":     app_sessions,
                    "active_time":      active_time,
                    "clipboard_events": clipboard_events,
                    "browser_visits":   browser_visits,
                    "keystrokes":       keystrokes,
                }
            except Exception as exc:
                logger.error("get_statistics: %s", exc)
                return {}

    def get_activity_stats(self, start: str, end: str) -> List[Dict]:
        start_ts = f"{start}T00:00:00" if "T" not in start else start
        end_ts   = f"{end}T23:59:59"   if "T" not in end   else end
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT app_name, SUM(duration_seconds) as total_duration "
                    "FROM app_activity WHERE timestamp BETWEEN ? AND ? "
                    "GROUP BY app_name ORDER BY total_duration DESC",
                    (start_ts, end_ts),
                )
                return [{"app_name": r[0], "total_seconds": r[1]} for r in cursor.fetchall()]
            except Exception as exc:
                logger.error("get_activity_stats: %s", exc)
                return []

    def get_timeline_data(self, date: str) -> List[Dict]:
        start_ts = f"{date}T00:00:00"
        end_ts   = f"{date}T23:59:59"
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT timestamp, app_name, window_title, duration_seconds "
                    "FROM app_activity WHERE timestamp BETWEEN ? AND ? "
                    "ORDER BY timestamp ASC",
                    (start_ts, end_ts),
                )
                return [
                    {
                        "timestamp": r[0], "app_name": r[1],
                        "window_title": r[2], "duration_seconds": r[3],
                    }
                    for r in cursor.fetchall()
                ]
            except Exception as exc:
                logger.error("get_timeline_data: %s", exc)
                return []

    # ─── SYNC HELPERS ─────────────────────────────────────────────────────────

    def get_unsynced_screenshots(self, limit: int = 20) -> List[Dict]:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT * FROM screenshots WHERE synced = 0 ORDER BY timestamp ASC LIMIT ?",
                    (limit,),
                )
                return [dict(r) for r in cursor.fetchall()]
            except Exception as exc:
                logger.error("get_unsynced_screenshots: %s", exc)
                return []

    def get_unsynced_app_activity(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT * FROM app_activity WHERE synced = 0 ORDER BY timestamp ASC LIMIT ?",
                    (limit,),
                )
                return [dict(r) for r in cursor.fetchall()]
            except Exception as exc:
                logger.error("get_unsynced_app_activity: %s", exc)
                return []

    def get_unsynced_browser(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT * FROM browser_activity WHERE synced = 0 ORDER BY timestamp ASC LIMIT ?",
                    (limit,),
                )
                return [dict(r) for r in cursor.fetchall()]
            except Exception as exc:
                logger.error("get_unsynced_browser: %s", exc)
                return []

    def get_unsynced_clipboard(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT * FROM clipboard_events WHERE synced = 0 ORDER BY timestamp ASC LIMIT ?",
                    (limit,),
                )
                return [dict(r) for r in cursor.fetchall()]
            except Exception as exc:
                logger.error("get_unsynced_clipboard: %s", exc)
                return []

    def get_unsynced_keystrokes(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT * FROM text_logs WHERE synced = 0 ORDER BY timestamp ASC LIMIT ?",
                    (limit,),
                )
                return [dict(r) for r in cursor.fetchall()]
            except Exception as exc:
                logger.error("get_unsynced_keystrokes: %s", exc)
                return []

    def get_unsynced_videos(self, limit: int = 5) -> List[Dict]:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT * FROM video_recordings WHERE is_synced = 0 "
                    "ORDER BY timestamp ASC LIMIT ?",
                    (limit,),
                )
                return [dict(r) for r in cursor.fetchall()]
            except Exception as exc:
                logger.error("get_unsynced_videos: %s", exc)
                return []

    def get_unsynced_data(self, limit: int = 10) -> Dict:
        """Legacy method — kept for backward compat with SyncService v1."""
        return {
            "screenshots":    self.get_unsynced_screenshots(limit),
            "app_activity":   self.get_unsynced_app_activity(limit),
            "clipboard_events": self.get_unsynced_clipboard(limit),
        }

    def mark_as_synced(self, table: str, ids: List[int]) -> None:
        if not ids:
            return
        with self._lock:
            try:
                placeholders = ",".join(["?"] * len(ids))
                self._conn.execute(
                    f"UPDATE {table} SET synced = 1 WHERE id IN ({placeholders})", ids
                )
                self._conn.commit()
            except Exception as exc:
                logger.error("mark_as_synced(%s): %s", table, exc)
                self._conn.rollback()

    def mark_videos_synced(self, ids: List[int]) -> None:
        if not ids:
            return
        with self._lock:
            try:
                placeholders = ",".join(["?"] * len(ids))
                self._conn.execute(
                    f"UPDATE video_recordings SET is_synced = 1 WHERE id IN ({placeholders})", ids
                )
                self._conn.commit()
            except Exception as exc:
                logger.error("mark_videos_synced: %s", exc)
                self._conn.rollback()

    # ─── MAINTENANCE ──────────────────────────────────────────────────────────

    def delete_screenshot(self, screenshot_id: int) -> bool:
        """Delete a screenshot record by ID and remove the file from disk."""
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT file_path FROM screenshots WHERE id = ?", (screenshot_id,)
                )
                row = cursor.fetchone()
                if not row:
                    return False
                file_path = row[0]
                self._conn.execute("DELETE FROM screenshots WHERE id = ?", (screenshot_id,))
                self._conn.commit()
                # Remove the file from disk
                if file_path:
                    p = Path(file_path)
                    if p.exists():
                        p.unlink()
                return True
            except Exception as exc:
                logger.error("delete_screenshot(%d): %s", screenshot_id, exc)
                self._conn.rollback()
                return False

    def delete_old_records(self, table: str, cutoff: str) -> int:
        """Delete records older than cutoff from the given table. Returns count deleted."""
        allowed_tables = {
            "screenshots", "app_activity", "clipboard_events",
            "browser_activity", "text_logs",
        }
        if table not in allowed_tables:
            logger.error("delete_old_records: unknown table %s", table)
            return 0
        with self._lock:
            try:
                cursor = self._conn.execute(
                    f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,)
                )
                self._conn.commit()
                return cursor.rowcount
            except Exception as exc:
                logger.error("delete_old_records(%s): %s", table, exc)
                self._conn.rollback()
                return 0

    def cleanup_old_data(self, synced_hours: int = 2, unsynced_days: int = 7) -> None:
        """
        Intelligent cleanup with two-tier retention:
        - Synced records: removed after `synced_hours` (default 2 hours).
        - Unsynced records: removed after `unsynced_days` (default 7 days).
        Physical .jpg/.png and .mp4 files are deleted from disk first, then DB rows
        are purged. Step 6 sweeps orphan files not tracked by the DB.
        """
        now = datetime.utcnow()
        synced_cutoff   = (now - timedelta(hours=synced_hours)).isoformat()
        unsynced_cutoff = (now - timedelta(days=unsynced_days)).isoformat()

        with self._lock:
            try:
                deleted_ss_files    = []
                deleted_video_files = []

                # ── 1. Delete physical files for expired screenshots ──────────
                failed_ss_ids = []
                for row in self._conn.execute(
                    "SELECT id, file_path FROM screenshots WHERE "
                    "  (synced = 1 AND timestamp < ?) OR "
                    "  (synced = 0 AND timestamp < ?)",
                    (synced_cutoff, unsynced_cutoff),
                ).fetchall():
                    row_id, fp = row[0], row[1]
                    if fp:
                        p = Path(fp)
                        if p.exists():
                            try:
                                p.unlink()
                                deleted_ss_files.append(fp)
                            except OSError as e:
                                logger.warning("Could not delete screenshot file %s: %s", fp, e)
                                failed_ss_ids.append(row_id)
                        else:
                            logger.debug("Screenshot file already missing: %s", fp)

                # ── 2. Delete physical files for expired video recordings ─────
                failed_video_ids = []
                for row in self._conn.execute(
                    "SELECT id, file_path FROM video_recordings WHERE "
                    "  (is_synced = 1 AND timestamp < ?) OR "
                    "  (is_synced = 0 AND timestamp < ?)",
                    (synced_cutoff, unsynced_cutoff),
                ).fetchall():
                    row_id, fp = row[0], row[1]
                    if fp:
                        p = Path(fp)
                        if p.exists():
                            try:
                                p.unlink()
                                deleted_video_files.append(fp)
                            except OSError as e:
                                logger.warning("Could not delete video file %s: %s", fp, e)
                                failed_video_ids.append(row_id)
                        else:
                            logger.debug("Video file already missing: %s", fp)

                # ── 3. Purge screenshot DB rows ───────────────────────────────
                ss_query = (
                    "DELETE FROM screenshots WHERE "
                    "  ((synced = 1 AND timestamp < ?) OR "
                    "  (synced = 0 AND timestamp < ?))"
                )
                if failed_ss_ids:
                    placeholders = ",".join(["?"] * len(failed_ss_ids))
                    ss_query += f" AND id NOT IN ({placeholders})"
                    ss_cur = self._conn.execute(ss_query, (synced_cutoff, unsynced_cutoff, *failed_ss_ids))
                else:
                    ss_cur = self._conn.execute(ss_query, (synced_cutoff, unsynced_cutoff))
                ss_deleted = ss_cur.rowcount

                # ── 4. Purge video_recordings DB rows ─────────────────────────
                vid_query = (
                    "DELETE FROM video_recordings WHERE "
                    "  ((is_synced = 1 AND timestamp < ?) OR "
                    "  (is_synced = 0 AND timestamp < ?))"
                )
                if failed_video_ids:
                    placeholders = ",".join(["?"] * len(failed_video_ids))
                    vid_query += f" AND id NOT IN ({placeholders})"
                    vid_cur = self._conn.execute(vid_query, (synced_cutoff, unsynced_cutoff, *failed_video_ids))
                else:
                    vid_cur = self._conn.execute(vid_query, (synced_cutoff, unsynced_cutoff))
                vid_deleted = vid_cur.rowcount

                # ── 5. Purge text-only tables (no physical files) ─────────────
                text_deleted_total = 0
                for table in ("app_activity", "clipboard_events", "browser_activity", "text_logs"):
                    cur = self._conn.execute(
                        f"DELETE FROM {table} WHERE "
                        f"  (synced = 1 AND timestamp < ?) OR "
                        f"  (synced = 0 AND timestamp < ?)",
                        (synced_cutoff, unsynced_cutoff),
                    )
                    text_deleted_total += cur.rowcount

                self._conn.commit()

                # ── 6. Sweep orphan files from physical directories ────────────
                # v5.2.7: matches Windows behaviour — removes files on disk that
                # have no DB record (e.g. written by a thread that crashed before
                # the INSERT committed).
                orphan_delete_count = 0
                max_retention_seconds = unsynced_days * 86400
                cutoff_time = now.timestamp() - max_retention_seconds

                for target_folder in ("screenshots", "videos"):
                    folder_path = self.db_dir / target_folder
                    if folder_path.exists() and folder_path.is_dir():
                        for file_path in folder_path.iterdir():
                            if file_path.is_file() and file_path.suffix.lower() in ('.jpg', '.png', '.mp4'):
                                try:
                                    if file_path.stat().st_mtime < cutoff_time:
                                        file_path.unlink()
                                        orphan_delete_count += 1
                                except OSError as e:
                                    logger.warning("Could not delete orphaned file %s: %s", file_path, e)

                logger.info(
                    "Cleanup done (synced >%dh, unsynced >%dd). "
                    "DB rows removed: %d SS, %d Videos, %d Text. "
                    "Physical files deleted: %d SS, %d Videos, %d Orphans.",
                    synced_hours, unsynced_days,
                    ss_deleted, vid_deleted, text_deleted_total,
                    len(deleted_ss_files), len(deleted_video_files), orphan_delete_count,
                )

                if deleted_ss_files:
                    sample = ", ".join(deleted_ss_files[:10])
                    if len(deleted_ss_files) > 10:
                        sample += f" ...and {len(deleted_ss_files) - 10} more"
                    logger.info("Deleted screenshot files: %s", sample)

                if deleted_video_files:
                    sample = ", ".join(deleted_video_files[:10])
                    if len(deleted_video_files) > 10:
                        sample += f" ...and {len(deleted_video_files) - 10} more"
                    logger.info("Deleted video files: %s", sample)

            except Exception as exc:
                logger.error("cleanup_old_data: %s", exc)
                self._conn.rollback()

    def close(self) -> None:
        """Explicitly close the persistent connection (call on process shutdown)."""
        with self._lock:
            try:
                self._conn.close()
                logger.info("Database connection closed.")
            except Exception:
                pass
