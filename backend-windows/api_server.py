"""
FastAPI REST API Server
Handles authentication, statistics, and monitoring control
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

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="Enterprise Monitor API", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
auth_manager = AuthManager()
db_manager = DatabaseManager()
screenshot_monitor = ScreenshotMonitor(db_manager)
clipboard_monitor = ClipboardMonitor(db_manager)
app_tracker = AppTracker(db_manager)
cleanup_service = CleanupService(db_manager)
config_manager = ConfigManager()
sync_service = SyncService(db_manager, config_manager)

# Global monitoring state
monitoring_active = True

# Pydantic models
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


# Dependency for auth verification
async def verify_token(authorization: Optional[str] = Header(None)):
    """Verify JWT token from Authorization header"""
    if not authorization:
        raise HTTPException(status_code=401, detail="No authorization header")
    
    try:
        # Expected format: "Bearer <token>"
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization format")
        
        token = parts[1]
        payload = auth_manager.verify_token(token)
        return payload
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid token")

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "platform": "windows",
        "timestamp": datetime.utcnow().isoformat()
    }

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Enterprise Monitor API",
        "version": "1.0.0",
        "status": "running",
        "docs_url": "/docs"
    }

# Authentication endpoints
@app.post("/api/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Authenticate user and return JWT token"""
    try:
        is_valid = auth_manager.verify_credentials(request.username, request.password)
        
        if is_valid:
            token = auth_manager.create_token(request.username)
            return LoginResponse(success=True, token=token)
        else:
            return LoginResponse(success=False, error="Invalid credentials")
    except Exception as e:
        logger.error(f"Login error: {e}")
        return LoginResponse(success=False, error="Login failed")

@app.get("/api/auth/check")
async def check_auth(user=Depends(verify_token)):
    """Check if current token is valid"""
    return {"authenticated": True, "username": user.get("sub")}

@app.post("/api/auth/change-password")
async def change_password(request: ChangePasswordRequest, user=Depends(verify_token)):
    """Change user password"""
    if "sub" not in user:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    username = user["sub"]
    
    # Verify old password
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

# Statistics endpoints
@app.get("/api/statistics", response_model=StatisticsResponse)
async def get_statistics(user=Depends(verify_token)):
    """Get monitoring statistics"""
    try:
        stats = db_manager.get_statistics()
        return StatisticsResponse(
            total_screenshots=stats.get("total_screenshots", 0),
            active_hours_today=stats.get("active_hours_today", 0.0),
            apps_tracked=stats.get("apps_tracked", 0),
            clipboard_events=stats.get("clipboard_events", 0)
        )
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get statistics")

@app.get("/api/stats/activity")
async def get_activity_stats(
    start: str,
    end: str,
    user=Depends(verify_token)
):
    """Get aggregated activity stats"""
    try:
        return db_manager.get_activity_stats(start, end)
    except Exception as e:
        logger.error(f"Error getting activity stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get activity stats")

@app.get("/api/stats/timeline")
async def get_timeline_data(
    date: str,
    user=Depends(verify_token)
):
    """Get timeline data"""
    try:
        return db_manager.get_timeline_data(date)
    except Exception as e:
        logger.error(f"Error getting timeline data: {e}")
        raise HTTPException(status_code=500, detail="Failed to get timeline data")

# Screenshot endpoints
@app.get("/api/screenshots", response_model=List[ScreenshotInfo])
async def get_screenshots(
    limit: int = 20,
    offset: int = 0,
    user=Depends(verify_token)
):
    """Get list of recent screenshots"""
    try:
        screenshots = db_manager.get_screenshots(limit=limit, offset=offset)
        return [
            ScreenshotInfo(
                id=s["id"],
                timestamp=s["timestamp"],
                file_path=s["file_path"],
                active_window=s["active_window"],
                active_app=s["active_app"]
            )
            for s in screenshots
        ]
    except Exception as e:
        logger.error(f"Error getting screenshots: {e}")
        raise HTTPException(status_code=500, detail="Failed to get screenshots")

# New Data Endpoints
@app.get("/api/data/apps")
async def get_app_logs(
    limit: int = 50,
    offset: int = 0,
    user=Depends(verify_token)
):
    """Get app activity logs"""
    try:
        return db_manager.get_app_activity_logs(limit, offset)
    except Exception as e:
        logger.error(f"Error getting app logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to get app logs")

@app.get("/api/data/browser")
async def get_browser_logs(
    limit: int = 50,
    offset: int = 0,
    user=Depends(verify_token)
):
    """Get browser activity logs"""
    try:
        return db_manager.get_browser_activity_logs(limit, offset)
    except Exception as e:
        logger.error(f"Error getting browser logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to get browser logs")

@app.get("/api/data/clipboard")
async def get_clipboard_logs(
    limit: int = 50,
    offset: int = 0,
    user=Depends(verify_token)
):
    """Get clipboard logs"""
    try:
        return db_manager.get_clipboard_logs(limit, offset)
    except Exception as e:
        logger.error(f"Error getting clipboard logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to get clipboard logs")

# Monitoring control endpoints
@app.get("/api/monitoring/status", response_model=MonitoringStatusResponse)
async def get_monitoring_status(user=Depends(verify_token)):
    """Get current monitoring status"""
    global monitoring_active
    return MonitoringStatusResponse(
        is_monitoring=monitoring_active,
        uptime_seconds=screenshot_monitor.get_uptime()
    )

@app.post("/api/monitoring/pause")
async def pause_monitoring(user=Depends(verify_token)):
    """Pause monitoring"""
    global monitoring_active
    monitoring_active = False
    screenshot_monitor.pause()
    clipboard_monitor.pause()
    app_tracker.pause()
    logger.info("Monitoring paused by admin")
    return {"success": True, "message": "Monitoring paused"}

@app.post("/api/monitoring/resume")
async def resume_monitoring(user=Depends(verify_token)):
    """Resume monitoring"""
    global monitoring_active
    monitoring_active = True
    screenshot_monitor.resume()
    clipboard_monitor.resume()
    app_tracker.resume()
    logger.info("Monitoring resumed by admin")
    return {"success": True, "message": "Monitoring resumed"}

# Configuration endpoints
@app.get("/api/config")
async def get_config(user=Depends(verify_token)):
    """Get current configuration"""
    return config_manager.config

@app.post("/api/config")
async def update_config(config: ConfigRequest, user=Depends(verify_token)):
    """Update configuration"""
    if config.server_url is not None:
        config_manager.set("server_url", config.server_url)
    if config.api_key is not None:
        config_manager.set("api_key", config.api_key)
    if config.sync_interval_seconds is not None:
        config_manager.set("sync_interval_seconds", config.sync_interval_seconds)
    return {"success": True, "config": config_manager.config}

# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize monitoring on startup"""
    logger.info("Starting monitoring services...")
    screenshot_monitor.start()
    clipboard_monitor.start()
    app_tracker.start()
    cleanup_service.start()
    sync_service.start()
    logger.info("All monitoring services started")

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Stopping monitoring services...")
    screenshot_monitor.stop()
    clipboard_monitor.stop()
    app_tracker.stop()
    cleanup_service.stop()
    sync_service.stop()
    logger.info("All monitoring services stopped")
