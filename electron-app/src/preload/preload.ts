// electron-app/src/preload/preload.ts
// v5.2.6 — Patch 1D: All push-event IPC channels guarded with removeAllListeners
// before re-registration. Guarantees listener stack never exceeds 1 regardless
// of how many times the renderer script executes or the window reloads.

import { contextBridge, ipcRenderer, IpcRendererEvent } from 'electron';

contextBridge.exposeInMainWorld('electronAPI', {
  // ── Auth ──────────────────────────────────────────────────────────────────
  checkAuth: () =>
    ipcRenderer.invoke('auth:check'),
  login: (credentials: { username: string; password: string }) =>
    ipcRenderer.invoke('auth:login', credentials),
  logout: () =>
    ipcRenderer.invoke('auth:logout'),
  updateCredentials: (payload: { new_username: string; new_password: string; security_q1: string; security_a1: string; security_q2: string; security_a2: string }) =>
    ipcRenderer.invoke('auth:updateCredentials', payload),
  getTokenExpiry: () =>
    ipcRenderer.invoke('auth:getTokenExpiry'),
  getSecurityQuestions: (username: string) =>
    ipcRenderer.invoke('auth:getSecurityQuestions', username),
  resetPassword: (payload: { username: string; answer1: string; answer2: string; new_password: string }) =>
    ipcRenderer.invoke('auth:resetPassword', payload),
  verifyCredentials: (credentials: { username: string; password: string }) =>
    ipcRenderer.invoke('auth:verifyOnly', credentials),

  // ── Data ──────────────────────────────────────────────────────────────────
  getStatistics: (params: { date?: string }) =>
    ipcRenderer.invoke('api:getStatistics', params),
  getScreenshots: (params: { limit?: number; offset?: number }) =>
    ipcRenderer.invoke('api:getScreenshots', params),
  getActivityStats: (params: { start: string; end: string }) =>
    ipcRenderer.invoke('api:getActivityStats', params),
  getTimelineData: (params: { date: string }) =>
    ipcRenderer.invoke('api:getTimelineData', params),
  getAppLogs: (params: { limit?: number; offset?: number }) =>
    ipcRenderer.invoke('api:getAppLogs', params),
  getBrowserLogs: (params: { limit?: number; offset?: number }) =>
    ipcRenderer.invoke('api:getBrowserLogs', params),
  getClipboardLogs: (params: { limit?: number; offset?: number }) =>
    ipcRenderer.invoke('api:getClipboardLogs', params),
  getKeyLogs: (params: { limit?: number; offset?: number }) =>
    ipcRenderer.invoke('api:getKeyLogs', params),

  // ── Monitoring ────────────────────────────────────────────────────────────
  pauseMonitoring: () => ipcRenderer.invoke('api:pauseMonitoring'),
  resumeMonitoring: () => ipcRenderer.invoke('api:resumeMonitoring'),
  getMonitoringStatus: () => ipcRenderer.invoke('api:getMonitoringStatus'),
  getBackendUrl: () => ipcRenderer.invoke('api:getBackendUrl'),

  // ── Identity ──────────────────────────────────────────────────────────────
  getIdentity: () =>
    ipcRenderer.invoke('api:getIdentity'),
  updateIdentity: (payload: { device_alias?: string; user_alias?: string }) =>
    ipcRenderer.invoke('api:updateIdentity', payload),

  // ── Location & Credential Confirmation ────────────────────────────────────────
  confirmCredential: (payload: { device_alias: string; user_alias: string; location: string }) =>
    ipcRenderer.invoke('api:confirmCredential', payload),

  getCredentialStatus: () =>
    ipcRenderer.invoke('api:getCredentialStatus'),


  // ── Video ─────────────────────────────────────────────────────────────────
  toggleVideoRecording: () => ipcRenderer.invoke('api:toggleVideoRecording'),
  getVideoStatus: () => ipcRenderer.invoke('api:getVideoStatus'),
  getVideos: (params: { limit?: number }) =>
    ipcRenderer.invoke('api:getVideos', params),

  // ── Screenshots ────────────────────────────────────────────────────────────
  toggleScreenshotCapturing: () => ipcRenderer.invoke('api:toggleScreenshotCapturing'),
  getScreenshotStatus: () => ipcRenderer.invoke('api:getScreenshotStatus'),

  // ── Config ────────────────────────────────────────────────────────────────
  getConfig: () => ipcRenderer.invoke('api:getConfig'),
  setConfig: (payload: { server_url: string; api_key: string; sync_interval_seconds?: number; url_app_activity?: string; url_browser?: string; url_clipboard?: string; url_keystrokes?: string; url_screenshots?: string; url_videos?: string }) =>
    ipcRenderer.invoke('api:setConfig', payload),
  getTimezone: () => ipcRenderer.invoke('api:getTimezone'),
  setTimezone: (tz: string) => ipcRenderer.invoke('api:setTimezone', tz),

  // ── Sync ──────────────────────────────────────────────────────────────────
  getSyncStatus: () => ipcRenderer.invoke('api:getSyncStatus'),
  triggerSync: () => ipcRenderer.invoke('api:triggerSync'),

  // ── App control ───────────────────────────────────────────────────────────
  openFolder: (filepath: string) => ipcRenderer.invoke('app:openFolder', filepath),
  quitApp: () => ipcRenderer.invoke('app:quit'),
  firstRunComplete: () => ipcRenderer.invoke('app:firstRunComplete'),
  getAppVersion: () => ipcRenderer.invoke('app:getVersion'),

  // ── Main → Renderer push events ───────────────────────────────────────────
  // Patch 1D: removeAllListeners before .on on every push channel.
  // This is the correct sanitization pattern: even if this registration code
  // runs more than once (hot-reload, double-script-execution), the channel
  // listener count is always reset to exactly 1.
  onQuitRequested: (cb: (event: IpcRendererEvent) => void) => {
    ipcRenderer.removeAllListeners('show-quit-dialog');
    ipcRenderer.on('show-quit-dialog', cb);
  },
  onFirstRunSetup: (cb: (event: IpcRendererEvent) => void) => {
    ipcRenderer.removeAllListeners('first-run-setup');
    ipcRenderer.on('first-run-setup', cb);
  },
  onForceLogout: (cb: (event: IpcRendererEvent) => void) => {
    ipcRenderer.removeAllListeners('force-logout');
    ipcRenderer.on('force-logout', cb);
  },

  // ── Auto-Update system ────────────────────────────────────────────────────
  installUpdate: () =>
    ipcRenderer.invoke('app:installUpdate'),
  deferUpdate: () =>
    ipcRenderer.invoke('app:deferUpdate'),
  checkForUpdates: () =>
    ipcRenderer.invoke('app:checkForUpdates'),

  onUpdateAvailable: (cb: (event: IpcRendererEvent, info: { version: string; releaseNotes: string }) => void) => {
    ipcRenderer.removeAllListeners('update-available');
    ipcRenderer.on('update-available', cb);
  },
  onDownloadProgress: (cb: (event: IpcRendererEvent, progress: { percent: number; bytesPerSecond: number; total: number }) => void) => {
    ipcRenderer.removeAllListeners('download-progress');
    ipcRenderer.on('download-progress', cb);
  },
  onUpdateDownloaded: (cb: (event: IpcRendererEvent, info: { version: string }) => void) => {
    ipcRenderer.removeAllListeners('update-downloaded');
    ipcRenderer.on('update-downloaded', cb);
  },
  onUpdateComplete: (cb: (event: IpcRendererEvent, info: { version: string; previousVersion: string }) => void) => {
    ipcRenderer.removeAllListeners('update-complete');
    ipcRenderer.on('update-complete', cb);
  },
  onUpdateError: (cb: (event: IpcRendererEvent, info: { message: string }) => void) => {
    ipcRenderer.removeAllListeners('update-error');
    ipcRenderer.on('update-error', cb);
  },
});
