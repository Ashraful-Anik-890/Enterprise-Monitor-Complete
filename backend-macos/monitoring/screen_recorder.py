"""
screen_recorder.py — macOS version
Captures the primary display as chunked MP4 video files.

Design:
  - Uses mss (fastest pure-Python screen capture, cross-platform)
  - Uses cv2.VideoWriter with mp4v codec (works on macOS with OpenCV)
  - Captures at ~10 FPS, scales to 720p (1280x720) to save disk space
  - Rotates files every CHUNK_SECONDS (default 300 = 5 minutes)
  - On chunk close: inserts a record into video_recordings table via db_manager
  - start() / stop() are thread-safe; may be called multiple times

CHANGES from Windows version:
  - REMOVED `import win32api` (module-level — would crash on import on macOS)
  - _resolve_video_dir() uses ~/Library/Application Support/EnterpriseMonitor/videos
  - Added Screen Recording permission check in start()

Requires: pip install mss opencv-python numpy
"""

import threading
import logging
import time
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

CHUNK_SECONDS  = 300          # 5-minute rolling files
TARGET_FPS     = 10
TARGET_W       = 1280
TARGET_H       = 720
FOURCC         = "mp4v"
FILE_EXT       = ".mp4"


def _resolve_video_dir() -> Path:
    """
    Resolve the video storage directory at runtime.
    macOS: ~/Library/Application Support/EnterpriseMonitor/videos
    """
    return Path.home() / 'Library' / 'Application Support' / 'EnterpriseMonitor' / 'videos'


class ScreenRecorder:
    """
    Admin-controlled screen recorder.

    start() / stop() are safe to call from any thread.
    Recording state is deliberately NOT auto-started — caller (api_server)
    checks config_manager on startup and calls start() only if enabled.
    """

    def __init__(self, db_manager, config_manager):
        self.db_manager     = db_manager
        self.config_manager = config_manager

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_running  = False
        self._lock        = threading.Lock()

        self.video_dir = _resolve_video_dir()
        try:
            self.video_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Video directory ready: %s", self.video_dir)
        except PermissionError:
            logger.error(
                "PERMISSION DENIED creating video dir: %s  "
                "Ensure the process runs as the logged-in user.",
                self.video_dir,
            )
        except Exception as e:
            logger.error("Failed to create video directory %s: %s", self.video_dir, e)

    # ─── PUBLIC API ──────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self):
        with self._lock:
            if self._is_running:
                logger.warning("ScreenRecorder already running — ignoring start()")
                return

            # ── TCC permission guard ─────────────────────────────────────────
            try:
                from Quartz import CGPreflightScreenCaptureAccess
                if not CGPreflightScreenCaptureAccess():
                    logger.warning("ScreenRecorder: Screen Recording permission denied — skipping start.")
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
            logger.info(
                "ScreenRecorder started (mp4v @ %d fps, %d-second chunks)",
                TARGET_FPS, CHUNK_SECONDS,
            )

    def stop(self):
        with self._lock:
            if not self._is_running:
                return
            self._stop_event.set()
            self._is_running = False

        if self._thread:
            self._thread.join(timeout=10)
        logger.info("ScreenRecorder stopped")

    # ─── INTERNALS ───────────────────────────────────────────────────────────

    def _record_loop(self):
        """
        Main capture loop.
        Each outer iteration writes one CHUNK_SECONDS chunk.
        Each inner iteration captures one frame.
        """
        try:
            import mss
        except ImportError:
            logger.error("mss not installed — screen recording disabled. Run: pip install mss")
            self._is_running = False
            return

        try:
            import cv2
        except ImportError:
            logger.error("opencv-python not installed — screen recording disabled.")
            self._is_running = False
            return

        logger.info("ScreenRecorder loop started (video dir: %s)", self.video_dir)

        with mss.mss() as sct:
            monitor = sct.monitors[1]   # primary monitor
            native_w = monitor["width"]
            native_h = monitor["height"]

            while not self._stop_event.is_set():
                chunk_path = self._new_chunk_path()
                fourcc     = cv2.VideoWriter_fourcc(*FOURCC)
                writer     = cv2.VideoWriter(
                    str(chunk_path), fourcc, TARGET_FPS, (TARGET_W, TARGET_H)
                )

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
                        raw = sct.grab(monitor)
                        # mss gives BGRA; cv2 needs BGR
                        frame = np.array(raw)[:, :, :3]
                        if (native_w, native_h) != (TARGET_W, TARGET_H):
                            frame = cv2.resize(
                                frame, (TARGET_W, TARGET_H),
                                interpolation=cv2.INTER_LINEAR,
                            )
                        writer.write(frame)
                        frame_count += 1
                    except Exception as exc:
                        logger.warning("Frame capture error: %s", exc)

                    elapsed = time.monotonic() - frame_start
                    sleep_for = max(0.0, (1.0 / TARGET_FPS) - elapsed)
                    if sleep_for > 0:
                        self._stop_event.wait(sleep_for)

                writer.release()
                duration_seconds = int(time.monotonic() - chunk_start)
                logger.debug(
                    "Chunk saved: %s (%d frames, %ds)",
                    chunk_path.name, frame_count, duration_seconds,
                )

                if frame_count > 0 and chunk_path.exists():
                    try:
                        timestamp = datetime.utcnow().isoformat()
                        self.db_manager.insert_video_recording(
                            timestamp,
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
