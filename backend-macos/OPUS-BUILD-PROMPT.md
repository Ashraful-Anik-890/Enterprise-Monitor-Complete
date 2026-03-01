# BUILD PROMPT — Enterprise Monitor macOS Backend
## Target Model: Claude Opus 4.6 (Extended Thinking Enabled)

---

## YOUR ROLE

You are a senior systems engineer. You are building the macOS backend for an existing enterprise employee monitoring application. The Windows version is **fully built and working**. You are NOT redesigning anything — you are porting and adapting specific modules to macOS while reusing everything that is cross-platform. Every architectural decision has already been made and documented. Your job is to execute with precision.

**Do not suggest alternative architectures. Do not ask if the user wants to change the design. Follow the spec exactly.**

---

## PROJECT CONTEXT — READ BEFORE TOUCHING ANY FILE

### What This System Does
Enterprise employee activity monitor. Electron desktop UI (TypeScript) spawns a Python FastAPI backend as a child process. They communicate over HTTP on a dynamic localhost port. The backend runs all monitoring in threads, stores data in SQLite, syncs to ERP endpoints. It runs in the system tray, is credential-protected, and auto-starts on login.

### The Master/Child Process Handshake (Critical — Unchanged for macOS)
1. Electron `main.ts` deletes stale `port.info` before spawning the backend
2. Electron spawns the backend binary via `child_process.spawn`
3. Backend `main.py` finds a free port via `socket.bind(("127.0.0.1", 0))`
4. Backend writes port to `port.info` atomically (write tmp → `os.replace`)
5. Electron polls `port.info` every 250ms, reads port, initializes `ApiClient`
6. Electron sends `POST /api/shutdown` on credential-gated quit, then force-kills after 3s

**This handshake is identical on macOS. Do not change it.**

### Existing Windows File Structure (Your Reference)
```
backend-windows/
├── main.py                         ← Entry point, port handshake, single-instance guard
├── api_server.py                   ← FastAPI, 30+ REST endpoints, lifespan hooks
├── auth/
│   └── auth_manager.py             ← JWT (python-jose), bcrypt, security Q&A
├── database/
│   └── db_manager.py               ← SQLite WAL mode, threading.Lock, shared connection
├── monitoring/
│   ├── app_tracker.py              ← win32gui + psutil — REWRITE for macOS
│   ├── browser_tracker.py          ← uiautomation COM API — REWRITE for macOS
│   ├── screenshot.py               ← mss — REUSE with permission check
│   ├── screen_recorder.py          ← mss + OpenCV — REUSE with permission check
│   ├── clipboard.py                ← pyperclip — REUSE unchanged
│   ├── keylogger.py                ← pynput + win32gui — PARTIAL REWRITE
│   └── data_cleaner.py             ← Pure Python — REUSE unchanged
├── services/
│   └── sync_service.py             ← requests, ERP sync — REUSE unchanged
├── utils/
│   └── config_manager.py           ← JSON config, LOCALAPPDATA paths — ONE PATH CHANGE
├── requirements.txt                ← pywin32, uiautomation (Windows-only) — REPLACE
└── enterprise_monitor_backend.spec ← PyInstaller Windows spec — NEW SPEC FOR macOS
```

### Your Output Structure
```
backend-mac/
├── main.py
├── api_server.py                   ← Copy from backend-windows (unchanged)
├── auth/
│   └── auth_manager.py             ← Copy from backend-windows (unchanged)
├── database/
│   └── db_manager.py               ← Copy from backend-windows (unchanged)
├── monitoring/
│   ├── app_tracker.py              ← Rewrite
│   ├── browser_tracker.py          ← Rewrite
│   ├── screenshot.py               ← Reuse + add permission guard
│   ├── screen_recorder.py          ← Reuse + add permission guard
│   ├── clipboard.py                ← Copy unchanged
│   ├── keylogger.py                ← Partial rewrite (remove win32 calls)
│   ├── data_cleaner.py             ← Copy unchanged
│   └── permissions.py              ← NEW FILE (most important)
├── services/
│   └── sync_service.py             ← Copy unchanged
├── utils/
│   ├── config_manager.py           ← One path change
│   └── autostart_manager.py        ← NEW FILE (LaunchAgent)
├── resources/
│   └── entitlements.plist          ← NEW FILE (code signing)
├── requirements.txt                ← New macOS deps
└── enterprise_monitor_backend_mac.spec  ← New PyInstaller spec
```

---

## CRITICAL TECHNICAL CONSTRAINTS — DO NOT VIOLATE

### 1. Thread Safety on macOS
**macOS AppKit requires an NSRunLoop on any thread that touches it. Python `threading.Thread` does NOT have an NSRunLoop.**

This means: **Never call `pyobjc` AppKit/NSWorkspace APIs directly from a `threading.Thread`.**

The safe solution decided for this project: **Use `osascript` subprocess for all AppKit-equivalent calls.** `subprocess.run(['osascript', ...])` is safe from any thread because it spawns a new process with its own RunLoop. The 5-second poll interval makes the ~100ms subprocess overhead completely irrelevant.

`pynput.keyboard.Listener` is safe — it manages its own internal thread with NSRunLoop. Do not interfere with it.

### 2. TCC Permission System
macOS TCC (Transparency, Consent, Control) silently blocks sensitive calls if permissions are not granted. Your company's existing raw Python files failed because they never handled TCC.

Three permissions are required:
- **Screen Recording** (`CGPreflightScreenCaptureAccess`) — required by `mss`
- **Accessibility** (`AXIsProcessTrusted`) — required by osascript System Events window title
- **Input Monitoring** — no programmatic check API; detect by monitoring pynput event count

**Rule:** Check permissions on the main thread at startup, BEFORE spawning any monitoring thread. If a permission is denied, disable only that monitor gracefully — do not crash, do not block other monitors.

### 3. PyInstaller Mode
**Use `--onedir` (COLLECT mode). Never use `--onefile` on macOS.** `--onefile` breaks Mach-O code signing format. macOS Gatekeeper silently blocks `--onefile` binaries that touch TCC APIs.

**UPX must be disabled** (`upx=False` everywhere in the spec). UPX breaks macOS code signatures.

**Required entitlement:** `com.apple.security.cs.allow-unsigned-executable-memory` — mandatory for PyInstaller apps using NumPy or OpenCV. Without it, the app crashes at import inside the PyInstaller bootstrap.

### 4. Single Instance Guard
Replace the Windows Named Mutex (`ctypes.windll.kernel32.CreateMutexW`) with a POSIX file lock (`fcntl.flock`). Keep the same exit code convention: exit with code `77` if another instance is detected (Electron checks for this).

### 5. Storage Path
Replace all `LOCALAPPDATA` / `AppData\Local` paths with `~/Library/Application Support/EnterpriseMonitor`. This is the macOS standard for application data. Use `Path.home() / 'Library' / 'Application Support' / 'EnterpriseMonitor'`.

---

## FILE-BY-FILE INSTRUCTIONS

### FILE 1: `backend-mac/main.py` — REWRITE (based on backend-windows/main.py)

**Changes from Windows version:**
- Remove `ctypes.windll.kernel32.CreateMutexW` single-instance guard
- Add `fcntl.flock` file lock guard (keep exit code 77 on duplicate)
- Change `_em_dir` from `LOCALAPPDATA/EnterpriseMonitor` to `~/Library/Application Support/EnterpriseMonitor`
- At startup, call `permissions.check_all_permissions()` BEFORE starting the API server
- Pass permission results into api_server so it can skip disabled monitors
- Everything else (port handshake, `_find_free_port`, `_write_port_info`, uvicorn start) is identical

**The fcntl lock pattern:**
```python
import fcntl

LOCK_FILE = BASE_DIR / 'backend.lock'

def acquire_single_instance_lock():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    lock_fd = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        return lock_fd  # MUST keep this reference alive for the process lifetime
    except BlockingIOError:
        logger.warning("Duplicate backend instance detected — exiting with code 77.")
        sys.exit(77)
```

---

### FILE 2: `backend-mac/monitoring/permissions.py` — NEW FILE (Most Critical)

This file must be complete and production-quality. It is the reason the company's existing raw Python failed.

```python
"""
permissions.py
macOS TCC permission checker and requester.

Called from main.py on the main thread at startup, BEFORE any monitoring
thread is spawned. Each permission is checked independently — a denied
permission disables only its dependent monitor(s) without crashing others.

macOS TCC permissions involved:
  - Screen Recording: required by mss (screenshot + screen_recorder)
  - Accessibility: required by osascript System Events (window titles in app_tracker)
  - Input Monitoring: no programmatic check — detect by pynput event count test

IMPORTANT: CGRequestScreenCaptureAccess() and AXIsProcessTrusted() MUST be
called from the main thread. Never call them from a threading.Thread.
"""
```

The file must expose:
```python
@dataclass
class PermissionState:
    screen_recording: bool
    accessibility: bool
    input_monitoring: bool  # starts as None, set after pynput probe

def check_all_permissions() -> PermissionState:
    """
    Check Screen Recording and Accessibility synchronously.
    Input Monitoring result is set later by probe_input_monitoring().
    """

def request_screen_recording_if_needed() -> bool:
    """
    If Screen Recording is denied, call CGRequestScreenCaptureAccess().
    This triggers the system dialog. Returns current state after request.
    Open System Settings directly since we cannot force-grant:
    subprocess.run(['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'])
    """

def open_accessibility_settings():
    """
    Accessibility cannot be requested programmatically — only opened.
    subprocess.run(['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'])
    """

def probe_input_monitoring(timeout_seconds: float = 5.0) -> bool:
    """
    Start a pynput listener, wait timeout_seconds, check if any events
    were received. If zero events AND user was typing (detected via
    checking keyboard state), Input Monitoring is denied.
    
    Simpler approach: just start the listener and set input_monitoring=True 
    if the listener starts without exception. Log a warning that it may be
    silently denied and events will simply not arrive if permission was denied.
    Returns True (optimistic) — the keylogger itself handles the silent-fail case.
    """
```

Use these exact imports:
```python
from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess
from ApplicationServices import AXIsProcessTrusted
```

---

### FILE 3: `backend-mac/monitoring/app_tracker.py` — FULL REWRITE

**Replace all win32gui/win32process calls with osascript subprocess.**

The monitoring loop and threading architecture is IDENTICAL to the Windows version. Only `_get_active_app_info()` changes.

```python
def _get_active_app_info(self) -> tuple[str, str]:
    """
    Get (app_name, window_title) via JXA osascript.
    Safe to call from threading.Thread — uses subprocess, not AppKit directly.
    Timeout: 3 seconds. On timeout or error, return last known values.
    Requires: Accessibility permission for window_title (app.windows[0].name())
              App name works without Accessibility.
    """
    script = '''
    var se = Application("System Events");
    var procs = se.applicationProcesses.whose({frontmost: true});
    if (procs.length === 0) { JSON.stringify({app: "", title: ""}) }
    else {
        var proc = procs[0];
        var title = "";
        try { title = proc.windows.length > 0 ? proc.windows[0].name() : ""; } catch(e) {}
        JSON.stringify({app: proc.name(), title: title});
    }
    '''
    try:
        result = subprocess.run(
            ['osascript', '-l', 'JavaScript', '-e', script],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            return data.get('app', ''), data.get('title', '')
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        logger.debug("osascript app_tracker error: %s", e)
    return '', ''
```

If `permissions_state.accessibility` is False, log a one-time warning that window titles will be empty and app names will still be captured. Do not block the tracker.

Keep all other methods (`start`, `stop`, `pause`, `resume`, `_monitor_loop`, `_track_app_usage`) identical to the Windows version — same thread pattern, same DB inserts, same poll interval.

---

### FILE 4: `backend-mac/monitoring/browser_tracker.py` — FULL REWRITE

**Replace uiautomation COM API with AppleScript subprocess per browser.**

This is actually SIMPLER than the Windows implementation. No UI tree walking. Direct AppleScript tells the browser to report its own URL.

```python
"""
browser_tracker.py
Tracks active browser URLs on macOS using AppleScript (osascript subprocess).

Strategy: Each supported browser has an AppleScript that asks it directly
for the URL of the active tab. No accessibility APIs needed for Chrome/Safari/Edge.
Firefox requires "Allow JavaScript from Apple Events" in Firefox Developer menu.

Browsers supported:
  Chromium:  Chrome, Edge, Brave, Vivaldi, Opera, Arc, Chromium
  Gecko:     Firefox
  WebKit:    Safari

Detection: app_tracker provides the current frontmost app name. If it matches
a browser in BROWSER_SCRIPTS, we run the AppleScript for that browser.
Thread-safe: osascript subprocess is safe from threading.Thread.
"""

BROWSER_SCRIPTS: dict[str, str] = {
    'Google Chrome':   'tell application "Google Chrome" to return URL of active tab of front window',
    'Microsoft Edge':  'tell application "Microsoft Edge" to return URL of active tab of front window',
    'Brave Browser':   'tell application "Brave Browser" to return URL of active tab of front window',
    'Safari':          'tell application "Safari" to return URL of front document',
    'Firefox':         'tell application "Firefox" to return URL of active tab of front window',
    'Arc':             'tell application "Arc" to return URL of active tab of front window',
    'Vivaldi':         'tell application "Vivaldi" to return URL of active tab of front window',
    'Opera':           'tell application "Opera" to return URL of active tab of front window',
    'Chromium':        'tell application "Chromium" to return URL of active tab of front window',
}

# Process names as reported by osascript may differ from display names:
PROCESS_TO_BROWSER: dict[str, str] = {
    'Google Chrome':   'Google Chrome',
    'chrome':          'Google Chrome',
    'Microsoft Edge':  'Microsoft Edge',
    'msedge':          'Microsoft Edge',
    'Brave Browser':   'Brave Browser',
    'Safari':          'Safari',
    'firefox':         'Firefox',
    'Firefox':         'Firefox',
    'Arc':             'Arc',
    'Vivaldi':         'Vivaldi',
    'Opera':           'Opera',
}
```

The `_get_browser_url(browser_name: str) -> Optional[str]` method:
- Runs the osascript with `timeout=3`
- On `returncode != 0` (browser not open, script error): return None silently
- Strip whitespace from stdout
- If empty string returned: return None

The monitoring loop polls the current frontmost app from `app_tracker` context OR runs its own subprocess check every N seconds. Use the same threading pattern as Windows `browser_tracker.py`. Insert into `browser_activity` table via `db_manager` — same schema.

---

### FILE 5: `backend-mac/monitoring/keylogger.py` — PARTIAL REWRITE

**Remove all win32 imports and calls. Replace `_get_active_window_info()` with osascript version.**

The `pynput.keyboard.Listener` code is UNCHANGED — it works identically on macOS.

Changes:
1. Remove `import win32gui, win32process` — these don't exist on macOS
2. Replace `_get_active_window_info()`:

```python
def _get_active_window_info(self) -> tuple[str, str]:
    """Get (app_name, window_title) for the foreground app. macOS version using osascript."""
    try:
        result = subprocess.run(
            ['osascript', '-l', 'JavaScript', '-e',
             'var p=Application("System Events").applicationProcesses.whose({frontmost:true})[0];'
             'JSON.stringify({app:p.name(),title:p.windows.length>0?p.windows[0].name():""})'],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            d = json.loads(result.stdout.strip())
            return d.get('app', ''), d.get('title', '')
    except Exception:
        pass
    return '', ''
```

3. Remove the `if sys.platform != "win32": return` guard at start of `start()`. On macOS, pynput is valid.
4. Add at the top of `start()`: check if Input Monitoring might be denied by attempting to verify pynput can start (just log a warning if uncertain — do not block).
5. The `PRIVACY_KEYWORDS` filter, buffer logic, flush on ENTER, flush on window switch — all unchanged.

---

### FILE 6: `backend-mac/monitoring/screenshot.py` — REUSE + PERMISSION GUARD

Copy from `backend-windows/monitoring/screenshot.py`.

**Only changes:**
1. Change storage path from `LOCALAPPDATA/EnterpriseMonitor/screenshots` to `~/Library/Application Support/EnterpriseMonitor/screenshots`
2. In `start()`, add at the top:
```python
from Quartz import CGPreflightScreenCaptureAccess
if not CGPreflightScreenCaptureAccess():
    logger.warning("Screenshot: Screen Recording permission denied — skipping start.")
    return
```
3. Remove any `win32api` imports or calls if present.

`mss` itself is unchanged — it's cross-platform and captures on macOS using `CoreGraphics`.

---

### FILE 7: `backend-mac/monitoring/screen_recorder.py` — REUSE + PERMISSION GUARD

Copy from `backend-windows/monitoring/screen_recorder.py`.

**Only changes:**
1. Change `_resolve_video_dir()` — replace the entire function:
```python
def _resolve_video_dir() -> Path:
    return Path.home() / 'Library' / 'Application Support' / 'EnterpriseMonitor' / 'videos'
```
2. Remove `import win32api` and any calls to it
3. In `start()`, add Screen Recording permission check (same as screenshot.py above)
4. Verify `FOURCC = "mp4v"` — this works on macOS with OpenCV. Do not change it.

---

### FILE 8: `backend-mac/utils/config_manager.py` — ONE PATH CHANGE

Copy from `backend-windows/utils/config_manager.py`.

**Only change:** The `BASE_DIR` definition:
```python
# Windows (remove this):
BASE_DIR = Path(os.environ.get('LOCALAPPDATA', '')) / 'EnterpriseMonitor'

# macOS (replace with this):
BASE_DIR = Path.home() / 'Library' / 'Application Support' / 'EnterpriseMonitor'
```

Everything else — JSON config structure, ERP endpoint keys, API key storage — is unchanged.

---

### FILE 9: `backend-mac/utils/autostart_manager.py` — NEW FILE

Replaces Windows Registry `Run` key with macOS LaunchAgent.

```python
"""
autostart_manager.py
Manages auto-start on macOS using a LaunchAgent plist.

LaunchAgent equivalent of Windows Registry Run key.
Placed in ~/Library/LaunchAgents/ — loaded by launchd per-user at login.

The primary auto-start mechanism is Electron's app.setLoginItemSettings().
This LaunchAgent is a secondary fallback: it starts the backend if the user
logs in and Electron is not running (e.g., headless monitoring scenario).

Note: The plist ProgramArguments path must point to the installed binary,
not a dev path. The install() method resolves sys.executable at call time.
"""

PLIST_LABEL = 'com.enterprisemonitor.backend'
PLIST_PATH = Path.home() / 'Library' / 'LaunchAgents' / f'{PLIST_LABEL}.plist'

def install(binary_path: str, log_dir: str) -> bool: ...
def uninstall() -> bool: ...
def is_installed() -> bool: ...
```

The plist content:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.enterprisemonitor.backend</string>
    <key>ProgramArguments</key>
    <array>
        <string>{binary_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardErrorPath</key>
    <string>{log_dir}/backend.log</string>
    <key>StandardOutPath</key>
    <string>{log_dir}/backend.log</string>
</dict>
</plist>
```

After writing: `subprocess.run(['launchctl', 'load', str(PLIST_PATH)])` to register immediately.
For uninstall: `launchctl unload` then `plist.unlink()`.

---

### FILE 10: `backend-mac/requirements.txt` — NEW

```
# Web Framework
fastapi
uvicorn[standard]

# Auth
python-jose[cryptography]
passlib[bcrypt]

# Screenshot & Recording
mss
Pillow
opencv-python
numpy

# System (cross-platform)
psutil
pyperclip
requests
tzdata

# Keylogger
pynput

# macOS TCC Permission Checks (replaces pywin32 + uiautomation)
pyobjc-framework-Quartz
pyobjc-framework-ApplicationServices

# Build
pyinstaller

# EXPLICITLY EXCLUDED (Windows-only — do not install):
# pywin32
# uiautomation
# comtypes
```

After `pip install -r requirements.txt`, immediately run:
```bash
pip freeze > requirements-lock.txt
```
Pin pyobjc versions in requirements-lock.txt — pyobjc C API version mismatches across macOS updates are a known failure mode (ActivityWatch hit this).

---

### FILE 11: `backend-mac/resources/entitlements.plist` — NEW

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!--
    MANDATORY for PyInstaller + NumPy/OpenCV.
    Without this, the app crashes at NumPy/OpenCV import inside the PyInstaller
    bootstrap with a MemoryError. Hardened Runtime blocks JIT/unsigned exec memory.
    -->
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>

    <!--
    Required to disable App Sandbox (enterprise apps must NOT be sandboxed —
    sandboxing blocks osascript, process listing, and cross-app monitoring).
    Only needed if you accidentally enable sandbox elsewhere.
    -->
    <!-- Do NOT add com.apple.security.app-sandbox — it breaks monitoring -->
</dict>
</plist>
```

---

### FILE 12: `backend-mac/enterprise_monitor_backend_mac.spec` — NEW

```python
# enterprise_monitor_backend_mac.spec
block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('resources/entitlements.plist', 'resources'),
    ],
    hiddenimports=[
        'pynput.keyboard._darwin',
        'pynput.mouse._darwin',
        'Quartz',
        'ApplicationServices',
        'passlib.handlers.bcrypt',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'pywin32', 'win32api', 'win32gui', 'win32process',
        'uiautomation', 'comtypes', 'winreg',
        'tkinter',
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # onedir mode — NOT onefile
    name='enterprise_monitor_backend',
    debug=False,
    strip=False,
    upx=False,                      # NEVER use UPX on macOS — breaks code signing
    console=True,
    target_arch='arm64',            # Change to 'x86_64' for Intel, 'universal2' for both
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='enterprise_monitor_backend',
)
```

Build command:
```bash
python -m PyInstaller enterprise_monitor_backend_mac.spec
```

Ad-hoc sign (for internal/dev distribution, no Apple Developer ID needed):
```bash
codesign --deep --force --options=runtime \
  --entitlements resources/entitlements.plist \
  --sign - \
  dist/enterprise_monitor_backend/enterprise_monitor_backend
```

---

### ELECTRON CHANGES (Minimal)

**`electron-app/package.json`** — change build target section:
```json
"mac": {
  "target": "dmg",
  "category": "public.app-category.business",
  "hardenedRuntime": true,
  "gatekeeperAssess": false,
  "entitlementsInherit": "build/entitlements.mac.plist"
},
"extraResources": [
  {
    "from": "../backend-mac/dist/enterprise_monitor_backend",
    "to": "backend"
  }
]
```

**`electron-app/src/main/main.ts`** — backend binary path:
```typescript
// Add platform check for binary name:
const binaryName = process.platform === 'win32'
  ? 'enterprise_monitor_backend.exe'
  : 'enterprise_monitor_backend';

// Add chmod before spawn (macOS — binary may not be executable after extraction):
if (process.platform !== 'win32') {
  try { fs.chmodSync(backendPath, '755'); } catch {}
}
```

**`electron-app/src/main/main.ts`** — EM_DIR path:
```typescript
const EM_DIR = process.platform === 'win32'
  ? path.join(process.env.LOCALAPPDATA ?? path.join(os.homedir(), 'AppData', 'Local'), 'EnterpriseMonitor')
  : path.join(os.homedir(), 'Library', 'Application Support', 'EnterpriseMonitor');
```

**`electron-app/build/entitlements.mac.plist`** — new file:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.security.cs.allow-jit</key>
  <true/>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
  <true/>
</dict>
</plist>
```

---

## STARTUP AND EXECUTION ORDER — VERIFY THIS IS CORRECT

```
main.py startup sequence (macOS):
  1. Setup logging → ~/Library/Application Support/EnterpriseMonitor/logs/backend.log
  2. acquire_single_instance_lock() → fcntl file lock, exit 77 if duplicate
  3. permissions.check_all_permissions() → PermissionState object
     ├─ CGPreflightScreenCaptureAccess() → state.screen_recording
     ├─ AXIsProcessTrusted() → state.accessibility
     └─ state.input_monitoring = True (optimistic, probe deferred)
  4. _find_free_port() → dynamic port
  5. _write_port_info(port) → atomic write to port.info
  6. import api_server → pass permission_state to it
  7. uvicorn.run(app, host="127.0.0.1", port=port)

api_server.py lifespan startup:
  8. db_manager.initialize()
  9. config_manager.load()
  10. Start monitoring threads (only those with permissions):
      ├─ app_tracker.start() → always (app name works without Accessibility)
      ├─ browser_tracker.start() → always (osascript, no permission needed)
      ├─ screenshot_monitor.start() → only if state.screen_recording
      ├─ screen_recorder.start() → only if state.screen_recording AND config enabled
      ├─ clipboard_monitor.start() → always (pyperclip, no TCC needed)
      ├─ keylogger.start() → always (Input Monitoring checked by pynput silently)
      └─ sync_service.start() → always
```

---

## VALIDATION CHECKLIST — RUN AFTER EACH FILE IS WRITTEN

After each module is complete, run:

```bash
# Syntax check:
python -m py_compile monitoring/permissions.py && echo "OK"
python -m py_compile monitoring/app_tracker.py && echo "OK"
python -m py_compile monitoring/browser_tracker.py && echo "OK"
python -m py_compile monitoring/keylogger.py && echo "OK"

# Import check (with venv active, TCC permissions granted to Terminal):
python -c "from monitoring.permissions import check_all_permissions; print(check_all_permissions())"
python -c "from monitoring.app_tracker import AppTracker; print('OK')"
python -c "from monitoring.browser_tracker import BrowserTracker; print('OK')"

# Live test (have a browser open):
osascript -e 'tell application "Google Chrome" to return URL of active tab of front window'

# Full backend smoke test:
python main.py
# Expected: port.info written, uvicorn starts, no import errors
```

---

## WHAT YOU MUST NOT DO

- Do not use `pyobjc` `NSWorkspace` or any AppKit class directly from a `threading.Thread`
- Do not use `--onefile` in the PyInstaller spec
- Do not enable `UPX` anywhere in the spec
- Do not add `com.apple.security.app-sandbox` to any plist
- Do not change the FastAPI API structure — the Electron renderer sends the same HTTP requests on both platforms
- Do not change the port handshake mechanism — it works identically on macOS
- Do not use `win32api`, `win32gui`, `pywin32`, `uiautomation`, or `comtypes`
- Do not import anything from `winreg`
- Do not suggest Swift. The decision is Python + osascript subprocess.
- Do not add `requirements.txt` as a markdown table or documentation — write the actual pip requirements file

---

## FINAL DELIVERABLE

Produce every file listed in the Output Structure section above. Each file must be complete and production-ready — no TODOs, no placeholder comments like `# implement this`. The code must run without modification after `pip install -r requirements.txt` on a macOS machine with TCC permissions granted.

Write files in this order (dependency order):
1. `resources/entitlements.plist`
2. `utils/config_manager.py`
3. `utils/autostart_manager.py`
4. `monitoring/permissions.py`
5. `monitoring/app_tracker.py`
6. `monitoring/browser_tracker.py`
7. `monitoring/keylogger.py`
8. `monitoring/screenshot.py`
9. `monitoring/screen_recorder.py`
10. `main.py`
11. `requirements.txt`
12. `enterprise_monitor_backend_mac.spec`
13. Electron changes: `package.json` diff, `main.ts` diff, `build/entitlements.mac.plist`
