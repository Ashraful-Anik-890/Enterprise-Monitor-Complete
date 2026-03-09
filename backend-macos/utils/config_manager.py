"""
config_manager.py — macOS version
Handles persistent configuration (server URL, API keys, ERP endpoints, etc.)

CHANGE from Windows version:
  BASE_DIR: LOCALAPPDATA/EnterpriseMonitor → ~/Library/Application Support/EnterpriseMonitor
  Everything else is identical.
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# macOS standard path for application data
BASE_DIR = Path.home() / "Library" / "Application Support" / "EnterpriseMonitor"


class ConfigManager:
    def __init__(self):
        self.config_dir = BASE_DIR
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.json"
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return self._create_default_config()
        try:
            with open(self.config_path, "r") as f:
                config = json.load(f)
            if "device_id" not in config:
                config["device_id"] = str(uuid.uuid4())
                self._save_to_disk(config)
            return config
        except Exception as e:
            logger.error("Failed to load config: %s", e)
            return self._create_default_config()

    def _create_default_config(self) -> Dict[str, Any]:
        default = {
            "server_url": "",
            "api_key": "",
            "base_url": "",          # persists the Base URL shortcut input
            "device_id": str(uuid.uuid4()),
            "sync_interval_seconds": 300,
            "screenshot_interval": 60,
            "recording_enabled": False,
            "url_app_activity": "",
            "url_browser": "",
            "url_clipboard": "",
            "url_keystrokes": "",
            "url_screenshots": "",
            "url_videos": "",
        }
        self._save_to_disk(default)
        return default

    def _save_to_disk(self, config: Dict[str, Any]) -> None:
        try:
            with open(self.config_path, "w") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            logger.error("Failed to save config: %s", e)

    def save_config(self, config: Dict[str, Any]) -> None:
        self.config = config
        self._save_to_disk(config)

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.config[key] = value
        self._save_to_disk(self.config)
