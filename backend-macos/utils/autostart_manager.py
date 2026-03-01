"""
autostart_manager.py — macOS version
Manages auto-start on macOS using a LaunchAgent plist.

LaunchAgent is the macOS equivalent of the Windows Registry Run key.
Placed in ~/Library/LaunchAgents/ — loaded by launchd per-user at login.

The PRIMARY auto-start mechanism is Electron's app.setLoginItemSettings().
This LaunchAgent is a SECONDARY fallback: it starts the backend if the user
logs in and Electron is not running (e.g. headless monitoring scenario).

Note: The plist ProgramArguments path must point to the installed binary,
not a dev path. Resolved at install() call time via the binary_path argument.
"""

import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PLIST_LABEL = "com.enterprisemonitor.backend"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"

_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{binary_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
</dict>
</plist>
"""


def install(binary_path: str, log_dir: str) -> bool:
    """
    Write the LaunchAgent plist and load it immediately via launchctl.
    binary_path: absolute path to the enterprise_monitor_backend binary.
    log_dir:     directory where backend.log is written.
    Returns True on success.
    """
    try:
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        log_path = str(Path(log_dir) / "backend.log")
        content = _PLIST_TEMPLATE.format(
            label=PLIST_LABEL,
            binary_path=binary_path,
            log_path=log_path,
        )
        PLIST_PATH.write_text(content, encoding="utf-8")
        logger.info("LaunchAgent plist written: %s", PLIST_PATH)

        result = subprocess.run(
            ["launchctl", "load", str(PLIST_PATH)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.warning("launchctl load returned %d: %s", result.returncode, result.stderr.strip())
        else:
            logger.info("LaunchAgent loaded successfully")
        return True
    except Exception as e:
        logger.error("Failed to install LaunchAgent: %s", e)
        return False


def uninstall() -> bool:
    """Unload and remove the LaunchAgent plist. Returns True on success."""
    try:
        if PLIST_PATH.exists():
            subprocess.run(
                ["launchctl", "unload", str(PLIST_PATH)],
                capture_output=True,
            )
            PLIST_PATH.unlink()
            logger.info("LaunchAgent removed: %s", PLIST_PATH)
        return True
    except Exception as e:
        logger.error("Failed to uninstall LaunchAgent: %s", e)
        return False


def is_installed() -> bool:
    """Returns True if the LaunchAgent plist exists."""
    return PLIST_PATH.exists()
