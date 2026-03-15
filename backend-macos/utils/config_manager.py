"""
config_manager.py — macOS
Handles persistent configuration (server URL, API keys, ERP endpoints, etc.)

Storage: ~/Library/Application Support/EnterpriseMonitor/config.json
         (replaces Windows %LOCALAPPDATA%/EnterpriseMonitor/config.json)

All seeding logic is identical to the Windows version.
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

BASE_DIR = Path.home() / "Library" / "Application Support" / "EnterpriseMonitor"


class ConfigManager:
    def __init__(self):
        self.config_dir = BASE_DIR
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.json"
        self.config = self._load_config()
        self._seed_urls_from_url_py()

    def _defaults(self) -> Dict[str, Any]:
        return {
            "server_url":              "",
            "api_key":                 "",
            "base_url":                "",
            "device_id":               str(uuid.uuid4()),
            "sync_interval_seconds":   60,
            "screenshot_interval":     60,
            "screenshot_enabled":      True,
            "recording_enabled":       False,
            "url_app_activity":        "",
            "url_browser":             "",
            "url_clipboard":           "",
            "url_keystrokes":          "",
            "url_screenshots":         "",
            "url_videos":              "",
            "url_monitoring_settings": "",
            "url_screenshot_settings": "",
            "url_video_settings":      "",
        }

    def _create_default_config(self) -> Dict[str, Any]:
        config = self._defaults()
        config["device_id"] = str(uuid.uuid4())
        self._save_to_disk(config)
        return config

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return self._create_default_config()
        try:
            with open(self.config_path, "r") as f:
                config = json.load(f)
            changed = False
            for key, default_val in self._defaults().items():
                if key not in config:
                    config[key] = default_val
                    changed = True
            if changed:
                self._save_to_disk(config)
            return config
        except Exception as e:
            logger.error("Failed to load config (corrupt?): %s — rebuilding defaults", e)
            return self._create_default_config()

    def _seed_urls_from_url_py(self) -> None:
        try:
            from url import (
                DYNAMIC_API_ENABLED,
                BASE_URL,
                PATH_APP_ACTIVITY,
                PATH_BROWSER,
                PATH_CLIPBOARD,
                PATH_KEYSTROKES,
                PATH_SCREENSHOTS,
                PATH_VIDEOS,
                PATH_VIDEO_SETTINGS,
                PATH_SCREENSHOT_SETTINGS,
                PATH_MONITORING_SETTINGS,
            )
        except ImportError:
            logger.warning("url.py not found — skipping URL seeding. Sync will not work.")
            return

        base = BASE_URL.strip().rstrip("/")
        if not base:
            logger.warning(
                "url.py BASE_URL is empty — URL seeding skipped. "
                "Set BASE_URL in url.py and restart."
            )
            return

        url_map = {
            "base_url":                base,
            "url_app_activity":        f"{base}{PATH_APP_ACTIVITY}",
            "url_browser":             f"{base}{PATH_BROWSER}",
            "url_clipboard":           f"{base}{PATH_CLIPBOARD}",
            "url_keystrokes":          f"{base}{PATH_KEYSTROKES}",
            "url_screenshots":         f"{base}{PATH_SCREENSHOTS}",
            "url_videos":              f"{base}{PATH_VIDEOS}",
            "url_video_settings":      f"{base}{PATH_VIDEO_SETTINGS}",
            "url_screenshot_settings": f"{base}{PATH_SCREENSHOT_SETTINGS}",
            "url_monitoring_settings": f"{base}{PATH_MONITORING_SETTINGS}",
        }

        if not DYNAMIC_API_ENABLED:
            changed = any(self.config.get(k) != v for k, v in url_map.items())
            if changed:
                self.config.update(url_map)
                self._save_to_disk(self.config)
                logger.info("Static mode: URL config seeded from url.py BASE_URL=%s", base)
            else:
                logger.debug("Static mode: URL config already matches url.py — no update needed")
        else:
            all_blank = all(
                not self.config.get(k, "").strip()
                for k in url_map if k != "base_url"
            )
            if all_blank:
                self.config.update(url_map)
                self._save_to_disk(self.config)
                logger.info("Dynamic mode: first-run URL seed from url.py BASE_URL=%s", base)
            else:
                logger.debug("Dynamic mode: user-configured URLs found — url.py seed skipped")

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
