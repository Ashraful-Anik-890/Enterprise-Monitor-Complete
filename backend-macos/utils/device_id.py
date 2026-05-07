"""
device_id.py — macOS
Machine-scoped UUID for stable device identification.

Storage:
  Primary:  /Library/Application Support/EnterpriseMonitor/device.id
  Backup:   defaults write /Library/Preferences/com.enterprisemonitor DeviceId <uuid>

Rules:
  - Write-once: only generate if BOTH locations are empty.
  - Primary wins on conflict (overwrites backup).
  - Returns None if generation/write fails (never empty string).

Trap Fix:
  Writing to /Library/Preferences/ requires root/sudo. The subprocess.run
  call is wrapped in try/except so that a standard-user agent gracefully
  falls back to the primary file without crashing the boot sequence.
"""

import logging
import subprocess
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PRIMARY_DIR = Path("/Library/Application Support/EnterpriseMonitor")
_PRIMARY_FILE = _PRIMARY_DIR / "device.id"

_DEFAULTS_DOMAIN = "/Library/Preferences/com.enterprisemonitor"
_DEFAULTS_KEY = "DeviceId"


def _read_primary() -> Optional[str]:
    try:
        if _PRIMARY_FILE.exists():
            text = _PRIMARY_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception as e:
        logger.debug("device_id: cannot read primary file: %s", e)
    return None


def _read_backup() -> Optional[str]:
    try:
        result = subprocess.run(
            ["defaults", "read", _DEFAULTS_DOMAIN, _DEFAULTS_KEY],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            value = result.stdout.strip()
            if value:
                return value
    except subprocess.TimeoutExpired:
        logger.debug("device_id: defaults read timed out")
    except PermissionError:
        logger.debug("device_id: no permission to read defaults domain")
    except Exception as e:
        logger.debug("device_id: defaults read error: %s", e)
    return None


def _write_primary(device_uuid: str) -> bool:
    try:
        _PRIMARY_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _PRIMARY_FILE.with_suffix(".tmp")
        tmp.write_text(device_uuid, encoding="utf-8")
        tmp.replace(_PRIMARY_FILE)
        return True
    except Exception as e:
        logger.warning("device_id: cannot write primary file: %s", e)
        return False


def _write_backup(device_uuid: str) -> bool:
    """
    Write UUID to macOS defaults (system domain).

    TRAP FIX: /Library/Preferences/ requires root. If the agent runs as
    a standard user, subprocess will fail with a permission error. We catch
    it gracefully and log a warning — the primary file is sufficient.
    """
    try:
        result = subprocess.run(
            ["defaults", "write", _DEFAULTS_DOMAIN, _DEFAULTS_KEY, device_uuid],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return True
        logger.warning(
            "device_id: defaults write failed (rc=%d): %s",
            result.returncode, result.stderr.strip(),
        )
    except PermissionError:
        logger.warning(
            "device_id: no permission to write /Library/Preferences/ "
            "(agent running as standard user — using primary file only)"
        )
    except subprocess.TimeoutExpired:
        logger.warning("device_id: defaults write timed out")
    except Exception as e:
        logger.warning("device_id: defaults write error: %s", e)
    return False


def get_device_uuid() -> Optional[str]:
    """
    Returns the machine-scoped UUID, generating it on first call.
    Returns None if no UUID can be established.
    """
    primary = _read_primary()
    backup = _read_backup()

    # Both exist and match
    if primary and backup and primary == backup:
        return primary

    # Primary exists, backup missing or mismatched → primary wins
    if primary:
        if backup != primary:
            _write_backup(primary)
        return primary

    # Primary missing, backup exists → restore primary
    if backup:
        _write_primary(backup)
        return backup

    # Neither exists → generate
    new_uuid = str(uuid.uuid4())
    wrote_primary = _write_primary(new_uuid)
    _write_backup(new_uuid)

    if wrote_primary:
        logger.info("device_id: generated new UUID: %s", new_uuid)
        return new_uuid

    # Write failed entirely
    logger.error("device_id: failed to persist UUID to any location")
    return None
