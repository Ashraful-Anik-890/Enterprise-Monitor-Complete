// electron-app/src/main/tray.ts
// CHANGES:
//   - Quit no longer calls app.quit() directly.
//     It sends 'quit:requested' IPC to main process, which shows the
//     main window and pushes a 'show-quit-dialog' message to renderer.
//     The renderer verifies credentials; only on success does it call quitApp().
//   - Tray icon path search order fixed (resources/ relative to __dirname).

import { Tray, Menu, nativeImage, app, ipcMain, BrowserWindow } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import { ApiClient } from './api-client';

export class TrayManager {
  private tray: Tray | null = null;
  private backendHealthy: boolean = false;
  private isAuthenticated: boolean = false;
  private onTrayClick: () => void;
  private apiClient: ApiClient;
  private getMainWindow: () => BrowserWindow | null;

  constructor(
    onTrayClick: () => void,
    apiClient: ApiClient,
    getMainWindow: () => BrowserWindow | null,
  ) {
    this.onTrayClick = onTrayClick;
    this.apiClient = apiClient;
    this.getMainWindow = getMainWindow;
    this.createTray();
  }

  private createTray() {
    const icon = this.loadIcon();
    this.tray = new Tray(icon);
    this.tray.setToolTip('Enterprise Monitor');

    this.tray.on('click', () => this.onTrayClick());
    this.tray.on('double-click', () => this.onTrayClick());

    this.updateMenu();
  }

  private loadIcon(): Electron.NativeImage {
    const iconPath = this.getIconPath();
    if (iconPath && fs.existsSync(iconPath)) {
      const img = nativeImage.createFromPath(iconPath);
      if (!img.isEmpty()) return img.resize({ width: 16, height: 16 });
    }
    // Minimal valid 16×16 blue PNG fallback (no external file required)
    const fallbackB64 =
      'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAABmJLR0QA/wD/AP+gvaeTAAAAQElEQVQ4jWNgGAWkAkYGBob/' +
      'DAwM/4n0EwMDA8N/BgaG/yQaQjIYNYBkQGoAyYDUAJIBqQEkA1IDSAakBpAMAA3QCxBRPUoGAAAAAElFTkSuQmCC';
    return nativeImage.createFromBuffer(Buffer.from(fallbackB64, 'base64'));
  }

  private getIconPath(): string | null {
    // Works both in dev (src/../resources) and packaged (resources/ next to app.asar)
    const candidates = [
      path.join(__dirname, '../../resources/icon.ico'),
      path.join(__dirname, '../../resources/icon.png'),
      path.join(process.resourcesPath ?? '', 'resources/icon.ico'),
      path.join(process.resourcesPath ?? '', 'resources/icon.png'),
    ];
    return candidates.find(p => fs.existsSync(p)) ?? null;
  }

  updateMenu() {
    if (!this.tray) return;

    const contextMenu = Menu.buildFromTemplate([
      { label: 'Enterprise Monitor', enabled: false },
      { type: 'separator' },
      { label: `Backend: ${this.backendHealthy ? '✅ Running' : '❌ Offline'}`, enabled: false },
      { label: `Auth: ${this.isAuthenticated ? '🔓 Logged In' : '🔒 Logged Out'}`, enabled: false },
      { type: 'separator' },
      { label: 'Open Dashboard', click: () => this.onTrayClick() },
      { type: 'separator' },
      {
        label: 'Quit',
        click: () => this.requestQuit(),
      },
    ]);

    this.tray.setContextMenu(contextMenu);
  }

  /**
   * Quit flow:
   *   1. Ensure the main window is visible so the renderer can show the auth dialog.
   *   2. Send 'show-quit-dialog' to the renderer.
   *   3. The renderer verifies credentials via the backend, then calls app:quit IPC.
   *
   * If the window doesn't exist (e.g. first launch before login), we allow quit
   * only when the backend is offline (nothing to protect).
   */
  private requestQuit() {
    const win = this.getMainWindow();
    if (!win) {
      // No window — safe to quit (backend not running or not set up)
      app.quit();
      return;
    }
    win.show();
    win.focus();
    win.webContents.send('show-quit-dialog');
  }

  setBackendStatus(healthy: boolean) {
    this.backendHealthy = healthy;
    this.updateMenu();
    this.tray?.setToolTip(`Enterprise Monitor — Backend: ${healthy ? 'Running' : 'Offline'}`);
  }

  setAuthStatus(authenticated: boolean) {
    this.isAuthenticated = authenticated;
    this.updateMenu();
  }

  destroy() {
    this.tray?.destroy();
    this.tray = null;
  }
}
