import { app, BrowserWindow, ipcMain, Menu, nativeImage, shell } from 'electron';
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

  // Decode JWT exp claim from stored token — used by renderer countdown timer
  ipcMain.handle('auth:getTokenExpiry', () => {
    const token = store.get('authToken') as string | undefined;
    if (!token) return { remainingMs: 0 };
    try {
      // JWT payload is the second base64url segment
      const payloadB64 = token.split('.')[1];
      if (!payloadB64) return { remainingMs: 0 };
      // atob is not available in Node; use Buffer instead
      const json = Buffer.from(payloadB64, 'base64').toString('utf8');
      const { exp } = JSON.parse(json) as { exp?: number };
      if (!exp) return { remainingMs: 0 };
      const remainingMs = exp * 1000 - Date.now();
      return { remainingMs: Math.max(0, remainingMs) };
    } catch {
      return { remainingMs: 0 };
    }
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

  ipcMain.handle('api:getKeyLogs', async (_event, params = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/keylogs', token, params);
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

  // Get identity config (machine_id, os_user, device_alias, user_alias)
  ipcMain.handle('api:getIdentity', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/config/identity', token);
      return response.data;
    } catch (error: any) {
      throw new Error(error.message);
    }
  });

  // Update identity aliases (device_alias and/or user_alias)
  ipcMain.handle('api:updateIdentity', async (
    _event,
    payload: { device_alias?: string; user_alias?: string }
  ) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/config/identity', payload, token);
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

  ipcMain.handle('auth:updateCredentials', async (_event, payload: {
    new_username: string;
    new_password: string;
    security_q1: string;
    security_a1: string;
    security_q2: string;
    security_a2: string;
  }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/auth/update-credentials', payload, token);
      if (response.data?.success && response.data?.force_logout) {
        // Invalidate stored session — user must log in again with new credentials
        store.delete('authToken');
        trayManager?.setAuthStatus(false);
      }
      return response.data;
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  });

  // Toggle screen recording
  ipcMain.handle('api:toggleVideoRecording', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/monitoring/video/toggle', {}, token);
      return response.data;
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  });

  // Get recording status
  ipcMain.handle('api:getVideoStatus', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/monitoring/video/status', token);
      return response.data;
    } catch (error: any) {
      return { recording: false, is_active: false };
    }
  });

  // Get video list
  ipcMain.handle('api:getVideos', async (_event, params: { limit?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/videos', token, params);
      return response.data;
    } catch (error: any) {
      return [];
    }
  });

  // Open folder / show file in Windows Explorer
  ipcMain.handle('app:openFolder', async (_event, filepath: string) => {
    try {
      // Normalize: Python Path produces forward slashes; Windows shell needs backslashes
      const normalizedPath = path.normalize(filepath);
      console.log('[app:openFolder] received:', JSON.stringify(filepath));
      console.log('[app:openFolder] normalized:', normalizedPath);
      console.log('[app:openFolder] exists:', fs.existsSync(normalizedPath));

      if (fs.existsSync(normalizedPath)) {
        // File exists → highlight it in Explorer
        shell.showItemInFolder(normalizedPath);
      } else {
        // File gone (deleted/moved) → open the parent directory
        const parentDir = path.dirname(normalizedPath);
        if (fs.existsSync(parentDir)) {
          await shell.openPath(parentDir);
        } else {
          // Parent also missing → open the known recordings root derived from home
          const recordingsRoot = path.join(
            process.env.LOCALAPPDATA || path.join(require('os').homedir(), 'AppData', 'Local'),
            'EnterpriseMonitor',
            'Videos'
          );
          if (!fs.existsSync(recordingsRoot)) {
            fs.mkdirSync(recordingsRoot, { recursive: true });
          }
          await shell.openPath(recordingsRoot);
        }
      }
    } catch (err: any) {
      console.error('app:openFolder error:', err.message);
    }
  });

  ipcMain.handle('api:getTimezone', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/config/timezone', token);
      return response.data;
    } catch (error: any) {
      return { timezone: 'UTC' };   // safe fallback — never crash
    }
  });

  // Save display timezone to backend config
  ipcMain.handle('api:setTimezone', async (_event, tz: string) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/config/timezone', { timezone: tz }, token);
      return response.data;
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  });

  // Read current server config for the Config Server API modal
  ipcMain.handle('api:getConfig', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/config', token);
      return response.data;
    } catch (error: any) {
      return { server_url: '', api_key: '', sync_interval_seconds: 300 };
    }
  });

  // Save server config from the Config Server API modal
  ipcMain.handle('api:setConfig', async (_event, payload: {
    server_url: string;
    api_key: string;
    sync_interval_seconds?: number;
  }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/config', payload, token);
      return response.data;
    } catch (error: any) {
      return { success: false, error: error.message };
    }
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
