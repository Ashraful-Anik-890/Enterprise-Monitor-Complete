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
import subprocess
import re
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
        self._apply_shared_machine_identity()

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

            # Check if this is a brand new database BEFORE creating tables
            cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='screenshots'")
            is_fresh_install = cursor.fetchone()[0] == 0

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

            # Seed the default sync state based on installation type
            if is_fresh_install:
                cursor.execute("INSERT OR IGNORE INTO device_config (key, value) VALUES ('sync_enabled', 'false')")
            else:
                cursor.execute("INSERT OR IGNORE INTO device_config (key, value) VALUES ('sync_enabled', 'true')")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_summary (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    date          TEXT    NOT NULL UNIQUE,
                    screenshots   INTEGER DEFAULT 0,
                    app_sessions  INTEGER DEFAULT 0,
                    active_time   INTEGER DEFAULT 0,
                    clipboard_events INTEGER DEFAULT 0,
                    browser_visits   INTEGER DEFAULT 0,
                    keystrokes       INTEGER DEFAULT 0,
                    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_app_summary (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    date          TEXT NOT NULL,
                    app_name      TEXT NOT NULL,
                    total_seconds INTEGER DEFAULT 0,
                    UNIQUE(date, app_name)
                )
            ''')

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version    INTEGER PRIMARY KEY,
                    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()

        self._run_migrations()
        logger.info("Database initialised (WAL mode, shared connection, thread-safe lock).")

    LATEST_SCHEMA_VERSION = 6

    def _get_schema_version(self) -> int:
        """
        Returns the highest applied migration version, or 0 if none have run.
        Called without holding self._lock — callers acquire it.
        """
        try:
            row = self._conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
            return row[0] if row and row[0] is not None else 0
        except Exception:
            # schema_version table not yet created (very first boot before _initialize_database ran)
            return 0

    def _run_migrations(self) -> None:
        """
        Versioned migration runner.

        Applies all migrations with version > current schema version, in order.
        Each migration is atomic: if it fails, the version is NOT recorded and the
        next boot retries from that version.
        """
        with self._lock:
            current = self._get_schema_version()

            if current >= self.LATEST_SCHEMA_VERSION:
                return  # Nothing to do

            logger.info("Schema migration: current=%d, target=%d", current, self.LATEST_SCHEMA_VERSION)

            for target in range(current + 1, self.LATEST_SCHEMA_VERSION + 1):
                try:
                    if target == 1:
                        # v1: Add synced columns to screenshots and app_activity
                        self._migrate_v1_synced_columns()

                    elif target == 2:
                        # v2: Add username column to all tracking tables
                        self._migrate_v2_username_columns()

                    elif target == 3:
                        # v3: Add synced column to browser_activity and text_logs
                        self._migrate_v3_browser_textlog_synced()

                    elif target == 4:
                        # v4: Add daily_summary and daily_app_summary tables
                        self._migrate_v4_daily_summary_tables()

                    elif target == 5:
                        # v5: Add schema_version table itself + seed current version
                        self._migrate_v5_schema_version_table()

                    elif target == 6:
                        # v6: Add failure_count to screenshots and video_recordings
                        self._migrate_v6_failure_count()

                    # Record successful migration
                    self._conn.execute(
                        "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                        (target,),
                    )
                    self._conn.commit()
                    logger.info("Migration v%d applied successfully", target)

                except Exception as exc:
                    self._conn.rollback()
                    logger.error(
                        "Migration v%d FAILED — will retry on next boot: %s", target, exc
                    )
                    break

    # ─── INDIVIDUAL MIGRATION HELPERS ────────────────────────────────────────────

    def _col_exists(self, table: str, column: str) -> bool:
        """Returns True if `column` exists in `table`. Safe to call inside _lock."""
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r[1] == column for r in rows)

    def _migrate_v1_synced_columns(self) -> None:
        """Add synced INTEGER DEFAULT 0 to screenshots and app_activity."""
        for tbl in ("screenshots", "app_activity"):
            if not self._col_exists(tbl, "synced"):
                self._conn.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN synced INTEGER DEFAULT 0"
                )
                logger.info("v1: added synced to %s", tbl)

    def _migrate_v2_username_columns(self) -> None:
        """Add username TEXT DEFAULT '' to all tracking tables."""
        tables = ("screenshots", "app_activity", "clipboard_events",
                  "browser_activity", "text_logs", "video_recordings")
        for tbl in tables:
            if not self._col_exists(tbl, "username"):
                self._conn.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN username TEXT DEFAULT ''"
                )
                logger.info("v2: added username to %s", tbl)

    def _migrate_v3_browser_textlog_synced(self) -> None:
        """Add synced column to browser_activity and text_logs."""
        for tbl in ("browser_activity", "text_logs"):
            if not self._col_exists(tbl, "synced"):
                self._conn.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN synced INTEGER DEFAULT 0"
                )
                logger.info("v3: added synced to %s", tbl)

    def _migrate_v4_daily_summary_tables(self) -> None:
        """Create daily_summary and daily_app_summary if they don't exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_summary (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                date             TEXT    NOT NULL UNIQUE,
                screenshots      INTEGER DEFAULT 0,
                app_sessions     INTEGER DEFAULT 0,
                active_time      INTEGER DEFAULT 0,
                clipboard_events INTEGER DEFAULT 0,
                browser_visits   INTEGER DEFAULT 0,
                keystrokes       INTEGER DEFAULT 0,
                created_at       TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_app_summary (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                date          TEXT NOT NULL,
                app_name      TEXT NOT NULL,
                total_seconds INTEGER DEFAULT 0,
                UNIQUE(date, app_name)
            )
        """)
        logger.info("v4: daily_summary / daily_app_summary ensured")

    def _migrate_v5_schema_version_table(self) -> None:
        """
        Ensure schema_version table exists and back-fill v1–v4 for installs that
        already have those columns (deployed via the old flat migration system).
        """
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version    INTEGER PRIMARY KEY,
                applied_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        already_v1 = self._col_exists("screenshots", "synced")
        already_v2 = self._col_exists("screenshots", "username")
        already_v3 = self._col_exists("browser_activity", "synced")
        already_v4 = self._conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='daily_summary'"
        ).fetchone()[0] > 0

        for ver, present in [(1, already_v1), (2, already_v2), (3, already_v3), (4, already_v4)]:
            if present:
                self._conn.execute(
                    "INSERT OR IGNORE INTO schema_version (version) VALUES (?)", (ver,)
                )
                logger.info("v5: back-filled migration v%d (columns already present)", ver)

        logger.info("v5: schema_version table ready")

    def _migrate_v6_failure_count(self) -> None:
        """Add failure_count column to screenshots and video_recordings for circuit breaker."""
        for tbl in ("screenshots", "video_recordings"):
            if not self._col_exists(tbl, "failure_count"):
                self._conn.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0"
                )
                logger.info("v6: added failure_count to %s", tbl)

    def _apply_shared_machine_identity(self):
        """If this is a fresh install but a shared machine identity exists, auto-confirm."""
        with self._lock:
            # Check if already confirmed
            cursor = self._conn.cursor()
            cursor.execute("SELECT value FROM device_config WHERE key = 'credential_confirmed'")
            row = cursor.fetchone()
            if row and row[0] == "true":
                return # Already confirmed, do nothing
            
            # Check shared file
            import platform
            if platform.system() == "Windows":
                shared_path = Path(os.environ.get('PUBLIC', 'C:\\Users\\Public')) / "EnterpriseMonitor" / "machine_identity.json"
            else:
                shared_path = Path("/Users/Shared/EnterpriseMonitor/machine_identity.json")
                
            if shared_path.exists():
                try:
                    with open(shared_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        
                    device_alias = data.get("device_alias")
                    location = data.get("location")
                    if device_alias and location:
                        user_alias = getpass.getuser()
                        # Auto-confirm!
                        pairs = [
                            ("device_alias",          device_alias),
                            ("user_alias",            user_alias),
                            ("location",              location),
                            ("credential_confirmed",  "true"),
                            ("sync_enabled",          "true"),
                            ("confirmed_device_alias", device_alias),
                            ("confirmed_user_alias",   user_alias),
                            ("confirmed_location",     location),
                        ]
                        for key, value in pairs:
                            self._conn.execute(
                                "INSERT INTO device_config (key, value) VALUES (?, ?) "
                                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                                (key, value),
                            )
                        self._conn.commit()
                        logger.info("Auto-confirmed credentials from shared machine identity: device=%s location=%s user=%s", device_alias, location, user_alias)
                except Exception as e:
                    logger.error("Failed to read shared machine identity: %s", e)

    # ─── IDENTITY CONFIG ──────────────────────────────────────────────────────

    def get_identity_config(self) -> dict:
        """
        Returns machine identity config.

        v5.3.0 changes:
          - MAC address is computed once and persisted in device_config.
            uuid.getnode() on macOS returns different values per interface state;
            storing it eliminates duplicate ERP entries from the same device.
          - Added: location, credential_confirmed fields.
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT key, value FROM device_config")
            rows = {r["key"]: r["value"] for r in cursor.fetchall()}

        # Use stored MAC; compute and persist only on first run (soft migration)
        stored_mac = rows.get("mac_address", "")
        if not stored_mac:
            stored_mac = self._get_physical_mac()
            with self._lock:
                self._conn.execute(
                    "INSERT INTO device_config (key, value) VALUES ('mac_address', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (stored_mac,),
                )
                self._conn.commit()

        credential_confirmed = rows.get("credential_confirmed", "false") == "true"

        # Detect post-confirmation drift (alias/user/location changed without re-confirming)
        confirmed_device   = rows.get("confirmed_device_alias", "")
        confirmed_user     = rows.get("confirmed_user_alias", "")
        confirmed_location = rows.get("confirmed_location", "")
        current_device     = rows.get("device_alias", "")
        current_user       = rows.get("user_alias", "")
        current_location   = rows.get("location", "")
        credential_drifted = credential_confirmed and (
            current_device != confirmed_device or 
            current_user != confirmed_user or
            current_location != confirmed_location
        )

        return {
            "machine_id":          socket.gethostname(),
            "mac_address":         stored_mac,
            "os_user":             getpass.getuser(),
            "device_alias":        current_device,
            "user_alias":          current_user,
            "login_username":      rows.get("login_username", ""),
            "location":            rows.get("location", ""),
            "credential_confirmed": credential_confirmed and not credential_drifted,
            "credential_drifted":  credential_drifted,
        }

    def update_identity_config(
        self,
        device_alias: str = None,
        user_alias:   str = None,
        location:     str = None,
    ) -> bool:
        """Update device alias, user alias, and/or location."""
        if device_alias is None and user_alias is None and location is None:
            return False
        with self._lock:
            cursor = self._conn.cursor()
            try:
                updates = []
                if device_alias is not None:
                    updates.append(("device_alias", device_alias))
                if user_alias is not None:
                    updates.append(("user_alias", user_alias))
                if location is not None:
                    updates.append(("location", location))

                for key, value in updates:
                    cursor.execute(
                        "INSERT INTO device_config (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, value),
                    )
                self._conn.commit()
                return True
            except Exception as exc:
                logger.error("update_identity_config: %s", exc)
                self._conn.rollback()
                return False

    def confirm_credential(
        self,
        device_alias: str,
        user_alias:   str,
        location:     str,
    ) -> bool:
        """
        Atomically save device_alias, user_alias, location and mark credentials
        as confirmed. Also snapshots the confirmed values so drift can be detected
        later without re-prompting.
        Enables syncing (sync_enabled = true).
        """
        with self._lock:
            try:
                pairs = [
                    ("device_alias",          device_alias),
                    ("user_alias",            user_alias),
                    ("location",              location),
                    ("credential_confirmed",  "true"),
                    ("sync_enabled",          "true"),
                    ("confirmed_device_alias", device_alias),   # drift baseline
                    ("confirmed_user_alias",   user_alias),     # drift baseline
                    ("confirmed_location",     location),       # drift baseline
                ]
                for key, value in pairs:
                    self._conn.execute(
                        "INSERT INTO device_config (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, value),
                    )
                self._conn.commit()
                logger.info("Credentials confirmed: device=%s user=%s location=%s",
                            device_alias, user_alias, location)
                            
                # Write to shared machine identity file
                try:
                    import platform
                    if platform.system() == "Windows":
                        shared_dir = Path(os.environ.get('PUBLIC', 'C:\\Users\\Public')) / "EnterpriseMonitor"
                    else:
                        shared_dir = Path("/Users/Shared/EnterpriseMonitor")
                    
                    shared_dir.mkdir(parents=True, exist_ok=True)
                    shared_file = shared_dir / "machine_identity.json"
                    
                    data = {
                        "device_alias": device_alias,
                        "location": location
                    }
                    with open(shared_file, "w", encoding="utf-8") as f:
                        json.dump(data, f)
                except Exception as e:
                    logger.error("Failed to write shared machine identity: %s", e)

                return True
            except Exception as exc:
                logger.error("confirm_credential: %s", exc)
                self._conn.rollback()
                return False

    def is_sync_enabled(self) -> bool:
        """Returns True if the admin has confirmed credentials at least once."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM device_config WHERE key = 'sync_enabled'"
            ).fetchone()
        # Default True for backwards-compat with existing deployments that pre-date
        # the confirm-credential feature (they have no 'sync_enabled' key).
        if row is None:
            return True
        return row[0] == "true"

    def _aggregate_before_cleanup(self, synced_cutoff: str, unsynced_cutoff: str) -> None:
        """
        Aggregate stats into daily_summary / daily_app_summary for all dates
        that are about to be deleted.  Called at the top of cleanup_old_data()
        while self._lock is already held.

        Uses INSERT OR REPLACE with MAX so re-running is idempotent.
        """
        # Collect dates affected by the upcoming DELETE
        affected_dates: set = set()
        for tbl in ("screenshots", "app_activity", "clipboard_events",
                    "browser_activity", "text_logs"):
            col = "synced" if tbl != "video_recordings" else "is_synced"
            try:
                rows = self._conn.execute(
                    f"SELECT DISTINCT date(timestamp) FROM {tbl} WHERE "
                    f"(synced = 1 AND timestamp < ?) OR (synced = 0 AND timestamp < ?)",
                    (synced_cutoff, unsynced_cutoff),
                ).fetchall()
                affected_dates.update(r[0] for r in rows if r[0])
            except Exception:
                pass  # table may not have 'synced' col yet — migration handles it

        for date in affected_dates:
            start = f"{date}T00:00:00"
            end   = f"{date}T23:59:59"

            ss   = self._conn.execute("SELECT COUNT(*) FROM screenshots WHERE timestamp BETWEEN ? AND ?", (start, end)).fetchone()[0]
            apps = self._conn.execute("SELECT COUNT(*) FROM app_activity WHERE timestamp BETWEEN ? AND ?", (start, end)).fetchone()[0]
            secs = self._conn.execute("SELECT COALESCE(SUM(duration_seconds),0) FROM app_activity WHERE timestamp BETWEEN ? AND ?", (start, end)).fetchone()[0]
            clip = self._conn.execute("SELECT COUNT(*) FROM clipboard_events WHERE timestamp BETWEEN ? AND ?", (start, end)).fetchone()[0]
            brow = self._conn.execute("SELECT COUNT(*) FROM browser_activity WHERE timestamp BETWEEN ? AND ?", (start, end)).fetchone()[0]
            keys = self._conn.execute("SELECT COUNT(*) FROM text_logs WHERE timestamp BETWEEN ? AND ?", (start, end)).fetchone()[0]

            self._conn.execute(
                "INSERT INTO daily_summary "
                "(date, screenshots, app_sessions, active_time, clipboard_events, browser_visits, keystrokes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(date) DO UPDATE SET "
                "screenshots      = MAX(screenshots,      excluded.screenshots), "
                "app_sessions     = MAX(app_sessions,     excluded.app_sessions), "
                "active_time      = MAX(active_time,      excluded.active_time), "
                "clipboard_events = MAX(clipboard_events, excluded.clipboard_events), "
                "browser_visits   = MAX(browser_visits,   excluded.browser_visits), "
                "keystrokes       = MAX(keystrokes,       excluded.keystrokes)",
                (date, ss, apps, secs, clip, brow, keys),
            )

            # Per-app aggregates for the doughnut chart
            app_rows = self._conn.execute(
                "SELECT app_name, SUM(duration_seconds) FROM app_activity "
                "WHERE timestamp BETWEEN ? AND ? GROUP BY app_name",
                (start, end),
            ).fetchall()
            for app_name, total in app_rows:
                self._conn.execute(
                    "INSERT INTO daily_app_summary (date, app_name, total_seconds) VALUES (?, ?, ?) "
                    "ON CONFLICT(date, app_name) DO UPDATE SET "
                    "total_seconds = MAX(total_seconds, excluded.total_seconds)",
                    (date, app_name or "Unknown", total or 0),
                )

        if affected_dates:
            logger.info("_aggregate_before_cleanup: archived %d date(s): %s",
                        len(affected_dates), ", ".join(sorted(affected_dates)))

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

    def get_statistics(self, date=None) -> dict:
        """
        Return daily stats. Falls back to daily_summary when live records are
        gone (cleaned up after sync).
        """
        target_date = date or datetime.utcnow().strftime("%Y-%m-%d")
        start_ts = f"{target_date}T00:00:00"
        end_ts   = f"{target_date}T23:59:59"

        with self._lock:
            try:
                c = self._conn
                screenshots      = c.execute("SELECT COUNT(*) FROM screenshots WHERE timestamp BETWEEN ? AND ?", (start_ts, end_ts)).fetchone()[0]
                app_sessions     = c.execute("SELECT COUNT(*) FROM app_activity WHERE timestamp BETWEEN ? AND ?", (start_ts, end_ts)).fetchone()[0]
                active_time      = c.execute("SELECT COALESCE(SUM(duration_seconds),0) FROM app_activity WHERE timestamp BETWEEN ? AND ?", (start_ts, end_ts)).fetchone()[0]
                clipboard_events = c.execute("SELECT COUNT(*) FROM clipboard_events WHERE timestamp BETWEEN ? AND ?", (start_ts, end_ts)).fetchone()[0]
                browser_visits   = c.execute("SELECT COUNT(*) FROM browser_activity WHERE timestamp BETWEEN ? AND ?", (start_ts, end_ts)).fetchone()[0]
                keystrokes       = c.execute("SELECT COUNT(*) FROM text_logs WHERE timestamp BETWEEN ? AND ?", (start_ts, end_ts)).fetchone()[0]

                # If no live data, try archived summary
                if app_sessions == 0 and screenshots == 0 and clipboard_events == 0:
                    archived = c.execute(
                        "SELECT * FROM daily_summary WHERE date = ?", (target_date,)
                    ).fetchone()
                    if archived:
                        return {
                            "date":             target_date,
                            "screenshots":      archived["screenshots"],
                            "app_sessions":     archived["app_sessions"],
                            "active_time":      archived["active_time"],
                            "clipboard_events": archived["clipboard_events"],
                            "browser_visits":   archived["browser_visits"],
                            "keystrokes":       archived["keystrokes"],
                            "archived":         True,
                        }

                return {
                    "date":             target_date,
                    "screenshots":      screenshots,
                    "app_sessions":     app_sessions,
                    "active_time":      active_time,
                    "clipboard_events": clipboard_events,
                    "browser_visits":   browser_visits,
                    "keystrokes":       keystrokes,
                    "archived":         False,
                }
            except Exception as exc:
                logger.error("get_statistics: %s", exc)
                return {}

    def get_activity_stats(self, start: str, end: str) -> list:
        """
        Returns per-app usage for the given date range.
        Falls back to daily_app_summary for dates whose live records were cleaned.
        """
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
                results = [{"app_name": r[0], "total_seconds": r[1]} for r in cursor.fetchall()]

                if not results:
                    # Single-day fallback (charts always query one day at a time)
                    date = start[:10]
                    archived = self._conn.execute(
                        "SELECT app_name, total_seconds FROM daily_app_summary "
                        "WHERE date = ? ORDER BY total_seconds DESC",
                        (date,),
                    ).fetchall()
                    results = [{"app_name": r[0], "total_seconds": r[1]} for r in archived]

                return results
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
                    "SELECT * FROM screenshots WHERE synced = 0 "
                    "AND (failure_count IS NULL OR failure_count < 3) "
                    "ORDER BY timestamp ASC LIMIT ?",
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
                    "AND (failure_count IS NULL OR failure_count < 3) "
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

    def increment_failure_count(self, table: str, record_id: int) -> None:
        """Increment the failure_count for a record. Table must be allowlisted."""
        if table not in ("screenshots", "video_recordings"):
            raise ValueError(f"increment_failure_count: invalid table '{table}'")
        with self._lock:
            try:
                self._conn.execute(
                    f"UPDATE {table} SET failure_count = failure_count + 1 WHERE id = ?",
                    (record_id,),
                )
                self._conn.commit()
            except Exception as exc:
                logger.error("increment_failure_count(%s, %d): %s", table, record_id, exc)
                self._conn.rollback()

    def mark_dead_letter(self, table: str, record_id: int) -> None:
        """Mark a record as dead-lettered (synced = -1 / is_synced = -1)."""
        sync_col = {"screenshots": "synced", "video_recordings": "is_synced"}
        col = sync_col.get(table)
        if not col:
            raise ValueError(f"mark_dead_letter: invalid table '{table}'")
        with self._lock:
            try:
                self._conn.execute(
                    f"UPDATE {table} SET {col} = -1 WHERE id = ?",
                    (record_id,),
                )
                self._conn.commit()
            except Exception as exc:
                logger.error("mark_dead_letter(%s, %d): %s", table, record_id, exc)
                self._conn.rollback()

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
            self._aggregate_before_cleanup(synced_cutoff, unsynced_cutoff)
            try:
                deleted_ss_files    = []
                deleted_video_files = []

                # ── 1. Delete physical files for expired screenshots ──────────
                failed_ss_ids = []
                for row in self._conn.execute(
                    "SELECT id, file_path FROM screenshots WHERE "
                    "  (synced = 1 AND timestamp < ?) OR "
                    "  (synced = 0 AND timestamp < ?) OR "
                    "  (synced = -1 AND timestamp < ?)",
                    (synced_cutoff, unsynced_cutoff, unsynced_cutoff),
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
                    "  (is_synced = 0 AND timestamp < ?) OR "
                    "  (is_synced = -1 AND timestamp < ?)",
                    (synced_cutoff, unsynced_cutoff, unsynced_cutoff),
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
                    "  (synced = 0 AND timestamp < ?) OR "
                    "  (synced = -1 AND timestamp < ?))"
                )
                ss_params: list = [synced_cutoff, unsynced_cutoff, unsynced_cutoff]
                if failed_ss_ids:
                    placeholders = ",".join(["?"] * len(failed_ss_ids))
                    ss_query += f" AND id NOT IN ({placeholders})"
                    ss_params.extend(failed_ss_ids)
                ss_cur = self._conn.execute(ss_query, ss_params)
                ss_deleted = ss_cur.rowcount

                # ── 4. Purge video_recordings DB rows ─────────────────────────
                vid_query = (
                    "DELETE FROM video_recordings WHERE "
                    "  ((is_synced = 1 AND timestamp < ?) OR "
                    "  (is_synced = 0 AND timestamp < ?) OR "
                    "  (is_synced = -1 AND timestamp < ?))"
                )
                vid_params: list = [synced_cutoff, unsynced_cutoff, unsynced_cutoff]
                if failed_video_ids:
                    placeholders = ",".join(["?"] * len(failed_video_ids))
                    vid_query += f" AND id NOT IN ({placeholders})"
                    vid_params.extend(failed_video_ids)
                vid_cur = self._conn.execute(vid_query, vid_params)
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

    # ─── MAC ADDRESS DETECTION (macOS) ────────────────────────────────────────

    @staticmethod
    def _get_physical_mac() -> str:
        """
        Returns the MAC address of the primary physical NIC on macOS.

        Strategy: Read `ifconfig en0` (built-in Wi-Fi/Ethernet), then fall back
        to en1, then to uuid.getnode(). This avoids picking up virtual NICs
        (VPN, Docker, Parallels) that cause duplicate MAC entries on the server.
        """
        for iface in ("en0", "en1"):
            try:
                output = subprocess.check_output(
                    ["ifconfig", iface], stderr=subprocess.DEVNULL, text=True,
                )
                match = re.search(r"ether\s+([0-9a-f:]{17})", output)
                if match:
                    mac = match.group(1)
                    logger.info("Physical MAC from %s: %s", iface, mac)
                    return mac
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue

        # Fallback: uuid.getnode() — volatile but better than nothing
        logger.warning("Could not read physical NIC MAC — falling back to uuid.getnode()")
        return ':'.join(
            '{:02x}'.format((uuid.getnode() >> ele) & 0xff)
            for ele in reversed(range(0, 8 * 6, 8))
        )

    # ─── SYNC MARKER RESET ───────────────────────────────────────────────────

    def reset_sync_markers(self) -> int:
        """
        Resets all `synced` / `is_synced` flags to 0 across every data table.
        Used by the admin to force a full re-upload after a server-side DB reset.
        Returns the total number of rows affected.
        """
        tables_synced   = ["screenshots", "app_activity", "clipboard_events",
                           "browser_activity", "text_logs"]
        tables_is_synced = ["video_recordings"]
        total = 0
        with self._lock:
            try:
                for tbl in tables_synced:
                    self._conn.execute(f"UPDATE {tbl} SET synced = 0 WHERE synced = 1")
                    total += self._conn.execute(
                        f"SELECT changes()"
                    ).fetchone()[0]
                for tbl in tables_is_synced:
                    self._conn.execute(f"UPDATE {tbl} SET is_synced = 0 WHERE is_synced = 1")
                    total += self._conn.execute(
                        f"SELECT changes()"
                    ).fetchone()[0]
                self._conn.commit()
                logger.info("reset_sync_markers: %d rows reset across all tables", total)
            except Exception as exc:
                logger.error("reset_sync_markers failed: %s", exc)
                self._conn.rollback()
                total = 0
        return total

    def close(self) -> None:
        """Explicitly close the persistent connection (call on process shutdown)."""
        with self._lock:
            try:
                self._conn.close()
                logger.info("Database connection closed.")
            except Exception:
                pass
