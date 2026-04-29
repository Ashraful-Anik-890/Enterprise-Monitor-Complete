"""
api_server.py — macOS version
FastAPI REST API Server

FIXES vs the truncated version in the repo:
  1. sync_service = SyncService(db  ← was cut off; now complete
  2. @app.on_event("startup"/"shutdown") ← deprecated FastAPI 0.95+; migrated to lifespan
  3. startup is permission-gated: reads TCC state from permissions.py
  4. Graceful shutdown cleans macOS port.info path (not LOCALAPPDATA)
  5. Health endpoint returns platform: "macos"
"""

import asyncio
import getpass
import logging
import os
import socket
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Any
import threading
import requests

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth.auth_manager import AuthManager
from database.db_manager import DatabaseManager
from monitoring.app_tracker import AppTracker
from monitoring.browser_tracker import BrowserTracker
from monitoring.clipboard import ClipboardMonitor
from monitoring.data_cleaner import CleanupService
from monitoring.keylogger import Keylogger
from monitoring.screen_recorder import ScreenRecorder
from monitoring.screenshot import ScreenshotMonitor
from services.sync_service import SyncService
from utils.config_manager import ConfigManager
from url import (
    DYNAMIC_API_ENABLED,
    COMPANY_NAME,
    PATH_APP_ACTIVITY,
    PATH_BROWSER,
    PATH_CLIPBOARD,
    PATH_KEYSTROKES,
    PATH_SCREENSHOTS,
    PATH_VIDEOS,
    PATH_VIDEO_SETTINGS,
    PATH_SCREENSHOT_SETTINGS,
    PATH_MONITORING_SETTINGS,
    PATH_DEVICE_STATUS,
    PATH_CONFIRM_IDENTITY,
)

logger = logging.getLogger(__name__)

# ── Module-level service instances ───────────────────────────────────────────
auth_manager       = AuthManager()
db_manager         = DatabaseManager()
screenshot_monitor = ScreenshotMonitor(db_manager)
clipboard_monitor  = ClipboardMonitor(db_manager)
app_tracker        = AppTracker(db_manager)
browser_tracker    = BrowserTracker(db_manager)
keylogger          = Keylogger(db_manager)
cleanup_service    = CleanupService(db_manager)
config_manager     = ConfigManager()
sync_service       = SyncService(db_manager, config_manager)   # ← was truncated here
screen_recorder    = ScreenRecorder(db_manager, config_manager)

monitoring_active = True

def _notify_server_sync(endpoint_path_key: str, payload_key: str, payload_value: Any):
    """
    Unified helper to notify the remote server of state changes (macOS).
    """
    try:
        config = db_manager.get_identity_config()
        pc_name = config.get("device_alias") or socket.gethostname()
        # Use stored MAC from DB (matches what was registered with the server)
        # uuid.getnode() is unreliable on macOS and may return a different value
        mac_address = config.get("mac_address", "")
        user_name = config.get("user_alias") or config.get("os_user", "")
        
        # Determine URL
        url = config_manager.get(endpoint_path_key, "").strip()
        if not url:
            base_url = config_manager.get("base_url", "").strip()
            if not base_url:
                return
            
            from url import (
                PATH_MONITORING_SETTINGS, 
                PATH_SCREENSHOT_SETTINGS, 
                PATH_VIDEO_SETTINGS
            )
            mapping = {
                "url_monitoring_settings": PATH_MONITORING_SETTINGS,
                "url_screenshot_settings": PATH_SCREENSHOT_SETTINGS,
                "url_video_settings": PATH_VIDEO_SETTINGS
            }
            path = mapping.get(endpoint_path_key)
            if not path:
                return
            url = f"{base_url.rstrip('/')}{path}"
            
        headers = {"Accept": "application/json"}
        api_key = config_manager.get("api_key", "").strip()
        if api_key:
            headers["X-API-Key"] = api_key
            
        payload = {
            "pcName": pc_name,
            "macAddress": mac_address,
            "userName": user_name,
            payload_key: payload_value
        }
        # Mark cooldown BEFORE the network call so it activates even on timeout/failure
        sync_service.mark_local_update()
        requests.post(url, json=payload, headers=headers, timeout=5)
    except Exception as e:
        logger.error(f"Failed to notify remote server for {payload_key}: {e}")


def _notify_server_confirm_identity():
    """
    v5.3.0: POST confirmed identity to the ERP server so the device is
    registered/updated in the admin dashboard. Fire-and-forget — called
    from a background thread after local confirm_credential succeeds.
    """
    try:
        from url import PATH_CONFIRM_IDENTITY

        config = db_manager.get_identity_config()
        url = config_manager.get("url_confirm_identity", "").strip()
        if not url:
            base_url = config_manager.get("base_url", "").strip()
            if not base_url:
                return
            url = f"{base_url.rstrip('/')}{PATH_CONFIRM_IDENTITY}"

        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        api_key = config_manager.get("api_key", "").strip()
        if api_key:
            headers["X-API-Key"] = api_key

        payload = {
            "pcName":     config.get("device_alias") or socket.gethostname(),
            "macAddress": config.get("mac_address", ""),
            "userName":   config.get("user_alias") or config.get("os_user", ""),
            "location":   config.get("location", ""),
            "osUser":     config.get("os_user", ""),
            "machineId":  config.get("machine_id", ""),
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.ok:
            logger.info("Identity confirmed on remote server: %s", payload.get("pcName"))
        else:
            logger.warning("Remote confirm-identity returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.error("Failed to notify remote server for confirm-identity: %s", e)

# ── Lifespan (replaces deprecated @app.on_event) ─────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager — replaces @app.on_event('startup'/'shutdown')."""

    # ── STARTUP ──────────────────────────────────────────────────────────────
    from monitoring.permissions import get_permission_state

    state = get_permission_state()
    logger.info("Starting monitoring services (TCC state: %s)", state)

    db_manager.initialize()

    screenshot_interval = int(config_manager.get("screenshot_interval", 10))
    screenshot_monitor.__init__(db_manager, interval_seconds=screenshot_interval)

    # Always start — no TCC permission required
    app_tracker.start()
    browser_tracker.start()
    clipboard_monitor.start()
    keylogger.start()
    cleanup_service.start()
    sync_service.start()

    # Screen Recording gated — mss returns black frames if denied
    if state.screen_recording:
        if config_manager.get("screenshot_enabled", True):
            screenshot_monitor.start()
            logger.info("Screenshot monitor started (was enabled in config)")
            
        if config_manager.get("recording_enabled", False):
            screen_recorder.start()
            logger.info("Screen recording started (was enabled in config)")
    else:
        logger.warning(
            "Screen Recording DENIED — screenshots and recording disabled. "
            "Grant in System Settings → Privacy & Security → Screen Recording."
        )

    yield  # ── app is running ─────────────────────────────────────────────

    # ── SHUTDOWN ─────────────────────────────────────────────────────────────
    logger.info("Shutdown: stopping all monitoring services")
    screenshot_monitor.stop()
    screen_recorder.stop()
    clipboard_monitor.stop()
    app_tracker.stop()
    browser_tracker.stop()
    keylogger.stop()
    cleanup_service.stop()
    sync_service.stop()
    logger.info("All services stopped")


app = FastAPI(title="Enterprise Monitor API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ───────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    error: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class StatisticsResponse(BaseModel):
    total_screenshots: int
    active_hours_today: float
    apps_tracked: int
    clipboard_events: int

class MonitoringStatusResponse(BaseModel):
    is_monitoring: bool
    uptime_seconds: int

class ScreenshotInfo(BaseModel):
    id: int
    timestamp: str
    file_path: str
    active_window: str
    active_app: str
    synced: bool = False

class ConfigRequest(BaseModel):
    # Global settings
    api_key:               Optional[str] = None
    sync_interval_seconds: Optional[int] = None
    screenshot_interval:   Optional[int] = None

    # Base URL shortcut — admin sets this; full URLs are derived in the frontend
    # and stored as the individual url_* keys below. Persisted here for UI reload.
    base_url: Optional[str] = None

    # Per-type ERP endpoint URLs (all optional — blank = that type is skipped)
    url_app_activity:      Optional[str] = None
    url_browser:           Optional[str] = None
    url_clipboard:         Optional[str] = None
    url_keystrokes:        Optional[str] = None
    url_screenshots:       Optional[str] = None
    url_videos:            Optional[str] = None
    url_monitoring_settings: Optional[str] = None
    url_screenshot_settings: Optional[str] = None
    url_video_settings:      Optional[str] = None
    url_device_status:       Optional[str] = None
    url_confirm_identity:    Optional[str] = None

    # Legacy — kept for backward compatibility with old installs
    server_url:            Optional[str] = None

class IdentityResponse(BaseModel):
    machine_id:           str
    mac_address:          str
    os_user:              str
    device_alias:         str
    user_alias:           str
    login_username:       str
    location:             str  = ""
    credential_confirmed: bool = False
    credential_drifted:   bool = False

class IdentityUpdateRequest(BaseModel):
    device_alias: Optional[str] = None
    user_alias:   Optional[str] = None
    location:     Optional[str] = None

class ConfirmCredentialRequest(BaseModel):
    device_alias: str
    user_alias:   str
    location:     str

class TimezoneRequest(BaseModel):
    timezone: str

class UpdateCredentialsRequest(BaseModel):
    new_username: str
    new_password: str
    security_q1:  str
    security_a1:  str
    security_q2:  str
    security_a2:  str

class VideoRecordingInfo(BaseModel):
    id:               int
    timestamp:        str
    file_path:        str
    duration_seconds: int
    is_synced:        bool

class ResetPasswordRequest(BaseModel):
    username:     str
    answer1:      str
    answer2:      str
    new_password: str


# ── Auth dependency ───────────────────────────────────────────────────────────
async def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="No authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    token = parts[1]
    try:
        payload = auth_manager.verify_token(token)
    except Exception as e:
        logger.error("Unexpected error in verify_token: %s", e)
        raise HTTPException(status_code=401, detail="Token validation error")
    if payload is None:
        raise HTTPException(status_code=401, detail="Token is invalid or has expired")
    return payload


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "platform": "macos",
        "hostname": socket.gethostname(),
        "os_user": getpass.getuser(),
    }


# ── Shutdown ──────────────────────────────────────────────────────────────────
@app.post("/api/shutdown")
async def shutdown(user=Depends(verify_token)):
    """Graceful shutdown — called by Electron on credential-gated quit."""
    logger.info("Graceful shutdown requested via /api/shutdown")

    # Clean up port.info — macOS path
    _port_file = Path.home() / "Library" / "Application Support" / "EnterpriseMonitor" / "port.info"
    try:
        if _port_file.exists():
            _port_file.unlink()
            logger.info("port.info cleaned up")
    except OSError:
        pass

    async def _delayed_exit():
        await asyncio.sleep(0.5)
        logger.info("Exiting process after graceful shutdown")
        os._exit(0)

    asyncio.get_event_loop().create_task(_delayed_exit())
    return {"success": True, "message": "Shutting down"}


# ── Auth endpoints ────────────────────────────────────────────────────────────
@app.post("/api/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    try:
        is_valid = auth_manager.verify_credentials(request.username, request.password)
        if is_valid:
            token = auth_manager.create_token(request.username)
            db_manager.update_login_username(request.username)
            return LoginResponse(success=True, token=token)
        return LoginResponse(success=False, error="Invalid credentials")
    except Exception as e:
        logger.error("Login error: %s", e)
        return LoginResponse(success=False, error="Login failed")

@app.get("/api/auth/check")
async def check_auth(user=Depends(verify_token)):
    return {"authenticated": True, "username": user.get("sub")}

@app.post("/api/auth/change-password")
async def change_password(request: ChangePasswordRequest, user=Depends(verify_token)):
    if "sub" not in user:
        raise HTTPException(status_code=401, detail="Invalid token")
    username = user["sub"]
    if not auth_manager.verify_credentials(username, request.old_password):
        return {"success": False, "error": "Invalid old password"}
    try:
        auth_manager.change_password(username, request.new_password)
        return {"success": True, "message": "Password changed successfully"}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Password change error: %s", e)
        return {"success": False, "error": "Failed to change password"}

@app.post("/api/auth/update-credentials")
async def update_credentials(request: UpdateCredentialsRequest, user=Depends(verify_token)):
    if "sub" not in user:
        raise HTTPException(status_code=401, detail="Invalid token")
    current_username = user["sub"]
    success, error = auth_manager.update_credentials(
        old_username=current_username,
        new_username=request.new_username,
        new_password=request.new_password,
    )
    if not success:
        return {"success": False, "error": error}
    try:
        auth_manager.save_security_qa(
            username=request.new_username,
            q1=request.security_q1, a1=request.security_a1,
            q2=request.security_q2, a2=request.security_a2,
        )
    except Exception as e:
        logger.error("QA save failed after credential update: %s", e)
        return {"success": True, "force_logout": True,
                "warning": "Credentials updated but security questions could not be saved."}
    return {"success": True, "force_logout": True}

@app.get("/api/auth/security-questions")
async def get_security_questions(username: str):
    try:
        questions = auth_manager.get_security_questions(username)
        if not questions:
            return {"success": False, "error": "No security questions found for this username."}
        return {"success": True, "questions": questions}
    except Exception as e:
        logger.error("get_security_questions error: %s", e)
        raise HTTPException(status_code=500, detail="Internal error")

@app.post("/api/auth/reset-password")
async def reset_password(request: ResetPasswordRequest):
    success, error = auth_manager.reset_password_with_qa(
        username=request.username,
        answer1=request.answer1,
        answer2=request.answer2,
        new_password=request.new_password,
    )
    if success:
        return {"success": True, "message": "Password reset successfully"}
    return {"success": False, "error": error}


# ── Identity ──────────────────────────────────────────────────────────────────
@app.get("/api/config/identity", response_model=IdentityResponse)
async def get_identity(user=Depends(verify_token)):
    try:
        config = db_manager.get_identity_config()
        return IdentityResponse(
            machine_id           = config["machine_id"],
            mac_address          = config["mac_address"],
            os_user              = config["os_user"],
            device_alias         = config["device_alias"],
            user_alias           = config["user_alias"],
            login_username       = config.get("login_username", ""),
            location             = config.get("location", ""),
            credential_confirmed = config.get("credential_confirmed", False),
            credential_drifted   = config.get("credential_drifted", False),
        )
    except Exception as e:
        logger.error("Error getting identity config: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get identity config")

@app.post("/api/config/identity")
async def update_identity(request: IdentityUpdateRequest, user=Depends(verify_token)):
    if request.device_alias is None and request.user_alias is None and request.location is None:
        return {"success": False, "error": "No fields to update"}
    try:
        ok = db_manager.update_identity_config(
            device_alias = request.device_alias,
            user_alias   = request.user_alias,
            location     = request.location,
        )
        if ok:
            return {"success": True, "message": "Identity updated"}
        return {"success": False, "error": "Update failed"}
    except Exception as e:
        logger.error("Error updating identity config: %s", e)
        raise HTTPException(status_code=500, detail="Failed to update identity config")

@app.post("/api/config/confirm-credential")
async def confirm_credential(request: ConfirmCredentialRequest, user=Depends(verify_token)):
    """
    Confirm identity credentials (PC name, user, location) after first install.
    Sets sync_enabled = true so ERP syncing begins with the confirmed values.
    Subsequent calls re-confirm (e.g. after alias drift is detected).

    v5.3.0: Also notifies the remote ERP server via POST /api/pctracking/confirm-identity
    so the device is registered/updated in the admin dashboard.
    """
    try:
        ok = db_manager.confirm_credential(
            device_alias = request.device_alias.strip(),
            user_alias   = request.user_alias.strip(),
            location     = request.location.strip(),
        )
        if ok:
            # Notify remote ERP server of identity confirmation (fire-and-forget)
            threading.Thread(
                target=_notify_server_confirm_identity,
                daemon=True,
            ).start()
        return {"success": ok}
    except Exception as e:
        logger.error("confirm_credential endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to confirm credential")

@app.get("/api/config/credential-status")
async def credential_status(user=Depends(verify_token)):
    """
    Returns whether credentials have been confirmed and whether they've drifted
    since confirmation (i.e., alias was changed without re-confirming).
    """
    try:
        config = db_manager.get_identity_config()
        return {
            "confirmed":          config.get("credential_confirmed", False),
            "drifted":            config.get("credential_drifted", False),
            "needs_confirmation": not config.get("credential_confirmed", False) or config.get("credential_drifted", False),
            "sync_enabled":       db_manager.is_sync_enabled(),
        }
    except Exception as e:
        logger.error("credential_status error: %s", e)
        raise HTTPException(status_code=500, detail="Internal error")


# ── Config ────────────────────────────────────────────────────────────────────
@app.get("/api/config")
async def get_config(user=Depends(verify_token)):
    return {
        # ── Lock / branding (read from url.py at build time) ─────────────────
        "dynamic_api_enabled": DYNAMIC_API_ENABLED,
        "company_name":        COMPANY_NAME,

        # ── URL path suffixes (server contract, from url.py) ─────────────────
        "path_app_activity": PATH_APP_ACTIVITY,
        "path_browser":      PATH_BROWSER,
        "path_clipboard":    PATH_CLIPBOARD,
        "path_keystrokes":   PATH_KEYSTROKES,
        "path_screenshots":  PATH_SCREENSHOTS,
        "path_videos":       PATH_VIDEOS,
        "path_monitoring_settings": PATH_MONITORING_SETTINGS,
        "path_screenshot_settings": PATH_SCREENSHOT_SETTINGS,
        "path_video_settings":      PATH_VIDEO_SETTINGS,
        "path_device_status":       PATH_DEVICE_STATUS,
        "path_confirm_identity":    PATH_CONFIRM_IDENTITY,

        # ── User-saved settings ───────────────────────────────────────────────
        "api_key":               config_manager.get("api_key", ""),
        "sync_interval_seconds": config_manager.get("sync_interval_seconds", 300),
        "screenshot_interval":   config_manager.get("screenshot_interval", 10),
        "base_url":              config_manager.get("base_url", ""),
        "url_app_activity":      config_manager.get("url_app_activity", ""),
        "url_browser":           config_manager.get("url_browser", ""),
        "url_clipboard":         config_manager.get("url_clipboard", ""),
        "url_keystrokes":        config_manager.get("url_keystrokes", ""),
        "url_screenshots":       config_manager.get("url_screenshots", ""),
        "url_videos":            config_manager.get("url_videos", ""),
        "url_monitoring_settings": config_manager.get("url_monitoring_settings", ""),
        "url_screenshot_settings": config_manager.get("url_screenshot_settings", ""),
        "url_video_settings":      config_manager.get("url_video_settings", ""),
        "url_device_status":       config_manager.get("url_device_status", ""),
        "url_confirm_identity":    config_manager.get("url_confirm_identity", ""),
        # legacy
        "server_url":            config_manager.get("server_url", ""),
        "screenshot_enabled":    config_manager.get("screenshot_enabled", True),
    }

@app.post("/api/config")
async def update_config(config: ConfigRequest, user=Depends(verify_token)):
    _fields = [
        ("api_key",               config.api_key),
        ("sync_interval_seconds", config.sync_interval_seconds),
        ("screenshot_interval",   config.screenshot_interval),
        ("base_url",              config.base_url),          # ← NEW
        ("url_app_activity",      config.url_app_activity),
        ("url_browser",           config.url_browser),
        ("url_clipboard",         config.url_clipboard),
        ("url_keystrokes",        config.url_keystrokes),
        ("url_screenshots",       config.url_screenshots),
        ("url_videos",            config.url_videos),
        ("url_monitoring_settings", config.url_monitoring_settings),
        ("url_screenshot_settings", config.url_screenshot_settings),
        ("url_video_settings",      config.url_video_settings),
        ("url_device_status",       config.url_device_status),
        ("url_confirm_identity",    config.url_confirm_identity),
        ("server_url",            config.server_url),
    ]
    for key, value in _fields:
        if value is not None:
            config_manager.set(key, value)
    return {"success": True}

@app.get("/api/config/timezone")
async def get_timezone(user=Depends(verify_token)):
    return {"timezone": config_manager.get("timezone", "UTC")}

@app.post("/api/config/timezone")
async def set_timezone(request: TimezoneRequest, user=Depends(verify_token)):
    config_manager.set("timezone", request.timezone)
    return {"success": True, "timezone": request.timezone}


# ── Sync ──────────────────────────────────────────────────────────────────────
@app.get("/api/sync/status")
async def get_sync_status(user=Depends(verify_token)):
    return sync_service.get_status()

@app.post("/api/sync/trigger")
async def trigger_sync(user=Depends(verify_token)):
    try:
        return sync_service.trigger_sync_now()
    except Exception as e:
        logger.error("Error triggering sync: %s", e)
        raise HTTPException(status_code=500, detail="Failed to trigger sync")


# ── Monitoring control ────────────────────────────────────────────────────────
@app.get("/api/monitoring/status", response_model=MonitoringStatusResponse)
async def get_monitoring_status(user=Depends(verify_token)):
    global monitoring_active
    return MonitoringStatusResponse(
        is_monitoring=monitoring_active,
        uptime_seconds=screenshot_monitor.get_uptime(),
    )

@app.post("/api/monitoring/pause")
async def pause_monitoring(user=Depends(verify_token)):
    global monitoring_active
    if not monitoring_active:
        return {"success": True}
        
    monitoring_active = False
    screenshot_monitor.pause()
    clipboard_monitor.pause()
    app_tracker.pause()
    browser_tracker.pause()
    keylogger.pause()
    screen_recorder.pause()
    sync_service.set_device_status("PAUSED")
    logger.info("Monitoring paused manually")
    
    # Inform remote server
    threading.Thread(
        target=_notify_server_sync, 
        args=("url_monitoring_settings", "monitoringActive", False), 
        daemon=True
    ).start()

    return {"success": True, "message": "Monitoring paused"}

@app.post("/api/monitoring/resume")
async def resume_monitoring(user=Depends(verify_token)):
    global monitoring_active
    if monitoring_active:
        return {"success": True}
        
    monitoring_active = True

    # Screenshot — resume if paused; start if stopped but config-enabled
    if screenshot_monitor.is_running:
        screenshot_monitor.resume()
        logger.info("Screenshot monitor resumed")
    elif config_manager.get("screenshot_enabled", True):
        screenshot_monitor.start()
        logger.info("Screenshot monitor started on resume (was stopped but enabled in config)")
    else:
        logger.info("Screenshot monitor not started on resume (disabled in config)")

    # Screen recorder — resume if paused; start if stopped but config-enabled
    if screen_recorder.is_running:
        screen_recorder.resume()
        logger.info("Screen recording resumed")
    elif config_manager.get("recording_enabled", False):
        screen_recorder.start()
        logger.info("Screen recording started on resume (was stopped but enabled in config)")
    else:
        logger.info("Screen recording not started on resume (disabled in config)")

    clipboard_monitor.resume()
    app_tracker.resume()
    browser_tracker.resume()
    keylogger.resume()
    sync_service.set_device_status("ACTIVE")
    logger.info("Monitoring resumed manually")
    
    # Inform remote server
    threading.Thread(
        target=_notify_server_sync, 
        args=("url_monitoring_settings", "monitoringActive", True), 
        daemon=True
    ).start()

    return {"success": True, "message": "Monitoring resumed"}


# ── Internal auto-pause/shutdown endpoints (no JWT — localhost-only, called by Electron) ──
@app.post("/api/internal/shutdown")
async def internal_shutdown(request: Request):
    """Localhost-only graceful shutdown. Electron calls this if JWT is expired."""
    if request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Internal endpoint only")
    logger.info("Graceful shutdown requested via /api/internal/shutdown")
    sync_service.set_device_status("SHUTDOWN")
    try:
        await shutdown_event()
    except Exception as exc:
        logger.error("Error during shutdown_event: %s", exc)

    _port_file = Path.home() / "Library" / "Application Support" / "EnterpriseMonitor" / "port.info"
    try:
        if _port_file.exists():
            _port_file.unlink()
            logger.info("port.info cleaned up during internal shutdown")
    except OSError:
        pass

    async def _delayed_exit():
        await asyncio.sleep(0.5)
        logger.info("Exiting process after internal shutdown")
        os._exit(0)
    asyncio.get_event_loop().create_task(_delayed_exit())
    return {"success": True, "message": "Shutting down"}


# ⚙️  IDLE THRESHOLD: The 10-minute idle timeout is controlled on the Electron side.
#     To change it, edit IDLE_PAUSE_THRESHOLD_SECS in electron-app/src/main/main.ts.
#     These endpoints have no timeout logic of their own — they just act on the command.
@app.post("/api/internal/monitoring/pause")
async def internal_pause_monitoring(request: Request):
    """
    Called by the Electron idle-tracker when the user has been inactive
    for IDLE_PAUSE_THRESHOLD_SECS seconds.  No JWT required — access is
    restricted to 127.0.0.1 by the host check below (uvicorn already binds
    exclusively to 127.0.0.1 so no external traffic can reach this).
    """
    if request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Internal endpoint — localhost only")
    logger.info("Auto-pause triggered by Electron idle tracker (no JWT)")
    sync_service.set_device_status("AUTO_PAUSED")
    return await pause_monitoring(user={"sub": "_idle_system"})


@app.post("/api/internal/monitoring/resume")
async def internal_resume_monitoring(request: Request):
    """
    Called by the Electron idle-tracker when the user returns (idle time
    drops below threshold).  No JWT required — localhost-only.
    """
    if request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Internal endpoint — localhost only")
    logger.info("Auto-resume triggered by Electron idle tracker (no JWT)")
    sync_service.set_device_status("ACTIVE")
    return await resume_monitoring(user={"sub": "_idle_system"})


# ── Device Status (internal, no JWT) ─────────────────────────────────────────
@app.post("/api/internal/device-status")
async def internal_set_device_status(request: Request):
    """Localhost-only endpoint for Electron to set device status (sleep/shutdown/etc)."""
    if request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Internal endpoint — localhost only")
    body = await request.json()
    status = body.get("status", "")
    sync_service.set_device_status(status)
    return {"success": True, "status": sync_service.get_device_status()}


@app.get("/api/device/status")
async def get_device_status(user=Depends(verify_token)):
    """Returns the current device operational status for the Electron renderer."""
    return {"status": sync_service.get_device_status()}


# ── Sync marker reset ────────────────────────────────────────────────────────
@app.post("/api/sync/reset-markers")
async def reset_sync_markers(user=Depends(verify_token)):
    """
    Resets all synced flags to 0 across all data tables.
    Used after a server-side DB reset to force full re-upload.
    """
    total = db_manager.reset_sync_markers()
    return {"success": True, "rows_reset": total}


@app.get("/api/data/screenshots", response_model=List[ScreenshotInfo])
async def get_screenshots_data(limit: int = 50, offset: int = 0, user=Depends(verify_token)):
    """Electron calls /api/data/screenshots — was missing on macOS."""
    try:
        screenshots = db_manager.get_screenshots(limit, offset)
        return [
            ScreenshotInfo(
                id=s["id"],
                timestamp=s["timestamp"],
                file_path=s["file_path"],
                active_window=s.get("active_window") or "",
                active_app=s.get("active_app") or "",
                synced=bool(s.get("synced", False)),
            )
            for s in screenshots
        ]
    except Exception as e:
        logger.error("Error getting screenshots: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get screenshots")

# Keep original /api/screenshots as alias so nothing else breaks
@app.get("/api/screenshots", response_model=List[ScreenshotInfo])
async def get_screenshots(limit: int = 50, offset: int = 0, user=Depends(verify_token)):
    return await get_screenshots_data(limit, offset, user)

@app.delete("/api/screenshots/{screenshot_id}")
async def delete_screenshot(screenshot_id: int, user=Depends(verify_token)):
    try:
        ok = db_manager.delete_screenshot(screenshot_id)
        return {"success": ok}
    except Exception as e:
        logger.error("Error deleting screenshot: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete screenshot")


# ── Videos ────────────────────────────────────────────────────────────────────
@app.get("/api/data/videos")
async def get_videos_data(limit: int = 50, user=Depends(verify_token)):
    """Electron calls /api/data/videos — was missing on macOS."""
    try:
        return db_manager.get_video_recordings(limit)
    except Exception as e:
        logger.error("Error getting videos: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get videos")

# Keep /api/videos as alias
@app.get("/api/videos")
async def get_videos(limit: int = 50, user=Depends(verify_token)):
    return await get_videos_data(limit, user)

@app.get("/api/monitoring/video/status")
async def get_video_monitoring_status(user=Depends(verify_token)):
    """Electron calls /api/monitoring/video/status — was missing on macOS."""
    return {
        "recording": config_manager.get("recording_enabled", False),
        "is_active": screen_recorder.is_running,
    }

# Keep /api/video/status as alias
@app.get(PATH_VIDEO_SETTINGS)
@app.get("/api/video/status")
async def get_video_status(user=Depends(verify_token)):
    return await get_video_monitoring_status(user)

@app.post("/api/monitoring/video/toggle")
async def toggle_video_monitoring(user=Depends(verify_token)):
    currently_enabled = config_manager.get("recording_enabled", False)
    new_state = not currently_enabled
    config_manager.set("recording_enabled", new_state)
    
    if new_state:
        # Only start the recorder if global monitoring is currently active.
        # If monitoring is paused, resume_monitoring will call start() on resume.
        if monitoring_active:
            screen_recorder.start()
        logger.info("Screen recording ENABLED by admin (Active: %s)", screen_recorder.is_running)
    else:
        screen_recorder.stop()
        logger.info("Screen recording DISABLED by admin")

    # Inform remote server of the change
    # Use _notify_server_sync so mark_local_update() is called and sync cooldown activates,
    # preventing the next sync cycle from overriding this local toggle.
    threading.Thread(
        target=_notify_server_sync,
        args=("url_video_settings", "recordingEnabled", new_state),
        daemon=True
    ).start()

    return {"success": True, "recording": new_state, "is_active": screen_recorder.is_running}

@app.get("/api/monitoring/screenshot/status")
async def get_screenshot_status(user=Depends(verify_token)):
    return {
        "recording": config_manager.get("screenshot_enabled", True),
        "is_active": screenshot_monitor.is_running,
    }

@app.post("/api/monitoring/screenshot/toggle")
async def toggle_screenshot_recording(user=Depends(verify_token)):
    currently_enabled = config_manager.get("screenshot_enabled", True)
    new_state = not currently_enabled
    config_manager.set("screenshot_enabled", new_state)

    if new_state:
        # Only start if global monitoring is currently active.
        # If monitoring is paused, resume_monitoring will call start() on resume.
        if monitoring_active:
            screenshot_monitor.start()
        logger.info("Screenshot capturing ENABLED by admin (Active: %s)", screenshot_monitor.is_running)
    else:
        screenshot_monitor.stop()
        logger.info("Screenshot capturing DISABLED by admin")

    # Inform remote server — use _notify_server_sync so mark_local_update() is called
    # and sync cooldown activates, preventing the next sync cycle from overriding this toggle.
    threading.Thread(
        target=_notify_server_sync,
        args=("url_screenshot_settings", "screenshotEnabled", new_state),
        daemon=True
    ).start()

    return {"success": True, "recording": new_state, "is_active": screenshot_monitor.is_running}

# Keep /api/video/toggle as alias
@app.post(PATH_VIDEO_SETTINGS)
@app.post("/api/video/toggle")
async def toggle_video(user=Depends(verify_token)):
    return await toggle_video_monitoring(user)


# ── Data endpoints ────────────────────────────────────────────────────────────
@app.get("/api/data/apps")
async def get_app_logs(limit: int = 50, offset: int = 0, user=Depends(verify_token)):
    try:
        return db_manager.get_app_activity_logs(limit, offset)
    except Exception as e:
        logger.error("Error getting app logs: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get app logs")

@app.get("/api/data/browser")
async def get_browser_logs(limit: int = 50, offset: int = 0, user=Depends(verify_token)):
    try:
        return db_manager.get_browser_activity(limit, offset)
    except Exception as e:
        logger.error("Error getting browser logs: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get browser logs")

@app.get("/api/data/keylogs")
async def get_key_logs(limit: int = 100, offset: int = 0, user=Depends(verify_token)):
    try:
        return db_manager.get_text_logs(limit, offset)
    except Exception as e:
        logger.error("Error getting key logs: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get key logs")

@app.get("/api/data/clipboard")
async def get_clipboard_logs(limit: int = 50, offset: int = 0, user=Depends(verify_token)):
    try:
        return db_manager.get_clipboard_logs(limit, offset)
    except Exception as e:
        logger.error("Error getting clipboard logs: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get clipboard logs")


# ── Statistics ────────────────────────────────────────────────────────────────
@app.get("/api/statistics", response_model=StatisticsResponse)
async def get_statistics(date: Optional[str] = None, user=Depends(verify_token)):
    """Fixed: now accepts optional `date` param, matching Windows backend."""
    try:
        stats = db_manager.get_statistics(date=date)
        active_seconds = stats.get("active_time", 0)
        return StatisticsResponse(
            total_screenshots=stats.get("screenshots", 0),
            active_hours_today=round(active_seconds / 3600.0, 2) if active_seconds else 0.0,
            apps_tracked=stats.get("app_sessions", 0),
            clipboard_events=stats.get("clipboard_events", 0),
        )
    except Exception as e:
        logger.error("Error getting statistics: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get statistics")


# ── Activity Stats & Timeline ─────────────────────────────────────────────────
@app.get("/api/stats/activity")
async def get_activity_stats(start: str, end: str, user=Depends(verify_token)):
    """Was missing on macOS. db_manager.get_activity_stats() already exists."""
    try:
        return db_manager.get_activity_stats(start, end)
    except Exception as e:
        logger.error("Error getting activity stats: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get activity stats")

@app.get("/api/stats/timeline")
async def get_timeline_data(date: str, user=Depends(verify_token)):
    """Was missing on macOS. db_manager.get_timeline_data() already exists."""
    try:
        return db_manager.get_timeline_data(date)
    except Exception as e:
        logger.error("Error getting timeline data: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get timeline data")


# ── Permissions status (macOS-only endpoint) ──────────────────────────────────
@app.get("/api/permissions")
async def get_permissions(user=Depends(verify_token)):
    """Returns current TCC permission state. macOS-only."""
    try:
        from monitoring.permissions import get_permission_state, check_automation_permission
        state = get_permission_state()
        return {
            "screen_recording": state.screen_recording,
            "accessibility": state.accessibility,
            "input_monitoring": state.input_monitoring,
            "automation": check_automation_permission(),
        }
    except Exception as e:
        logger.error("Error getting permission state: %s", e)
        return {"screen_recording": False, "accessibility": False, "input_monitoring": False, "automation": False}


@app.post("/api/permissions/request")
async def request_permissions(user=Depends(verify_token)):
    """Trigger native macOS TCC permission dialogs for first-run onboarding."""
    try:
        from monitoring.permissions import request_all_permissions
        results = request_all_permissions()
        return {"success": True, **results}
    except Exception as e:
        logger.error("Error requesting permissions: %s", e)
        return {"success": False, "error": str(e)}
