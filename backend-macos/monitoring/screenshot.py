"""
Screenshot Monitor — macOS
Captures screenshots at regular intervals.

v5.2.6 — COMPRESSION REFACTOR (same as Windows version)
  Resize-first pipeline targeting 10-15 KB per screenshot.
  See backend-windows/monitoring/screenshot.py for full rationale.

macOS-specific:
  - Storage path: ~/Library/Application Support/EnterpriseMonitor/screenshots
  - TCC Screen Recording guard in start()
  - Active window info via osascript JXA
"""

import io
import json
import subprocess
import threading
import time
import logging
import getpass
from pathlib import Path
from datetime import datetime

import mss
from PIL import Image

logger = logging.getLogger(__name__)

# ── Compression constants ─────────────────────────────────────────────────────
TARGET_WIDTH    = 800
TARGET_SIZE_KB  = 15
QUALITY_INITIAL = 35
QUALITY_MIN     = 15
QUALITY_STEP    = 5


class ScreenshotMonitor:
    def __init__(self, db_manager, interval_seconds: int = 5):
        self.db_manager       = db_manager
        self.interval_seconds = interval_seconds
        self.is_running       = False
        self.is_paused        = False
        self.thread           = None
        self.start_time       = None

        self.screenshot_dir = (
            Path.home()
            / "Library"
            / "Application Support"
            / "EnterpriseMonitor"
            / "screenshots"
        )
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._os_user: str = getpass.getuser()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        if self.is_running:
            logger.warning("Screenshot monitor already running")
            return

        # TCC permission guard
        try:
            from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

            if not CGPreflightScreenCaptureAccess():
                CGRequestScreenCaptureAccess()
                try:
                    from Quartz import (
                        CGWindowListCreateImage, CGRectMake,
                        kCGWindowListOptionOnScreenOnly, kCGNullWindowID,
                        kCGWindowImageDefault,
                    )
                    CGWindowListCreateImage(
                        CGRectMake(0, 0, 1, 1),
                        kCGWindowListOptionOnScreenOnly,
                        kCGNullWindowID,
                        kCGWindowImageDefault,
                    )
                except Exception:
                    pass

                if not CGPreflightScreenCaptureAccess():
                    logger.warning("Screenshot: Screen Recording denied — skipping start.")
                    return
        except ImportError:
            logger.error("pyobjc-framework-Quartz not installed")
            return

        self.is_running  = True
        self.is_paused   = False
        self.start_time  = datetime.utcnow()
        self.thread      = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("Screenshot monitor started")

    def stop(self):
        self.is_running = False
        if self.thread is not None:
            self.thread.join(timeout=5)
            self.thread = None
        logger.info("Screenshot monitor stopped")

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def get_uptime(self) -> int:
        if self.start_time is not None:
            return int((datetime.utcnow() - self.start_time).total_seconds())
        return 0

    # ── Window info ───────────────────────────────────────────────────────────

    def _get_active_window_info(self):
        try:
            result = subprocess.run(
                [
                    "osascript", "-l", "JavaScript", "-e",
                    'var p=Application("System Events").applicationProcesses'
                    '.whose({frontmost:true})[0];'
                    'JSON.stringify({app:p.name(),'
                    'title:p.windows.length>0?p.windows[0].name():""})',
                ],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                d = json.loads(result.stdout.strip())
                return d.get("title", "Unknown"), d.get("app", "Unknown")
        except Exception as e:
            logger.error("Failed to get active window info: %s", e)
        return "Unknown", "Unknown"

    # ── Compress ──────────────────────────────────────────────────────────────

    def _compress_image(self, img: Image.Image) -> bytes:
        orig_w, orig_h = img.size
        scale = TARGET_WIDTH / orig_w if orig_w > TARGET_WIDTH else 1.0
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)

        working = img.resize((new_w, new_h), Image.Resampling.LANCZOS) if scale < 1.0 else img

        quality = QUALITY_INITIAL
        buf     = io.BytesIO()

        while True:
            buf.seek(0)
            buf.truncate(0)
            working.save(buf, format="JPEG", quality=quality, optimize=True)
            size_kb = len(buf.getvalue()) / 1024

            if size_kb <= TARGET_SIZE_KB:
                break
            if quality > QUALITY_MIN:
                quality = max(QUALITY_MIN, quality - QUALITY_STEP)
                continue

            # Last resort: scale to 70%
            w, h    = working.size
            working = working.resize((int(w * 0.7), int(h * 0.7)), Image.Resampling.LANCZOS)
            buf.seek(0)
            buf.truncate(0)
            working.save(buf, format="JPEG", quality=QUALITY_MIN, optimize=True)
            size_kb = len(buf.getvalue()) / 1024
            if size_kb > TARGET_SIZE_KB:
                logger.debug("Screenshot: complex content — %.1f KB after max compression", size_kb)
            break

        logger.debug(
            "Screenshot compressed: %dx%d Q%d → %.1f KB",
            working.width, working.height, quality, len(buf.getvalue()) / 1024,
        )
        return buf.getvalue()

    def _capture_screenshot(self):
        try:
            window_title, app_name = self._get_active_window_info()

            with mss.mss() as sct:
                monitor    = sct.monitors[1]
                screenshot = sct.grab(monitor)
                img        = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

            jpeg_bytes = self._compress_image(img)

            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename  = f"screenshot_{timestamp}.jpg"
            filepath  = self.screenshot_dir / filename

            with open(filepath, "wb") as f:
                f.write(jpeg_bytes)

            self.db_manager.insert_screenshot(
                str(filepath),
                window_title,
                app_name,
                self._os_user,
            )
            logger.debug("Screenshot saved: %s (%.1f KB)", filename, len(jpeg_bytes) / 1024)

        except Exception as e:
            logger.error("Failed to capture screenshot: %s", e)

    # ── Loop ──────────────────────────────────────────────────────────────────

    def _monitor_loop(self):
        logger.info("Screenshot monitoring loop started")
        while self.is_running:
            try:
                if not self.is_paused:
                    self._capture_screenshot()
                time.sleep(self.interval_seconds)
            except Exception as e:
                logger.error("Error in screenshot monitor loop: %s", e)
                time.sleep(self.interval_seconds)
        logger.info("Screenshot monitoring loop ended")
