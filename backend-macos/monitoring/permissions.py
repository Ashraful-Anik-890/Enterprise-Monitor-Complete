"""
permissions.py
macOS TCC permission checker and requester.

Called from main.py on the main thread at startup, BEFORE any monitoring
thread is spawned. Each permission is checked independently — a denied
permission disables only its dependent monitor(s) without crashing others.

macOS TCC permissions involved:
  - Screen Recording: required by mss (screenshot + screen_recorder)
  - Accessibility: required by osascript System Events (window titles in app_tracker)
  - Input Monitoring: no programmatic check — detect by pynput event count test

IMPORTANT: CGRequestScreenCaptureAccess() and AXIsProcessTrusted() MUST be
called from the main thread. Never call them from a threading.Thread.
"""

import subprocess
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Module-level cached state — set once by check_all_permissions(), read many times.
_state: 'PermissionState | None' = None


@dataclass
class PermissionState:
    screen_recording: bool = False
    accessibility: bool = False
    input_monitoring: bool = True  # optimistic — pynput handles silent-deny


def check_all_permissions() -> PermissionState:
    """
    Check Screen Recording and Accessibility synchronously on the main thread.
    Input Monitoring is set to True (optimistic) — the keylogger itself handles
    the silent-fail case where pynput starts but receives zero events.

    Must be called from the main thread BEFORE any monitoring thread is spawned.
    Results are cached in module-level _state for later retrieval by api_server.
    """
    global _state

    state = PermissionState()

    # ── Screen Recording ─────────────────────────────────────────────────────
    try:
        from Quartz import CGPreflightScreenCaptureAccess
        state.screen_recording = bool(CGPreflightScreenCaptureAccess())
        if state.screen_recording:
            logger.info("TCC: Screen Recording permission GRANTED")
        else:
            logger.warning("TCC: Screen Recording permission DENIED — screenshots and recording will be disabled")
    except ImportError:
        logger.error("TCC: pyobjc-framework-Quartz not installed — cannot check Screen Recording")
        state.screen_recording = False
    except Exception as e:
        logger.error("TCC: Screen Recording check failed: %s", e)
        state.screen_recording = False

    # ── Accessibility ────────────────────────────────────────────────────────
    try:
        from ApplicationServices import AXIsProcessTrusted
        state.accessibility = bool(AXIsProcessTrusted())
        if state.accessibility:
            logger.info("TCC: Accessibility permission GRANTED")
        else:
            logger.warning(
                "TCC: Accessibility permission DENIED — window titles will be empty. "
                "App names will still be captured."
            )
    except ImportError:
        logger.error("TCC: pyobjc-framework-ApplicationServices not installed — cannot check Accessibility")
        state.accessibility = False
    except Exception as e:
        logger.error("TCC: Accessibility check failed: %s", e)
        state.accessibility = False

    # ── Input Monitoring ─────────────────────────────────────────────────────
    # No programmatic check API exists for Input Monitoring on macOS.
    # We set it to True (optimistic). If permission is actually denied,
    # pynput's listener will start but receive zero keydown events forever.
    # The keylogger handles this gracefully by simply having nothing to flush.
    state.input_monitoring = True
    logger.info("TCC: Input Monitoring set to True (optimistic — pynput handles silent-deny)")

    _state = state
    logger.info("TCC permission check complete: %s", state)
    return state


def get_permission_state() -> PermissionState:
    """
    Return the cached permission state.
    Must be called AFTER check_all_permissions() has run in main.py.
    If somehow called before check, returns a default (all denied) state
    and logs an error.
    """
    global _state
    if _state is None:
        logger.error(
            "get_permission_state() called before check_all_permissions()! "
            "Returning default (all denied) state. This is a startup ordering bug."
        )
        return PermissionState()
    return _state


def request_screen_recording_if_needed() -> bool:
    """
    If Screen Recording is denied, call CGRequestScreenCaptureAccess().
    This triggers the system dialog. Returns current state after request.
    Also opens System Settings directly since we cannot force-grant.
    """
    try:
        from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

        if CGPreflightScreenCaptureAccess():
            return True

        # Trigger the system dialog
        CGRequestScreenCaptureAccess()

        # Open System Settings to the Screen Recording pane
        subprocess.run(
            ['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'],
            capture_output=True, timeout=5,
        )
        logger.info("Opened System Settings → Screen Recording pane")

        # Re-check (user may not have granted yet — dialog is async)
        return bool(CGPreflightScreenCaptureAccess())

    except ImportError:
        logger.error("pyobjc-framework-Quartz not installed — cannot request Screen Recording")
        return False
    except Exception as e:
        logger.error("request_screen_recording_if_needed failed: %s", e)
        return False


def open_accessibility_settings():
    """
    Accessibility cannot be requested programmatically — only opened.
    Opens System Settings → Accessibility pane.
    """
    try:
        subprocess.run(
            ['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'],
            capture_output=True, timeout=5,
        )
        logger.info("Opened System Settings → Accessibility pane")
    except Exception as e:
        logger.error("open_accessibility_settings failed: %s", e)


def probe_input_monitoring(timeout_seconds: float = 5.0) -> bool:
    """
    Start a pynput listener and check if it starts without exception.

    Simpler approach: just start the listener and set input_monitoring=True
    if the listener starts without exception. Log a warning that it may be
    silently denied and events will simply not arrive if permission was denied.
    Returns True (optimistic) — the keylogger itself handles the silent-fail case.
    """
    try:
        from pynput import keyboard as _kb

        # Attempt to create a listener — this will raise if pynput
        # cannot hook into the event system at all.
        listener = _kb.Listener(on_press=lambda key: None, suppress=False)
        listener.daemon = True
        listener.start()
        # Give it a moment to start
        import time
        time.sleep(0.5)
        listener.stop()

        logger.info(
            "Input Monitoring probe: pynput listener started successfully. "
            "Note: if permission is denied, events will silently not arrive."
        )
        return True

    except ImportError:
        logger.error("pynput not installed — Input Monitoring probe failed")
        return False
    except Exception as e:
        logger.warning("Input Monitoring probe failed: %s — keylogger may not receive events", e)
        return False
