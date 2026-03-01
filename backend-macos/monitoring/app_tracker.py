"""
App Tracker — macOS version
Tracks active applications and windows using osascript (JXA) subprocess.

CHANGES from Windows version:
- _get_active_app_info() uses osascript JXA subprocess instead of win32gui/win32process
- Safe to call from threading.Thread — subprocess spawns its own process with RunLoop
- Captures os_user via getpass.getuser() at startup
"""

import json
import subprocess
import threading
import time
import logging
import getpass
from datetime import datetime

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
        """
        Get (app_name, window_title) via JXA osascript.
        Safe to call from threading.Thread — uses subprocess, not AppKit directly.
        Timeout: 3 seconds. On timeout or error, return ('', '').
        Requires: Accessibility permission for window_title (app.windows[0].name())
                  App name works without Accessibility.
        """
        script = '''
        var se = Application("System Events");
        var procs = se.applicationProcesses.whose({frontmost: true});
        if (procs.length === 0) { JSON.stringify({app: "", title: ""}) }
        else {
            var proc = procs[0];
            var title = "";
            try { title = proc.windows.length > 0 ? proc.windows[0].name() : ""; } catch(e) {}
            JSON.stringify({app: proc.name(), title: title});
        }
        '''
        try:
            result = subprocess.run(
                ['osascript', '-l', 'JavaScript', '-e', script],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout.strip())
                return data.get('app', ''), data.get('title', '')
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
            logger.debug("osascript app_tracker error: %s", e)
        return '', ''

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
                            self._os_user,
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
                if not self.is_paused:
                    self._track_app_usage()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in app tracker loop: {e}")
                time.sleep(self.check_interval)

        logger.info("App tracking loop ended")
