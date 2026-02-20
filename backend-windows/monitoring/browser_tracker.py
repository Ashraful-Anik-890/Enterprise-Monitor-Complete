"""
browser_tracker.py
Tracks active browser URLs using the uiautomation library.

Uses UI Automation (NOT Selenium) — reads the address bar control directly.
Runs in a daemon thread, matching the existing threading architecture.

Requires: pip install uiautomation pywin32

BUGS FIXED:
- Bug 1: Operator precedence: `return browser, hwnd if browser else (None, None)`
         is parsed as `return (browser, (hwnd if browser else (None, None)))`.
         When browser=None, hwnd gets assigned (None, None) — a non-empty tuple
         which is truthy — so the `not hwnd` guard never fires. Fixed with explicit
         tuple construction.
- Bug 2: Chrome's Omnibox Name attribute is empty in modern builds. Added
         AutomationId="omnibox" as primary lookup (works for all Chromium builds).
         Name-based lookup is now a secondary fallback.
- Bug 3: Only Chrome/Edge/Firefox were in BROWSER_PROCESS_MAP. Added Brave, Opera,
         Yandex, DuckDuckGo, UC Browser, and Vivaldi. All are Chromium-based so
         they share the same omnibox AutomationId.

NOTE: Samsung Internet and Safari are mobile/macOS-only — not available as
      Windows desktop processes, so they cannot be tracked on Windows.
"""

import threading
import getpass
import time
import logging
import sys
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ── Process name → friendly display name ──────────────────────────────────────
# All Chromium-based browsers share AutomationId="omnibox" on their address bar.
# Firefox has a different UIA tree and uses its own reader.
BROWSER_PROCESS_MAP = {
    # Chromium engine
    "chrome.exe":          "Chrome",
    "msedge.exe":          "Edge",
    "brave.exe":           "Brave",
    "opera.exe":           "Opera",
    "operagx.exe":         "Opera GX",
    "browser.exe":         "Yandex Browser",   # Yandex installs as browser.exe
    "duckduckgo.exe":      "DuckDuckGo",
    "ucbrowser.exe":       "UC Browser",
    "vivaldi.exe":         "Vivaldi",
    "cent.exe":            "Cent Browser",
    "360chrome.exe":       "360 Browser",
    # Gecko engine
    "firefox.exe":         "Firefox",
    "waterfox.exe":        "Waterfox",
    "librewolf.exe":       "LibreWolf",
    "thunderbird.exe":     "Thunderbird",      # has an address bar too
}

# Chromium Omnibox control identifiers
# AutomationId is stable across locales; Name is locale-dependent (only Edge reliably sets it)
CHROMIUM_OMNIBOX_AUTOMATION_ID = "omnibox"
CHROMIUM_OMNIBOX_NAME          = "Address and search bar"

# Firefox toolbar name candidates (locale-dependent — we try all of them)
FIREFOX_TOOLBAR_NAMES = [
    "Search with Google or enter address",
    "Search with DuckDuckGo or enter address",
    "Search with Bing or enter address",
    "Search or enter address",
    "Address bar",
]

# Gecko-engine browsers (different UIA tree from Chromium)
GECKO_BROWSERS = {"Firefox", "Waterfox", "LibreWolf", "Thunderbird"}


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
        self._uia = None
        self._os_user: str = getpass.getuser()

    # ─── LIFECYCLE ───────────────────────────────────────────────────────────

    def start(self):
        if self._is_running:
            logger.warning("BrowserTracker already running")
            return
        if sys.platform != "win32":
            logger.warning("BrowserTracker is Windows-only; skipping start")
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
        # Lazy import: uiautomation initialises COM on first use (~0.5s)
        try:
            import uiautomation as uia
            self._uia = uia
        except ImportError:
            logger.error(
                "uiautomation not installed. Run: pip install uiautomation -- "
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

            # Interruptible sleep
            for _ in range(self.POLL_INTERVAL):
                if not self._is_running:
                    return
                time.sleep(1)

        logger.info("BrowserTracker loop ended")

    # ─── POLL ────────────────────────────────────────────────────────────────

    def _poll(self):
        browser_name, hwnd = self._get_active_browser()
        if browser_name is None or hwnd is None:
            return

        url, title = self._extract_url_and_title(browser_name, hwnd)
        if not url:
            return

        if url != self._last_url:
            self._last_url = url
            self.db_manager.insert_browser_activity(
                browser_name=browser_name,
                url=url,
                page_title=title or "",
                username=self._os_user,
            )
            logger.info(f"[BrowserTracker] {browser_name} -> {url}")

    # ─── WINDOW DETECTION ────────────────────────────────────────────────────

    def _get_active_browser(self) -> Tuple[Optional[str], Optional[int]]:
        """
        Returns (browser_friendly_name, hwnd) for the foreground window if it
        belongs to a tracked browser, otherwise (None, None).

        FIX: explicit tuple literals prevent Python operator-precedence bugs.
        """
        try:
            import win32gui
            import win32process
            import psutil

            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return (None, None)

            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            exe_name = proc.name().lower()

            browser = BROWSER_PROCESS_MAP.get(exe_name)
            if browser:
                return (browser, hwnd)
            return (None, None)

        except Exception as e:
            logger.debug(f"BrowserTracker: window detection error: {e}")
            return (None, None)

    # ─── URL EXTRACTION ──────────────────────────────────────────────────────

    def _extract_url_and_title(
        self, browser_name: str, hwnd: int
    ) -> Tuple[Optional[str], Optional[str]]:
        try:
            import win32gui
            uia = self._uia

            window_title = win32gui.GetWindowText(hwnd)
            window_ctrl  = uia.ControlFromHandle(hwnd)

            if browser_name in GECKO_BROWSERS:
                url = self._read_gecko_address_bar(window_ctrl, browser_name)
            else:
                # All Chromium-based browsers (Chrome, Edge, Brave, Opera, ...)
                url = self._read_chromium_address_bar(window_ctrl, browser_name)

            if url:
                return (url, window_title)

            logger.debug(
                f"[BrowserTracker] Could not read URL from {browser_name} "
                f"(title: '{window_title}')"
            )
            return (None, None)

        except Exception as e:
            err = str(e).lower()
            if "access" in err or "denied" in err:
                logger.debug(
                    f"[BrowserTracker] Access denied for {browser_name} "
                    f"(browser may be running elevated)"
                )
            else:
                logger.debug(f"[BrowserTracker] extract error for {browser_name}: {e}")
            return (None, None)

    # ─── CHROMIUM READER ─────────────────────────────────────────────────────

    def _read_chromium_address_bar(
        self, window_ctrl, browser_name: str
    ) -> Optional[str]:
        """
        Reads the Omnibox from any Chromium-based browser.

        Strategy (in order):
          1. AutomationId="omnibox"         — works for Chrome, Brave, Opera, etc.
          2. Name="Address and search bar"  — works for Edge (and some Chrome versions)
          3. Structural deep walk           — last resort for any Chromium variant
        """
        uia = self._uia

        # ── Strategy 1: AutomationId (most reliable across all Chromium builds) ──
        try:
            ctrl = window_ctrl.EditControl(
                AutomationId=CHROMIUM_OMNIBOX_AUTOMATION_ID,
                searchDepth=20
            )
            if ctrl.Exists(0, 0):
                value = ctrl.GetValuePattern().Value
                if value:
                    logger.debug(f"[{browser_name}] URL via AutomationId: {value}")
                    return value
        except Exception as e:
            logger.debug(f"[{browser_name}] AutomationId lookup error: {e}")

        # ── Strategy 2: Name attribute (Edge + some Chrome versions) ─────────
        try:
            ctrl = window_ctrl.EditControl(
                Name=CHROMIUM_OMNIBOX_NAME,
                searchDepth=20
            )
            if ctrl.Exists(0, 0):
                value = ctrl.GetValuePattern().Value
                if value:
                    logger.debug(f"[{browser_name}] URL via Name: {value}")
                    return value
        except Exception as e:
            logger.debug(f"[{browser_name}] Name lookup error: {e}")

        # ── Strategy 3: Structural deep walk ─────────────────────────────────
        try:
            result = self._deep_find_url_edit(window_ctrl, depth=0, max_depth=10)
            if result:
                logger.debug(f"[{browser_name}] URL via deep walk: {result}")
                return result
        except Exception as e:
            logger.debug(f"[{browser_name}] Deep walk error: {e}")

        return None

    def _deep_find_url_edit(
        self, ctrl, depth: int, max_depth: int
    ) -> Optional[str]:
        """
        Recursively walks the UIA control tree looking for an EditControl whose
        value looks like a URL. Limited to max_depth to bound traversal time.
        """
        if depth > max_depth:
            return None
        try:
            if ctrl.ControlTypeName == "EditControl":
                try:
                    value = ctrl.GetValuePattern().Value
                    if value and self._looks_like_url(value):
                        return value
                except Exception:
                    pass
            for child in ctrl.GetChildren():
                found = self._deep_find_url_edit(child, depth + 1, max_depth)
                if found:
                    return found
        except Exception:
            pass
        return None

    # ─── GECKO (FIREFOX) READER ──────────────────────────────────────────────

    def _read_gecko_address_bar(
        self, window_ctrl, browser_name: str
    ) -> Optional[str]:
        """
        Reads the address bar from Firefox / Waterfox / LibreWolf.

        Firefox v110+ changed its UIA tree: the address bar is now inside a
        ToolbarControl, NOT a ComboBoxControl as in older versions.

        Strategy (in order):
          1. Walk ToolbarControls looking for a child EditControl with a URL value
             — covers Firefox v110+
          2. Named ComboBoxControl — covers Firefox < v110
          3. Any ComboBoxControl with a URL-like child edit — legacy fallback
        """
        uia = self._uia

        # ── Strategy 1: ToolbarControl (Firefox v110+) ───────────────────────
        try:
            # Walk all toolbar controls at any depth up to 15
            toolbar = window_ctrl.ToolbarControl(searchDepth=15)
            while toolbar and toolbar.Exists(0, 0):
                url = self._extract_edit_url(toolbar, depth=5)
                if url:
                    logger.debug(f"[{browser_name}] URL via ToolbarControl: {url}")
                    return url
                next_ctrl = toolbar.GetNextSiblingControl()
                if (not next_ctrl or
                        next_ctrl.ControlTypeName != "ToolbarControl"):
                    break
                toolbar = next_ctrl
        except Exception as e:
            logger.debug(f"[{browser_name}] Toolbar walk error: {e}")

        # ── Strategy 2: Named toolbar (locale variants) ───────────────────────
        try:
            for name in FIREFOX_TOOLBAR_NAMES:
                ctrl = window_ctrl.ToolbarControl(Name=name, searchDepth=15)
                if ctrl.Exists(0, 0):
                    url = self._extract_edit_url(ctrl, depth=5)
                    if url:
                        logger.debug(f"[{browser_name}] URL via named toolbar: {url}")
                        return url
        except Exception as e:
            logger.debug(f"[{browser_name}] Named toolbar error: {e}")

        # ── Strategy 3: ComboBoxControl (Firefox < v110) ─────────────────────
        try:
            for name in FIREFOX_TOOLBAR_NAMES:
                combo = window_ctrl.ComboBoxControl(Name=name, searchDepth=15)
                if combo.Exists(0, 0):
                    url = self._extract_edit_url(combo, depth=5)
                    if url:
                        logger.debug(f"[{browser_name}] URL via named ComboBox: {url}")
                        return url

            # unnamed ComboBox fallback
            combo = window_ctrl.ComboBoxControl(searchDepth=15)
            while combo and combo.Exists(0, 0):
                url = self._extract_edit_url(combo, depth=5)
                if url:
                    logger.debug(f"[{browser_name}] URL via ComboBox walk: {url}")
                    return url
                next_ctrl = combo.GetNextSiblingControl()
                if (not next_ctrl or
                        next_ctrl.ControlTypeName != "ComboBoxControl"):
                    break
                combo = next_ctrl
        except Exception as e:
            logger.debug(f"[{browser_name}] ComboBox fallback error: {e}")

        return None

    # ─── HELPERS ─────────────────────────────────────────────────────────────

    def _extract_edit_url(self, parent_ctrl, depth: int) -> Optional[str]:
        """
        Finds an EditControl child within parent_ctrl and returns its value
        if it looks like a URL.
        """
        try:
            edit = parent_ctrl.EditControl(searchDepth=depth)
            if edit.Exists(0, 0):
                value = edit.GetValuePattern().Value
                if value and self._looks_like_url(value):
                    return value
        except Exception:
            pass
        return None

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