"""
App Tracker
Tracks active applications and windows.

CHANGES:
- IDENTITY: Captures os_user via getpass.getuser() at startup.
- IDENTITY: Passes username to insert_app_activity() on every record.
"""

import sys
import threading
import time
import logging
import getpass
from datetime import datetime
import psutil
from utils.session_utils import is_user_session_active

logger = logging.getLogger(__name__)


class AppTracker:
    def __init__(self, db_manager, check_interval: int = 5):
        self.db_manager     = db_manager
        self.check_interval = check_interval
        self.is_running     = False
        self.is_paused      = False
        self.thread         = None
        self.current_app    = None
        self.current_window = None
        self.app_start_time = None

        # Capture once at startup — the OS user won't change mid-session.
        # getpass.getuser() is cross-platform (Windows + macOS + Linux).
        self._os_user: str = getpass.getuser()
        logger.info("AppTracker: tracking user '%s'", self._os_user)

    def start(self):
        """Start app tracking"""
        if self.is_running:
            logger.warning("App tracker already running")
            return

        self.is_running = True
        self.is_paused  = False
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("App tracker started")

    def stop(self):
        """Stop app tracking"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("App tracker stopped")

    def pause(self):
        """Pause app tracking"""
        self.is_paused = True
        logger.info("App tracker paused")

    def resume(self):
        """Resume app tracking"""
        self.is_paused = False
        logger.info("App tracker resumed")

    def _get_active_app_info(self):
        """Get active application and window title (cross-platform)."""
        if sys.platform == "win32":
            try:
                import win32gui
                import win32process
                hwnd = win32gui.GetForegroundWindow()
                window_title = win32gui.GetWindowText(hwnd)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    process = psutil.Process(pid)
                    app_name = process.name()
                except Exception:
                    app_name = "Unknown"
                return app_name, window_title
            except Exception as e:
                logger.error(f"Failed to get active app info (Windows): {e}")
                return None, None
        else:
            # Linux implementation using xprop
            if os.environ.get("XDG_SESSION_TYPE") == "wayland":
                # Only log once every few minutes to avoid spamming
                if not hasattr(self, "_last_wayland_warn") or time.time() - self._last_wayland_warn > 300:
                    logger.warning("Wayland detected — app tracking/screenshots may be limited. Switch to Xorg for full support.")
                    self._last_wayland_warn = time.time()

            try:
                import subprocess
                # 1. Get active window ID
                out = subprocess.check_output(["xprop", "-root", "_NET_ACTIVE_WINDOW"], stderr=subprocess.DEVNULL).decode()
                window_id = out.split("#")[-1].strip()
                if not window_id or window_id == "0x0":
                    return None, None

                # 2. Get Window Name
                window_title = "Unknown"
                try:
                    name_out = subprocess.check_output(["xprop", "-id", window_id, "WM_NAME"], stderr=subprocess.DEVNULL).decode()
                    if ' = "' in name_out:
                        window_title = name_out.split(' = "')[1].rstrip('"\n')
                except:
                    pass

                # 3. Get PID to get App Name
                app_name = "Unknown"
                try:
                    pid_out = subprocess.check_output(["xprop", "-id", window_id, "_NET_WM_PID"], stderr=subprocess.DEVNULL).decode()
                    if " = " in pid_out:
                        pid = int(pid_out.split(" = ")[1].strip())
                        app_name = psutil.Process(pid).name()
                except:
                    # Fallback to WM_CLASS if PID fails
                    try:
                        class_out = subprocess.check_output(["xprop", "-id", window_id, "WM_CLASS"], stderr=subprocess.DEVNULL).decode()
                        if ' = "' in class_out:
                            app_name = class_out.split(' = "')[1].split('"')[0]
                    except:
                        pass

                return app_name, window_title
            except Exception as e:
                # Silently fail if xprop is missing or fails, to avoid log spam
                return None, None

    def _track_app_usage(self):
        """Flush previous app session and start tracking the current one."""
        try:
            app_name, window_title = self._get_active_app_info()

            if not app_name:
                return

            # App or window changed — flush previous session
            if app_name != self.current_app or window_title != self.current_window:
                if self.current_app and self.app_start_time:
                    duration = int(
                        (datetime.utcnow() - self.app_start_time).total_seconds()
                    )
                    if duration > 0:
                        self.db_manager.insert_app_activity(
                            self.current_app,
                            self.current_window or "",
                            duration,
                            self._os_user,          # ← identity tracking
                        )

                self.current_app    = app_name
                self.current_window = window_title
                self.app_start_time = datetime.utcnow()
                logger.debug(f"App switched to: {app_name}")
        except Exception as e:
            logger.error(f"Failed to track app usage: {e}")

    def _monitor_loop(self):
        """Main monitoring loop"""
        logger.info("App tracking loop started")

        while self.is_running:
            try:
                if not self.is_paused and is_user_session_active():
                    self._track_app_usage()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in app tracker loop: {e}")
                time.sleep(self.check_interval)

        logger.info("App tracking loop ended")
