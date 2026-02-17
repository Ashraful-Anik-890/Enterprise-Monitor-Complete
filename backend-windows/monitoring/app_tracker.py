"""
App Tracker
Tracks active applications and windows
"""

import threading
import time
import logging
from datetime import datetime
import psutil

logger = logging.getLogger(__name__)

class AppTracker:
    def __init__(self, db_manager, check_interval: int = 5):
        self.db_manager = db_manager
        self.check_interval = check_interval
        self.is_running = False
        self.is_paused = False
        self.thread = None
        self.current_app = None
        self.current_window = None
        self.app_start_time = None
    
    def start(self):
        """Start app tracking"""
        if self.is_running:
            logger.warning("App tracker already running")
            return
        
        self.is_running = True
        self.is_paused = False
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("App tracker started")
    
    def stop(self):
        """Stop app tracking"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("App tracker stopped")
    
    def pause(self):
        """Pause app tracking"""
        self.is_paused = True
        logger.info("App tracker paused")
    
    def resume(self):
        """Resume app tracking"""
        self.is_paused = False
        logger.info("App tracker resumed")
    
    def _get_active_app_info(self):
        """Get active application and window"""
        try:
            import win32gui
            import win32process
            
            # Get foreground window
            hwnd = win32gui.GetForegroundWindow()
            window_title = win32gui.GetWindowText(hwnd)
            
            # Get process name
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                process = psutil.Process(pid)
                app_name = process.name()
            except:
                app_name = "Unknown"
            
            return app_name, window_title
        except Exception as e:
            logger.error(f"Failed to get active app info: {e}")
            return None, None
    
    def _track_app_usage(self):
        """Track current app usage"""
        try:
            app_name, window_title = self._get_active_app_info()
            
            if not app_name:
                return
            
            # Check if app changed
            if app_name != self.current_app or window_title != self.current_window:
                # Save previous app duration
                if self.current_app and self.app_start_time:
                    duration = int((datetime.utcnow() - self.app_start_time).total_seconds())
                    if duration > 0:
                        self.db_manager.insert_app_activity(
                            self.current_app,
                            self.current_window or "",
                            duration
                        )
                
                # Update current app
                self.current_app = app_name
                self.current_window = window_title
                self.app_start_time = datetime.utcnow()
                logger.debug(f"App switched to: {app_name}")
        except Exception as e:
            logger.error(f"Failed to track app usage: {e}")
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        logger.info("App tracking loop started")
        
        while self.is_running:
            try:
                if not self.is_paused:
                    self._track_app_usage()
                
                # Wait for next check
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in app tracker loop: {e}")
                time.sleep(self.check_interval)
        
        logger.info("App tracking loop ended")
