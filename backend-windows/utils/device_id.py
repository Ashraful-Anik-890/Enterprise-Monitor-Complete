"""
device_id.py — Windows
Machine-scoped UUID for stable device identification.

Storage:
  Primary:  %PROGRAMDATA%\\EnterpriseMonitor\\device.id
  Backup:   HKLM\\Software\\EnterpriseMonitor\\DeviceId

Rules:
  - Write-once: only generate if BOTH locations are empty.
  - Primary wins on conflict (overwrites backup).
  - Returns None if generation/write fails (never empty string).
"""

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PRIMARY_DIR = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "EnterpriseMonitor"
_PRIMARY_FILE = _PRIMARY_DIR / "device.id"

_REG_KEY = r"Software\EnterpriseMonitor"
_REG_VALUE = "DeviceId"


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
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REG_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, _REG_VALUE)
            if value:
                return str(value).strip()
    except FileNotFoundError:
        pass
    except PermissionError:
        logger.debug("device_id: no read access to HKLM registry key")
    except Exception as e:
        logger.debug("device_id: registry read error: %s", e)
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
    try:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, _REG_KEY, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, _REG_VALUE, 0, winreg.REG_SZ, device_uuid)
        return True
    except PermissionError:
        logger.warning("device_id: no write access to HKLM (agent running as standard user)")
    except Exception as e:
        logger.warning("device_id: registry write error: %s", e)
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
