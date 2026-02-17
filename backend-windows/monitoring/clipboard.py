"""
Clipboard Monitor
Monitors clipboard changes (for security/audit purposes)
"""

import threading
import time
import logging
from datetime import datetime
import pyperclip

logger = logging.getLogger(__name__)

class ClipboardMonitor:
    def __init__(self, db_manager, check_interval: int = 2):
        self.db_manager = db_manager
        self.check_interval = check_interval
        self.is_running = False
        self.is_paused = False
        self.thread = None
        self.last_clipboard_content = ""
    
    def start(self):
        """Start clipboard monitoring"""
        if self.is_running:
            logger.warning("Clipboard monitor already running")
            return
        
        self.is_running = True
        self.is_paused = False
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("Clipboard monitor started")
    
    def stop(self):
        """Stop clipboard monitoring"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Clipboard monitor stopped")
    
    def pause(self):
        """Pause clipboard monitoring"""
        self.is_paused = True
        logger.info("Clipboard monitor paused")
    
    def resume(self):
        """Resume clipboard monitoring"""
        self.is_paused = False
        logger.info("Clipboard monitor resumed")
    
    def _check_clipboard(self):
        """Check for clipboard changes"""
        try:
            current_content = pyperclip.paste()
            
            # Check if clipboard changed
            if current_content and current_content != self.last_clipboard_content:
                self.last_clipboard_content = current_content
                
                # Determine content type
                content_type = "text"
                
                # Create preview (limit to 100 characters)
                preview = current_content[:100]
                if len(current_content) > 100:
                    preview += "..."
                
                # Store in database
                self.db_manager.insert_clipboard_event(content_type, preview)
                logger.debug(f"Clipboard event recorded: {len(current_content)} chars")
        except Exception as e:
            logger.error(f"Failed to check clipboard: {e}")
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        logger.info("Clipboard monitoring loop started")
        
        while self.is_running:
            try:
                if not self.is_paused:
                    self._check_clipboard()
                
                # Wait for next check
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in clipboard monitor loop: {e}")
                time.sleep(self.check_interval)
        
        logger.info("Clipboard monitoring loop ended")
