// electron-app/src/main/main.ts  ← REPLACE the entire file with this
// FIXES vs previous delivery:
//   - api:getAppLogs      → /api/data/apps       (was wrongly /api/data/app-activity)
//   - api:getKeyLogs      → /api/data/keylogs     (was wrongly /api/data/keystrokes)
//   - Added api:getSyncStatus → GET /api/sync/status
//   - TrayManager now receives getMainWindow() for quit-auth flow
//   - window-all-closed no longer calls app.quit() (tray keeps app alive)

import { app, BrowserWindow, ipcMain, shell } from 'electron';
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

function getMainWindow() { return mainWindow; }

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1000,
    height: 750,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    title: 'Enterprise Monitor',
    resizable: true,
    minimizable: true,
    maximizable: true,
  });

  mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show();  // Show on first launch (post-install)
  });

  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      // X button → hide to tray. Monitoring continues uninterrupted.
      event.preventDefault();
      mainWindow?.hide();
    }
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

app.whenReady().then(async () => {
  app.setLoginItemSettings({ openAtLogin: true, path: app.getPath('exe') });

  trayManager = new TrayManager(
    () => showMainWindow(),
    apiClient,
    getMainWindow,   // Tray uses this to show window before sending quit-dialog event
  );

  createWindow();
  setupIpcHandlers();
  startBackendHealthCheck();
});

// Do NOT call app.quit() here. The tray keeps the process alive intentionally.
// The only exit path is through the authenticated quit-auth flow.
app.on('window-all-closed', () => { /* intentional no-op on Windows */ });

app.on('activate', () => { if (mainWindow === null) createWindow(); });

app.on('before-quit', () => { isQuitting = true; });

function showMainWindow() {
  if (!mainWindow) createWindow();
  mainWindow?.show();
  mainWindow?.focus();
}

// ─── Backend health check (every 10s) ────────────────────────────────────────
function startBackendHealthCheck() {
  const check = async () => {
    try {
      await apiClient.get('/health');
      trayManager?.setBackendStatus(true);
    } catch {
      trayManager?.setBackendStatus(false);
    }
  };
  check();
  setInterval(check, 10_000);
}

// ─── All IPC handlers ────────────────────────────────────────────────────────
function setupIpcHandlers() {

  // ── Auth ────────────────────────────────────────────────────────────────────
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

  ipcMain.handle('auth:login', async (_event, credentials: { username: string; password: string }) => {
    try {
      const response = await apiClient.post('/api/auth/login', credentials);
      if (response.data.success && response.data.token) {
        store.set('authToken', response.data.token);
        trayManager?.setAuthStatus(true);

        // First-run: if admin hasn't completed setup, nudge them
        const firstRunDone = store.get('firstRunComplete') as boolean | undefined;
        if (!firstRunDone) {
          setTimeout(() => {
            mainWindow?.webContents.send('first-run-setup');
          }, 800);
        }

        return { success: true, token: response.data.token };
      }
      return { success: false, error: response.data.error || 'Invalid credentials' };
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  });

  ipcMain.handle('app:firstRunComplete', () => {
    store.set('firstRunComplete', true);
  });

  ipcMain.handle('auth:logout', async () => {
    store.delete('authToken');
    trayManager?.setAuthStatus(false);
    return { success: true };
  });

  ipcMain.handle('auth:getTokenExpiry', () => {
    const token = store.get('authToken') as string | undefined;
    if (!token) return { remainingMs: 0 };
    try {
      const payloadB64 = token.split('.')[1];
      if (!payloadB64) return { remainingMs: 0 };
      const { exp } = JSON.parse(Buffer.from(payloadB64, 'base64').toString('utf8')) as { exp?: number };
      if (!exp) return { remainingMs: 0 };
      return { remainingMs: Math.max(0, exp * 1000 - Date.now()) };
    } catch {
      return { remainingMs: 0 };
    }
  });

  // Forgot password
  ipcMain.handle('auth:getSecurityQuestions', async (_event, username: string) => {
    try {
      const response = await apiClient.get(`/api/auth/security-questions?username=${encodeURIComponent(username)}`);
      return response.data;
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  });

  ipcMain.handle('auth:resetPassword', async (_event, payload: {
    username: string; answer1: string; answer2: string; new_password: string;
  }) => {
    try {
      const response = await apiClient.post('/api/auth/reset-password', payload);
      return response.data;
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  });

  ipcMain.handle('auth:updateCredentials', async (_event, payload: {
    new_username: string; new_password: string;
    security_q1: string; security_a1: string;
    security_q2: string; security_a2: string;
  }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/auth/update-credentials', payload, token);
      if (response.data?.success && response.data?.force_logout) {
        store.delete('authToken');
        trayManager?.setAuthStatus(false);
      }
      return response.data;
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  });

  // ── Statistics & Timeline ────────────────────────────────────────────────────
  ipcMain.handle('api:getStatistics', async (_event, params: { date?: string } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/statistics', token, params);
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  ipcMain.handle('api:getActivityStats', async (_event, params: { start: string; end: string }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/stats/activity', token, params);
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  ipcMain.handle('api:getTimelineData', async (_event, params: { date: string }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/stats/timeline', token, params);
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  // ── Screenshots ──────────────────────────────────────────────────────────────
  ipcMain.handle('api:getScreenshots', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/screenshots', token, params);
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  // ── Monitoring controls ──────────────────────────────────────────────────────
  ipcMain.handle('api:pauseMonitoring', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/monitoring/pause', {}, token);
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  ipcMain.handle('api:resumeMonitoring', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/monitoring/resume', {}, token);
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  ipcMain.handle('api:getMonitoringStatus', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/monitoring/status', token);
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  // ── Data endpoints — EXACT URLs matching api_server.py ──────────────────────
  ipcMain.handle('api:getAppLogs', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/apps', token, params);       // ← CORRECT
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  ipcMain.handle('api:getBrowserLogs', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/browser', token, params);    // ← CORRECT
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  ipcMain.handle('api:getKeyLogs', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/keylogs', token, params);    // ← CORRECT (was wrongly /keystrokes)
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  ipcMain.handle('api:getClipboardLogs', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/clipboard', token, params);  // ← CORRECT
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  // ── Identity ─────────────────────────────────────────────────────────────────
  ipcMain.handle('api:getIdentity', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/config/identity', token);
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  ipcMain.handle('api:updateIdentity', async (_event, payload: { device_alias?: string; user_alias?: string }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/config/identity', payload, token);
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  // ── Video recording ──────────────────────────────────────────────────────────
  ipcMain.handle('api:toggleVideoRecording', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/monitoring/video/toggle', {}, token);
      return response.data;
    } catch (error: any) { return { success: false, error: error.message }; }
  });

  ipcMain.handle('api:getVideoStatus', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/monitoring/video/status', token);
      return response.data;
    } catch { return { recording: false, is_active: false }; }
  });

  ipcMain.handle('api:getVideos', async (_event, params: { limit?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/videos', token, params);
      return response.data;
    } catch { return []; }
  });

  // ── Config ───────────────────────────────────────────────────────────────────
  ipcMain.handle('api:getConfig', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/config', token);
      return response.data;
    } catch (error: any) {
      return { server_url: '', api_key: '', sync_interval_seconds: 300 };
    }
  });

  ipcMain.handle('api:setConfig', async (_event, payload: {
    server_url: string; api_key: string; sync_interval_seconds?: number;
    url_app_activity?: string; url_browser?: string; url_clipboard?: string;
    url_keystrokes?: string; url_screenshots?: string; url_videos?: string;
  }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/config', payload, token);
      return response.data;
    } catch (error: any) { throw new Error(error.message); }
  });

  ipcMain.handle('api:getTimezone', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/config/timezone', token);
      return response.data;
    } catch { return { timezone: 'UTC' }; }
  });

  ipcMain.handle('api:setTimezone', async (_event, tz: string) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/config/timezone', { timezone: tz }, token);
      return response.data;
    } catch (error: any) { return { success: false, error: error.message }; }
  });

  // ── Sync status (NEW) ────────────────────────────────────────────────────────
  ipcMain.handle('api:getSyncStatus', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/sync/status', token);
      return response.data;
    } catch {
      return { last_sync: null, last_error: null, is_syncing: false };
    }
  });

  ipcMain.handle('api:triggerSync', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/sync/trigger', {}, token);
      return response.data;
    } catch (error: any) { return { success: false, error: error.message }; }
  });

  // ── File / folder ────────────────────────────────────────────────────────────
  ipcMain.handle('app:openFolder', async (_event, filepath: string) => {
    try {
      const normalizedPath = path.normalize(filepath);
      if (fs.existsSync(normalizedPath)) {
        shell.showItemInFolder(normalizedPath);
      } else {
        const parentDir = path.dirname(normalizedPath);
        if (fs.existsSync(parentDir)) {
          await shell.openPath(parentDir);
        } else {
          const recordingsRoot = path.join(
            process.env.LOCALAPPDATA || path.join(require('os').homedir(), 'AppData', 'Local'),
            'EnterpriseMonitor', 'Videos'
          );
          if (!fs.existsSync(recordingsRoot)) fs.mkdirSync(recordingsRoot, { recursive: true });
          await shell.openPath(recordingsRoot);
        }
      }
    } catch (err: any) {
      console.error('app:openFolder error:', err.message);
    }
  });

  // ── Quit (auth-gated — only called by renderer after credential verification) ─
  ipcMain.handle('app:quit', async () => {
    isQuitting = true;
    app.quit();
  });
}
