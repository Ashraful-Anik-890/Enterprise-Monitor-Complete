"""
Clipboard Monitor
Monitors clipboard changes (for security/audit purposes)
"""

import threading
import getpass
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
        self._os_user: str = getpass.getuser()
    
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
        """Check for clipboard changes with retry logic to handle locked clipboard."""
        max_retries = 3
        retry_delay = 0.2
        
        for attempt in range(max_retries):
            try:
                # pyperclip.paste() internally calls OpenClipboard on Windows
                current_content = pyperclip.paste()
                
                # Check if clipboard changed
                if current_content and current_content != self.last_clipboard_content:
                    self.last_clipboard_content = current_content
                    
                    # Create preview (limit for DB storage)
                    preview = current_content[:100]
                    if len(current_content) > 100:
                        preview += "..."
                    
                    # Store in database
                    self.db_manager.insert_clipboard_event("text", preview, self._os_user)
                    logger.debug(f"Clipboard event recorded: {len(current_content)} chars")
                
                # Success, break the retry loop
                return
                
            except Exception as e:
                # WinError 0 is often just a transient "busy" signal on Windows
                if "OpenClipboard" in str(e) and attempt < max_retries - 1:
                    logger.debug(f"Clipboard locked (attempt {attempt + 1}), retrying...")
                    time.sleep(retry_delay)
                else:
                    # After all retries, or if it's a different error, log as warning
                    # Changed from ERROR to WARNING to reduce log noise for expected OS behavior
                    logger.warning(f"Failed to check clipboard after {attempt + 1} attempts: {e}")
                    break
    
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
