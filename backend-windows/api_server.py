"""
FastAPI REST API Server

CHANGES:
- Bug 1: login() now calls auth_manager.verify_credentials() — the actual method name.
- Bug 2: verify_token() dependency wraps auth_manager.verify_token() safely.
- IDENTITY: GET /api/config/identity — returns machine_id, os_user, device_alias, user_alias.
- IDENTITY: POST /api/config/identity — updates device_alias and/or user_alias.

FIX (v2): Restored @app.on_event("startup") and @app.on_event("shutdown") lifecycle
           handlers that were accidentally omitted in the previous delivery. Without
           these, no monitoring services ever started after uvicorn loaded.
           Also restored GET/POST /api/config endpoints that were dropped.
"""

import socket
import getpass
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import logging
from datetime import datetime

from auth.auth_manager import AuthManager
from database.db_manager import DatabaseManager
from monitoring.screenshot import ScreenshotMonitor
from monitoring.clipboard import ClipboardMonitor
from monitoring.app_tracker import AppTracker
from monitoring.data_cleaner import CleanupService
from services.sync_service import SyncService
from utils.config_manager import ConfigManager
from monitoring.browser_tracker import BrowserTracker
from monitoring.keylogger import Keylogger
from monitoring.screen_recorder import ScreenRecorder

logger = logging.getLogger(__name__)

app = FastAPI(title="Enterprise Monitor API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

auth_manager       = AuthManager()
db_manager         = DatabaseManager()
screenshot_monitor = ScreenshotMonitor(db_manager)
clipboard_monitor  = ClipboardMonitor(db_manager)
app_tracker        = AppTracker(db_manager)
browser_tracker    = BrowserTracker(db_manager)
keylogger          = Keylogger(db_manager)
cleanup_service    = CleanupService(db_manager)
config_manager     = ConfigManager()
sync_service       = SyncService(db_manager, config_manager)
screen_recorder    = ScreenRecorder(db_manager, config_manager)

monitoring_active = True


# ─── PYDANTIC MODELS ─────────────────────────────────────────────────────────
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

class ConfigRequest(BaseModel):
    # Global settings
    api_key:               Optional[str] = None
    sync_interval_seconds: Optional[int] = None

    # Per-type ERP endpoint URLs (all optional — blank = that type is skipped)
    url_app_activity: Optional[str] = None
    url_browser:      Optional[str] = None
    url_clipboard:    Optional[str] = None
    url_keystrokes:   Optional[str] = None
    url_screenshots:  Optional[str] = None
    url_videos:       Optional[str] = None

    # Legacy — kept for backward compatibility with old installs
    server_url: Optional[str] = None

class IdentityResponse(BaseModel):
    machine_id:   str
    os_user:      str
    device_alias: str
    user_alias:   str

class IdentityUpdateRequest(BaseModel):
    device_alias: Optional[str] = None
    user_alias:   Optional[str] = None

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

# ─── AUTH DEPENDENCY ─────────────────────────────────────────────────────────
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
        logger.error(f"Unexpected error in verify_token: {e}")
        raise HTTPException(status_code=401, detail="Token validation error")

    if payload is None:
        raise HTTPException(status_code=401, detail="Token is invalid or has expired")

    return payload

async def update_credentials(request, user=Depends(None)):
    """
    ENDPOINT: POST /api/auth/update-credentials
    Protected: Bearer token required.

    Paste this function body verbatim. Replace the async def signature with:
        @app.post("/api/auth/update-credentials")
        async def update_credentials(request: UpdateCredentialsRequest, user=Depends(verify_token)):
    """
    if "sub" not in user:
        raise HTTPException(status_code=401, detail="Invalid token")

    current_username = user["sub"]

    # Update username + password
    success, error = auth_manager.update_credentials(
        old_username=current_username,
        new_username=request.new_username,
        new_password=request.new_password,
    )
    if not success:
        return {"success": False, "error": error}

    # Save security Q&A under the NEW username
    try:
        auth_manager.save_security_qa(
            username=request.new_username,
            q1=request.security_q1,
            a1=request.security_a1,
            q2=request.security_q2,
            a2=request.security_a2,
        )
    except Exception as e:
        logger.error("Credentials changed but QA save failed: %s", e)
        # Credentials already changed — don't roll back, just warn
        return {
            "success": True,
            "force_logout": True,
            "warning": "Credentials updated but security questions could not be saved.",
        }

    return {"success": True, "force_logout": True}

async def toggle_video_recording(user=None):
    """
    ENDPOINT: POST /api/monitoring/video/toggle
    Protected: Bearer token required.

    Paste this function body verbatim. Replace the async def signature with:
        @app.post("/api/monitoring/video/toggle")
        async def toggle_video_recording(user=Depends(verify_token)):
    """
    currently_enabled = config_manager.get("recording_enabled", False)
    new_state         = not currently_enabled
    config_manager.set("recording_enabled", new_state)

    if new_state:
        screen_recorder.start()
        logger.info("Screen recording ENABLED by admin")
    else:
        screen_recorder.stop()
        logger.info("Screen recording DISABLED by admin")

    return {"success": True, "recording": new_state}

async def get_video_status(user=None):
    """
    ENDPOINT: GET /api/monitoring/video/status
    Protected: Bearer token required.

    Paste this function body verbatim. Replace the async def signature with:
        @app.get("/api/monitoring/video/status")
        async def get_video_status(user=Depends(verify_token)):
    """
    return {
        "recording": config_manager.get("recording_enabled", False),
        "is_active": screen_recorder.is_running,
    }

async def get_videos(limit: int = 50, user=None):
    """
    ENDPOINT: GET /api/data/videos
    Protected: Bearer token required.

    Paste this function body verbatim. Replace the async def signature with:
        @app.get("/api/data/videos")
        async def get_videos(limit: int = 50, user=Depends(verify_token)):
    """
    try:
        recordings = db_manager.get_video_recordings(limit=limit)
        return recordings
    except Exception as e:
        logger.error("Failed to get video recordings: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve recordings")


# ─── LIFECYCLE  ──────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    logger.info("Starting monitoring services...")
    screenshot_monitor.start()
    clipboard_monitor.start()
    app_tracker.start()
    browser_tracker.start()
    keylogger.start()
    if config_manager.get("recording_enabled", False):
        screen_recorder.start()
        logger.info("Screen recording auto-started (was enabled in config)")
    cleanup_service.start()
    sync_service.start()
    logger.info("All monitoring services started")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Stopping monitoring services...")
    screenshot_monitor.stop()
    clipboard_monitor.stop()
    app_tracker.stop()
    browser_tracker.stop()
    keylogger.stop()
    cleanup_service.stop()
    sync_service.stop()
    screen_recorder.stop()
    logger.info("All monitoring services stopped")


# ─── HEALTH ──────────────────────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    return {
        "status":    "healthy",
        "platform":  "windows",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/")
async def root():
    return {
        "name":     "Enterprise Monitor API",
        "version":  "1.0.0",
        "status":   "running",
        "docs_url": "/docs"
    }


# ─── AUTH ENDPOINTS ──────────────────────────────────────────────────────────
@app.post("/api/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    try:
        is_valid = auth_manager.verify_credentials(request.username, request.password)
        if is_valid:
            token = auth_manager.create_token(request.username)
            return LoginResponse(success=True, token=token)
        return LoginResponse(success=False, error="Invalid credentials")
    except Exception as e:
        logger.error(f"Login error: {e}")
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
        logger.error(f"Password change error: {e}")
        return {"success": False, "error": "Failed to change password"}


# ─── IDENTITY CONFIG ─────────────────────────────────────────────────────────
@app.get("/api/config/identity", response_model=IdentityResponse)
async def get_identity(user=Depends(verify_token)):
    """
    Returns raw machine identity plus any custom aliases.
    Falls back to hostname / os_user when no alias is configured.
    """
    try:
        config = db_manager.get_identity_config()
        return IdentityResponse(
            machine_id=config["machine_id"],
            os_user=config["os_user"],
            device_alias=config["device_alias"],
            user_alias=config["user_alias"],
        )
    except Exception as e:
        logger.error(f"Error getting identity config: {e}")
        raise HTTPException(status_code=500, detail="Failed to get identity config")

@app.post("/api/config/identity")
async def update_identity(request: IdentityUpdateRequest, user=Depends(verify_token)):
    """Updates device_alias and/or user_alias. Null fields are left unchanged."""
    if request.device_alias is None and request.user_alias is None:
        return {"success": False, "error": "No fields to update"}
    try:
        ok = db_manager.update_identity_config(
            device_alias=request.device_alias,
            user_alias=request.user_alias,
        )
        if ok:
            return {"success": True, "message": "Identity updated"}
        return {"success": False, "error": "Update failed"}
    except Exception as e:
        logger.error(f"Error updating identity config: {e}")
        raise HTTPException(status_code=500, detail="Failed to update identity config")

@app.get("/api/config/timezone")
async def get_timezone(user=Depends(verify_token)):
    """Return the currently configured display timezone (IANA string)."""
    return {"timezone": config_manager.get("timezone", "UTC")}


@app.post("/api/config/timezone")
async def set_timezone(request: TimezoneRequest, user=Depends(verify_token)):
    """Persist the display timezone to config.json."""
    # On Windows, zoneinfo requires 'pip install tzdata'.
    # We attempt validation but fall back gracefully if the DB is missing,
    # rather than rejecting every valid IANA string with HTTP 400.
    try:
        import zoneinfo
        try:
            zoneinfo.ZoneInfo(request.timezone)
        except (KeyError, Exception) as tz_err:
            # ZoneInfoNotFoundError on Windows without tzdata — treat as invalid
            raise HTTPException(status_code=400, detail=f"Unknown timezone: {request.timezone}")
    except HTTPException:
        raise
    except ImportError:
        # zoneinfo not available (Python < 3.9) — skip validation
        pass
    
    config_manager.set("timezone", request.timezone)
    logger.info("Display timezone set to: %s", request.timezone)
    return {"success": True, "timezone": request.timezone}

# ─── STATISTICS ──────────────────────────────────────────────────────────────
@app.get("/api/statistics", response_model=StatisticsResponse)
async def get_statistics(date: Optional[str] = None, user=Depends(verify_token)):
    try:
        stats = db_manager.get_statistics(date=date)
        return StatisticsResponse(
            total_screenshots=stats.get("screenshots_today", 0),
            active_hours_today=stats.get("active_hours_today", 0.0),
            apps_tracked=stats.get("apps_tracked", 0),
            clipboard_events=stats.get("clipboard_events", 0),
        )
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get statistics")

@app.get("/api/stats/activity")
async def get_activity_stats(start: str, end: str, user=Depends(verify_token)):
    try:
        return db_manager.get_activity_stats(start, end)
    except Exception as e:
        logger.error(f"Error getting activity stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get activity stats")

@app.get("/api/stats/timeline")
async def get_timeline_data(date: str, user=Depends(verify_token)):
    try:
        return db_manager.get_timeline_data(date)
    except Exception as e:
        logger.error(f"Error getting timeline data: {e}")
        raise HTTPException(status_code=500, detail="Failed to get timeline data")


# ─── SCREENSHOTS ─────────────────────────────────────────────────────────────
@app.get("/api/screenshots", response_model=List[ScreenshotInfo])
async def get_screenshots(limit: int = 20, offset: int = 0, user=Depends(verify_token)):
    try:
        screenshots = db_manager.get_screenshots(limit=limit, offset=offset)
        return [
            ScreenshotInfo(
                id=s["id"],
                timestamp=s["timestamp"],
                file_path=s["file_path"],
                active_window=s.get("active_window") or "",
                active_app=s.get("active_app") or ""
            )
            for s in screenshots
        ]
    except Exception as e:
        logger.error(f"Error getting screenshots: {e}")
        raise HTTPException(status_code=500, detail="Failed to get screenshots")


# ─── DATA ENDPOINTS ──────────────────────────────────────────────────────────
@app.get("/api/data/apps")
async def get_app_logs(limit: int = 50, offset: int = 0, user=Depends(verify_token)):
    try:
        return db_manager.get_app_activity_logs(limit, offset)
    except Exception as e:
        logger.error(f"Error getting app logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to get app logs")

@app.get("/api/data/browser")
async def get_browser_logs(limit: int = 50, offset: int = 0, user=Depends(verify_token)):
    try:
        return db_manager.get_browser_activity_logs(limit, offset)
    except Exception as e:
        logger.error(f"Error getting browser logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to get browser logs")

@app.get("/api/data/keylogs")
async def get_key_logs(limit: int = 100, offset: int = 0, user=Depends(verify_token)):
    try:
        return db_manager.get_text_logs(limit, offset)
    except Exception as e:
        logger.error(f"Error getting key logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to get key logs")

@app.get("/api/data/clipboard")
async def get_clipboard_logs(limit: int = 50, offset: int = 0, user=Depends(verify_token)):
    try:
        return db_manager.get_clipboard_logs(limit, offset)
    except Exception as e:
        logger.error(f"Error getting clipboard logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to get clipboard logs")


# ─── MONITORING CONTROL ──────────────────────────────────────────────────────
@app.get("/api/monitoring/status", response_model=MonitoringStatusResponse)
async def get_monitoring_status(user=Depends(verify_token)):
    global monitoring_active
    return MonitoringStatusResponse(
        is_monitoring=monitoring_active,
        uptime_seconds=screenshot_monitor.get_uptime()
    )

@app.post("/api/monitoring/pause")
async def pause_monitoring(user=Depends(verify_token)):
    global monitoring_active
    monitoring_active = False
    screenshot_monitor.pause()
    clipboard_monitor.pause()
    app_tracker.pause()
    browser_tracker.pause()
    keylogger.pause()
    logger.info("Monitoring paused")
    return {"success": True, "message": "Monitoring paused"}

@app.post("/api/monitoring/resume")
async def resume_monitoring(user=Depends(verify_token)):
    global monitoring_active
    monitoring_active = True
    screenshot_monitor.resume()
    clipboard_monitor.resume()
    app_tracker.resume()
    browser_tracker.resume()
    keylogger.resume()
    logger.info("Monitoring resumed")
    return {"success": True, "message": "Monitoring resumed"}


# ─── CONFIG ──────────────────────────────────────────────────────────────────
@app.get("/api/config")
async def get_config(user=Depends(verify_token)):
    return {
        "api_key":               config_manager.get("api_key", ""),
        "sync_interval_seconds": config_manager.get("sync_interval_seconds", 300),
        "url_app_activity":      config_manager.get("url_app_activity", ""),
        "url_browser":           config_manager.get("url_browser", ""),
        "url_clipboard":         config_manager.get("url_clipboard", ""),
        "url_keystrokes":        config_manager.get("url_keystrokes", ""),
        "url_screenshots":       config_manager.get("url_screenshots", ""),
        "url_videos":            config_manager.get("url_videos", ""),
        # legacy
        "server_url":            config_manager.get("server_url", ""),
    }

@app.post("/api/config")
async def update_config(config: ConfigRequest, user=Depends(verify_token)):
    _fields = [
        ("api_key",               config.api_key),
        ("sync_interval_seconds", config.sync_interval_seconds),
        ("url_app_activity",      config.url_app_activity),
        ("url_browser",           config.url_browser),
        ("url_clipboard",         config.url_clipboard),
        ("url_keystrokes",        config.url_keystrokes),
        ("url_screenshots",       config.url_screenshots),
        ("url_videos",            config.url_videos),
        ("server_url",            config.server_url),   # legacy
    ]
    for key, value in _fields:
        if value is not None:
            config_manager.set(key, value)
    return {"success": True}


# ─── SYNC ────────────────────────────────────────────────────────────────────
@app.post("/api/sync/trigger")
async def trigger_sync(user=Depends(verify_token)):
    try:
        result = sync_service.trigger_sync_now()
        return result
    except Exception as e:
        logger.error(f"Error triggering sync: {e}")
        raise HTTPException(status_code=500, detail="Failed to trigger sync")

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


@app.post("/api/monitoring/video/toggle")
async def toggle_video_recording(user=Depends(verify_token)):
    currently_enabled = config_manager.get("recording_enabled", False)
    new_state = not currently_enabled
    config_manager.set("recording_enabled", new_state)
    if new_state:
        screen_recorder.start()
        logger.info("Screen recording ENABLED by admin")
    else:
        screen_recorder.stop()
        logger.info("Screen recording DISABLED by admin")
    return {"success": True, "recording": new_state}


@app.get("/api/monitoring/video/status")
async def get_video_status(user=Depends(verify_token)):
    return {
        "recording": config_manager.get("recording_enabled", False),
        "is_active": screen_recorder.is_running,
    }


@app.get("/api/data/videos")
async def get_videos(limit: int = 50, user=Depends(verify_token)):
    try:
        recordings = db_manager.get_video_recordings(limit=limit)
        return recordings
    except Exception as e:
        logger.error("Failed to get video recordings: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve recordings")