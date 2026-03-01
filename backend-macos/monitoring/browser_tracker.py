"""
browser_tracker.py
Tracks active browser URLs on macOS using AppleScript (osascript subprocess).

Strategy: Each supported browser has an AppleScript that asks it directly
for the URL of the active tab. No accessibility APIs needed for Chrome/Safari/Edge.
Firefox requires "Allow JavaScript from Apple Events" in Firefox Developer menu.

Browsers supported:
  Chromium:  Chrome, Edge, Brave, Vivaldi, Opera, Arc, Chromium
  Gecko:     Firefox
  WebKit:    Safari

Detection: Checks the frontmost app name via osascript. If it matches
a browser in BROWSER_SCRIPTS, we run the AppleScript for that browser.
Thread-safe: osascript subprocess is safe from threading.Thread.
"""

import subprocess
import threading
import getpass
import time
import json
import logging

logger = logging.getLogger(__name__)

# ── AppleScript per browser to get the URL of the active tab ──────────────────
BROWSER_SCRIPTS: dict[str, str] = {
    'Google Chrome':   'tell application "Google Chrome" to return URL of active tab of front window',
    'Microsoft Edge':  'tell application "Microsoft Edge" to return URL of active tab of front window',
    'Brave Browser':   'tell application "Brave Browser" to return URL of active tab of front window',
    'Safari':          'tell application "Safari" to return URL of front document',
    'Firefox':         'tell application "Firefox" to return URL of active tab of front window',
    'Arc':             'tell application "Arc" to return URL of active tab of front window',
    'Vivaldi':         'tell application "Vivaldi" to return URL of active tab of front window',
    'Opera':           'tell application "Opera" to return URL of active tab of front window',
    'Chromium':        'tell application "Chromium" to return URL of active tab of front window',
}

# Process names as reported by osascript may differ from display names:
PROCESS_TO_BROWSER: dict[str, str] = {
    'Google Chrome':   'Google Chrome',
    'chrome':          'Google Chrome',
    'Microsoft Edge':  'Microsoft Edge',
    'msedge':          'Microsoft Edge',
    'Brave Browser':   'Brave Browser',
    'Safari':          'Safari',
    'firefox':         'Firefox',
    'Firefox':         'Firefox',
    'Arc':             'Arc',
    'Vivaldi':         'Vivaldi',
    'Opera':           'Opera',
    'Chromium':        'Chromium',
}

# JXA script to get the frontmost application name
_FRONTMOST_APP_SCRIPT = (
    'Application("System Events").applicationProcesses.whose({frontmost:true})[0].name()'
)


class BrowserTracker:
    """
    Polls the frontmost app every 3 seconds.
    When a supported browser is in focus, reads the URL via AppleScript
    and persists it to the database if it changed.
    """

    POLL_INTERVAL = 3  # seconds

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._thread: threading.Thread | None = None
        self._is_running = False
        self._is_paused = False
        self._last_url: str = ""
        self._os_user: str = getpass.getuser()

    # ─── LIFECYCLE ───────────────────────────────────────────────────────────

    def start(self):
        if self._is_running:
            logger.warning("BrowserTracker already running")
            return

        self._is_running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="BrowserTracker"
        )
        self._thread.start()
        logger.info("BrowserTracker started")

    def stop(self):
        self._is_running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("BrowserTracker stopped")

    def pause(self):
        self._is_paused = True
        logger.info("BrowserTracker paused")

    def resume(self):
        self._is_paused = False
        logger.info("BrowserTracker resumed")

    # ─── MAIN LOOP ───────────────────────────────────────────────────────────

    def _run_loop(self):
        logger.info("BrowserTracker loop running")
        while self._is_running:
            try:
                if not self._is_paused:
                    self._poll()
            except Exception as e:
                logger.error(f"BrowserTracker poll error: {e}")

            # Interruptible sleep
            for _ in range(self.POLL_INTERVAL):
                if not self._is_running:
                    return
                time.sleep(1)

        logger.info("BrowserTracker loop ended")

    # ─── POLL ────────────────────────────────────────────────────────────────

    def _poll(self):
        browser_name, window_title = self._get_active_browser()
        if browser_name is None:
            return

        url = self._get_browser_url(browser_name)
        if not url:
            return

        if url != self._last_url:
            self._last_url = url
            self.db_manager.insert_browser_activity(
                browser_name=browser_name,
                url=url,
                page_title=window_title or "",
                username=self._os_user,
            )
            logger.info(f"[BrowserTracker] {browser_name} -> {url}")

    # ─── BROWSER DETECTION ───────────────────────────────────────────────────

    def _get_active_browser(self) -> tuple[str | None, str | None]:
        """
        Returns (browser_friendly_name, window_title) if the frontmost app
        is a tracked browser, otherwise (None, None).
        Uses osascript JXA — safe from threading.Thread.
        """
        try:
            # Get frontmost app name and window title
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
            result = subprocess.run(
                ['osascript', '-l', 'JavaScript', '-e', script],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode != 0:
                return (None, None)

            data = json.loads(result.stdout.strip())
            app_name = data.get('app', '')
            window_title = data.get('title', '')

            # Check if the frontmost app is a tracked browser
            browser = PROCESS_TO_BROWSER.get(app_name)
            if browser:
                return (browser, window_title)
            return (None, None)

        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            logger.debug(f"BrowserTracker: detection error: {e}")
            return (None, None)
        except Exception as e:
            logger.debug(f"BrowserTracker: window detection error: {e}")
            return (None, None)

    # ─── URL EXTRACTION ──────────────────────────────────────────────────────

    def _get_browser_url(self, browser_name: str) -> str | None:
        """
        Ask the browser directly for the URL of its active tab via AppleScript.
        Returns the URL string or None.
        """
        script = BROWSER_SCRIPTS.get(browser_name)
        if not script:
            return None

        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode != 0:
                # Browser not open, script error, etc. — silent return
                return None

            url = result.stdout.strip()
            if not url:
                return None

            # Basic validation — must look like a URL
            if self._looks_like_url(url):
                return url
            return None

        except subprocess.TimeoutExpired:
            logger.debug(f"[BrowserTracker] osascript timeout for {browser_name}")
            return None
        except Exception as e:
            logger.debug(f"[BrowserTracker] URL extraction error for {browser_name}: {e}")
            return None

    # ─── HELPERS ─────────────────────────────────────────────────────────────

    @staticmethod
    def _looks_like_url(value: str) -> bool:
        """
        Heuristic: returns True if value looks like a URL or domain.
        Rejects pure search queries (spaces), empty values, and single words.
        """
        if not value or len(value) < 3:
            return False
        if value.startswith(("http://", "https://", "ftp://", "file://")):
            return True
        # domain-like: has a dot, no spaces, more than 4 chars
        if "." in value and " " not in value and len(value) > 4:
            return True
        return False
