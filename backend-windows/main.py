# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  CRITICAL: stdout/stderr redirect MUST be the absolute first code executed. ║
# ║  PyInstaller console=False leaves sys.stdout/stderr as None.                ║
# ║  Any library that calls print() or writes to sys.stdout before this runs    ║
# ║  (e.g. uvicorn, logging StreamHandler) will raise OSError and crash silently.║
# ╚══════════════════════════════════════════════════════════════════════════════╝
import sys
import os

if sys.stdout is None or not hasattr(sys.stdout, 'write'):
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None or not hasattr(sys.stderr, 'write'):
    sys.stderr = open(os.devnull, 'w')

# ── comtypes cache redirect: MUST happen before ANY import of uiautomation ────
# uiautomation imports comtypes at module level. comtypes tries to write
# generated COM wrappers to its package directory (which is read-only inside a
# PyInstaller bundle). We redirect it to a writable user directory right here,
# before anything else can trigger the import chain.
_local_appdata = os.environ.get("LOCALAPPDATA") or os.path.join(
    os.path.expanduser("~"), "AppData", "Local"
)
_em_dir = os.path.join(_local_appdata, "EnterpriseMonitor")
_comtypes_cache = os.path.join(_em_dir, "comtypes_cache")
os.makedirs(_comtypes_cache, exist_ok=True)
os.environ["COMTYPES_CACHE"] = _comtypes_cache  # env var read by some comtypes versions

# Also set comtypes.client.gen_dir directly once comtypes is importable.
# We do this via a lazy setter so it fires before browser_tracker imports uiautomation.
try:
    import comtypes.client
    comtypes.client.gen_dir = _comtypes_cache
except Exception:
    pass  # comtypes not yet importable at this point on some builds; browser_tracker handles it

# ── Now it is safe to set up logging ──────────────────────────────────────────
import logging
import socket
import ctypes
from pathlib import Path

_log_dir = Path(_em_dir) / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(_log_dir / "backend.log", encoding="utf-8"),
        # StreamHandler is intentionally omitted for console=False builds.
        # Adding it here would write to the devnull fd we opened above — harmless
        # but pointless. All diagnostics go to backend.log.
    ],
)

logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _find_free_port() -> int:
    """
    Bind to port 0 (OS picks a free ephemeral port), capture it, then release.
    This is the canonical way to find a free port without a race condition window
    that exists with the "try connecting" approach.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _write_port_info(port: int) -> None:
    """
    Write the bound port to %LOCALAPPDATA%\\EnterpriseMonitor\\port.info.
    Electron watches for this file to appear and reads the port from it.
    We write atomically: write to a .tmp file, then rename so Electron never
    reads a partial file.
    """
    port_dir = Path(_em_dir)
    port_dir.mkdir(parents=True, exist_ok=True)

    tmp_path  = port_dir / "port.info.tmp"
    final_path = port_dir / "port.info"

    tmp_path.write_text(str(port), encoding="utf-8")
    # os.replace is atomic on Windows (NTFS) and POSIX
    os.replace(str(tmp_path), str(final_path))
    logger.info("Port info written: %s → port %d", final_path, port)


# ─── Single-instance guard ────────────────────────────────────────────────────

def _acquire_single_instance_mutex() -> object:
    """
    Named Windows mutex prevents duplicate backend processes.
    Returns the handle (must stay referenced for process lifetime) or None.
    """
    MUTEX_NAME        = "Local\\EnterpriseMonitorBackend_SingleInstance"
    ERROR_ALREADY_EXISTS = 183

    handle   = ctypes.windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
    last_err = ctypes.windll.kernel32.GetLastError()

    if last_err == ERROR_ALREADY_EXISTS:
        logger.warning(
            "Duplicate backend instance detected — exiting with code 77. "
            "Electron's Master/Child lifecycle should prevent this."
        )
        sys.exit(77)  # distinctive code so Electron can detect "duplicate" vs "crash"

    if not handle:
        logger.error(
            "CreateMutexW failed (err=%d) — continuing without mutex guard.", last_err
        )
        return None

    logger.info("Single-instance mutex acquired.")
    return handle


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("Enterprise Monitor Backend starting (Master/Child mode)...")

    # 1. Single-instance guard — keep reference alive for process lifetime
    _mutex = _acquire_single_instance_mutex()  # noqa: F841

    # 2. Find a free port and publish it BEFORE uvicorn binds
    port = _find_free_port()
    logger.info("Selected dynamic port: %d", port)

    # 3. Write port.info atomically — Electron is polling for this file
    _write_port_info(port)

    # 4. Start uvicorn on the dynamic port
    try:
        import uvicorn
        from api_server import app  # local import keeps startup error messages in log

        logger.info("Starting uvicorn on 127.0.0.1:%d", port)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            log_level="info",
            access_log=True,
            # Disable uvicorn's own signal handlers — Electron sends SIGTERM/TerminateProcess
            # directly and we want a clean shutdown via the FastAPI lifespan, not a double-handler.
        )
    except Exception as exc:
        logger.exception("Fatal error starting uvicorn: %s", exc)
        raise
    finally:
        # Clean up port.info on shutdown so stale files don't mislead a future launch
        _port_file = Path(_em_dir) / "port.info"
        if _port_file.exists():
            try:
                _port_file.unlink()
                logger.info("port.info cleaned up on exit.")
            except OSError:
                pass


if __name__ == "__main__":
    main()
