import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('electronAPI', {
  // Authentication
  checkAuth: () => ipcRenderer.invoke('auth:check'),
  login: (credentials: { username: string; password: string }) =>
    ipcRenderer.invoke('auth:login', credentials),
  logout: () => ipcRenderer.invoke('auth:logout'),

  // NEW: Update credentials (username + password + security Q&A)
  updateCredentials: (payload: {
    new_username: string;
    new_password: string;
    security_q1: string;
    security_a1: string;
    security_q2: string;
    security_a2: string;
  }) => ipcRenderer.invoke('auth:updateCredentials', payload),

  getStatistics: (params: { date?: string }) =>
    ipcRenderer.invoke('api:getStatistics', params),

  getScreenshots: (params: { limit?: number; offset?: number }) =>
    ipcRenderer.invoke('api:getScreenshots', params),
  pauseMonitoring: () => ipcRenderer.invoke('api:pauseMonitoring'),
  resumeMonitoring: () => ipcRenderer.invoke('api:resumeMonitoring'),
  getMonitoringStatus: () => ipcRenderer.invoke('api:getMonitoringStatus'),
  getActivityStats: (params: { start: string; end: string }) =>
    ipcRenderer.invoke('api:getActivityStats', params),
  getTimelineData: (params: { date: string }) =>
    ipcRenderer.invoke('api:getTimelineData', params),

  // Data Logs
  getAppLogs: (params: { limit?: number; offset?: number }) =>
    ipcRenderer.invoke('api:getAppLogs', params),
  getBrowserLogs: (params: { limit?: number; offset?: number }) =>
    ipcRenderer.invoke('api:getBrowserLogs', params),
  getClipboardLogs: (params: { limit?: number; offset?: number }) =>
    ipcRenderer.invoke('api:getClipboardLogs', params),
  getKeyLogs: (params: { limit?: number; offset?: number }) =>
    ipcRenderer.invoke('api:getKeyLogs', params),

  // Identity / Alias Management
  getIdentity: () =>
    ipcRenderer.invoke('api:getIdentity'),
  updateIdentity: (payload: { device_alias?: string; user_alias?: string }) =>
    ipcRenderer.invoke('api:updateIdentity', payload),

  // NEW: Screen Recording
  toggleVideoRecording: () => ipcRenderer.invoke('api:toggleVideoRecording'),
  getVideoStatus: () => ipcRenderer.invoke('api:getVideoStatus'),
  getVideos: (params?: { limit?: number }) => ipcRenderer.invoke('api:getVideos', params),

  // NEW: Open folder in Windows Explorer
  openFolder: (filepath: string) => ipcRenderer.invoke('app:openFolder', filepath),
  getTimezone: () => ipcRenderer.invoke('api:getTimezone'),
  setTimezone: (tz: string) => ipcRenderer.invoke('api:setTimezone', tz),
  getTokenExpiry: () => ipcRenderer.invoke('auth:getTokenExpiry'),
  getConfig: () => ipcRenderer.invoke('api:getConfig'),
  setConfig: (payload: { server_url: string; api_key: string; sync_interval_seconds?: number }) =>
    ipcRenderer.invoke('api:setConfig', payload),
  // App control
  quitApp: () => ipcRenderer.invoke('app:quit'),
});

declare global {
  interface Window {
    electronAPI: {
      checkAuth: () => Promise<{ authenticated: boolean }>;
      login: (credentials: { username: string; password: string }) => Promise<{ success: boolean; token?: string; error?: string }>;
      logout: () => Promise<{ success: boolean }>;
      updateCredentials: (payload: {
        new_username: string;
        new_password: string;
        security_q1: string;
        security_a1: string;
        security_q2: string;
        security_a2: string;
      }) => Promise<{ success: boolean; force_logout?: boolean; error?: string; warning?: string }>;
      getStatistics: (params: { date?: string }) => Promise<any>;
      getScreenshots: (params: { limit?: number; offset?: number }) => Promise<any>;
      pauseMonitoring: () => Promise<any>;
      resumeMonitoring: () => Promise<any>;
      getMonitoringStatus: () => Promise<any>;
      getActivityStats: (params: { start: string; end: string }) => Promise<any>;
      getTimelineData: (params: { date: string }) => Promise<any>;
      getAppLogs: (params: { limit?: number; offset?: number }) => Promise<any>;
      getBrowserLogs: (params: { limit?: number; offset?: number }) => Promise<any>;
      getClipboardLogs: (params: { limit?: number; offset?: number }) => Promise<any>;
      getKeyLogs: (params: { limit?: number; offset?: number }) => Promise<any>;
      getIdentity: () => Promise<{
        machine_id: string;
        os_user: string;
        device_alias: string;
        user_alias: string;
      }>;
      updateIdentity: (payload: { device_alias?: string; user_alias?: string }) => Promise<{ success: boolean; message?: string; error?: string }>;
      toggleVideoRecording: () => Promise<{ success: boolean; recording: boolean }>;
      getVideoStatus: () => Promise<{ recording: boolean; is_active: boolean }>;
      getVideos: (params?: { limit?: number }) => Promise<any[]>;
      openFolder: (filepath: string) => Promise<void>;
      getTimezone: () => Promise<{ timezone: string }>;
      setTimezone: (tz: string) => Promise<{ success: boolean; timezone: string; error?: string }>;
      getTokenExpiry: () => Promise<{ remainingMs: number }>;
      getConfig: () => Promise<{ server_url: string; api_key: string; sync_interval_seconds: number }>;
      setConfig: (payload: { server_url: string; api_key: string; sync_interval_seconds?: number }) =>
        Promise<{ success: boolean; error?: string }>;

      quitApp: () => Promise<void>;
    };
  }
}
