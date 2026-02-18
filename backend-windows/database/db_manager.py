"""
Database Manager
Handles SQLite database operations for storing monitoring data

CHANGES:
- FIX #2: get_statistics(date=None) — accepts an optional date string (YYYY-MM-DD).
          Defaults to UTC today if None. This makes the stats cards respect the
          date picker instead of always showing today's data.
- NEW: browser_activity table + insert/query methods.
- NEW: text_logs table + insert/query methods.
- UPDATED: cleanup_old_data and migrations cover new tables.
- IDENTITY: device_config table for device_alias / user_alias (KV store).
- IDENTITY: username column added to all 5 tracking tables via migration.
- IDENTITY: get_identity_config() / update_identity_config() methods.
- All insert methods now accept optional username param (default '').
"""

import sqlite3
import logging
import socket
import getpass
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import json

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self):
        self.db_dir = Path.home() / "AppData" / "Local" / "EnterpriseMonitor"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / "monitoring.db"
        self._initialize_database()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_database(self):
        conn = self._get_connection()
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

        # ── Browser URL tracking ──────────────────────────────────────────────
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS browser_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                browser_name TEXT NOT NULL,
                url TEXT NOT NULL,
                page_title TEXT,
                username TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ── Text / Keystroke logging ──────────────────────────────────────────
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS text_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                application TEXT,
                window_title TEXT,
                content TEXT NOT NULL,
                username TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ── Identity / Alias config (KV store) ────────────────────────────────
        # Keys: "device_alias", "user_alias"
        # Default fallback: hostname / os_user (resolved at query time, not stored here)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_config (
                key   TEXT PRIMARY KEY NOT NULL,
                value TEXT NOT NULL
            )
        ''')

        conn.commit()
        conn.close()
        self._run_migrations()
        logger.info("Database initialized successfully")

    def _run_migrations(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # ── synced column (legacy migration) ─────────────────────────────
            cursor.execute("PRAGMA table_info(screenshots)")
            columns = [info[1] for info in cursor.fetchall()]
            if "synced" not in columns:
                cursor.execute("ALTER TABLE screenshots ADD COLUMN synced INTEGER DEFAULT 0")
                cursor.execute("ALTER TABLE app_activity ADD COLUMN synced INTEGER DEFAULT 0")
                conn.commit()
                logger.info("Migration: added synced columns")

            # ── username column on all 5 tracking tables ──────────────────────
            _tables_needing_username = [
                "screenshots",
                "app_activity",
                "clipboard_events",
                "browser_activity",
                "text_logs",
            ]
            for table in _tables_needing_username:
                cursor.execute(f"PRAGMA table_info({table})")
                existing_cols = [info[1] for info in cursor.fetchall()]
                if "username" not in existing_cols:
                    cursor.execute(
                        f"ALTER TABLE {table} ADD COLUMN username TEXT DEFAULT ''"
                    )
                    logger.info("Migration: added username column to %s", table)

            conn.commit()
        except Exception as e:
            logger.error(f"Migration failed: {e}")
        finally:
            conn.close()

    # ─── IDENTITY CONFIG ─────────────────────────────────────────────────────

    def get_identity_config(self) -> Dict[str, str]:
        """
        Returns resolved identity info.
        Falls back to raw hostname / os_user when no alias is stored.
        """
        raw_machine_id = socket.gethostname()
        raw_os_user    = getpass.getuser()

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT key, value FROM device_config WHERE key IN ('device_alias', 'user_alias')")
            rows = {row["key"]: row["value"] for row in cursor.fetchall()}
        except Exception as e:
            logger.error("Failed to read device_config: %s", e)
            rows = {}
        finally:
            conn.close()

        return {
            "machine_id":    raw_machine_id,
            "os_user":       raw_os_user,
            "device_alias":  rows.get("device_alias") or raw_machine_id,
            "user_alias":    rows.get("user_alias")   or raw_os_user,
        }

    def update_identity_config(self, device_alias: str = None, user_alias: str = None) -> bool:
        """
        Upsert device_alias and/or user_alias into device_config.
        Passing None for either field leaves it unchanged.
        """
        if not device_alias and not user_alias:
            return False

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            if device_alias is not None:
                cursor.execute(
                    "INSERT INTO device_config (key, value) VALUES ('device_alias', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (device_alias,)
                )
            if user_alias is not None:
                cursor.execute(
                    "INSERT INTO device_config (key, value) VALUES ('user_alias', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (user_alias,)
                )
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to update identity config: %s", e)
            conn.rollback()
            return False
        finally:
            conn.close()

    # ─── INSERTS ─────────────────────────────────────────────────────────────

    def insert_screenshot(self, file_path: str, active_window: str, active_app: str,
                          username: str = ''):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO screenshots (timestamp, file_path, active_window, active_app, username, synced)
                VALUES (?, ?, ?, ?, ?, 0)
            ''', (datetime.utcnow().isoformat(), file_path, active_window, active_app, username))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert screenshot: {e}")
            conn.rollback()
        finally:
            conn.close()

    def insert_app_activity(self, app_name: str, window_title: str, duration_seconds: int,
                            username: str = ''):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO app_activity (timestamp, app_name, window_title, duration_seconds, username, synced)
                VALUES (?, ?, ?, ?, ?, 0)
            ''', (datetime.utcnow().isoformat(), app_name, window_title, duration_seconds, username))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert app activity: {e}")
            conn.rollback()
        finally:
            conn.close()

    def insert_clipboard_event(self, content_type: str, content_preview: str,
                               username: str = ''):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO clipboard_events (timestamp, content_type, content_preview, username, synced)
                VALUES (?, ?, ?, ?, 0)
            ''', (datetime.utcnow().isoformat(), content_type, content_preview, username))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert clipboard event: {e}")
            conn.rollback()
        finally:
            conn.close()

    def insert_browser_activity(self, browser_name: str, url: str, page_title: str,
                                username: str = ''):
        """Record a browser URL visit."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO browser_activity (timestamp, browser_name, url, page_title, username)
                VALUES (?, ?, ?, ?, ?)
            ''', (datetime.utcnow().isoformat(), browser_name, url, page_title, username))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert browser activity: {e}")
            conn.rollback()
        finally:
            conn.close()

    def insert_text_log(self, application: str, window_title: str, content: str,
                        username: str = ''):
        """Record a buffered keystroke/text entry."""
        if not content or not content.strip():
            return
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO text_logs (timestamp, application, window_title, content, username)
                VALUES (?, ?, ?, ?, ?)
            ''', (datetime.utcnow().isoformat(), application, window_title, content, username))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert text log: {e}")
            conn.rollback()
        finally:
            conn.close()

    # ─── QUERIES ─────────────────────────────────────────────────────────────

    def get_screenshots(self, limit: int = 20, offset: int = 0) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT id, timestamp, file_path, active_window, active_app, username
                FROM screenshots
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "file_path": row[2],
                    "active_window": row[3],
                    "active_app": row[4],
                    "username": row[5],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get screenshots: {e}")
            return []
        finally:
            conn.close()

    def get_app_activity_logs(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT id, timestamp, app_name, window_title, duration_seconds, username
                FROM app_activity
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "app_name": row[2],
                    "window_title": row[3],
                    "duration_seconds": row[4],
                    "username": row[5],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get app activity logs: {e}")
            return []
        finally:
            conn.close()

    def get_clipboard_logs(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT id, timestamp, content_type, content_preview, username
                FROM clipboard_events
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "content_type": row[2],
                    "content_preview": row[3],
                    "username": row[4],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get clipboard logs: {e}")
            return []
        finally:
            conn.close()

    def get_browser_activity_logs(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Return browser URL history, newest first."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT id, timestamp, browser_name, url, page_title, username
                FROM browser_activity
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "browser_name": row[2],
                    "url": row[3],
                    "page_title": row[4],
                    "username": row[5],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get browser activity logs: {e}")
            return []
        finally:
            conn.close()

    def get_text_logs(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Return keystroke/text logs, newest first."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT id, timestamp, application, window_title, content, username
                FROM text_logs
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            ''', (limit, offset))
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "application": row[2],
                    "window_title": row[3],
                    "content": row[4],
                    "username": row[5],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get text logs: {e}")
            return []
        finally:
            conn.close()

    # ─── STATISTICS ──────────────────────────────────────────────────────────

    def get_statistics(self, date: Optional[str] = None) -> Dict:
        """
        Return summary stats for a given date (YYYY-MM-DD).
        Defaults to UTC today if date is None.
        """
        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")

        start_ts = f"{date}T00:00:00"
        end_ts   = f"{date}T23:59:59"

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM screenshots WHERE timestamp BETWEEN ? AND ?",
                (start_ts, end_ts)
            )
            screenshots_today = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COALESCE(SUM(duration_seconds), 0) FROM app_activity WHERE timestamp BETWEEN ? AND ?",
                (start_ts, end_ts)
            )
            total_seconds = cursor.fetchone()[0]
            active_hours  = round(total_seconds / 3600, 2)

            cursor.execute(
                "SELECT COUNT(DISTINCT app_name) FROM app_activity WHERE timestamp BETWEEN ? AND ?",
                (start_ts, end_ts)
            )
            apps_tracked = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM clipboard_events WHERE timestamp BETWEEN ? AND ?",
                (start_ts, end_ts)
            )
            clipboard_events = cursor.fetchone()[0]

            return {
                "screenshots_today":  screenshots_today,
                "active_hours_today": active_hours,
                "apps_tracked":       apps_tracked,
                "clipboard_events":   clipboard_events,
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {
                "screenshots_today":  0,
                "active_hours_today": 0.0,
                "apps_tracked":       0,
                "clipboard_events":   0,
            }
        finally:
            conn.close()

    def get_activity_stats(self, start: str, end: str) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            start_ts = f"{start}T00:00:00"
            end_ts   = f"{end}T23:59:59"
            cursor.execute('''
                SELECT app_name, SUM(duration_seconds) as total_duration
                FROM app_activity
                WHERE timestamp BETWEEN ? AND ?
                GROUP BY app_name
                ORDER BY total_duration DESC
            ''', (start_ts, end_ts))
            rows = cursor.fetchall()
            return [{"app_name": row[0], "total_seconds": row[1]} for row in rows]
        except Exception as e:
            logger.error(f"Failed to get activity stats: {e}")
            return []
        finally:
            conn.close()

    def get_timeline_data(self, date: str) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            start_ts = f"{date}T00:00:00"
            end_ts   = f"{date}T23:59:59"
            cursor.execute('''
                SELECT timestamp, app_name, window_title, duration_seconds
                FROM app_activity
                WHERE timestamp BETWEEN ? AND ?
                ORDER BY timestamp ASC
            ''', (start_ts, end_ts))
            rows = cursor.fetchall()
            return [
                {
                    "timestamp":        row[0],
                    "app_name":         row[1],
                    "window_title":     row[2],
                    "duration_seconds": row[3],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get timeline data: {e}")
            return []
        finally:
            conn.close()

    # ─── SYNC HELPERS ────────────────────────────────────────────────────────

    def get_unsynced_data(self, limit: int = 10) -> Dict:
        conn = self._get_connection()
        cursor = conn.cursor()
        data: Dict = {}
        try:
            cursor.execute('SELECT * FROM screenshots WHERE synced = 0 LIMIT ?', (limit,))
            data["screenshots"] = [dict(row) for row in cursor.fetchall()]

            cursor.execute('SELECT * FROM app_activity WHERE synced = 0 LIMIT ?', (limit,))
            data["app_activity"] = [dict(row) for row in cursor.fetchall()]

            cursor.execute('SELECT * FROM clipboard_events WHERE synced = 0 LIMIT ?', (limit,))
            data["clipboard_events"] = [dict(row) for row in cursor.fetchall()]

            return data
        except Exception as e:
            logger.error(f"Failed to get unsynced data: {e}")
            return data
        finally:
            conn.close()

    def mark_as_synced(self, table: str, ids: List[int]):
        if not ids:
            return
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            placeholders = ','.join(['?'] * len(ids))
            cursor.execute(
                f"UPDATE {table} SET synced = 1 WHERE id IN ({placeholders})",
                ids
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to mark data as synced: {e}")
            conn.rollback()
        finally:
            conn.close()

    def cleanup_old_data(self, days: int = 7):
        conn = self._get_connection()
        cursor = conn.cursor()
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        try:
            cursor.execute("DELETE FROM screenshots       WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM app_activity      WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM clipboard_events  WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM browser_activity  WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM text_logs         WHERE timestamp < ?", (cutoff,))
            conn.commit()
            logger.info(f"Cleanup: removed records older than {days} days")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            conn.rollback()
        finally:
            conn.close()
