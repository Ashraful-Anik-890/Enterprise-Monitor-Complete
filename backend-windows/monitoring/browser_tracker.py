"""
browser_tracker.py
Tracks active browser URLs using the uiautomation library.

Supported browsers: Chrome, Edge, Firefox
Uses UI Automation (NOT Selenium) — reads the address bar control directly.
Runs in a daemon thread, matching the existing threading architecture.

Requires: pip install uiautomation pywin32
"""

import threading
import time
import logging
import sys
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Map of process names → friendly browser names
BROWSER_PROCESS_MAP = {
    "chrome.exe":  "Chrome",
    "msedge.exe":  "Edge",
    "firefox.exe": "Firefox",
}

# Chrome/Edge address bar control name (Omnibox)
CHROMIUM_ADDRESS_BAR_NAME = "Address and search bar"


class BrowserTracker:
    """
    Polls the active window every 3 seconds.
    When a supported browser is in focus, reads the URL from its address bar
    via UI Automation and persists it to the database if it changed.
    """

    POLL_INTERVAL = 3  # seconds

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._thread: Optional[threading.Thread] = None
        self._is_running = False
        self._is_paused = False
        self._last_url: str = ""

        # uiautomation is Windows-only — import lazily so the module can be
        # imported on non-Windows without immediately crashing.
        self._uia = None

    # ─── LIFECYCLE ───────────────────────────────────────────────────────────

    def start(self):
        if self._is_running:
            logger.warning("BrowserTracker already running")
            return
        if sys.platform != "win32":
            logger.warning("BrowserTracker is Windows-only; skipping start")
            return

        self._is_running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="BrowserTracker")
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
        # Lazy import — uiautomation takes ~0.5 s to initialise COM on first use
        try:
            import uiautomation as uia
            self._uia = uia
        except ImportError:
            logger.error(
                "uiautomation not installed. Run: pip install uiautomation\n"
                "BrowserTracker will not function."
            )
            self._is_running = False
            return

        logger.info("BrowserTracker loop running")
        while self._is_running:
            try:
                if not self._is_paused:
                    self._poll()
            except Exception as e:
                logger.error(f"BrowserTracker poll error: {e}")

            # Interruptible sleep — checks is_running every second
            for _ in range(self.POLL_INTERVAL):
                if not self._is_running:
                    return
                time.sleep(1)

        logger.info("BrowserTracker loop ended")

    def _poll(self):
        """Check the active window; if it's a browser, extract and store the URL."""
        browser_name, hwnd = self._get_active_browser()
        if not browser_name or not hwnd:
            return

        url, title = self._extract_url_and_title(browser_name, hwnd)
        if not url:
            return

        if url != self._last_url:
            self._last_url = url
            self.db_manager.insert_browser_activity(
                browser_name=browser_name,
                url=url,
                page_title=title or ""
            )
            logger.debug(f"Browser activity: [{browser_name}] {url}")

    # ─── HELPERS ─────────────────────────────────────────────────────────────

    def _get_active_browser(self) -> Tuple[Optional[str], Optional[int]]:
        """
        Returns (browser_friendly_name, hwnd) if the foreground window belongs
        to a tracked browser; otherwise (None, None).
        """
        try:
            import win32gui
            import win32process
            import psutil

            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None, None

            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            exe_name = proc.name().lower()

            browser = BROWSER_PROCESS_MAP.get(exe_name)
            return browser, hwnd if browser else (None, None)

        except Exception:
            return None, None

    def _extract_url_and_title(
        self, browser_name: str, hwnd: int
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Use uiautomation to locate the address bar control and read its value.
        Returns (url, page_title).  Both may be None on failure.
        """
        try:
            import win32gui
            uia = self._uia

            window_title = win32gui.GetWindowText(hwnd)
            ctrl = uia.ControlFromHandle(hwnd)

            if browser_name in ("Chrome", "Edge"):
                url = self._read_chromium_address_bar(ctrl)
            elif browser_name == "Firefox":
                url = self._read_firefox_address_bar(ctrl)
            else:
                return None, None

            return url, window_title

        except Exception as e:
            # "Access Denied" surfaces as a generic Exception from uiautomation
            if "Access" in str(e) or "denied" in str(e).lower():
                logger.debug(f"Access denied reading {browser_name} address bar (elevated process)")
            else:
                logger.debug(f"Could not read {browser_name} URL: {e}")
            return None, None

    def _read_chromium_address_bar(self, window_ctrl) -> Optional[str]:
        """
        Chrome and Edge share the same Omnibox control name.
        Search depth 15 covers all toolbar nesting.
        """
        try:
            addr = window_ctrl.EditControl(
                Name=CHROMIUM_ADDRESS_BAR_NAME,
                searchDepth=15
            )
            if addr.Exists(0, 0):
                value = addr.GetValuePattern().Value
                return value if value else None
        except Exception:
            pass
        return None

    def _read_firefox_address_bar(self, window_ctrl) -> Optional[str]:
        """
        Firefox URL bar: ComboBoxControl → EditControl inside.
        The ComboBox is typically named 'Search with Google or enter address'
        but the Name can change with locale, so we fall back to role-based search.
        """
        try:
            # Attempt 1: named combo box (English locale)
            combo = window_ctrl.ComboBoxControl(
                Name="Search with Google or enter address",
                searchDepth=15
            )
            if combo.Exists(0, 0):
                edit = combo.EditControl(searchDepth=3)
                if edit.Exists(0, 0):
                    value = edit.GetValuePattern().Value
                    return value if value else None

            # Attempt 2: look for any ComboBox whose child Edit has a URL-like value
            for combo in window_ctrl.GetChildren():
                if combo.ControlTypeName == "ComboBoxControl":
                    edit = combo.EditControl(searchDepth=3)
                    if edit.Exists(0, 0):
                        value = edit.GetValuePattern().Value
                        if value and ("." in value or value.startswith("http")):
                            return value
        except Exception:
            pass
        return None
