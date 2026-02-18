import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('electronAPI', {
  // Authentication
  checkAuth: () => ipcRenderer.invoke('auth:check'),
  login: (credentials: { username: string; password: string }) =>
    ipcRenderer.invoke('auth:login', credentials),
  logout: () => ipcRenderer.invoke('auth:logout'),

  // FIX #2: getStatistics now accepts { date } param for date-filtered stats
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

  // App control
  quitApp: () => ipcRenderer.invoke('app:quit')
});

declare global {
  interface Window {
    electronAPI: {
      checkAuth: () => Promise<{ authenticated: boolean }>;
      login: (credentials: { username: string; password: string }) => Promise<{ success: boolean; token?: string; error?: string }>;
      logout: () => Promise<{ success: boolean }>;
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
      quitApp: () => Promise<void>;
    };
  }
}
