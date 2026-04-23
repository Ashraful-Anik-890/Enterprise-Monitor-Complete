/**
 * electron-app/src/main/main.ts
 *
 * Auto-Update Phase 1 + Electron Frontend Logging + 3-Layer Rollback
 * ──────────────────────────────────────────────────────────────────
 * PATCH A — Import: Added `autoUpdater` from 'electron-updater'
 * PATCH B — Flags: isSystemUpdate, updateDownloaded, updatePendingVersion
 * PATCH C — before-quit: isSystemUpdate as first check
 * PATCH D — setupAutoUpdater(): Event wiring + 4h schedule
 * PATCH E — app.whenReady(): Post-update detection + rollback + setupAutoUpdater()
 * PATCH F — setupIpcHandlers(): Modified app:quit, new update IPC handlers
 * NEW    — Electron frontend logging to %LOCALAPPDATA%/EnterpriseMonitor/logs/electron.log
 * NEW    — 3-Layer rollback (binary integrity check + DB snapshot)
 */

// ─── PATCH A — Import autoUpdater ────────────────────────────────────────────
import { autoUpdater } from 'electron-updater';
// ─────────────────────────────────────────────────────────────────────────────

import { app, BrowserWindow, ipcMain, shell, powerMonitor } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { spawn, ChildProcess } from 'child_process';
import { TrayManager } from './tray';
import { ApiClient } from './api-client';
import Store from 'electron-store';

const store = new Store();

// ── Paths ─────────────────────────────────────────────────────────────────────
const IS_MAC = process.platform === 'darwin';

const EM_DIR = IS_MAC
  ? path.join(os.homedir(), 'Library', 'Application Support', 'EnterpriseMonitor')
  : path.join(
    process.env.LOCALAPPDATA ?? path.join(os.homedir(), 'AppData', 'Local'),
    'EnterpriseMonitor',
  );

const PORT_INFO = path.join(EM_DIR, 'port.info');

const BACKEND_BIN = IS_MAC
  ? 'enterprise_monitor_backend'
  : 'enterprise_monitor_backend.exe';

// ─── Electron Frontend Logging ────────────────────────────────────────────────
// Mirror backend's approach: backend writes to EM_DIR/logs/backend.log,
// Electron writes to EM_DIR/logs/electron.log. Dynamically resolved, no hardcoding.
const LOG_DIR = path.join(EM_DIR, 'logs');
fs.mkdirSync(LOG_DIR, { recursive: true });

const logStream = fs.createWriteStream(path.join(LOG_DIR, 'electron.log'), { flags: 'a' });
const originalLog = console.log;
const originalError = console.error;
const originalWarn = console.warn;

function timestamp(): string { return new Date().toISOString(); }

console.log = (...args: any[]) => {
  const line = `${timestamp()} [INFO] ${args.join(' ')}\n`;
  logStream.write(line);
  originalLog.apply(console, args);
};
console.error = (...args: any[]) => {
  const line = `${timestamp()} [ERROR] ${args.join(' ')}\n`;
  logStream.write(line);
  originalError.apply(console, args);
};
console.warn = (...args: any[]) => {
  const line = `${timestamp()} [WARN] ${args.join(' ')}\n`;
  logStream.write(line);
  originalWarn.apply(console, args);
};

console.log('[main] Electron frontend logging initialised:', path.join(LOG_DIR, 'electron.log'));
// ─────────────────────────────────────────────────────────────────────────────

// ── Process state ─────────────────────────────────────────────────────────────
let mainWindow: BrowserWindow | null = null;
let trayManager: TrayManager | null = null;
let apiClient: ApiClient;
let backendProcess: ChildProcess | null = null;
let isQuitting = false;
let allowAuthenticatedQuit = false;
let isSystemShutdown = false;
let backendKilled = false;
let backendExited = false;
let backendExitCode: number | null = null;

// ─── PATCH B — New update flags ───────────────────────────────────────────────
let isSystemUpdate = false;
let updateDownloaded = false;
let updatePendingVersion: string | null = null;
// ─────────────────────────────────────────────────────────────────────────────

// ─── Idle Auto-Pause Tracker ──────────────────────────────────────────────────
// ⚙️  HOW TO CHANGE THE IDLE TIMEOUT:
//     Edit IDLE_PAUSE_THRESHOLD_SECS below and rebuild the Electron app.
//     Formula: seconds = minutes × 60.  E.g. 15 min → 15 * 60 = 900.
const IDLE_PAUSE_THRESHOLD_SECS = 5 * 60; // 5 minutes

// True only when WE auto-paused due to idle. Distinguishes from an admin's
// manual pause so auto-resume cannot accidentally un-pause a deliberate pause.
let isAutoPaused = false;
// ─────────────────────────────────────────────────────────────────────────────


// ── 401 helpers ───────────────────────────────────────────────────────────────
function is401(error: any): boolean {
  return error?.response?.status === 401;
}

function handleAuthExpired(): { __forceLogout: true } {
  store.delete('authToken');
  trayManager?.setAuthStatus(false);
  mainWindow?.webContents.send('force-logout');
  return { __forceLogout: true };
}

function getBackendLaunchCmd(): [string, string[], boolean] {
  const packaged = path.join(
    process.resourcesPath ?? '',
    'backend',
    BACKEND_BIN,
  );
  if (fs.existsSync(packaged)) {
    if (IS_MAC) {
      try { fs.chmodSync(packaged, 0o755); } catch { /* best effort */ }
    }
    return [packaged, [], false];
  }

  const devBinDir = IS_MAC ? 'backend-macos' : 'backend-windows';
  const devExe = path.resolve(
    __dirname,
    `../../../${devBinDir}/dist/enterprise_monitor_backend/${BACKEND_BIN}`,
  );
  if (fs.existsSync(devExe)) {
    if (IS_MAC) {
      try { fs.chmodSync(devExe, 0o755); } catch { /* best effort */ }
    }
    return [devExe, [], false];
  }

  const devScriptDir = IS_MAC ? 'backend-macos' : 'backend-windows';
  const devScript = path.resolve(__dirname, `../../../${devScriptDir}/main.py`);
  if (fs.existsSync(devScript)) {
    console.log('[main] No binary found — launching via python directly (dev mode)');
    const python = IS_MAC ? 'python3' : 'python';
    return [python, [devScript], true];
  }

  throw new Error(
    `Backend not found. Tried:\n` +
    `  ${packaged}\n  ${devExe}\n  ${devScript}`,
  );
}

// ─── Port Handshake ───────────────────────────────────────────────────────────
function deleteStalePortInfo(): void {
  if (fs.existsSync(PORT_INFO)) {
    try {
      fs.unlinkSync(PORT_INFO);
      console.log('[main] Deleted stale port.info');
    } catch (err) {
      console.warn('[main] Could not delete stale port.info:', err);
    }
  }
}

function waitForPortInfo(timeoutMs = 30_000, intervalMs = 250): Promise<number> {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;

    const poll = () => {
      if (backendExited) {
        if (backendExitCode === 77) {
          return reject(new Error(
            `[main] Another backend is already running (exit code 77). ` +
            `Kill the other python/backend process first.`,
          ));
        }
        return reject(new Error(
          `[main] Backend exited early (code=${backendExitCode}) before writing port.info. ` +
          `Check ${path.join(EM_DIR, 'logs', 'backend.log')} for errors.`,
        ));
      }

      if (fs.existsSync(PORT_INFO)) {
        try {
          const raw = fs.readFileSync(PORT_INFO, 'utf-8').trim();
          const port = parseInt(raw, 10);
          if (!isNaN(port) && port > 0) {
            console.log(`[main] Backend port acquired from port.info: ${port}`);
            return resolve(port);
          }
        } catch {
          // File appeared but couldn't be read yet — try again
        }
      }

      if (Date.now() >= deadline) {
        return reject(
          new Error(
            `[main] Timed out after ${timeoutMs}ms waiting for backend port.info. ` +
            `Check ${path.join(EM_DIR, 'logs', 'backend.log')} for errors.`,
          ),
        );
      }

      setTimeout(poll, intervalMs);
    };

    poll();
  });
}

// ─── Backend spawn ────────────────────────────────────────────────────────────
function spawnBackend(): ChildProcess {
  const [cmd, args, isDevMode] = getBackendLaunchCmd();
  console.log(`[main] Spawning backend: ${cmd} ${args.join(' ')}`);

  fs.mkdirSync(EM_DIR, { recursive: true });

  const child = spawn(cmd, args, {
    detached: false,
    stdio: isDevMode ? ['ignore', 'pipe', 'pipe'] : 'ignore',
    windowsHide: true,
  });

  if (isDevMode && child.stdout) {
    child.stdout.on('data', (data: Buffer) => {
      const lines = data.toString().trim();
      if (lines) console.log(`[backend:stdout] ${lines}`);
    });
  }
  if (isDevMode && child.stderr) {
    child.stderr.on('data', (data: Buffer) => {
      const lines = data.toString().trim();
      if (lines) console.error(`[backend:stderr] ${lines}`);
    });
  }

  child.on('error', (err) => {
    console.error('[main] Backend process error:', err.message);
    backendExited = true;
    backendExitCode = -1;
    trayManager?.setBackendStatus(false);
  });

  child.on('exit', (code, signal) => {
    backendExited = true;
    backendExitCode = code;
    if (!backendKilled) {
      console.error(`[main] Backend exited unexpectedly: code=${code} signal=${signal}`);
      trayManager?.setBackendStatus(false);
    }
    backendProcess = null;
  });

  console.log(`[main] Backend spawned (pid=${child.pid})`);
  return child;
}

async function killBackend(): Promise<void> {
  if (!backendProcess || backendKilled) return;
  backendKilled = true;

  if (apiClient) {
    console.log('[main] Requesting graceful backend shutdown via /api/internal/shutdown...');
    try {
      await Promise.race([
        apiClient.post('/api/internal/shutdown', {}),
        new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 3000)),
      ]);
      console.log('[main] Backend acknowledged graceful shutdown');
      await new Promise<void>((resolve) => {
        const check = setInterval(() => {
          if (backendExited) { clearInterval(check); resolve(); }
        }, 200);
        setTimeout(() => { clearInterval(check); resolve(); }, 2000);
      });
    } catch (err: any) {
      console.warn('[main] Graceful shutdown failed or timed out:', err.message);
    }
  }

  if (backendProcess && !backendExited) {
    console.log('[main] Force-killing backend process...');
    try {
      backendProcess.kill('SIGTERM');
    } catch (err) {
      console.warn('[main] kill(SIGTERM) failed:', err);
      try { backendProcess.kill('SIGKILL'); } catch { /* already dead */ }
    }
  }

  if (fs.existsSync(PORT_INFO)) {
    try { fs.unlinkSync(PORT_INFO); } catch { /* best effort */ }
  }
}

// ─── 3-Layer Rollback: Database Snapshot Helper ───────────────────────────────
// Layer 3: Snapshot the SQLite database BEFORE killBackend() when an update
// is pending. This ensures the DB is backed up before the new Python backend
// touches it on a new version boot.
function createDatabaseSnapshot(): void {
  const dbPath = path.join(EM_DIR, 'enterprise_monitor.db');
  const backupDir = path.join(EM_DIR, 'backup');
  const snapshotPath = path.join(backupDir, `enterprise_monitor_pre_v${app.getVersion()}.db`);

  if (fs.existsSync(dbPath)) {
    try {
      fs.mkdirSync(backupDir, { recursive: true });
      fs.copyFileSync(dbPath, snapshotPath);
      console.log(`[rollback] Database snapshot saved: ${snapshotPath}`);
    } catch (err: any) {
      console.error(`[rollback] Failed to create database snapshot: ${err.message}`);
    }
  } else {
    console.log('[rollback] No database found to snapshot — skipping');
  }
}

// ─── Window ───────────────────────────────────────────────────────────────────
function createWindow(showOnReady = true): void {
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
    if (showOnReady) {
      mainWindow?.show();
    }
  });

  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow?.hide();
    }
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

function getMainWindow(): BrowserWindow | null { return mainWindow; }

function showMainWindow(): void {
  if (!mainWindow) createWindow(true);
  mainWindow?.show();
  mainWindow?.focus();
}

// ─── Idle Auto-Pause Tracker ──────────────────────────────────────────────────
/**
 * Polls powerMonitor.getSystemIdleTime() every 10 seconds.
 *
 * Auto-PAUSE  — fires when idleSeconds ≥ IDLE_PAUSE_THRESHOLD_SECS and we
 *               are not already auto-paused.  Calls the internal (no-JWT)
 *               endpoint so an expired token can never trigger a force-logout.
 *
 * Auto-RESUME — fires when idleSeconds < IDLE_PAUSE_THRESHOLD_SECS and we
 *               were the ones who caused the pause (isAutoPaused === true).
 *               This guard ensures a manual admin pause is never reversed by
 *               someone just moving the mouse.
 *
 * ⚙️  To change the timeout: edit IDLE_PAUSE_THRESHOLD_SECS at the top of
 *     this file.  No backend changes needed.
 */
function startIdleTracker(): void {
  const POLL_MS = 10_000; // check every 10 seconds

  setInterval(async () => {
    if (!apiClient || !backendProcess) return; // backend not ready yet

    const idleSeconds = powerMonitor.getSystemIdleTime();

    if (idleSeconds >= IDLE_PAUSE_THRESHOLD_SECS && !isAutoPaused) {
      isAutoPaused = true;
      console.log(`[idle-tracker] User idle for ${idleSeconds}s — auto-pausing monitoring`);
      try {
        await apiClient.post('/api/internal/monitoring/pause', {});
      } catch (err: any) {
        // Non-fatal: backend may be temporarily unavailable. Log and retry next cycle.
        console.warn('[idle-tracker] Auto-pause request failed (will retry):', err.message);
        isAutoPaused = false; // Reset so the next poll tries again
      }
      return;
    }

    if (idleSeconds < IDLE_PAUSE_THRESHOLD_SECS && isAutoPaused) {
      isAutoPaused = false;
      console.log(`[idle-tracker] User returned (idle=${idleSeconds}s) — auto-resuming monitoring`);
      try {
        await apiClient.post('/api/internal/monitoring/resume', {});
      } catch (err: any) {
        console.warn('[idle-tracker] Auto-resume request failed (will retry):', err.message);
        isAutoPaused = true; // Reset so the next poll tries again
      }
    }
  }, POLL_MS);

  console.log(`[idle-tracker] Started — threshold: ${IDLE_PAUSE_THRESHOLD_SECS}s (${IDLE_PAUSE_THRESHOLD_SECS / 60} min), poll: ${POLL_MS / 1000}s`);
}
// ─────────────────────────────────────────────────────────────────────────────

// ─── PATCH D — Auto-Updater Setup ────────────────────────────────────────────
function setupAutoUpdater(): void {
  if (!app.isPackaged) {
    console.log('[updater] Development mode — auto-update is disabled');
    return;
  }

  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = false;
  autoUpdater.allowPrerelease = false;

  autoUpdater.on('checking-for-update', () => {
    console.log('[updater] Checking for updates...');
  });

  autoUpdater.on('update-available', (info: any) => {
    console.log(`[updater] Update available: v${info.version} — downloading silently`);
    updatePendingVersion = info.version;
    mainWindow?.webContents.send('update-available', {
      version: info.version,
      releaseNotes: typeof info.releaseNotes === 'string' ? info.releaseNotes : '',
    });
  });

  autoUpdater.on('download-progress', (progress: any) => {
    mainWindow?.webContents.send('download-progress', {
      percent: Math.round(progress.percent),
      bytesPerSecond: Math.round(progress.bytesPerSecond),
      total: progress.total,
    });
  });

  autoUpdater.on('update-downloaded', (info: any) => {
    console.log(`[updater] Update downloaded and verified: v${info.version}`);
    updateDownloaded = true;
    updatePendingVersion = info.version;
    showMainWindow();
    mainWindow?.webContents.send('update-downloaded', { version: info.version });
  });

  autoUpdater.on('update-not-available', () => {
    console.log('[updater] Application is up to date.');
  });

  autoUpdater.on('error', (err: any) => {
    console.error('[updater] Update error:', err.message);
    // Notify renderer about download failure so admin is aware
    mainWindow?.webContents.send('update-error', { message: err.message });
  });

  // Startup check (delayed 30s for backend safety)
  setTimeout(() => {
    autoUpdater.checkForUpdates().catch((err: any) => {
      console.error('[updater] Startup check failed:', err.message);
    });
  }, 30_000);

  // Periodic check every 4 hours
  setInterval(() => {
    autoUpdater.checkForUpdates().catch((err: any) => {
      console.error('[updater] Scheduled check failed:', err.message);
    });
  }, 4 * 60 * 60 * 1000);

  console.log('[updater] Auto-update configured — GitHub Releases, Windows only');
}
// ─────────────────────────────────────────────────────────────────────────────

// ─── App lifecycle ────────────────────────────────────────────────────────────
const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    } else {
      createWindow(true);
    }
  });

  app.whenReady().then(async () => {
    app.setLoginItemSettings({
      openAtLogin: true,
      path: app.getPath('exe'),
      args: ['--hidden'],
    });

    // Self-heal: remove stale Task Scheduler entry from old installs (Windows only)
    if (!IS_MAC) {
      try {
        const { execSync } = require('child_process');
        execSync('schtasks /delete /tn "EnterpriseMonitorBackend" /f', {
          stdio: 'ignore',
          windowsHide: true,
        });
        console.log('[main] Removed stale Task Scheduler entry "EnterpriseMonitorBackend"');
      } catch {
        // Not found or no admin rights — that is fine
      }
    }

    // ─── PATCH E (Part 1) — Post-update detection ─────────────────────────
    const pendingUpdateVersion = store.get('pendingUpdateVersion') as string | undefined;
    const previousAppVersion = store.get('currentVersionBeforeUpdate') as string | undefined;
    const justUpdated = !!pendingUpdateVersion && pendingUpdateVersion === app.getVersion();
    if (justUpdated) {
      store.delete('pendingUpdateVersion');
      store.delete('currentVersionBeforeUpdate');
      console.log(`[updater] Post-update restart detected: v${previousAppVersion} → v${app.getVersion()}`);
    }

    // ─── Layer 2 Rollback: Binary Integrity Check ─────────────────────────
    // After an update, verify critical files exist. If backend binary is
    // missing (corrupted/failed NSIS extraction), attempt auto-restore
    // from shadow backup created by installer.nsh.
    if (justUpdated && app.isPackaged) {
      const backendPath = path.join(process.resourcesPath ?? '', 'backend', BACKEND_BIN);
      const backupPath = path.join(EM_DIR, 'backup', BACKEND_BIN);

      if (!fs.existsSync(backendPath)) {
        console.error('[rollback] Backend binary missing after update!');
        if (fs.existsSync(backupPath)) {
          try {
            const backendDir = path.dirname(backendPath);
            fs.mkdirSync(backendDir, { recursive: true });
            fs.copyFileSync(backupPath, backendPath);
            console.log('[rollback] Backend restored from shadow backup successfully');
          } catch (restoreErr: any) {
            console.error(`[rollback] Shadow restore failed: ${restoreErr.message}`);
            // Will be caught by spawnBackend() failure path
          }
        } else {
          console.error('[rollback] No shadow backup available — manual reinstall required');
        }
      } else {
        console.log('[rollback] Post-update integrity check passed — backend binary exists');
        // Clean up old shadow backup (successful update, no longer needed)
        try {
          if (fs.existsSync(backupPath)) {
            fs.unlinkSync(backupPath);
            console.log('[rollback] Old shadow backup cleaned up');
          }
        } catch { /* best effort */ }
      }
    }
    // ──────────────────────────────────────────────────────────────────────

    // Delete stale port.info (race-condition hardening)
    deleteStalePortInfo();

    // Spawn backend as child
    try {
      backendProcess = spawnBackend();
    } catch (err: any) {
      console.error('[main] FATAL: Could not spawn backend:', err.message);
    }

    // Pre-initialize apiClient and IPC handlers to prevent race conditions 
    // where macOS `activate` opens a window (and triggers renderer IPCs) 
    // before the long waitForPortInfo (TCC prompts) resolves.
    apiClient = new ApiClient(`http://127.0.0.1:0`);
    setupIpcHandlers();

    // Wait for port.info (backend writes it on startup)
    let port = 51235;
    try {
      port = await waitForPortInfo(30_000);
    } catch (err: any) {
      console.error('[main] Port handshake failed:', err.message);

      if (backendExitCode === 77) {
        console.log('[main] Another backend instance detected. Attempting to adopt it...');
        try {
          const { execSync } = require('child_process');
          if (IS_MAC) {
            execSync('pkill -f enterprise_monitor_backend || true', { stdio: 'ignore' });
          } else {
            execSync('taskkill /F /IM "enterprise_monitor_backend.exe"', { stdio: 'ignore', windowsHide: true });
          }
          console.log('[main] Killed orphan backend. Retrying spawn...');
        } catch { /* already dead */ }

        await new Promise(resolve => setTimeout(resolve, 2000));

        backendExited = false;
        backendExitCode = null;
        backendKilled = false;
        backendProcess = null;

        try {
          backendProcess = spawnBackend();
          port = await waitForPortInfo(30_000);
        } catch (retryErr: any) {
          console.error('[main] Retry also failed:', retryErr.message);
          console.warn('[main] Falling back to port 51235 (for development only)');
        }
      } else {
        console.warn('[main] Falling back to port 51235 (for development only)');
      }
    }

    apiClient = new ApiClient(`http://127.0.0.1:${port}`);
    console.log(`[main] ApiClient connected to http://127.0.0.1:${port}`);

    trayManager = new TrayManager(
      () => showMainWindow(),
      apiClient,
      getMainWindow,
    );

    const isHiddenStartup = process.argv.includes('--hidden') || (IS_MAC && app.getLoginItemSettings().wasOpenedAsHidden);
    createWindow(!isHiddenStartup);
    startBackendHealthCheck();
    startIdleTracker(); // Silent auto-pause when user is idle for IDLE_PAUSE_THRESHOLD_SECS

    // ─── PATCH E (Part 2) — Send post-update notification to renderer ─────
    if (justUpdated) {
      setTimeout(() => {
        mainWindow?.webContents.send('update-complete', {
          version: app.getVersion(),
          previousVersion: previousAppVersion ?? 'unknown',
        });
      }, 3000);
    }

    // ─── PATCH E (Part 3) — Call setupAutoUpdater ─────────────────────────
    if (!IS_MAC) {
      setupAutoUpdater();
    } else {
      console.log('[updater] Auto-update skipped on macOS (not configured)');
    }

    powerMonitor.on('shutdown', () => {
      console.log('[main] powerMonitor: system shutdown/restart/logout detected');
      isSystemShutdown = true;
    });
  });
}

// ─── PATCH C — Modified before-quit handler ───────────────────────────────────
// Helper: trigger pending update install from any quit path
function installPendingUpdateOnQuit(): boolean {
  if (updateDownloaded && updatePendingVersion) {
    console.log(`[updater] Pending update v${updatePendingVersion} — installing before quit...`);
    store.set('pendingUpdateVersion', updatePendingVersion);
    store.set('currentVersionBeforeUpdate', app.getVersion());
    isSystemUpdate = true;
    autoUpdater.quitAndInstall(true, true);
    return true;
  }
  return false;
}

app.on('before-quit', (event) => {
  // Update install path — backend already killed in IPC handler
  if (isSystemUpdate) {
    isQuitting = true;
    return;
  }

  if (allowAuthenticatedQuit) {
    isQuitting = true;
    killBackend().catch(() => { });
    return;
  }

  if (isSystemShutdown) {
    console.log('[main] System shutdown/restart detected — allowing quit without authentication.');
    isQuitting = true;
    killBackend().catch(() => { });
    installPendingUpdateOnQuit();
    return;
  }

  if (backendExited || !backendProcess) {
    console.log('[main] Backend is not running — allowing quit without authentication.');
    isQuitting = true;
    installPendingUpdateOnQuit();
    return;
  }

  event.preventDefault();
  console.log('[main] Quit blocked — authentication required. Use the app UI to quit.');

  if (mainWindow) {
    mainWindow.show();
    mainWindow.focus();
    mainWindow.webContents.send('show-quit-dialog');
  }
});
// ─────────────────────────────────────────────────────────────────────────────

app.on('window-all-closed', () => { /* no-op — tray keeps app alive */ });

app.on('activate', () => {
  if (mainWindow) {
    mainWindow.show();
    mainWindow.focus();
  } else {
    createWindow(true);
  }
});

// ─── Backend health check ─────────────────────────────────────────────────────
function startBackendHealthCheck(): void {
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

// ─── IPC Handlers ─────────────────────────────────────────────────────────────
function setupIpcHandlers(): void {

  // ── Auth ──────────────────────────────────────────────────────────────────
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

        const firstRunDone = store.get('firstRunComplete') as boolean | undefined;
        if (!firstRunDone) {
          setTimeout(() => mainWindow?.webContents.send('first-run-setup'), 800);
        }
        return { success: true, token: response.data.token };
      }
      return { success: false, error: response.data.error || 'Invalid credentials' };
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  });

  ipcMain.handle('app:firstRunComplete', () => { store.set('firstRunComplete', true); });

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
      const { exp } = JSON.parse(
        Buffer.from(payloadB64, 'base64').toString('utf-8'),
      ) as { exp?: number };
      if (!exp) return { remainingMs: 0 };
      return { remainingMs: Math.max(0, exp * 1000 - Date.now()) };
    } catch {
      return { remainingMs: 0 };
    }
  });

  ipcMain.handle('auth:getSecurityQuestions', async (_event, username: string) => {
    try {
      const response = await apiClient.get(
        `/api/auth/security-questions?username=${encodeURIComponent(username)}`,
      );
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

  // ── Statistics & Timeline ─────────────────────────────────────────────────
  ipcMain.handle('api:getStatistics', async (_event, params: { date?: string } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/statistics', token, params);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  ipcMain.handle('api:getActivityStats', async (_event, params: { start: string; end: string }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/stats/activity', token, params);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  ipcMain.handle('api:getTimelineData', async (_event, params: { date: string }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/stats/timeline', token, params);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  // ── Screenshots ───────────────────────────────────────────────────────────
  ipcMain.handle('api:getScreenshots', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/screenshots', token, params);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  ipcMain.handle('api:getScreenshotStatus', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/monitoring/screenshot/status', token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { recording: false, is_active: false };
    }
  });

  ipcMain.handle('api:toggleScreenshotCapturing', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/monitoring/screenshot/toggle', {}, token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { success: false, error: error.message };
    }
  });

  // ── App logs ──────────────────────────────────────────────────────────────
  ipcMain.handle('api:getAppLogs', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/apps', token, params);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  // ── Key logs ──────────────────────────────────────────────────────────────
  ipcMain.handle('api:getKeyLogs', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/keylogs', token, params);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  // ── Browser logs ──────────────────────────────────────────────────────────
  ipcMain.handle('api:getBrowserLogs', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/browser', token, params);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  // ── Clipboard logs ────────────────────────────────────────────────────────
  ipcMain.handle('api:getClipboardLogs', async (_event, params: { limit?: number; offset?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/clipboard', token, params);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  // ── Video recordings ──────────────────────────────────────────────────────
  ipcMain.handle('api:getVideoRecordings', async (_event, params: { limit?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/videos', token, params);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  // ── Monitoring controls ───────────────────────────────────────────────────
  ipcMain.handle('api:getMonitoringStatus', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/monitoring/status', token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { error: error.message };
    }
  });

  ipcMain.handle('api:setMonitoringStatus', async (_event, payload: Record<string, boolean>) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/monitoring/status', payload, token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { success: false, error: error.message };
    }
  });

  // ── Config ────────────────────────────────────────────────────────────────
  ipcMain.handle('api:getConfig', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/config', token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  ipcMain.handle('api:updateConfig', async (_event, payload: Record<string, unknown>) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/config', payload, token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  ipcMain.handle('api:getIdentity', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/config/identity', token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      console.warn('[main] Failed to fetch identity config:', error.message);
      return {};
    }
  });

  ipcMain.handle('api:updateIdentity', async (_event, payload: Record<string, string>) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/config/identity', payload, token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  ipcMain.handle('api:confirmCredential', async (_event, payload: { device_alias: string; user_alias: string; location: string }) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/config/confirm-credential', payload, token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { success: false, error: error.message };
    }
  });

  ipcMain.handle('api:getCredentialStatus', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/config/credential-status', token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { confirmed: false, drifted: false, needs_confirmation: true };
    }
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
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { success: false, error: error.message };
    }
  });

  // ── Sync ──────────────────────────────────────────────────────────────────
  ipcMain.handle('api:getSyncStatus', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/sync/status', token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { last_sync: null, last_error: null, is_syncing: false };
    }
  });

  ipcMain.handle('api:triggerSync', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/sync/trigger', {}, token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { success: false, error: error.message };
    }
  });

  // ── File / folder ─────────────────────────────────────────────────────────
  ipcMain.handle('app:openFolder', async (_event, filepath: string) => {
    try {
      const normalised = path.normalize(filepath);
      if (fs.existsSync(normalised)) {
        shell.showItemInFolder(normalised);
      } else {
        const parent = path.dirname(normalised);
        if (fs.existsSync(parent)) {
          await shell.openPath(parent);
        } else {
          const root = path.join(EM_DIR, 'Videos');
          fs.mkdirSync(root, { recursive: true });
          await shell.openPath(root);
        }
      }
    } catch (err: any) {
      console.error('app:openFolder error:', err.message);
    }
  });

  // ── Pause / Resume monitoring ──────────────────────────────────────────────
  ipcMain.handle('api:pauseMonitoring', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/monitoring/pause', {}, token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { success: false, error: error.message };
    }
  });

  ipcMain.handle('api:resumeMonitoring', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/monitoring/resume', {}, token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { success: false, error: error.message };
    }
  });

  // ── Video ─────────────────────────────────────────────────────────────────
  ipcMain.handle('api:getVideoStatus', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/monitoring/video/status', token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { recording: false, is_active: false };
    }
  });

  ipcMain.handle('api:getVideos', async (_event, params: { limit?: number } = {}) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.get('/api/data/videos', token, params);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  ipcMain.handle('api:toggleVideoRecording', async () => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/monitoring/video/toggle', {}, token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      return { success: false, error: error.message };
    }
  });

  // ── Config (setConfig alias) ──────────────────────────────────────────────
  ipcMain.handle('api:setConfig', async (_event, payload: Record<string, unknown>) => {
    try {
      const token = store.get('authToken') as string;
      const response = await apiClient.post('/api/config', payload, token);
      return response.data;
    } catch (error: any) {
      if (is401(error)) return handleAuthExpired();
      throw new Error(error.message);
    }
  });

  // ── Verify credentials (quit dialog) ─────────────────────────────────────
  ipcMain.handle('auth:verifyOnly', async (_event, credentials: { username: string; password: string }) => {
    try {
      const response = await apiClient.post('/api/auth/login', credentials);
      if (response.data.success) {
        return { success: true };
      }
      return { success: false, error: response.data.error || 'Invalid credentials' };
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  });

  // ─── PATCH F — Modified app:quit + new update IPC handlers ────────────────
  ipcMain.handle('app:quit', async () => {
    console.log('[main] Authenticated quit requested — graceful backend shutdown...');
    allowAuthenticatedQuit = true;
    isQuitting = true;

    if (updateDownloaded && updatePendingVersion) {
      // Layer 3: Snapshot database before killing backend
      createDatabaseSnapshot();
    }

    await killBackend();

    if (updateDownloaded && updatePendingVersion) {
      console.log(`[main] Update v${updatePendingVersion} ready — installing on quit...`);
      store.set('pendingUpdateVersion', updatePendingVersion);
      store.set('currentVersionBeforeUpdate', app.getVersion());
      isSystemUpdate = true;
      autoUpdater.quitAndInstall(true, true);
    } else {
      app.quit();
    }
  });

  ipcMain.handle('app:installUpdate', async () => {
    if (!updateDownloaded || !updatePendingVersion) {
      return { success: false, error: 'No update has been downloaded yet' };
    }
    console.log(`[updater] Admin initiated immediate install of v${updatePendingVersion}`);
    isQuitting = true;
    allowAuthenticatedQuit = true; // Belt-and-suspenders: prevents before-quit from blocking

    // Layer 3: Snapshot database before killing backend
    createDatabaseSnapshot();

    await killBackend();
    store.set('pendingUpdateVersion', updatePendingVersion);
    store.set('currentVersionBeforeUpdate', app.getVersion());
    isSystemUpdate = true;
    autoUpdater.quitAndInstall(true, true);
    return { success: true };
  });

  ipcMain.handle('app:deferUpdate', () => {
    console.log('[updater] Update deferred — will install on next authenticated quit');
    return { success: true };
  });

  ipcMain.handle('app:checkForUpdates', async () => {
    if (!app.isPackaged) {
      return { success: false, error: 'Auto-update only works in packaged (built) mode' };
    }
    try {
      await autoUpdater.checkForUpdates();
      return { success: true };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  });

  // ── App version ───────────────────────────────────────────────────────────
  ipcMain.handle('app:getVersion', () => app.getVersion());
  // ─────────────────────────────────────────────────────────────────────────
}