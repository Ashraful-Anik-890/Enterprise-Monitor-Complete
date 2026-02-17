"""
data_cleaner.py
Background service to automatically clean up old data
"""

import threading
import time
import logging

logger = logging.getLogger(__name__)

class CleanupService:
    def __init__(self, db_manager, interval_hours: int = 24, retention_days: int = 7):
        """
        Initialize the cleanup service
        :param db_manager: DatabaseManager instance
        :param interval_hours: How often to run cleanup (default 24h)
        :param retention_days: How many days of data to keep (default 7)
        """
        self.db_manager = db_manager
        self.interval_seconds = interval_hours * 3600
        self.retention_days = retention_days
        self.is_running = False
        self.thread = None
    
    def start(self):
        """Start the cleanup service"""
        if self.is_running:
            logger.warning("Cleanup service already running")
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.thread.start()
        logger.info(f"Cleanup service started (Retention: {self.retention_days} days)")
    
    def stop(self):
        """Stop the cleanup service"""
        self.is_running = False
        if self.thread:
            # We don't wait for the full sleep to finish, just join with timeout
            # The daemon thread will be killed when main process exits anyway
            self.thread.join(timeout=1)
        logger.info("Cleanup service stopped")
    
    def _cleanup_loop(self):
        """Main cleanup loop"""
        logger.info("Cleanup loop started")
        
        # Run cleanup immediately on startup
        self._run_cleanup()
        
        while self.is_running:
            try:
                # Sleep for interval (checking is_running every second)
                for _ in range(self.interval_seconds):
                    if not self.is_running:
                        break
                    time.sleep(1)
                
                if self.is_running:
                    self._run_cleanup()
                    
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                time.sleep(300) # Retry in 5 mins on error
        
        logger.info("Cleanup loop ended")

    def _run_cleanup(self):
        """Execute the cleanup logic"""
        try:
            logger.info("Running scheduled data cleanup...")
            self.db_manager.cleanup_old_data(days=self.retention_days)
        except Exception as e:
            logger.error(f"Failed to run data cleanup: {e}")
