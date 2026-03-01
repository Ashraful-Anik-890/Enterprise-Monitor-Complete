"""
autostart_manager.py
Manages auto-start on macOS using a LaunchAgent plist.

LaunchAgent equivalent of Windows Registry Run key.
Placed in ~/Library/LaunchAgents/ — loaded by launchd per-user at login.

The primary auto-start mechanism is Electron's app.setLoginItemSettings().
This LaunchAgent is a secondary fallback: it starts the backend if the user
logs in and Electron is not running (e.g., headless monitoring scenario).

Note: The plist ProgramArguments path must point to the installed binary,
not a dev path. The install() method resolves sys.executable at call time.
"""

import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PLIST_LABEL = 'com.enterprisemonitor.backend'
PLIST_PATH = Path.home() / 'Library' / 'LaunchAgents' / f'{PLIST_LABEL}.plist'

PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
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
    <string>{log_dir}/backend.log</string>
    <key>StandardOutPath</key>
    <string>{log_dir}/backend.log</string>
</dict>
</plist>
"""


def install(binary_path: str, log_dir: str) -> bool:
    """
    Install a LaunchAgent plist to auto-start the backend at login.

    Args:
        binary_path: Absolute path to the backend binary.
        log_dir:     Absolute path to the log directory.

    Returns:
        True if the plist was written and loaded successfully.
    """
    try:
        # Ensure the LaunchAgents directory exists
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Ensure log directory exists
        Path(log_dir).mkdir(parents=True, exist_ok=True)

        plist_content = PLIST_TEMPLATE.format(
            label=PLIST_LABEL,
            binary_path=binary_path,
            log_dir=log_dir,
        )

        PLIST_PATH.write_text(plist_content, encoding='utf-8')
        logger.info("LaunchAgent plist written: %s", PLIST_PATH)

        # Register immediately with launchctl
        result = subprocess.run(
            ['launchctl', 'load', str(PLIST_PATH)],
            capture_output=True, text=True, timeout=10,
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
    """
    Unload and remove the LaunchAgent plist.

    Returns:
        True if the plist was unloaded and deleted (or did not exist).
    """
    try:
        if not PLIST_PATH.exists():
            logger.info("LaunchAgent plist not found — nothing to uninstall")
            return True

        # Unload from launchctl
        result = subprocess.run(
            ['launchctl', 'unload', str(PLIST_PATH)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.warning("launchctl unload returned %d: %s", result.returncode, result.stderr.strip())

        # Remove the plist file
        PLIST_PATH.unlink(missing_ok=True)
        logger.info("LaunchAgent uninstalled: %s", PLIST_PATH)
        return True

    except Exception as e:
        logger.error("Failed to uninstall LaunchAgent: %s", e)
        return False


def is_installed() -> bool:
    """Check if the LaunchAgent plist exists on disk."""
    return PLIST_PATH.exists()
