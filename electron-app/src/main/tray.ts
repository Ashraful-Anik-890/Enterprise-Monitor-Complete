import { Tray, Menu, nativeImage, app } from 'electron';
import * as path from 'path';
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
    // Create tray icon
    const iconPath = this.getTrayIconPath();
    const icon = nativeImage.createFromPath(iconPath);
    
    this.tray = new Tray(icon.resize({ width: 16, height: 16 }));
    this.tray.setToolTip('Enterprise Monitor');
    
    // Click handler
    this.tray.on('click', () => {
      this.onTrayClick();
    });

    // Build initial menu
    this.updateMenu();
  }

  private getTrayIconPath(): string {
    const platform = process.platform;
    
    if (platform === 'darwin') {
      return path.join(__dirname, '../../resources/iconTemplate.png');
    } else if (platform === 'win32') {
      return path.join(__dirname, '../../resources/icon.ico');
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
      {
        type: 'separator'
      },
      {
        label: `Status: ${this.backendHealthy ? 'Running' : 'Backend Offline'}`,
        enabled: false
      },
      {
        type: 'separator'
      },
      {
        label: 'Open Dashboard',
        click: () => {
          this.onTrayClick();
        }
      },
      {
        type: 'separator'
      },
      {
        label: 'Quit',
        click: () => {
          app.quit();
        }
      }
    ]);

    this.tray.setContextMenu(contextMenu);
  }

  setBackendStatus(healthy: boolean) {
    this.backendHealthy = healthy;
    this.updateMenu();
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
