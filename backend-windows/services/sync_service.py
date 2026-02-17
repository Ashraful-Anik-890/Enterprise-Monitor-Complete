"""
sync_service.py
Service to synchronize data with a central server
"""

import threading
import time
import logging
import requests
import base64
from pathlib import Path

logger = logging.getLogger(__name__)

class SyncService:
    def __init__(self, db_manager, config_manager):
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.is_running = False
        self.thread = None
        self.batch_size = 10
    
    def start(self):
        """Start the sync service"""
        if self.is_running:
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.thread.start()
        logger.info("Sync service started")
    
    def stop(self):
        """Stop the sync service"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=2)
        logger.info("Sync service stopped")
    
    def _sync_loop(self):
        """Main sync loop"""
        logger.info("Sync loop started")
        
        while self.is_running:
            try:
                # Check config
                server_url = self.config_manager.get("server_url")
                if not server_url:
                    # No server configured, sleep and retry
                    time.sleep(60)
                    continue
                
                # Sync data
                self._sync_data(server_url)
                
                # Sleep
                interval = self.config_manager.get("sync_interval_seconds", 60)
                for _ in range(interval):
                    if not self.is_running:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")
                time.sleep(60)
    
    def _sync_data(self, server_url):
        """Sync unsynced data to server"""
        # Get pending data
        data = self.db_manager.get_unsynced_data(limit=self.batch_size)
        
        # Sync screenshots
        screenshots = data.get("screenshots", [])
        if screenshots:
            self._upload_screenshots(server_url, screenshots)
            
        # Sync app activity (batch upload)
        activities = data.get("app_activity", [])
        if activities:
            if self._post_batch(server_url, "activity", activities):
                ids = [item["id"] for item in activities]
                self.db_manager.mark_as_synced("app_activity", ids)
                
        # Sync clipboard events
        clipboard = data.get("clipboard_events", [])
        if clipboard:
            if self._post_batch(server_url, "clipboard", clipboard):
                ids = [item["id"] for item in clipboard]
                self.db_manager.mark_as_synced("clipboard_events", ids)
    
    def _upload_screenshots(self, server_url, screenshots):
        """Upload screenshots one by one (or batch if API supports it)"""
        device_id = self.config_manager.get("device_id")
        headers = {"Authorization": f"Bearer {self.config_manager.get('api_key')}"}
        
        for s in screenshots:
            try:
                file_path = Path(s["file_path"])
                if not file_path.exists():
                    # File missing, mark as synced (skipped) to avoid stuck loop
                    self.db_manager.mark_as_synced("screenshots", [s["id"]])
                    continue
                
                # Prepare payload
                # In real prod, might use multipart/form-data. 
                # Here we simulate JSON payload for simplicity or base64
                with open(file_path, "rb") as f:
                    img_data = base64.b64encode(f.read()).decode()
                
                payload = {
                    "device_id": device_id,
                    "timestamp": s["timestamp"],
                    "active_window": s["active_window"],
                    "active_app": s["active_app"],
                    "image_data": img_data
                }
                
                response = requests.post(f"{server_url}/api/v1/sync/screenshot", json=payload, headers=headers, timeout=30)
                
                if response.status_code in [200, 201]:
                    self.db_manager.mark_as_synced("screenshots", [s["id"]])
                else:
                    logger.warning(f"Failed to upload screenshot {s['id']}: {response.status_code}")
                    
            except Exception as e:
                logger.error(f"Error uploading screenshot {s['id']}: {e}")

    def _post_batch(self, server_url, endpoint_suffix, items):
        """Post a batch of items"""
        try:
            device_id = self.config_manager.get("device_id")
            headers = {"Authorization": f"Bearer {self.config_manager.get('api_key')}"}
            
            payload = {
                "device_id": device_id,
                "items": items
            }
            
            response = requests.post(f"{server_url}/api/v1/sync/{endpoint_suffix}", json=payload, headers=headers, timeout=10)
            
            if response.status_code in [200, 201]:
                return True
            else:
                logger.warning(f"Failed to sync {endpoint_suffix}: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error syncing {endpoint_suffix}: {e}")
            return False
