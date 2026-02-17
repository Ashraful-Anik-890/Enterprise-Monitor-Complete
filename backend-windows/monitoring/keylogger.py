"""
keylogger.py
Captures typed text by buffering keystrokes and flushing on ENTER or window switch.

Uses pynput.keyboard.Listener — runs its own internal thread, so this class is
non-blocking by design. The public API matches the other monitoring services
(start / stop / pause / resume).

Privacy filter: buffers are NOT saved when the active window title contains
"password" or "login" (case-insensitive).

Requires: pip install pynput pywin32
"""

import sys
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Window title fragments that trigger a privacy blackout (case-insensitive)
PRIVACY_KEYWORDS = ("password", "login", "sign in", "signin", "credentials")


def _get_active_window_info():
    """
    Returns (process_name, window_title) for the current foreground window.
    Returns ('', '') on any failure.
    """
    try:
        import win32gui
        import win32process
        import psutil

        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        app_name = proc.name()
        return app_name, title
    except Exception:
        return "", ""


class Keylogger:
    """
    Keystroke buffer logger.

    Flush conditions:
      - User presses ENTER  → save buffer attributed to the current window.
      - User switches window → save buffer attributed to the PREVIOUS window.

    The pynput Listener runs its own daemon thread internally. This class only
    wraps lifecycle management around it.
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._listener = None
        self._is_running = False
        self._is_paused = False

        # Buffer state — protected by a lock because the listener callback runs
        # on pynput's internal thread.
        self._lock = threading.Lock()
        self._buffer: str = ""
        self._current_app: str = ""
        self._current_title: str = ""

    # ─── LIFECYCLE ───────────────────────────────────────────────────────────

    def start(self):
        if self._is_running:
            logger.warning("Keylogger already running")
            return
        if sys.platform != "win32":
            logger.warning("Keylogger is Windows-only; skipping start")
            return

        try:
            from pynput import keyboard as _kb
        except ImportError:
            logger.error(
                "pynput not installed. Run: pip install pynput\n"
                "Keylogger will not function."
            )
            return

        # Seed the initial window context before the listener starts
        self._current_app, self._current_title = _get_active_window_info()

        self._is_running = True
        self._listener = _kb.Listener(
            on_press=self._on_key_press,
            on_release=None,
            suppress=False       # Never suppress keystrokes — monitoring only
        )
        self._listener.daemon = True
        self._listener.start()
        logger.info("Keylogger started")

    def stop(self):
        self._is_running = False
        if self._listener:
            self._listener.stop()
            self._listener = None
        # Flush any remaining buffer
        self._flush_buffer()
        logger.info("Keylogger stopped")

    def pause(self):
        self._is_paused = True
        logger.info("Keylogger paused")

    def resume(self):
        self._is_paused = False
        logger.info("Keylogger resumed")

    # ─── LISTENER CALLBACK ───────────────────────────────────────────────────

    def _on_key_press(self, key):
        """Called by pynput on every keydown event (runs on pynput's thread)."""
        if not self._is_running or self._is_paused:
            return

        try:
            from pynput.keyboard import Key

            # ── Context switching check ──────────────────────────────────────
            new_app, new_title = _get_active_window_info()
            with self._lock:
                if new_title != self._current_title:
                    # Window changed — flush buffer attributed to the OLD window
                    self._flush_buffer_locked(
                        app=self._current_app,
                        title=self._current_title
                    )
                    self._current_app = new_app
                    self._current_title = new_title

            # ── Privacy filter ───────────────────────────────────────────────
            title_lower = new_title.lower()
            if any(kw in title_lower for kw in PRIVACY_KEYWORDS):
                return  # Silently discard — do NOT buffer sensitive fields

            # ── Key translation ──────────────────────────────────────────────
            with self._lock:
                if key == Key.enter:
                    self._flush_buffer_locked(
                        app=self._current_app,
                        title=self._current_title
                    )
                elif key == Key.space:
                    self._buffer += " "
                elif key == Key.backspace:
                    self._buffer = self._buffer[:-1]
                elif key == Key.tab:
                    self._buffer += "\t"
                elif hasattr(key, "char") and key.char is not None:
                    self._buffer += key.char
                # Ignore modifier keys (Shift, Ctrl, Alt, Win, etc.)

        except Exception as e:
            logger.debug(f"Keylogger callback error: {e}")

    # ─── BUFFER HELPERS ──────────────────────────────────────────────────────

    def _flush_buffer(self):
        """Thread-safe flush — acquires lock internally."""
        with self._lock:
            self._flush_buffer_locked(
                app=self._current_app,
                title=self._current_title
            )

    def _flush_buffer_locked(self, app: str, title: str):
        """
        Flush self._buffer to the database.
        MUST be called while self._lock is held (or during stop when listener
        is already halted).
        """
        content = self._buffer.strip()
        self._buffer = ""  # Always clear, even if content is empty
        if not content:
            return

        try:
            self.db_manager.insert_text_log(
                application=app or "Unknown",
                window_title=title or "Unknown",
                content=content
            )
            logger.debug(f"Keylog flushed for [{app}]: {len(content)} chars")
        except Exception as e:
            logger.error(f"Failed to flush keystroke buffer: {e}")
