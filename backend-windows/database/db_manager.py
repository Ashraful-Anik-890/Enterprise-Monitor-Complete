"""
Database Manager
Handles SQLite database operations for storing monitoring data
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
        # Database location
        self.db_dir = Path.home() / "AppData" / "Local" / "EnterpriseMonitor"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / "monitoring.db"
        
        # Initialize database
        self._initialize_database()
        
    def _initialize_database(self):
        """Create database tables if they don't exist"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Screenshots table
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
        
        # App activity table
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
        
        # Clipboard events table
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
        
        conn.commit()
        conn.close()
        
        # Run migrations to ensure schema is up to date
        self._run_migrations()
        
        logger.info("Database initialized successfully")
    
    def _run_migrations(self):
        """Run database migrations"""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # Check if synced column exists in screenshots (for existing DBs)
            cursor.execute("PRAGMA table_info(screenshots)")
            columns = [info[1] for info in cursor.fetchall()]
            if "synced" not in columns:
                logger.info("Migrating database: Adding synced columns")
                cursor.execute("ALTER TABLE screenshots ADD COLUMN synced INTEGER DEFAULT 0")
                cursor.execute("ALTER TABLE app_activity ADD COLUMN synced INTEGER DEFAULT 0")
                cursor.execute("ALTER TABLE clipboard_events ADD COLUMN synced INTEGER DEFAULT 0")
                conn.commit()
        except Exception as e:
            logger.error(f"Migration failed: {e}")
        finally:
            conn.close()

    def _get_connection(self):
        """Get database connection"""
        return sqlite3.connect(self.db_path)
    
    def insert_screenshot(self, file_path: str, active_window: str, active_app: str):
        """Insert screenshot record"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO screenshots (timestamp, file_path, active_window, active_app, synced)
                VALUES (?, ?, ?, ?, 0)
            ''', (datetime.utcnow().isoformat(), file_path, active_window, active_app))
            
            conn.commit()
            logger.debug(f"Inserted screenshot record: {file_path}")
        except Exception as e:
            logger.error(f"Failed to insert screenshot: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def insert_app_activity(self, app_name: str, window_title: str, duration_seconds: int):
        """Insert app activity record"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO app_activity (timestamp, app_name, window_title, duration_seconds, synced)
                VALUES (?, ?, ?, ?, 0)
            ''', (datetime.utcnow().isoformat(), app_name, window_title, duration_seconds))
            
            conn.commit()
            logger.debug(f"Inserted app activity: {app_name}")
        except Exception as e:
            logger.error(f"Failed to insert app activity: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def insert_clipboard_event(self, content_type: str, content_preview: str):
        """Insert clipboard event"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO clipboard_events (timestamp, content_type, content_preview, synced)
                VALUES (?, ?, ?, 0)
            ''', (datetime.utcnow().isoformat(), content_type, content_preview))
            
            conn.commit()
            logger.debug(f"Inserted clipboard event: {content_type}")
        except Exception as e:
            logger.error(f"Failed to insert clipboard event: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def get_screenshots(self, limit: int = 20, offset: int = 0) -> List[Dict]:
        """Get list of screenshots"""
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
    
    def get_statistics(self) -> Dict:
        """Get monitoring statistics"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Total screenshots
            cursor.execute('SELECT COUNT(*) FROM screenshots')
            total_screenshots = cursor.fetchone()[0]
            
            # Active hours today
            today = datetime.utcnow().date().isoformat()
            cursor.execute('''
                SELECT SUM(duration_seconds) FROM app_activity
                WHERE DATE(timestamp) = ?
            ''', (today,))
            result = cursor.fetchone()[0]
            active_hours_today = (result or 0) / 3600.0
            
            # Apps tracked
            cursor.execute('SELECT COUNT(DISTINCT app_name) FROM app_activity')
            apps_tracked = cursor.fetchone()[0]
            
            # Clipboard events
            cursor.execute('SELECT COUNT(*) FROM clipboard_events')
            clipboard_events = cursor.fetchone()[0]
            
            return {
                "total_screenshots": total_screenshots,
                "active_hours_today": active_hours_today,
                "apps_tracked": apps_tracked,
                "clipboard_events": clipboard_events
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {
                "total_screenshots": 0,
                "active_hours_today": 0.0,
                "apps_tracked": 0,
                "clipboard_events": 0
            }
        finally:
            conn.close()
    
    def cleanup_old_data(self, days: int = 7):
        """Delete data older than specified days"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
            
            cursor.execute('DELETE FROM screenshots WHERE timestamp < ?', (cutoff_date,))
            cursor.execute('DELETE FROM app_activity WHERE timestamp < ?', (cutoff_date,))
            cursor.execute('DELETE FROM clipboard_events WHERE timestamp < ?', (cutoff_date,))
            
            conn.commit()
            logger.info(f"Cleaned up data older than {days} days")
        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")
            conn.rollback()
        finally:
            conn.close()

    def get_unsynced_data(self, limit: int = 50) -> Dict[str, List[Dict]]:
        """Get data that hasn't been synced yet"""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        data = {
            "screenshots": [],
            "app_activity": [],
            "clipboard_events": []
        }
        
        try:
            # Get unsynced screenshots
            cursor.execute('SELECT * FROM screenshots WHERE synced = 0 LIMIT ?', (limit,))
            data["screenshots"] = [dict(row) for row in cursor.fetchall()]
            
            # Get unsynced app activity
            cursor.execute('SELECT * FROM app_activity WHERE synced = 0 LIMIT ?', (limit,))
            data["app_activity"] = [dict(row) for row in cursor.fetchall()]
            
            # Get unsynced clipboard events
            cursor.execute('SELECT * FROM clipboard_events WHERE synced = 0 LIMIT ?', (limit,))
            data["clipboard_events"] = [dict(row) for row in cursor.fetchall()]
            
            return data
        except Exception as e:
            logger.error(f"Failed to get unsynced data: {e}")
            return data
        finally:
            conn.close()

    def mark_as_synced(self, table: str, ids: List[int]):
        """Mark records as synced"""
        if not ids:
            return
            
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            placeholders = ','.join(['?'] * len(ids))
            query = f"UPDATE {table} SET synced = 1 WHERE id IN ({placeholders})"
            cursor.execute(query, ids)
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to mark data as synced: {e}")
            conn.rollback()
        finally:
            conn.close()
    def get_activity_stats(self, start_date: str, end_date: str) -> List[Dict]:
        """Get aggregated activity stats for date range"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Parse dates to ensure valid format, but keep as string for sqlite comparison
            # Assumes ISO format YYYY-MM-DD
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
            return [
                {
                    "app_name": row[0],
                    "total_seconds": row[1]
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get activity stats: {e}")
            return []
        finally:
            conn.close()

    def get_timeline_data(self, date: str) -> List[Dict]:
        """Get detailed timeline data for specific date"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Query for specific date
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

    def get_app_activity_logs(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get paginated app activity logs"""
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

    def get_browser_activity_logs(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get paginated browser activity logs"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Common browser process names
            browsers = ['chrome.exe', 'firefox.exe', 'msedge.exe', 'opera.exe', 'brave.exe', 'safari']
            placeholders = ','.join(['?'] * len(browsers))
            
            # Note: partial matching might be better if app_name isn't exact exe name
            # For now assuming app_name comes from psutil.Process.name() which is usually exe name on Windows
            query = f'''
                SELECT id, timestamp, app_name, window_title, duration_seconds
                FROM app_activity
                WHERE LOWER(app_name) IN ({placeholders}) 
                   OR LOWER(app_name) LIKE '%chrome%' 
                   OR LOWER(app_name) LIKE '%firefox%'
                   OR LOWER(app_name) LIKE '%edge%'
                   OR LOWER(app_name) LIKE '%browser%'
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            '''
            
            # Combine params: browsers list + limit + offset
            params = browsers + [limit, offset]
            
            cursor.execute(query, params)
            
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
            logger.error(f"Failed to get browser activity logs: {e}")
            return []
        finally:
            conn.close()

    def get_clipboard_logs(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get paginated clipboard logs"""
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
