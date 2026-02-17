import { app, BrowserWindow, ipcMain, Menu, nativeImage } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import { TrayManager } from './tray';
import { ApiClient } from './api-client';
import Store from 'electron-store';

const store = new Store();
const apiClient = new ApiClient('http://127.0.0.1:51235');

let mainWindow: BrowserWindow | null = null;
let trayManager: TrayManager | null = null;
let isQuitting = false;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1000,
    height: 750,
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

  mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));

  mainWindow.once('ready-to-show', () => {
    // Intentionally hidden on start — user opens via tray
  });

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

app.whenReady().then(async () => {
  app.setLoginItemSettings({
    openAtLogin: true,
    path: app.getPath('exe')
  });

  trayManager = new TrayManager(
    () => showMainWindow(),
    apiClient
  );

  createWindow();
  setupIpcHandlers();
  startBackendHealthCheck();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (mainWindow === null) createWindow();
});

app.on('before-quit', () => {
  isQuitting = true;
});

function showMainWindow() {
  if (!mainWindow) createWindow();
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
    } catch {
      return { authenticated: false };
    }
  });

  // Login
  ipcMain.handle('auth:login', async (_event, credentials: { username: string; password: string }) => {
    try {
      const response = await apiClient.post('/api/auth/login', credentials);
      if (response.data.success && response.data.token) {
        store.set('authToken', response.data.token);
        trayManager?.setAuthStatus(true);
        return { success: true, token: response.data.token };
      }
      return { success: false, error: response.data.error || 'Invalid credentials' };
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  });

  // Logout
  ipcMain.handle('auth:logout', async () => {
    store.delete('authToken');
    trayManager?.setAuthStatus(false);
    return { success: true };
  });

  // FIX #2: getStatistics now forwards the date param to the backend
  ipcMain.handle('api:getStatistics', async (_event, params: { date?: string } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/statistics', token, params);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Get screenshots
  ipcMain.handle('api:getScreenshots', async (_event, params: { limit?: number; offset?: number } = {}) => {
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

  // Monitoring status
  ipcMain.handle('api:getMonitoringStatus', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/monitoring/status', token);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Activity stats (charts — already date-aware)
  ipcMain.handle('api:getActivityStats', async (_event, { start, end }: { start: string; end: string }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/stats/activity', token, { start, end });
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Timeline data (charts — already date-aware)
  ipcMain.handle('api:getTimelineData', async (_event, { date }: { date: string }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/stats/timeline', token, { date });
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // App logs
  ipcMain.handle('api:getAppLogs', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/apps', token, params);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Browser logs
  ipcMain.handle('api:getBrowserLogs', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/browser', token, params);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Clipboard logs
  ipcMain.handle('api:getClipboardLogs', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/clipboard', token, params);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Quit app
  ipcMain.handle('app:quit', async () => {
    isQuitting = true;
    app.quit();
  });
}

function startBackendHealthCheck() {
  const checkInterval = 30000; // 30 seconds

  const check = async () => {
    try {
      await apiClient.get('/health');
      trayManager?.setBackendStatus(true);
    } catch {
      trayManager?.setBackendStatus(false);
    }
  };

  check();
  setInterval(check, checkInterval);
}
