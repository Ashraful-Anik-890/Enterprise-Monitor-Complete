"""
main.py — macOS Entry Point

Enterprise Monitor Backend (macOS)

Equivalent of backend-windows/main.py, with the following macOS adaptations:
  1. Single-instance guard via fcntl.flock (replaces Windows Mutex)
  2. Storage path ~/Library/Application Support/EnterpriseMonitor (replaces LOCALAPPDATA)
  3. TCC permission checks on the main thread BEFORE any monitoring thread starts
  4. Atomic port.info write (write to .tmp, then os.replace) for race-condition safety
  5. Port discovery: find an available port, write it to port.info for Electron to read
  6. No comtypes cache, no win32 imports, no UPX

Exit codes:
  0  — normal shutdown
  77 — another instance is already running (this mirrors the Windows version)
  1  — fatal error
"""

import os
import sys
import fcntl
import socket
import signal
import logging
import tempfile
from pathlib import Path

# ── macOS storage directory ──────────────────────────────────────────────────
EM_DIR = Path.home() / 'Library' / 'Application Support' / 'EnterpriseMonitor'
LOG_DIR = EM_DIR / 'logs'
PORT_INFO = EM_DIR / 'port.info'
LOCK_FILE = EM_DIR / '.backend.lock'


def _setup_logging(level=logging.INFO):
    """Configure root logger to file + stderr."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / 'backend.log'

    formatter = logging.Formatter(
        '%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    file_handler = logging.FileHandler(str(log_file), encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(level)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)

    return logging.getLogger(__name__)


def _acquire_lock(logger) -> int:
    """
    POSIX single-instance guard.
    Opens a lock file and tries fcntl.flock(LOCK_EX | LOCK_NB).
    On success, returns the fd (kept open for process lifetime).
    On failure (another instance holds the lock), logs and exits with code 77.
    """
    EM_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Write our PID for diagnostic purposes
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        logger.info("Single-instance lock acquired: %s (pid=%d)", LOCK_FILE, os.getpid())
        return fd
    except (OSError, IOError):
        logger.error(
            "Another backend instance is already running (lock held on %s). "
            "Exiting with code 77.",
            LOCK_FILE,
        )
        sys.exit(77)


def _find_available_port() -> int:
    """Find an available TCP port by binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _write_port_info(port: int, logger):
    """
    Write the port number to port.info atomically.
    Strategy: write to a temp file in the same directory, then os.replace().
    This prevents Electron from ever reading a partial/empty file.
    """
    EM_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = PORT_INFO.with_suffix('.tmp')
    try:
        tmp_path.write_text(str(port), encoding='utf-8')
        os.replace(str(tmp_path), str(PORT_INFO))
        logger.info("port.info written: %s → port %d", PORT_INFO, port)
    except Exception as e:
        logger.error("Failed to write port.info: %s", e)
        raise


def _cleanup_port_info(logger):
    """Remove port.info on shutdown."""
    try:
        if PORT_INFO.exists():
            PORT_INFO.unlink()
            logger.info("port.info removed")
    except OSError as e:
        logger.warning("Could not remove port.info: %s", e)


def main():
    """
    Main entry point.
    Execution order is critical:
      1. Setup logging
      2. Acquire single-instance lock (exit 77 if already running)
      3. Check TCC permissions on the main thread
      4. Find available port, write port.info
      5. Start uvicorn (api_server handles starting monitors in startup_event)
    """
    logger = _setup_logging()
    logger.info("="*60)
    logger.info("Enterprise Monitor Backend (macOS) starting")
    logger.info("Storage: %s", EM_DIR)
    logger.info("="*60)

    # ── Step 1: Single-instance guard ────────────────────────────────────────
    lock_fd = _acquire_lock(logger)

    # ── Step 2: Create all needed directories ────────────────────────────────
    for subdir in ('logs', 'screenshots', 'videos'):
        (EM_DIR / subdir).mkdir(parents=True, exist_ok=True)

    # ── Step 3: TCC permission checks (MUST be on main thread) ───────────────
    logger.info("Checking macOS TCC permissions...")
    try:
        from monitoring.permissions import check_all_permissions
        perm_state = check_all_permissions()
        logger.info("TCC permission state: %s", perm_state)
    except Exception as e:
        logger.error("TCC permission check failed: %s — continuing with defaults", e)

    # ── Step 4: Find available port and write port.info ──────────────────────
    port = _find_available_port()
    logger.info("Selected port: %d", port)
    _write_port_info(port, logger)

    # ── Step 5: Register cleanup for port.info on shutdown ───────────────────
    def _on_signal(signum, frame):
        logger.info("Signal %d received — cleaning up", signum)
        _cleanup_port_info(logger)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    # ── Step 6: Start uvicorn ────────────────────────────────────────────────
    try:
        import uvicorn
        logger.info("Starting uvicorn on 127.0.0.1:%d", port)
        uvicorn.run(
            "api_server:app",
            host="127.0.0.1",
            port=port,
            log_level="info",
            workers=1,          # single process — matches Windows behavior
        )
    except Exception as e:
        logger.critical("Uvicorn failed: %s", e, exc_info=True)
        _cleanup_port_info(logger)
        sys.exit(1)
    finally:
        _cleanup_port_info(logger)
        # Lock is released automatically when the process exits and the fd closes


if __name__ == "__main__":
    main()
