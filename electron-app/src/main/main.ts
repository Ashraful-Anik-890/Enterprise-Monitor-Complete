import { app, BrowserWindow, ipcMain, Menu } from 'electron';
import * as path from 'path';
import { TrayManager } from './tray';
import { ApiClient } from './api-client';
import Store from 'electron-store';

// Store for persistent data
const store = new Store();

// Backend API client
const apiClient = new ApiClient('http://127.0.0.1:51235');

let mainWindow: BrowserWindow | null = null;
let trayManager: TrayManager | null = null;
let isQuitting = false;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 700,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    },
    title: 'Enterprise Monitor',
    resizable: true,
    minimizable: true,
    maximizable: true
  });

  // Load the HTML file
  mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    // Don't show by default - only show when user clicks tray icon
  });



  // Hide window instead of closing
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow?.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// App ready
app.whenReady().then(async () => {
  // Enable auto-launch on login
  app.setLoginItemSettings({
    openAtLogin: true,
    path: app.getPath('exe')
  });

  // Create system tray
  trayManager = new TrayManager(
    () => {
      // On tray click - check auth and show appropriate window
      showMainWindow();
    },
    apiClient
  );

  // Create main window (hidden initially)
  createWindow();

  // IPC handlers
  setupIpcHandlers();

  // Start monitoring backend health
  startBackendHealthCheck();
});

// Quit when all windows are closed (except on macOS)
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow();
  }
});

app.on('before-quit', () => {
  isQuitting = true;
});

function showMainWindow() {
  if (!mainWindow) {
    createWindow();
  }
  mainWindow?.show();
  mainWindow?.focus();
}

function setupIpcHandlers() {
  // Auth check
  ipcMain.handle('auth:check', async () => {
    try {
      const token = store.get('authToken') as string | undefined;
      if (!token) return { authenticated: false };

      const response = await apiClient.get('/api/auth/check', token);
      return response.data;
    } catch (error) {
      return { authenticated: false };
    }
  });

  // Login
  ipcMain.handle('auth:login', async (_event, credentials: { username: string; password: string }) => {
    try {
      const response = await apiClient.post('/api/auth/login', credentials);
      if (response.data.success && response.data.token) {
        store.set('authToken', response.data.token);
        return { success: true, token: response.data.token };
      }
      return { success: false, error: 'Invalid credentials' };
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  });

  // Logout
  ipcMain.handle('auth:logout', async () => {
    store.delete('authToken');
    return { success: true };
  });

  // Get statistics
  ipcMain.handle('api:getStatistics', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/statistics', token);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Get screenshots
  ipcMain.handle('api:getScreenshots', async (_event, params: { limit?: number; offset?: number }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/screenshots', token, params);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Pause monitoring
  ipcMain.handle('api:pauseMonitoring', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/monitoring/pause', {}, token);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Resume monitoring
  ipcMain.handle('api:resumeMonitoring', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/monitoring/resume', {}, token);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Get monitoring status
  ipcMain.handle('api:getMonitoringStatus', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/monitoring/status', token);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Get activity stats
  ipcMain.handle('api:getActivityStats', async (_event, { start, end }: { start: string; end: string }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/stats/activity', token, { start, end });
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Get timeline data
  ipcMain.handle('api:getTimelineData', async (_event, { date }: { date: string }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/stats/timeline', token, { date });
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // New Data Handlers
  ipcMain.handle('api:getAppLogs', async (_event, params: { limit?: number; offset?: number }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/apps', token, params);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  ipcMain.handle('api:getBrowserLogs', async (_event, params: { limit?: number; offset?: number }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/browser', token, params);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  ipcMain.handle('api:getClipboardLogs', async (_event, params: { limit?: number; offset?: number }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/clipboard', token, params);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Quit application
  ipcMain.handle('app:quit', async () => {
    app.quit();
  });
}

let backendHealthCheckInterval: NodeJS.Timeout | null = null;

function startBackendHealthCheck() {
  // Check backend health every 30 seconds
  backendHealthCheckInterval = setInterval(async () => {
    try {
      await apiClient.get('/health');
      trayManager?.setBackendStatus(true);
    } catch (error) {
      trayManager?.setBackendStatus(false);
    }
  }, 30000);

  // Initial check
  apiClient.get('/health')
    .then(() => trayManager?.setBackendStatus(true))
    .catch(() => trayManager?.setBackendStatus(false));
}

// Clean up on app quit
app.on('will-quit', () => {
  if (backendHealthCheckInterval) {
    clearInterval(backendHealthCheckInterval);
  }
});
