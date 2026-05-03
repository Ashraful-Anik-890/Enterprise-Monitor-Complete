"""
Screenshot Monitor — Windows
Captures screenshots at regular intervals.

v5.2.6 — COMPRESSION REFACTOR
  Old logic: capture → compress at Q85 → reduce quality loop → resize as fallback
  Problem:   Iterating quality on a full-resolution image (1920x1080) is slow and
             still produces 60-80KB files. Even at Q10, 1080p JPEG is 30-50KB.

  New logic: resize-first pipeline
    1. Capture full resolution
    2. Immediately resize to TARGET_WIDTH=800px (aspect-ratio preserved, LANCZOS)
    3. JPEG encode at QUALITY_INITIAL=35, optimize=True
    4. If > TARGET_SIZE_KB (15): reduce quality by 5 per step down to QUALITY_MIN=15
    5. If still > 15KB (extreme: full-screen video/complex graphics): resize to 0.7x

  Result: ~10-15KB for typical desktop content, ~15-20KB for graphics-heavy screens.
  Max compression iterations: 4 quality steps + 1 scale = 5 total (negligible CPU cost).
  Width 800px keeps text legible in the dashboard screenshot grid.
"""

import sys
import io
import threading
import time
import logging
import getpass
import os
from pathlib import Path
from datetime import datetime

import mss
from PIL import Image
import psutil

from utils.session_utils import is_user_session_active

logger = logging.getLogger(__name__)

# ── Compression constants ─────────────────────────────────────────────────────
TARGET_WIDTH    = 800    # px — resize target before compression
TARGET_SIZE_KB  = 15     # KB — hard ceiling
QUALITY_INITIAL = 35     # JPEG quality for first attempt
QUALITY_MIN     = 15     # never go below this (severe blocking artefacts)
QUALITY_STEP    = 5      # reduce by this per iteration if over target


class ScreenshotMonitor:
    def __init__(self, db_manager, interval_seconds: int = 5):
        self.db_manager       = db_manager
        self.interval_seconds = interval_seconds
        self.is_running       = False
        self.is_paused        = False
        self.thread           = None
        self.start_time       = None

        _local_appdata = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
        if os.name != "nt":
            _local_appdata = os.path.join(os.path.expanduser("~"), ".local", "share")

        self.screenshot_dir = Path(_local_appdata) / "EnterpriseMonitor" / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._os_user: str = getpass.getuser()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        if self.is_running:
            logger.warning("Screenshot monitor already running")
            return
        self.is_running  = True
        self.is_paused   = False
        self.start_time  = datetime.utcnow()
        self.thread      = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("Screenshot monitor started")

    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None
        logger.info("Screenshot monitor stopped")

    def pause(self):
        self.is_paused = True
        logger.info("Screenshot monitor paused")

    def resume(self):
        self.is_paused = False
        logger.info("Screenshot monitor resumed")

    def get_uptime(self) -> int:
        if self.start_time:
            return int((datetime.utcnow() - self.start_time).total_seconds())
        return 0

    # ── Window info ───────────────────────────────────────────────────────────

    def _get_active_window_info(self):
        """Get active window title and app name (cross-platform)."""
        if sys.platform == "win32":
            try:
                import win32gui
                import win32process
                hwnd = win32gui.GetForegroundWindow()
                window_title = win32gui.GetWindowText(hwnd)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    app_name = psutil.Process(pid).name()
                except Exception:
                    app_name = "Unknown"
                return window_title, app_name
            except Exception as e:
                logger.error("Failed to get active window info (Windows): %s", e)
                return "Unknown", "Unknown"
        else:
            # Linux implementation using xprop
            try:
                import subprocess
                out = subprocess.check_output(["xprop", "-root", "_NET_ACTIVE_WINDOW"], stderr=subprocess.DEVNULL).decode()
                window_id = out.split("#")[-1].strip()
                if not window_id or window_id == "0x0":
                    return "Unknown", "Unknown"

                window_title = "Unknown"
                try:
                    name_out = subprocess.check_output(["xprop", "-id", window_id, "WM_NAME"], stderr=subprocess.DEVNULL).decode()
                    if ' = "' in name_out:
                        window_title = name_out.split(' = "')[1].rstrip('"\n')
                except:
                    pass

                app_name = "Unknown"
                try:
                    pid_out = subprocess.check_output(["xprop", "-id", window_id, "_NET_WM_PID"], stderr=subprocess.DEVNULL).decode()
                    if " = " in pid_out:
                        pid = int(pid_out.split(" = ")[1].strip())
                        app_name = psutil.Process(pid).name()
                except:
                    try:
                        class_out = subprocess.check_output(["xprop", "-id", window_id, "WM_CLASS"], stderr=subprocess.DEVNULL).decode()
                        if ' = "' in class_out:
                            app_name = class_out.split(' = "')[1].split('"')[0]
                    except:
                        pass
                return window_title, app_name
            except:
                return "Unknown", "Unknown"

    # ── Capture + compress ────────────────────────────────────────────────────

    def _compress_image(self, img: Image.Image) -> bytes:
        """
        Resize-first pipeline:
          1. Downscale to TARGET_WIDTH while preserving aspect ratio (LANCZOS).
          2. JPEG at QUALITY_INITIAL.
          3. If over TARGET_SIZE_KB, reduce quality in QUALITY_STEP increments.
          4. If still over (extreme content), scale to 70% and retry once.

        Returns compressed JPEG bytes.
        """
        orig_w, orig_h = img.size
        scale = TARGET_WIDTH / orig_w if orig_w > TARGET_WIDTH else 1.0
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)

        working = img.resize((new_w, new_h), Image.Resampling.LANCZOS) if scale < 1.0 else img

        quality = QUALITY_INITIAL
        buf = io.BytesIO()

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

            # Quality floor hit — last resort: scale down by 30%
            w, h = working.size
            working = working.resize((int(w * 0.7), int(h * 0.7)), Image.Resampling.LANCZOS)
            buf.seek(0)
            buf.truncate(0)
            working.save(buf, format="JPEG", quality=QUALITY_MIN, optimize=True)
            size_kb = len(buf.getvalue()) / 1024
            if size_kb > TARGET_SIZE_KB:
                logger.debug(
                    "Screenshot: complex content — %.1f KB after max compression", size_kb
                )
            break

        logger.debug(
            "Screenshot compressed: %dx%d Q%d → %.1f KB",
            working.width, working.height, quality, len(buf.getvalue()) / 1024,
        )
        return buf.getvalue()

    def _capture_screenshot(self):
        if not is_user_session_active():
            logger.debug("Session inactive — skipping screenshot")
            return

        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            logger.warning("Wayland detected — screenshots may be black. Switch to Xorg for full support.")

        try:
            window_title, app_name = self._get_active_window_info()

            with mss.mss() as sct:
                # with_cursor is read-only on some platforms/versions of mss
                try:
                    sct.with_cursor = False
                except (AttributeError, TypeError):
                    pass
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

    # ── Monitor loop ──────────────────────────────────────────────────────────

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
