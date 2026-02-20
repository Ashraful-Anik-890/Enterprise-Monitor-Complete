"""
screen_recorder.py
Captures the primary display as chunked MP4 video files.

Design:
  - Uses mss (fastest pure-Python screen capture, no DXGI dependency)
  - Uses cv2.VideoWriter with XVID codec (bundled in all OpenCV wheels,
    PyInstaller-safe, plays in VLC/Chrome/Edge even with .mp4 extension)
  - Captures at ~10 FPS, scales to 720p (1280x720) to save disk space
  - Rotates files every CHUNK_SECONDS (default 300 = 5 minutes)
  - On chunk close: inserts a record into video_recordings table via db_manager
  - start() / stop() are thread-safe; may be called multiple times

Directory: C:/ProgramData/EnterpriseMonitor/videos
  (created on first start if it does not exist)

Requires: pip install mss opencv-python numpy
"""

import threading
import logging
import time
import os
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

CHUNK_SECONDS  = 300          # 5-minute rolling files
TARGET_FPS     = 10
TARGET_W       = 1280
TARGET_H       = 720
FOURCC         = "mp4v"      #
FILE_EXT       = ".mp4"
VIDEO_DIR      = Path("C:/ProgramData/EnterpriseMonitor/videos")


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

        try:
            VIDEO_DIR.mkdir(parents=True, exist_ok=True)
            logger.info("Video directory ready: %s", VIDEO_DIR)
        except PermissionError:
            logger.error(
                "PERMISSION DENIED creating video dir: %s — "
                "run main.py as Administrator (or as SYSTEM service). "
                "Screen recording will not work until resolved.", VIDEO_DIR
            )
        except Exception as e:
            logger.error("Failed to create video directory %s: %s", VIDEO_DIR, e)

    # ─── PUBLIC API ──────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self):
        with self._lock:
            if self._is_running:
                logger.warning("ScreenRecorder already running — ignoring start()")
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._record_loop, daemon=True, name="ScreenRecorder"
            )
            self._is_running = True
            self._thread.start()
            logger.info("ScreenRecorder started (XVID @ %d fps, %d-second chunks)", TARGET_FPS, CHUNK_SECONDS)

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
        Each iteration of the outer while writes one CHUNK_SECONDS chunk.
        Each iteration of the inner while captures one frame.
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

        while not self._stop_event.is_set():
            chunk_start  = datetime.utcnow()
            filepath     = self._build_filepath(chunk_start)
            writer       = None
            frames_written = 0

            try:
                with mss.mss() as sct:
                    monitor = sct.monitors[1]   # primary monitor (index 0 = all screens)
                    fourcc  = cv2.VideoWriter_fourcc(*FOURCC)
                    writer  = cv2.VideoWriter(
                        str(filepath), fourcc, TARGET_FPS, (TARGET_W, TARGET_H)
                    )

                    if not writer.isOpened():
                        logger.error("VideoWriter failed to open: %s", filepath)
                        break

                    chunk_deadline = time.monotonic() + CHUNK_SECONDS
                    frame_interval = 1.0 / TARGET_FPS

                    while not self._stop_event.is_set() and time.monotonic() < chunk_deadline:
                        t0 = time.monotonic()

                        try:
                            img  = sct.grab(monitor)                           # BGRA numpy-compatible
                            arr  = np.frombuffer(img.raw, dtype=np.uint8)
                            arr  = arr.reshape((img.height, img.width, 4))
                            bgr  = arr[:, :, :3]                               # drop alpha
                            frame = cv2.resize(bgr, (TARGET_W, TARGET_H),
                                               interpolation=cv2.INTER_LINEAR)
                            writer.write(frame)
                            frames_written += 1
                        except Exception as frame_err:
                            logger.warning("Frame capture error: %s", frame_err)

                        elapsed = time.monotonic() - t0
                        sleep_t = max(0.0, frame_interval - elapsed)
                        time.sleep(sleep_t)

            except Exception as exc:
                logger.error("ScreenRecorder chunk error: %s", exc, exc_info=True)
            finally:
                if writer:
                    writer.release()

            # ── persist completed chunk ──────────────────────────────────────
            if frames_written > 0 and filepath.exists():
                duration_secs = max(1, round(frames_written / TARGET_FPS))
                self._save_recording_to_db(
                    filepath=str(filepath),
                    timestamp=chunk_start.isoformat(),
                    duration_seconds=duration_secs,
                )
            else:
                # Empty file from a failed chunk — remove it
                try:
                    filepath.unlink(missing_ok=True)
                except Exception:
                    pass

        self._is_running = False

    # ─── HELPERS ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_filepath(dt: datetime) -> Path:
        """Build a timestamped filename for a recording chunk."""
        filename = dt.strftime("rec_%Y%m%d_%H%M%S") + FILE_EXT
        return VIDEO_DIR / filename

    def _save_recording_to_db(self, filepath: str, timestamp: str, duration_seconds: int):
        """Persist finished chunk metadata into video_recordings table."""
        try:
            self.db_manager.save_video_recording(
                timestamp=timestamp,
                file_path=filepath,
                duration_seconds=duration_seconds,
            )
            logger.info("Saved recording: %s (%ds)", filepath, duration_seconds)
        except Exception as e:
            logger.error("Failed to save recording to DB: %s", e)
