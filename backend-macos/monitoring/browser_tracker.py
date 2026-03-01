"""
browser_tracker.py — macOS version
Tracks active browser URLs using AppleScript (osascript subprocess).

CHANGES from Windows version:
  - Replaced uiautomation COM API entirely
  - Strategy: each browser gets a direct AppleScript ask for its URL
  - No accessibility APIs needed for Chrome/Safari/Edge
  - Firefox requires: Preferences → Privacy & Security → Allow JavaScript from Apple Events
  - Safe from threading.Thread — subprocess does not touch AppKit
  - Fixed thread type annotation: Optional[threading.Thread] = None
"""

import getpass
import logging
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# AppleScript per browser — direct URL ask, no UI tree walking needed
BROWSER_SCRIPTS: dict[str, str] = {
    "Google Chrome":   'tell application "Google Chrome" to return URL of active tab of front window',
    "Chrome":          'tell application "Google Chrome" to return URL of active tab of front window',
    "Safari":          'tell application "Safari" to return URL of front document',
    "Microsoft Edge":  'tell application "Microsoft Edge" to return URL of active tab of front window',
    "Brave Browser":   'tell application "Brave Browser" to return URL of active tab of front window',
    "Firefox":         'tell application "Firefox" to return URL of active tab of front window',
    "Arc":             'tell application "Arc" to return URL of active tab of front window',
    "Vivaldi":         'tell application "Vivaldi" to return URL of active tab of front window',
    "Opera":           'tell application "Opera" to return URL of active tab of front window',
    "Chromium":        'tell application "Chromium" to return URL of active tab of front window',
    "Waterfox":        'tell application "Waterfox" to return URL of active tab of front window',
    "LibreWolf":       'tell application "LibreWolf" to return URL of active tab of front window',
}


def _get_browser_url(browser_name: str) -> Optional[str]:
    """Run the AppleScript for the given browser name. Returns URL string or None."""
    script = BROWSER_SCRIPTS.get(browser_name)
    if not script:
        return None
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            return url if url else None
    except subprocess.TimeoutExpired:
        logger.debug("BrowserTracker: osascript timeout for %s", browser_name)
    except Exception as e:
        logger.debug("BrowserTracker: error for %s: %s", browser_name, e)
    return None


def _get_page_title(browser_name: str) -> Optional[str]:
    """Get the page title for Chromium browsers. Falls back to None."""
    title_scripts = {
        "Google Chrome":  'tell application "Google Chrome" to return title of active tab of front window',
        "Chrome":         'tell application "Google Chrome" to return title of active tab of front window',
        "Microsoft Edge": 'tell application "Microsoft Edge" to return title of active tab of front window',
        "Brave Browser":  'tell application "Brave Browser" to return title of active tab of front window',
        "Safari":         'tell application "Safari" to return name of front document',
        "Arc":            'tell application "Arc" to return title of active tab of front window',
    }
    script = title_scripts.get(browser_name)
    if not script:
        return None
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
        pass
    return None


class BrowserTracker:
    def __init__(self, db_manager, check_interval: int = 5):
        self.db_manager = db_manager
        self.check_interval = check_interval
        self.is_running = False
        self.is_paused = False
        self.thread: Optional[threading.Thread] = None  # Fix: proper type annotation
        self._os_user: str = getpass.getuser()
        self._last_url: Optional[str] = None
        self._last_browser: Optional[str] = None
        logger.info("BrowserTracker: tracking user '%s'", self._os_user)

    def start(self) -> None:
        if self.is_running:
            logger.warning("BrowserTracker already running")
            return
        self.is_running = True
        self.is_paused = False
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True, name="BrowserTracker")
        self.thread.start()
        logger.info("BrowserTracker started")

    def stop(self) -> None:
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("BrowserTracker stopped")

    def pause(self) -> None:
        self.is_paused = True
        logger.info("BrowserTracker paused")

    def resume(self) -> None:
        self.is_paused = False
        logger.info("BrowserTracker resumed")

    def _get_frontmost_app(self) -> Optional[str]:
        """Get the frontmost application name via JXA. Returns None on failure."""
        try:
            result = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e",
                 'Application("System Events").applicationProcesses.whose({frontmost:true})[0].name()'],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                name = result.stdout.strip()
                return name if name else None
        except Exception:
            pass
        return None

    def _check_browser(self) -> None:
        """Check the active browser URL and record if it changed."""
        frontmost = self._get_frontmost_app()
        if not frontmost or frontmost not in BROWSER_SCRIPTS:
            return

        url = _get_browser_url(frontmost)
        if not url:
            return

        # Only record if URL changed
        if url == self._last_url and frontmost == self._last_browser:
            return

        title = _get_page_title(frontmost) or ""
        self._last_url = url
        self._last_browser = frontmost

        try:
            self.db_manager.insert_browser_activity(
                browser_name=frontmost,
                url=url,
                page_title=title,
                username=self._os_user,
            )
            logger.debug("Browser URL recorded: [%s] %s", frontmost, url[:80])
        except Exception as e:
            logger.error("Failed to insert browser activity: %s", e)

    def _monitor_loop(self) -> None:
        logger.info("BrowserTracker monitoring loop started")
        while self.is_running:
            try:
                if not self.is_paused:
                    self._check_browser()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error("BrowserTracker loop error: %s", e)
                time.sleep(self.check_interval)
        logger.info("BrowserTracker monitoring loop ended")
