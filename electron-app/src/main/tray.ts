import { Tray, Menu, nativeImage, app } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import { ApiClient } from './api-client';

export class TrayManager {
  private tray: Tray | null = null;
  private backendHealthy: boolean = false;
  private isAuthenticated: boolean = false;
  private onTrayClick: () => void;
  private apiClient: ApiClient;

  constructor(onTrayClick: () => void, apiClient: ApiClient) {
    this.onTrayClick = onTrayClick;
    this.apiClient = apiClient;
    this.createTray();
  }

  private createTray() {
    const icon = this.loadIcon();
    this.tray = new Tray(icon);
    this.tray.setToolTip('Enterprise Monitor');

    this.tray.on('click', () => {
      this.onTrayClick();
    });

    this.tray.on('double-click', () => {
      this.onTrayClick();
    });

    this.updateMenu();
  }

  private loadIcon(): Electron.NativeImage {
    // FIX: Tray icon was blank because resources/icon.ico doesn't exist.
    // Strategy: Try the real file, fall back to a programmatic colored square.
    const iconPath = this.getIconPath();

    if (iconPath && fs.existsSync(iconPath)) {
      const img = nativeImage.createFromPath(iconPath);
      if (!img.isEmpty()) {
        return img.resize({ width: 16, height: 16 });
      }
    }

    // Fallback: generate a 16x16 PNG in memory (blue square with 'E' branding)
    // This is a valid 16x16 blue PNG encoded as base64
    const fallbackB64 =
      'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAA' +
      'BmJLR0QA/wD/AP+gvaeTAAAAQElEQVQ4jWNgGAWkAkYGBob/' +
      'DAwM/4n0EwMDA8N/BgaG/yQaQjIYNYBkQGoAyYDUAJIBqQEk' +
      'A1IDSAakBpAMAA3QCxBRPUoGAAAAAElFTkSuQmCC';

    return nativeImage.createFromBuffer(Buffer.from(fallbackB64, 'base64'));
  }

  private getIconPath(): string | null {
    const platform = process.platform;

    if (platform === 'darwin') {
      return path.join(__dirname, '../../resources/iconTemplate.png');
    } else if (platform === 'win32') {
      // Try .ico first, then .png
      const ico = path.join(__dirname, '../../resources/icon.ico');
      const png = path.join(__dirname, '../../resources/icon.png');
      if (fs.existsSync(ico)) return ico;
      if (fs.existsSync(png)) return png;
      return null;
    } else {
      return path.join(__dirname, '../../resources/icon.png');
    }
  }

  updateMenu() {
    if (!this.tray) return;

    const contextMenu = Menu.buildFromTemplate([
      {
        label: 'Enterprise Monitor',
        enabled: false
      },
      { type: 'separator' },
      {
        label: `Backend: ${this.backendHealthy ? '✅ Running' : '❌ Offline'}`,
        enabled: false
      },
      {
        label: `Auth: ${this.isAuthenticated ? '🔓 Logged In' : '🔒 Logged Out'}`,
        enabled: false
      },
      { type: 'separator' },
      {
        label: 'Open Dashboard',
        click: () => this.onTrayClick()
      },
      { type: 'separator' },
      {
        label: 'Quit',
        click: () => app.quit()
      }
    ]);

    this.tray.setContextMenu(contextMenu);
  }

  setBackendStatus(healthy: boolean) {
    this.backendHealthy = healthy;
    this.updateMenu();
    // Also update tooltip for quick status check
    this.tray?.setToolTip(
      `Enterprise Monitor — Backend: ${healthy ? 'Running' : 'Offline'}`
    );
  }

  setAuthStatus(authenticated: boolean) {
    this.isAuthenticated = authenticated;
    this.updateMenu();
  }

  destroy() {
    if (this.tray) {
      this.tray.destroy();
      this.tray = null;
    }
  }
}
