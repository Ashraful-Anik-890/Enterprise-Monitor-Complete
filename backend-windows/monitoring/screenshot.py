"""
Screenshot Monitor
Captures screenshots at regular intervals
"""

import threading
import time
import logging
from pathlib import Path
from datetime import datetime
import mss
from PIL import Image
import psutil

logger = logging.getLogger(__name__)

class ScreenshotMonitor:
    def __init__(self, db_manager, interval_seconds: int = 5):
        self.db_manager = db_manager
        self.interval_seconds = interval_seconds
        self.is_running = False
        self.is_paused = False
        self.thread = None
        self.start_time = None
        
        # Screenshot storage directory
        self.screenshot_dir = Path.home() / "AppData" / "Local" / "EnterpriseMonitor" / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
    
    def start(self):
        """Start screenshot monitoring"""
        if self.is_running:
            logger.warning("Screenshot monitor already running")
            return
        
        self.is_running = True
        self.is_paused = False
        self.start_time = datetime.utcnow()
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("Screenshot monitor started")
    
    def stop(self):
        """Stop screenshot monitoring"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Screenshot monitor stopped")
    
    def pause(self):
        """Pause screenshot monitoring"""
        self.is_paused = True
        logger.info("Screenshot monitor paused")
    
    def resume(self):
        """Resume screenshot monitoring"""
        self.is_paused = False
        logger.info("Screenshot monitor resumed")
    
    def get_uptime(self) -> int:
        """Get uptime in seconds"""
        if self.start_time:
            return int((datetime.utcnow() - self.start_time).total_seconds())
        return 0
    
    def _get_active_window_info(self):
        """Get active window and application info"""
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
            
            return window_title, app_name
        except Exception as e:
            logger.error(f"Failed to get active window info: {e}")
            return "Unknown", "Unknown"
    
    def _capture_screenshot(self):
        """Capture a screenshot"""
        try:
            # Get active window info
            window_title, app_name = self._get_active_window_info()
            
            # Capture screenshot
            with mss.mss() as sct:
                # Capture primary monitor
                monitor = sct.monitors[1]
                screenshot = sct.grab(monitor)
                
                # Convert to PIL Image
                img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
                
                # Generate filename
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}.jpg"
                filepath = self.screenshot_dir / filename
                
                # Save screenshot (compressed/resized to target 60-80KB)
                # First save to memory to check size
                import io
                img_byte_arr = io.BytesIO()
                quality = 85
                img.save(img_byte_arr, format='JPEG', quality=quality, optimize=True)
                size_kb = len(img_byte_arr.getvalue()) / 1024
                
                # If size is too large (>80KB), reduce quality or resize
                while size_kb > 80 and quality > 10:
                    quality -= 5
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG', quality=quality, optimize=True)
                    size_kb = len(img_byte_arr.getvalue()) / 1024
                
                # If still too large, resize
                if size_kb > 80:
                    width, height = img.size
                    ratio = 0.8
                    while size_kb > 80 and ratio > 0.1:
                        new_width = int(width * ratio)
                        new_height = int(height * ratio)
                        resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                        img_byte_arr = io.BytesIO()
                        resized_img.save(img_byte_arr, format='JPEG', quality=quality, optimize=True)
                        size_kb = len(img_byte_arr.getvalue()) / 1024
                        ratio -= 0.1
                
                # Save final image to disk
                with open(filepath, "wb") as f:
                    f.write(img_byte_arr.getvalue())
                
                # Store in database
                self.db_manager.insert_screenshot(
                    str(filepath),
                    window_title,
                    app_name
                )
                
                logger.debug(f"Screenshot captured: {filename}")
        except Exception as e:
            logger.error(f"Failed to capture screenshot: {e}")
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        logger.info("Screenshot monitoring loop started")
        
        while self.is_running:
            try:
                if not self.is_paused:
                    self._capture_screenshot()
                
                # Wait for next interval
                time.sleep(self.interval_seconds)
            except Exception as e:
                logger.error(f"Error in screenshot monitor loop: {e}")
                time.sleep(self.interval_seconds)
        
        logger.info("Screenshot monitoring loop ended")
