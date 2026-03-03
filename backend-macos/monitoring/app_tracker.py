"""
app_tracker.py — macOS version
Tracks active applications and windows.

BUG FIXES vs previous version:
  1. App name detection split from title detection.
     - App name: plain AppleScript (NO Accessibility required — works for ALL apps
       including sandboxed Mac App Store apps like Music/Apple TV/Photos).
     - Window title: JXA (requires Accessibility — degrades gracefully to empty string).
     Previous version used JXA for BOTH, which caused sandboxed apps to return
     procs.length === 0 and be silently dropped.

  2. Process name → display name mapping.
     System Events returns the OS process name, not the display name.
     Apple Music reports as "Music", Apple TV as "TV", etc.
     PROCESS_DISPLAY_NAMES maps these back to the user-visible app name.

  3. Poll interval reduced from 5s → 2s.
     A 5s poll means apps open/closed quickly were never captured.
     2s gives meaningful granularity without notable CPU impact.

  4. Minimum session duration reduced from >0 → >1s.
     Prevents noise from transient focus events (e.g. Spotlight open/close).

  5. osascript timeout reduced from 3s → 1.5s per call (two calls per poll now).
     Prevents the 5s poll from stretching to 8+ seconds on a slow system.
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

# ── Process name → user-visible display name ──────────────────────────────────
# System Events returns the OS process name. These differ from what the user
# sees in the Dock and what they expect in the log.
PROCESS_DISPLAY_NAMES: dict[str, str] = {
    "Music":                    "Apple Music",
    "TV":                       "Apple TV",
    "Podcasts":                 "Podcasts",
    "News":                     "Apple News",
    "Photos":                   "Photos",
    "Mail":                     "Mail",
    "Calendar":                 "Calendar",
    "Reminders":                "Reminders",
    "Notes":                    "Notes",
    "Maps":                     "Maps",
    "FaceTime":                 "FaceTime",
    "Messages":                 "Messages",
    "Contacts":                 "Contacts",
    "Safari":                   "Safari",
    "Google Chrome":            "Google Chrome",
    "Microsoft Edge":           "Microsoft Edge",
    "Brave Browser":            "Brave Browser",
    "Firefox":                  "Firefox",
    "Arc":                      "Arc",
    "Finder":                   "Finder",
    "Terminal":                 "Terminal",
    "iTerm2":                   "iTerm2",
    "Xcode":                    "Xcode",
    "Visual Studio Code":       "Visual Studio Code",
    "Code":                     "Visual Studio Code",
    "zoom.us":                  "Zoom",
    "Slack":                    "Slack",
    "Discord":                  "Discord",
    "Spotify":                  "Spotify",
    "Microsoft Word":           "Microsoft Word",
    "Microsoft Excel":          "Microsoft Excel",
    "Microsoft PowerPoint":     "Microsoft PowerPoint",
    "Microsoft Outlook":        "Microsoft Outlook",
    "Microsoft Teams":          "Microsoft Teams",
    "com.apple.dt.Xcode":       "Xcode",
    "Preview":                  "Preview",
    "QuickTime Player":         "QuickTime Player",
    "System Preferences":       "System Preferences",
    "System Settings":          "System Settings",
    "Activity Monitor":         "Activity Monitor",
    "Finder":                   "Finder",
    "Automator":                "Automator",
    "Script Editor":            "Script Editor",
    "Numbers":                  "Numbers",
    "Pages":                    "Pages",
    "Keynote":                  "Keynote",
    "GarageBand":               "GarageBand",
    "iMovie":                   "iMovie",
    "Final Cut Pro":            "Final Cut Pro",
    "Logic Pro":                "Logic Pro",
    "VLC":                      "VLC",
    "TextEdit":                 "TextEdit",
    "BBEdit":                   "BBEdit",
    "Sublime Text":             "Sublime Text",
    "PyCharm":                  "PyCharm",
    "IntelliJ IDEA":            "IntelliJ IDEA",
    "WebStorm":                 "WebStorm",
    "DataGrip":                 "DataGrip",
    "Figma":                    "Figma",
    "Sketch":                   "Sketch",
    "Adobe Photoshop 2024":     "Adobe Photoshop",
    "Adobe Illustrator 2024":   "Adobe Illustrator",
    "Adobe Premiere Pro 2024":  "Adobe Premiere Pro",
    "1Password 7":              "1Password",
    "1Password":                "1Password",
    "Notion":                   "Notion",
    "Obsidian":                 "Obsidian",
    "Telegram":                 "Telegram",
    "WhatsApp":                 "WhatsApp",
    "Signal":                   "Signal",
    "Skype":                    "Skype",
    "Dropbox":                  "Dropbox",
    "Google Drive":             "Google Drive",
    "OneDrive":                 "OneDrive",
    "Box":                      "Box",
    "Cyberduck":                "Cyberduck",
    "Transmit 5":               "Transmit",
    "TablePlus":                "TablePlus",
    "Sequel Pro":               "Sequel Pro",
    "Postico 2":                "Postico",
    "Insomnia":                 "Insomnia",
    "Paw":                      "Paw",
}


def _resolve_display_name(process_name: str) -> str:
    """Map OS process name to user-visible app name. Passthrough if not mapped."""
    return PROCESS_DISPLAY_NAMES.get(process_name, process_name)


class AppTracker:
    def __init__(self, db_manager, check_interval: int = 2):
        self.db_manager = db_manager
        self.check_interval = check_interval          # 2s — was 5s (too coarse)
        self.is_running = False
        self.is_paused = False
        self.thread: Optional[threading.Thread] = None
        self.current_app: Optional[str] = None
        self.current_window: Optional[str] = None
        self.app_start_time: Optional[datetime] = None
        self._os_user: str = getpass.getuser()
        self._accessibility_warned = False
        logger.info("AppTracker: tracking user '%s'", self._os_user)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self.is_running:
            logger.warning("AppTracker already running")
            return
        self.is_running = True
        self.is_paused = False
        self.thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="AppTracker"
        )
        self.thread.start()
        logger.info("AppTracker started (interval=%ds)", self.check_interval)

    def stop(self) -> None:
        self.is_running = False
        # Flush the last open session before stopping
        if self.current_app and self.app_start_time:
            duration = int((datetime.utcnow() - self.app_start_time).total_seconds())
            if duration > 1:
                self.db_manager.insert_app_activity(
                    self.current_app,
                    self.current_window or "",
                    duration,
                    self._os_user,
                )
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("AppTracker stopped")

    def pause(self) -> None:
        self.is_paused = True
        logger.info("AppTracker paused")

    def resume(self) -> None:
        self.is_paused = False
        logger.info("AppTracker resumed")

    # ── Detection — Method 1: App Name (no Accessibility required) ────────────

    def _get_frontmost_app_name(self) -> str:
        """
        Get the frontmost application process name using plain AppleScript.

        WHY plain AppleScript instead of JXA:
          Plain AppleScript `tell application "System Events"` resolves the frontmost
          process WITHOUT requiring Accessibility permission. JXA with
          applicationProcesses.whose({frontmost:true}) silently returns an empty array
          for sandboxed Mac App Store apps (Music, TV, Photos, App Store) when
          Accessibility is not granted.

        This call works for ALL apps, including sandboxed ones.
        Returns empty string on failure — never raises.
        """
        script = 'tell application "System Events" to return name of first application process whose frontmost is true'
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.debug("AppTracker: app name osascript timeout")
        except Exception as e:
            logger.debug("AppTracker: app name osascript error: %s", e)
        return ""

    # ── Detection — Method 2: Window Title (Accessibility required) ───────────

    def _get_window_title(self, process_name: str) -> str:
        """
        Get the frontmost window title for the given process via JXA.

        Requires Accessibility permission. Degrades gracefully to "" if denied.
        JXA is used here (not plain AppleScript) because it allows try/catch
        around windows[0].name() — some processes have no windows (menu bar apps).

        Returns empty string on any failure.
        """
        # Escape single quotes in process name for safe inline injection
        safe_name = process_name.replace("'", "\\'")
        script = (
            f'var se = Application("System Events");'
            f'var procs = se.applicationProcesses.whose({{name: "{safe_name}"}});'
            f'if (procs.length === 0) {{ ""; }}'
            f'else {{'
            f'  var w = procs[0].windows;'
            f'  w.length > 0 ? w[0].name() : "";'
            f'}}'
        )
        try:
            result = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", script],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            if result.returncode == 0:
                title = result.stdout.strip()
                # osascript returns "undefined" when Accessibility is denied
                if title and title != "undefined":
                    return title
                # One-time warning about Accessibility
                if not self._accessibility_warned:
                    logger.warning(
                        "AppTracker: window titles unavailable — grant Accessibility in "
                        "System Settings → Privacy & Security → Accessibility"
                    )
                    self._accessibility_warned = True
        except subprocess.TimeoutExpired:
            logger.debug("AppTracker: window title osascript timeout for '%s'", process_name)
        except Exception as e:
            logger.debug("AppTracker: window title error for '%s': %s", process_name, e)
        return ""

    def _get_active_app_info(self) -> tuple[str, str]:
        """
        Get (display_name, window_title) for the current frontmost application.

        Two independent calls:
          1. App name via plain AppleScript — always works, no Accessibility needed
          2. Window title via JXA — requires Accessibility, degrades to "" if denied

        The two calls are independent: a failure in #2 never drops the app name.
        """
        process_name = self._get_frontmost_app_name()
        if not process_name:
            return "", ""

        display_name = _resolve_display_name(process_name)
        window_title = self._get_window_title(process_name)
        return display_name, window_title

    # ── Tracking logic ────────────────────────────────────────────────────────

    def _track_app_usage(self) -> None:
        """Flush previous app session and start tracking the current one."""
        try:
            app_name, window_title = self._get_active_app_info()
            if not app_name:
                return

            if app_name != self.current_app or window_title != self.current_window:
                if self.current_app and self.app_start_time:
                    duration = int(
                        (datetime.utcnow() - self.app_start_time).total_seconds()
                    )
                    # >1s threshold — avoids noise from transient focus events
                    if duration > 1:
                        self.db_manager.insert_app_activity(
                            self.current_app,
                            self.current_window or "",
                            duration,
                            self._os_user,
                        )
                        logger.debug(
                            "AppTracker: saved '%s' (%ds)", self.current_app, duration
                        )

                self.current_app = app_name
                self.current_window = window_title
                self.app_start_time = datetime.utcnow()
                logger.debug("AppTracker: switch → '%s'", app_name)

        except Exception as e:
            logger.error("AppTracker._track_app_usage error: %s", e)

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