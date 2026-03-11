/**
 * electron-app/src/main/main.ts
 *
 * MASTER / CHILD PROCESS ARCHITECTURE
 * ─────────────────────────────────────
 * Electron is the Master. It owns the full process lifecycle:
 *
 *   1. DELETE stale port.info (race-condition fix — see §Port Handshake below)
 *   2. SPAWN backend.exe as a child process via child_process.spawn
 *   3. POLL for port.info to appear (backend writes it atomically on startup)
 *   4. READ the port, construct ApiClient with the dynamic URL
 *   5. On authenticated QUIT: send SIGTERM to child → child self-cleans → Electron exits
 *   6. On unexpected Electron exit: before-quit fires kill() — no zombie processes
 *
 * §Port Handshake (race-condition hardening):
 *   Problem:  Old port.info from yesterday → Electron reads it before Python writes
 *             the new one → connects to wrong port (or a port that is now taken).
 *   Solution: fs.unlinkSync() on port.info BEFORE spawning the backend.
 *             We then poll for the file's re-appearance with a 30-second timeout.
 *             The backend writes port.info atomically (write-to-.tmp, then rename),
 *             so Electron can never read a partial file.
 *
 * §Backend location (packaged):
 *   PyInstaller onedir output is copied to:
 *     <app>/resources/backend/enterprise_monitor_backend.exe
 *   In development (npm run dev), the exe path falls back to the local dist/ folder.
 */

import { app, BrowserWindow, ipcMain, shell, powerMonitor } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { spawn, ChildProcess } from 'child_process';
import { TrayManager } from './tray';
import { ApiClient } from './api-client';
import Store from 'electron-store';

const store = new Store();

// ── Process state ─────────────────────────────────────────────────────────────
let mainWindow: BrowserWindow | null = null;
let trayManager: TrayManager | null = null;
let apiClient: ApiClient;                    // initialised after port handshake
let backendProcess: ChildProcess | null = null;
let isQuitting = false;
let allowAuthenticatedQuit = false;   // only set true after authenticated app:quit IPC
let isSystemShutdown = false;         // set when OS is shutting down / restarting / logging out
let backendKilled = false;
let backendExited = false;     // set when child exits before port handshake completes
let backendExitCode: number | null = null;

// ── 401 helpers ───────────────────────────────────────────────────────────────

/** True when an axios error is an HTTP 401 (token expired / invalid). */
function is401(error: any): boolean {
  return error?.response?.status === 401;
}

/**
 * Clear stored token, update tray, and tell the renderer to force-logout.
 * Returns a sentinel object the renderer can also detect from the IPC return.
 */
function handleAuthExpired(): { __forceLogout: true } {
  store.delete('authToken');
  trayManager?.setAuthStatus(false);
  mainWindow?.webContents.send('force-logout');
  return { __forceLogout: true };
}

// ── Paths ─────────────────────────────────────────────────────────────────────
const IS_MAC = process.platform === 'darwin';

const EM_DIR = IS_MAC
  ? path.join(os.homedir(), 'Library', 'Application Support', 'EnterpriseMonitor')
  : path.join(
    process.env.LOCALAPPDATA ?? path.join(os.homedir(), 'AppData', 'Local'),
    'EnterpriseMonitor',
  );

const PORT_INFO = path.join(EM_DIR, 'port.info');

/** Binary name differs per platform — no .exe on macOS. */
const BACKEND_BIN = IS_MAC
  ? 'enterprise_monitor_backend'
  : 'enterprise_monitor_backend.exe';

/** Returns [command, args, isDevMode] to launch the backend. */
function getBackendLaunchCmd(): [string, string[], boolean] {
  // 1. Packaged app: binary sits in resources/backend/
  const packaged = path.join(
    process.resourcesPath ?? '',
    'backend',
    BACKEND_BIN,
  );
  if (fs.existsSync(packaged)) {
    // macOS: ensure binary is executable after extraction
    if (IS_MAC) {
      try { fs.chmodSync(packaged, 0o755); } catch { /* best effort */ }
    }
    return [packaged, [], false];
  }

  // 2. Dev: compiled binary exists
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

  // 3. Dev fallback: run Python source directly (no PyInstaller build needed)
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

/**
 * Delete any stale port.info BEFORE spawning the backend.
 * This is the race-condition fix: ensures Electron never reads yesterday's port.
 */
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

/**
 * Poll for port.info to appear, then read and return the port number.
 * The backend writes port.info atomically (tmp → rename), so we never
 * read a partial file.
 *
 * @param timeoutMs  Maximum wait in milliseconds (default 30 s)
 * @param intervalMs Poll interval in milliseconds (default 250 ms)
 */
function waitForPortInfo(timeoutMs = 30_000, intervalMs = 250): Promise<number> {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;

    const poll = () => {
      // ── Early exit: backend already died ──────────────────────────────
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

/**
 * Spawn the Python backend as a child process.
 * Electron is the Master — the backend is fully subordinate:
 *   - stdio: 'ignore'  → no pipes; all output goes to backend.log
 *   - detached: false  → child dies with parent if Electron crashes hard
 *
 * Returns the ChildProcess handle so we can kill it cleanly on quit.
 */
function spawnBackend(): ChildProcess {
  const [cmd, args, isDevMode] = getBackendLaunchCmd();
  console.log(`[main] Spawning backend: ${cmd} ${args.join(' ')}`);

  // Ensure EM_DIR exists (backend also creates it, but we may need it for port.info)
  fs.mkdirSync(EM_DIR, { recursive: true });

  // In dev mode, pipe stderr so we see Python errors in Electron's console.
  // In packaged mode, keep stdio:'ignore' — backend logs to file only.
  const child = spawn(cmd, args, {
    detached: false,
    stdio: isDevMode ? ['ignore', 'pipe', 'pipe'] : 'ignore',
    windowsHide: true,
  });

  // ── Dev-mode diagnostics: stream backend output to Electron console ──────
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
      // Unexpected exit — log and update tray
      console.error(`[main] Backend exited unexpectedly: code=${code} signal=${signal}`);
      trayManager?.setBackendStatus(false);
    }
    backendProcess = null;
  });

  console.log(`[main] Backend spawned (pid=${child.pid})`);
  return child;
}

/**
 * Gracefully terminate the backend child process.
 * Strategy:
 *   1. Try POST /api/shutdown — backend stops services, flushes data, exits.
 *   2. If that fails or times out (3 s), fall back to TerminateProcess.
 *
 * Returns a Promise so callers can await full shutdown before app.quit().
 */
async function killBackend(): Promise<void> {
  if (!backendProcess || backendKilled) return;
  backendKilled = true;

  // ── Step 1: Graceful shutdown via HTTP ────────────────────────────────────
  const token = store.get('authToken') as string | undefined;
  if (token && apiClient) {
    console.log('[main] Requesting graceful backend shutdown via /api/shutdown...');
    try {
      await Promise.race([
        apiClient.post('/api/shutdown', {}, token),
        new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 3000)),
      ]);
      console.log('[main] Backend acknowledged graceful shutdown');
      // Give the backend 2 s to actually exit
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

  // ── Step 2: Force-kill if still alive ─────────────────────────────────────
  if (backendProcess && !backendExited) {
    console.log('[main] Force-killing backend process...');
    try {
      backendProcess.kill('SIGTERM');  // = TerminateProcess on Windows
    } catch (err) {
      console.warn('[main] kill(SIGTERM) failed:', err);
      try { backendProcess.kill('SIGKILL'); } catch { /* already dead */ }
    }
  }

  // Clean up port.info so the next launch starts fresh
  if (fs.existsSync(PORT_INFO)) {
    try { fs.unlinkSync(PORT_INFO); } catch { /* best effort */ }
  }
}

// ─── Window ───────────────────────────────────────────────────────────────────

function createWindow(): void {
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

  mainWindow.once('ready-to-show', () => { mainWindow?.show(); });

  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow?.hide();  // X button → hide to tray
    }
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

function getMainWindow(): BrowserWindow | null { return mainWindow; }

function showMainWindow(): void {
  if (!mainWindow) createWindow();
  mainWindow?.show();
  mainWindow?.focus();
}

// ─── App lifecycle ────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  app.setLoginItemSettings({ openAtLogin: true, path: app.getPath('exe') });

  // ── Self-heal: remove stale Task Scheduler entry from old installs (Windows only)
  if (!IS_MAC) {
    try {
      const { execSync } = require('child_process');
      execSync('schtasks /delete /tn "EnterpriseMonitorBackend" /f', {
        stdio: 'ignore',
        windowsHide: true,
      });
      console.log('[main] Removed stale Task Scheduler entry "EnterpriseMonitorBackend"');
    } catch {
      // Not found or no admin rights — that's fine
    }
  }

  // ── Step 1: Delete stale port.info (race-condition hardening) ──────────────
  deleteStalePortInfo();

  // ── Step 2: Spawn backend as child ─────────────────────────────────────────
  try {
    backendProcess = spawnBackend();
  } catch (err: any) {
    console.error('[main] FATAL: Could not spawn backend:', err.message);
    // Continue loading UI — it will show "backend offline" state in the tray
  }

  // ── Step 3: Wait for port.info (backend writes it on startup) ───────────────
  let port = 51235; // fallback only if everything else fails
  try {
    port = await waitForPortInfo(30_000);
  } catch (err: any) {
    console.error('[main] Port handshake failed:', err.message);

    // ── Fallback: another backend is running (exit code 77) ──────────────────
    // The other backend wrote port.info, but we deleted it in Step 1.
    // Try to connect by re-reading whatever port.info the other backend has,
    // or if it doesn't exist, kill the orphan and retry.
    if (backendExitCode === 77) {
      console.log('[main] Another backend instance detected. Attempting to adopt it...');

      // Kill the orphan process so we can start fresh
      try {
        const { execSync } = require('child_process');
        if (IS_MAC) {
          execSync('pkill -f enterprise_monitor_backend || true', {
            stdio: 'ignore',
          });
        } else {
          execSync('taskkill /F /IM "enterprise_monitor_backend.exe"', {
            stdio: 'ignore',
            windowsHide: true,
          });
        }
        console.log('[main] Killed orphan backend. Retrying spawn...');
      } catch {
        // May fail if already dead — that's OK
      }

      // Wait briefly for the orphan to release the mutex
      await new Promise(resolve => setTimeout(resolve, 2000));

      // Reset state and retry
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

  // ── Step 4: Construct ApiClient with the dynamic port ──────────────────────
  apiClient = new ApiClient(`http://127.0.0.1:${port}`);
  console.log(`[main] ApiClient connected to http://127.0.0.1:${port}`);

  // ── Step 5: Boot UI ────────────────────────────────────────────────────────
  trayManager = new TrayManager(
    () => showMainWindow(),
    apiClient,
    getMainWindow,
  );

  createWindow();
  setupIpcHandlers();
  startBackendHealthCheck();

  // ── Detect system shutdown / restart / logout ──────────────────────────────
  // powerMonitor.on('shutdown') fires when the OS is about to power off,
  // restart, or when the user logs out. On macOS this is driven by
  // NSWorkspaceWillPowerOffNotification which fires BEFORE the app receives
  // its quit signal. We set a flag so before-quit can skip auth.
  powerMonitor.on('shutdown', () => {
    console.log('[main] powerMonitor: system shutdown/restart/logout detected');
    isSystemShutdown = true;
  });
});

// ── macOS quit-bypass protection ──────────────────────────────────────────────
// On macOS, Cmd+Q and Dock → Quit both fire 'before-quit'. We block quit
// attempts unless:
//   (a) allowAuthenticatedQuit has been set by the app:quit IPC handler, OR
//   (b) the system is shutting down / restarting / logging out, OR
//   (c) the backend is dead/unreachable — blocking quit when the user CAN'T
//       authenticate creates a deadlock (can't quit, can't uninstall).
app.on('before-quit', (event) => {
  if (allowAuthenticatedQuit) {
    // Authenticated quit path — proceed with cleanup
    isQuitting = true;
    killBackend().catch(() => { });
    return;
  }

  // System shutdown / restart / logout — allow quit without auth.
  // The app will auto-start again on next login via setLoginItemSettings.
  if (isSystemShutdown) {
    console.log('[main] System shutdown/restart detected — allowing quit without authentication.');
    isQuitting = true;
    killBackend().catch(() => { });
    return;
  }

  // If backend is dead, don't trap the user — let them quit
  if (backendExited || !backendProcess) {
    console.log('[main] Backend is not running — allowing quit without authentication.');
    isQuitting = true;
    return;
  }

  // Backend is alive — block quit and require authentication
  event.preventDefault();
  console.log('[main] Quit blocked — authentication required. Use the app UI to quit.');

  // Show the window AND tell the renderer to display the quit-auth dialog.
  // Without the IPC send, Cmd+Q / Dock→Quit would just show the current
  // page (login or dashboard) instead of the quit auth overlay.
  if (mainWindow) {
    mainWindow.show();
    mainWindow.focus();
    mainWindow.webContents.send('show-quit-dialog');
  }
});

// Tray keeps the app alive — intentional no-op
app.on('window-all-closed', () => { /* no-op on Windows */ });

app.on('activate', () => {
  if (mainWindow) {
    mainWindow.show();
    mainWindow.focus();
  } else {
    createWindow();
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
      throw new Error(error.message);
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

  // ── Config (setConfig alias for updateConfig) ─────────────────────────────
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

  // ── Verify credentials (quit dialog) — does NOT store token ────────────────
  // Cross-platform: both Windows tray-quit and macOS Cmd+Q/Dock quit use this
  // to verify the user's password before allowing app exit.
  ipcMain.handle('auth:verifyOnly', async (_event, credentials: { username: string; password: string }) => {
    try {
      const response = await apiClient.post('/api/auth/login', credentials);
      if (response.data.success) {
        // Intentionally do NOT store response.data.token — verify only
        return { success: true };
      }
      return { success: false, error: response.data.error || 'Invalid credentials' };
    } catch (error: any) {
      return { success: false, error: error.message };
    }
  });

  // ── QUIT — authenticated, Master/Child shutdown ───────────────────────────
  // This is the ONLY valid exit path (called by renderer after credential check).
  // It kills the backend child process before Electron exits to prevent zombies.
  ipcMain.handle('app:quit', async () => {
    console.log('[main] Authenticated quit requested — graceful backend shutdown...');
    allowAuthenticatedQuit = true;   // unlock before-quit handler
    isQuitting = true;
    await killBackend();     // graceful shutdown, then force-kill fallback
    app.quit();
  });
}