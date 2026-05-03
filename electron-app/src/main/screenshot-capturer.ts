/**
 * electron-app/src/main/screenshot-capturer.ts
 *
 * Wayland-compatible screenshot engine using Electron's desktopCapturer.
 * This runs entirely inside the Electron main process and works on:
 *   - Linux Wayland (GNOME, KDE, etc.)
 *   - Linux X11
 *   - macOS
 *   - Windows
 *
 * Flow:
 *  1. On an interval (matching backend config), capture a JPEG via desktopCapturer.
 *  2. Save the file to EM_DIR/screenshots/.
 *  3. POST the file metadata to the backend's internal API so it records it in the DB.
 *
 * The Python backend's ScreenshotMonitor is DISABLED when Electron capture is active
 * (controlled via /api/monitoring/status).
 */

import { desktopCapturer, NativeImage } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import { ApiClient } from './api-client';

export class ElectronScreenshotCapturer {
  private timer: ReturnType<typeof setInterval> | null = null;
  private screenshotDir: string;
  private apiClient: ApiClient;
  private token: () => string;
  private intervalMs: number;
  private isRunning = false;

  constructor(
    emDir: string,
    apiClient: ApiClient,
    token: () => string,
    intervalSeconds = 60,
  ) {
    this.screenshotDir = path.join(emDir, 'screenshots');
    this.apiClient = apiClient;
    this.token = token;
    this.intervalMs = intervalSeconds * 1000;

    fs.mkdirSync(this.screenshotDir, { recursive: true });
    console.log('[ElectronScreenshotCapturer] Initialized. dir:', this.screenshotDir);
  }

  start(): void {
    if (this.isRunning) return;
    this.isRunning = true;
    console.log('[ElectronScreenshotCapturer] Starting (interval:', this.intervalMs, 'ms)');
    // Capture immediately on start, then on schedule
    this._captureAndSave().catch(e => console.error('[ElectronScreenshotCapturer] First capture error:', e));
    this.timer = setInterval(() => {
      this._captureAndSave().catch(e => console.error('[ElectronScreenshotCapturer] Capture error:', e));
    }, this.intervalMs);
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.isRunning = false;
    console.log('[ElectronScreenshotCapturer] Stopped');
  }

  isActive(): boolean {
    return this.isRunning;
  }

  private async _captureAndSave(): Promise<void> {
    try {
      // Get all screen sources
      const sources = await desktopCapturer.getSources({
        types: ['screen'],
        thumbnailSize: { width: 1920, height: 1080 },
      });

      if (!sources || sources.length === 0) {
        console.warn('[ElectronScreenshotCapturer] No screen sources found');
        return;
      }

      // Use the primary screen (first source)
      const source = sources[0];
      const thumbnail: NativeImage = source.thumbnail;

      if (thumbnail.isEmpty()) {
        console.warn('[ElectronScreenshotCapturer] Thumbnail is empty (Wayland may need WebRTC flag)');
        return;
      }

      // Convert to JPEG buffer (quality 0-100)
      const jpegBuffer = thumbnail.toJPEG(60);

      const timestamp = new Date().toISOString().replace(/[:.]/g, '').replace('T', '_').slice(0, 15);
      const filename = `screenshot_${timestamp}.jpg`;
      const filepath = path.join(this.screenshotDir, filename);

      fs.writeFileSync(filepath, jpegBuffer);
      console.log(`[ElectronScreenshotCapturer] Saved: ${filename} (${Math.round(jpegBuffer.length / 1024)}KB)`);

      // Notify the Python backend to record this in the DB
      await this._notifyBackend(filepath);

    } catch (err: any) {
      console.error('[ElectronScreenshotCapturer] Capture failed:', err.message ?? err);
    }
  }

  private async _notifyBackend(filepath: string): Promise<void> {
    try {
      const tok = this.token();
      if (!tok) return;
      // Use the existing insert_screenshot endpoint
      await this.apiClient.post('/api/screenshots/record', {
        file_path: filepath,
        active_window: '',
        active_app: '',
      }, tok);
    } catch (err: any) {
      // Backend might not have this endpoint yet — log but don't fail
      console.warn('[ElectronScreenshotCapturer] Backend notify failed (will add endpoint):', err.message ?? err);
    }
  }
}
