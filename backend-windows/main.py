"""
Enterprise Monitor - Windows Backend Service
Main entry point for the monitoring service

SINGLE-INSTANCE GUARD:
  Uses a Windows named mutex to ensure only one instance runs at a time.
  If a second instance starts (e.g. Task Scheduler fires twice, or user
  runs it manually while the task is already running), it exits immediately.
  The mutex name is unique to this app and user session.
"""

import sys
import logging
import ctypes
from pathlib import Path

# ── Logging setup (must happen before any other imports) ─────────────────────
log_dir = Path.home() / "AppData" / "Local" / "EnterpriseMonitor" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "backend.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


# ── Single-instance guard ─────────────────────────────────────────────────────
def _acquire_single_instance_mutex() -> object:
    """
    Create a named Windows mutex. If it already exists this process is a
    duplicate — log and exit immediately.

    Returns the mutex handle (must stay alive for the process lifetime).
    """
    MUTEX_NAME = "Local\\EnterpriseMonitorBackend_SingleInstance"
    ERROR_ALREADY_EXISTS = 183

    handle = ctypes.windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
    last_err = ctypes.windll.kernel32.GetLastError()

    if last_err == ERROR_ALREADY_EXISTS:
        logger.warning(
            "Another instance of Enterprise Monitor Backend is already running. "
            "This instance will exit now."
        )
        sys.exit(0)   # clean exit — not an error

    if not handle:
        # CreateMutex failed entirely — log but continue running
        logger.error("Failed to create single-instance mutex (err=%d). Continuing anyway.", last_err)
        return None

    logger.info("Single-instance mutex acquired — this is the only running instance.")
    return handle   # keep reference alive; releasing it would free the mutex


def main():
    """Start the backend API server."""
    logger.info("Starting Enterprise Monitor Backend Service...")

    # Acquire mutex BEFORE starting uvicorn/services
    _mutex = _acquire_single_instance_mutex()

    try:
        import uvicorn
        from api_server import app

        uvicorn.run(
            app,
            host="127.0.0.1",
            port=51235,
            log_level="info",
            access_log=True,
        )
    except Exception as e:
        logger.error("Failed to start backend service: %s", e)
        raise


if __name__ == "__main__":
    main()