import ctypes
import win32gui
import logging

logger = logging.getLogger(__name__)

def is_user_session_active() -> bool:
    """
    Returns True if:
    1. The foreground window is not 0 (meaning there is an active UI context).
    2. The session is not locked.
    
    On Windows, when the screen is locked or hibernating, the foreground window 
    is typically part of the "LogonUI.exe" process or handle 0.
    """
    try:
        # Check for foreground window
        hwnd = win32gui.GetForegroundWindow()
        if hwnd == 0:
            return False
            
        # Optional: Check if the desktop is "Default" (not "Winlogon" or "ScreenSaver")
        # However, GetForegroundWindow handle 0 is a very strong proxy for "no interactive desktop".
        return True
    except Exception as e:
        logger.error(f"Error checking session activity: {e}")
        return True # Default to True to avoid missing data on error
