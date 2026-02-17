"""
config_manager.py
Handles persistent configuration (server URL, API keys, etc.)
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self):
        self.config_dir = Path.home() / "AppData" / "Local" / "EnterpriseMonitor"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.json"
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load config from disk or create default"""
        if not self.config_path.exists():
            return self._create_default_config()
        
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                
                # Ensure device_id exists (migration for existing configs)
                if "device_id" not in config:
                    config["device_id"] = str(uuid.uuid4())
                    self.save_config(config)
                    
                return config
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return self._create_default_config()

    def _create_default_config(self) -> Dict[str, Any]:
        """Create and save default configuration"""
        default_config = {
            "server_url": "",  # Empty by default, user must configure
            "api_key": "",
            "device_id": str(uuid.uuid4()),
            "sync_interval_seconds": 60,
            "screenshot_interval": 60
        }
        self.save_config(default_config)
        return default_config

    def save_config(self, config: Dict[str, Any]):
        """Save configuration to disk"""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=4)
            self.config = config
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value"""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set a config value and save"""
        self.config[key] = value
        self.save_config(self.config)
