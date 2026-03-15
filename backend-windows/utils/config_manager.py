"""
config_manager.py — Windows
Handles persistent configuration (server URL, API keys, ERP endpoints, etc.)

KEY FIX — url.py → config.json seeding
═══════════════════════════════════════
Previously url.py (compile-time constants) and config.json (runtime state) were
completely disconnected.  sync_service._get_url() only reads config.json, so when
config.json had empty URL strings (every fresh install), sync was permanently skipped
even when BASE_URL was set in url.py.

Rule implemented here:
  DYNAMIC_API_ENABLED = False  (static / enterprise deployment)
    → BASE_URL and all PATH_* from url.py are the source of truth.
    → On every startup, config.json URL fields are OVERWRITTEN with
      BASE_URL + PATH_* regardless of what is stored on disk.
    → The admin controls the server by changing url.py before compiling.

  DYNAMIC_API_ENABLED = True  (dynamic / user-configurable)
    → config.json is the source of truth.
    → If config.json URLs are all blank (first run), seed them from
      BASE_URL + PATH_* in url.py as a one-time convenience default.
    → Once the user saves their own URLs via the GUI, those values win.
    → BASE_URL in url.py has no effect on subsequent startups.
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ConfigManager:
    def __init__(self):
        self.config_dir = Path.home() / "AppData" / "Local" / "EnterpriseMonitor"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.json"
        self.config = self._load_config()
        self._seed_urls_from_url_py()  # ← THE FIX: bridge url.py → config.json

    # ─── LOAD ────────────────────────────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        """Load config from disk or create default."""
        if not self.config_path.exists():
            return self._create_default_config()
        try:
            with open(self.config_path, "r") as f:
                config = json.load(f)
            # Migration: ensure every key that matters exists
            changed = False
            if "device_id" not in config:
                config["device_id"] = str(uuid.uuid4())
                changed = True
            for key in (
                "base_url", "url_app_activity", "url_browser", "url_clipboard",
                "url_keystrokes", "url_screenshots", "url_videos",
                "url_monitoring_settings", "url_screenshot_settings", "url_video_settings",
                "api_key", "screenshot_enabled", "recording_enabled",
            ):
                if key not in config:
                    config[key] = self._defaults()[key]
                    changed = True
            if changed:
                self._save_to_disk(config)
            return config
        except Exception as e:
            logger.error("Failed to load config: %s — rebuilding defaults", e)
            return self._create_default_config()

    def _defaults(self) -> Dict[str, Any]:
        return {
            "server_url":              "",
            "api_key":                 "",
            "base_url":                "",
            "device_id":               str(uuid.uuid4()),
            "sync_interval_seconds":   300,
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
        """Create and persist a fresh default config."""
        config = self._defaults()
        self._save_to_disk(config)
        return config

    # ─── URL SEEDING (the fix) ───────────────────────────────────────────────

    def _seed_urls_from_url_py(self) -> None:
        """
        Bridge compile-time url.py constants into the runtime config.json.

        Static mode  (DYNAMIC_API_ENABLED = False):
          Overwrite all URL keys on every startup — url.py is always authoritative.

        Dynamic mode (DYNAMIC_API_ENABLED = True):
          One-time seed only: if ALL url_* keys are still blank (fresh install /
          config.json was just created), populate them from BASE_URL + PATH_*.
          Once the user saves their own values, those values persist untouched.
        """
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
            logger.warning("url.py not found — skipping URL seeding")
            return

        base = BASE_URL.strip().rstrip("/")
        if not base:
            # Nothing to seed — admin has not set BASE_URL
            logger.debug("url.py BASE_URL is empty — URL seeding skipped")
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
            # Static mode: enforce url.py values every startup
            changed = any(self.config.get(k) != v for k, v in url_map.items())
            if changed:
                self.config.update(url_map)
                self._save_to_disk(self.config)
                logger.info(
                    "Static mode: URL config seeded from url.py BASE_URL=%s", base
                )
            else:
                logger.debug("Static mode: URL config already matches url.py — no update needed")
        else:
            # Dynamic mode: one-time seed only when all URL fields are blank
            all_blank = all(
                not self.config.get(k, "").strip()
                for k in url_map
                if k != "base_url"
            )
            if all_blank:
                self.config.update(url_map)
                self._save_to_disk(self.config)
                logger.info(
                    "Dynamic mode: first-run URL seed from url.py BASE_URL=%s", base
                )
            else:
                logger.debug(
                    "Dynamic mode: user-configured URLs found in config.json — url.py seed skipped"
                )

    # ─── PERSISTENCE ─────────────────────────────────────────────────────────

    def _save_to_disk(self, config: Dict[str, Any]) -> None:
        try:
            with open(self.config_path, "w") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            logger.error("Failed to save config: %s", e)

    def save_config(self, config: Dict[str, Any]) -> None:
        self.config = config
        self._save_to_disk(config)

    # ─── PUBLIC API ──────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.config[key] = value
        self._save_to_disk(self.config)
