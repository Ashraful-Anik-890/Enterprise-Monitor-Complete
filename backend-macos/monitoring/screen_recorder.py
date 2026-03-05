"""
screen_recorder.py — macOS version
Captures the primary display as chunked MP4 video files.

CHANGES from Windows version:
  - REMOVED import win32api (crashes on macOS)
  - _resolve_video_dir() uses ~/Library/Application Support/EnterpriseMonitor/videos
  - Added Screen Recording permission check in start()
  - FOURCC = "mp4v" (works on macOS with OpenCV)

FIX (Python 3.9 compatibility):
  threading.Thread | None → Optional[threading.Thread]  (PEP 604 requires Python 3.10+)
"""

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

CHUNK_SECONDS = 300
TARGET_FPS    = 10
TARGET_W      = 1280
TARGET_H      = 720
FOURCC        = "mp4v"
FILE_EXT      = ".mp4"


def _resolve_video_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "EnterpriseMonitor" / "videos"


class ScreenRecorder:
    """
    Admin-controlled screen recorder.
    start() / stop() are safe to call from any thread.
    Not auto-started — api_server checks config on startup and calls start() if enabled.
    """

    def __init__(self, db_manager, config_manager):
        self.db_manager     = db_manager
        self.config_manager = config_manager

        self._thread: Optional[threading.Thread] = None  # FIX: was threading.Thread | None
        self._stop_event = threading.Event()
        self._is_running  = False
        self._lock        = threading.Lock()

        self.video_dir = _resolve_video_dir()
        try:
            self.video_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Video directory ready: %s", self.video_dir)
        except PermissionError:
            logger.error("PERMISSION DENIED creating video dir: %s", self.video_dir)
        except Exception as e:
            logger.error("Failed to create video directory %s: %s", self.video_dir, e)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> None:
        with self._lock:
            if self._is_running:
                logger.warning("ScreenRecorder already running — ignoring start()")
                return

            # TCC permission guard — PyInstaller child must explicitly request access
            try:
                from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

                if not CGPreflightScreenCaptureAccess():
                    # Attempt to request access — triggers system prompt on first call
                    CGRequestScreenCaptureAccess()

                    # Fallback: 1×1 pixel capture forces TCC to notice this specific
                    # binary (critical on macOS 14+ for unsigned PyInstaller binaries)
                    try:
                        from Quartz import (
                            CGWindowListCreateImage,
                            CGRectMake,
                            kCGWindowListOptionOnScreenOnly,
                            kCGNullWindowID,
                            kCGWindowImageDefault,
                        )
                        _img = CGWindowListCreateImage(
                            CGRectMake(0, 0, 1, 1),
                            kCGWindowListOptionOnScreenOnly,
                            kCGNullWindowID,
                            kCGWindowImageDefault,
                        )
                        logger.info("ScreenRecorder: 1×1 pixel capture fallback executed (TCC registration)")
                    except Exception as fallback_err:
                        logger.warning("ScreenRecorder: 1×1 pixel capture fallback failed: %s", fallback_err)

                    # Re-check after request + fallback
                    if not CGPreflightScreenCaptureAccess():
                        logger.warning(
                            "ScreenRecorder: Screen Recording permission denied — skipping start. "
                            "Grant in System Settings → Privacy & Security → Screen Recording."
                        )
                        return
            except ImportError:
                logger.error("pyobjc-framework-Quartz not installed — cannot check Screen Recording")
                return

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._record_loop, daemon=True, name="ScreenRecorder"
            )
            self._is_running = True
            self._thread.start()
            logger.info("ScreenRecorder started (mp4v @ %d fps, %d-second chunks)", TARGET_FPS, CHUNK_SECONDS)

    def stop(self) -> None:
        with self._lock:
            if not self._is_running:
                return
            self._stop_event.set()
            self._is_running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("ScreenRecorder stopped")

    def _record_loop(self) -> None:
        try:
            import mss
        except ImportError:
            logger.error("mss not installed — screen recording disabled")
            self._is_running = False
            return
        try:
            import cv2
        except ImportError:
            logger.error("opencv-python not installed — screen recording disabled")
            self._is_running = False
            return

        logger.info("ScreenRecorder loop started (video dir: %s)", self.video_dir)

        with mss.mss() as sct:
            monitor  = sct.monitors[1]
            native_w = monitor["width"]
            native_h = monitor["height"]

            while not self._stop_event.is_set():
                chunk_path = self._new_chunk_path()
                fourcc     = cv2.VideoWriter_fourcc(*FOURCC)
                writer     = cv2.VideoWriter(str(chunk_path), fourcc, TARGET_FPS, (TARGET_W, TARGET_H))

                if not writer.isOpened():
                    logger.error("cv2.VideoWriter failed to open: %s", chunk_path)
                    self._stop_event.wait(5)
                    continue

                chunk_start = time.monotonic()
                frame_count = 0

                while (
                    not self._stop_event.is_set()
                    and (time.monotonic() - chunk_start) < CHUNK_SECONDS
                ):
                    frame_start = time.monotonic()
                    try:
                        raw   = sct.grab(monitor)
                        frame = np.array(raw)[:, :, :3]  # BGRA → BGR
                        if (native_w, native_h) != (TARGET_W, TARGET_H):
                            frame = cv2.resize(frame, (TARGET_W, TARGET_H), interpolation=cv2.INTER_LINEAR)
                        writer.write(frame)
                        frame_count += 1
                    except Exception as exc:
                        logger.warning("Frame capture error: %s", exc)

                    elapsed   = time.monotonic() - frame_start
                    sleep_for = max(0.0, (1.0 / TARGET_FPS) - elapsed)
                    if sleep_for > 0:
                        self._stop_event.wait(sleep_for)

                writer.release()
                duration_seconds = int(time.monotonic() - chunk_start)
                logger.debug("Chunk saved: %s (%d frames, %ds)", chunk_path.name, frame_count, duration_seconds)

                if frame_count > 0 and chunk_path.exists():
                    try:
                        self.db_manager.insert_video_recording(
                            datetime.utcnow().isoformat(),
                            str(chunk_path),
                            duration_seconds,
                        )
                    except Exception as e:
                        logger.error("DB insert for video chunk failed: %s", e)
                elif chunk_path.exists():
                    chunk_path.unlink(missing_ok=True)

        logger.info("ScreenRecorder loop ended")

    def _new_chunk_path(self) -> Path:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return self.video_dir / f"recording_{ts}{FILE_EXT}"