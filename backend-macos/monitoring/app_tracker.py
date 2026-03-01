"""
app_tracker.py — macOS version
Tracks active applications and windows.

CHANGES from Windows version:
  - _get_active_app_info(): win32gui/win32process → osascript JXA subprocess
  - subprocess call is safe from threading.Thread (spawns its own process)
  - Requires Accessibility permission for window titles; app name works without it
  - Fixed thread type annotation: Optional[threading.Thread] = None
"""

import getpass
import json
import logging
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class AppTracker:
    def __init__(self, db_manager, check_interval: int = 5):
        self.db_manager = db_manager
        self.check_interval = check_interval
        self.is_running = False
        self.is_paused = False
        self.thread: Optional[threading.Thread] = None  # Fix: typed correctly — not inferred as None
        self.current_app: Optional[str] = None
        self.current_window: Optional[str] = None
        self.app_start_time: Optional[datetime] = None
        self._os_user: str = getpass.getuser()
        self._accessibility_warned = False
        logger.info("AppTracker: tracking user '%s'", self._os_user)

    def start(self) -> None:
        if self.is_running:
            logger.warning("AppTracker already running")
            return
        self.is_running = True
        self.is_paused = False
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True, name="AppTracker")
        self.thread.start()
        logger.info("AppTracker started")

    def stop(self) -> None:
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("AppTracker stopped")

    def pause(self) -> None:
        self.is_paused = True
        logger.info("AppTracker paused")

    def resume(self) -> None:
        self.is_paused = False
        logger.info("AppTracker resumed")

    def _get_active_app_info(self) -> tuple[str, str]:
        """
        Get (app_name, window_title) via JXA osascript.
        Safe to call from threading.Thread — uses subprocess, not AppKit directly.
        Timeout: 3s. Returns ('', '') on any error.
        Requires Accessibility permission for window_title.
        App name works without Accessibility.
        """
        script = (
            'var se = Application("System Events");'
            'var procs = se.applicationProcesses.whose({frontmost: true});'
            'if (procs.length === 0) { JSON.stringify({app: "", title: ""}) }'
            'else {'
            '  var proc = procs[0];'
            '  var title = "";'
            '  try { title = proc.windows.length > 0 ? proc.windows[0].name() : ""; } catch(e) {}'
            '  JSON.stringify({app: proc.name(), title: title});'
            '}'
        )
        try:
            result = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", script],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout.strip())
                app = data.get("app", "")
                title = data.get("title", "")
                if app and not title and not self._accessibility_warned:
                    logger.warning(
                        "AppTracker: window titles empty — grant Accessibility permission in "
                        "System Settings → Privacy & Security → Accessibility"
                    )
                    self._accessibility_warned = True
                return app, title
        except subprocess.TimeoutExpired:
            logger.debug("AppTracker: osascript timeout")
        except json.JSONDecodeError as e:
            logger.debug("AppTracker: JSON parse error: %s", e)
        except Exception as e:
            logger.debug("AppTracker: osascript error: %s", e)
        return "", ""

    def _track_app_usage(self) -> None:
        """Flush previous app session and start tracking the current one."""
        try:
            app_name, window_title = self._get_active_app_info()
            if not app_name:
                return

            if app_name != self.current_app or window_title != self.current_window:
                if self.current_app and self.app_start_time:
                    duration = int((datetime.utcnow() - self.app_start_time).total_seconds())
                    if duration > 0:
                        self.db_manager.insert_app_activity(
                            self.current_app,
                            self.current_window or "",
                            duration,
                            self._os_user,
                        )
                self.current_app = app_name
                self.current_window = window_title
                self.app_start_time = datetime.utcnow()
                logger.debug("App switched to: %s", app_name)
        except Exception as e:
            logger.error("Failed to track app usage: %s", e)

    def _monitor_loop(self) -> None:
        logger.info("AppTracker monitoring loop started")
        while self.is_running:
            try:
                if not self.is_paused:
                    self._track_app_usage()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error("AppTracker loop error: %s", e)
                time.sleep(self.check_interval)
        logger.info("AppTracker monitoring loop ended")
