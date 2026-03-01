# Enterprise Monitor — macOS Architecture

> **Status:** Pre-development reference. Read this fully before writing a single line of code.  
> **Ruthless correction from previous session:** I told you ActivityWatch deprecated Swift. That was wrong. ActivityWatch made Swift the **default strategy** for macOS window watching in v0.12.1 (Sep 2022). The pyobjc approach had C API version mismatch issues across macOS updates. This changes your architecture decisions.

---

## 1. The Real TCC Problem — Why Your Company's Raw Python Failed

macOS Transparency, Consent, and Control (TCC) is not just a permission dialog. It is a **database-level enforcement system** (`/Library/Application Support/com.apple.TCC/TCC.db`). Here is exactly what happens for each scenario:

### Scenario A: `python main.py` from Terminal
macOS checks which process is making the sensitive call. It sees `Terminal.app` (or `iTerm2`). macOS shows: **"Terminal wants to record your screen."** The user clicks Allow — but the permission is granted to **Terminal**, not to your script. The moment you distribute your app and run it any other way, permission is gone.

### Scenario B: PyInstaller `--onefile` binary
macOS cannot verify the binary's integrity because PyInstaller `--onefile` appends the Python archive after the Mach-O LINKEDIT segment, which **breaks the code signature format**. macOS Gatekeeper sees a tampered binary. Result: it blocks the app entirely, or TCC silently denies all sensitive calls with no dialog shown to the user. Your company's raw Python files hit exactly this.

### Scenario C: PyInstaller `--onedir` + proper `.app` bundle + code signing
This works. The `.app` bundle has a valid `Info.plist`, proper `CFBundleIdentifier`, an `entitlements.plist` with declared permissions, and the binary is signed with `codesign --deep`. TCC sees a recognized, signed entity and shows the correct permission dialogs attributed to **your app**.

**Conclusion: You must use `--onedir` mode (same as Windows), build a `.app` bundle, and sign it. `--onefile` is blocked on macOS for any app touching TCC.**

---

## 2. The Thread War Problem — What Actually Breaks

### What is the risk?
macOS AppKit (the UI/system framework) has a strict rule: **AppKit objects must be accessed on the main thread or a thread with an active NSRunLoop.** Python threads created with `threading.Thread` are plain POSIX threads — they have no NSRunLoop by default.

### What breaks without handling this?
| Module | Risk | Why |
|---|---|---|
| `pynput` keyboard listener | **High** | pynput on macOS internally starts an `NSRunLoop` via a Cocoa event tap. If another pyobjc call touches AppKit from a different thread simultaneously, you get race conditions or crashes. |
| `pyobjc` AppKit calls from threads | **High** | `NSWorkspace.sharedWorkspace()` must be called from a thread with a RunLoop. Calling it raw from `threading.Thread` is undefined behavior. |
| `osascript` subprocess | **None** | Subprocess spawning is safe from any thread. This is why ActivityWatch uses it as a fallback. |
| `mss` screenshots | **Low** | mss uses Quartz APIs which are thread-safe for capture. |
| `pynput` mouse listener | **Medium** | Same RunLoop concern as keyboard. |

### The solution ActivityWatch actually uses
They do **not** call AppKit directly from Python threads. For window tracking, they compile a small Swift binary (`aw-watcher-window-macos`) that Python calls via `subprocess`. The Swift binary handles the NSRunLoop natively, gets the window title, and writes JSON to stdout. Python reads it. Zero thread conflict.

For you, since you don't know Swift, the safe approach is:

**Use `osascript` subprocess calls for anything that needs AppKit. Never call pyobjc AppKit from `threading.Thread` directly.**

---

## 3. Architecture Decision: What You Actually Build

```
enterprise-monitor-mac/
├── backend-mac/                    ← Python, mirrors backend-windows structure
│   ├── main.py                     ← REUSE (remove Windows Mutex → fcntl file lock)
│   ├── api_server.py               ← REUSE 100% identical
│   ├── auth/                       ← REUSE 100% identical
│   ├── database/                   ← REUSE 100% identical
│   ├── services/                   ← REUSE 100% identical (sync_service.py)
│   ├── utils/
│   │   ├── config_manager.py       ← REUSE (change LOCALAPPDATA path → ~/Library/Application Support)
│   │   └── autostart_manager.py   ← NEW: LaunchAgent plist (replaces Registry Run key)
│   ├── monitoring/
│   │   ├── app_tracker.py          ← REWRITE: osascript subprocess (safe, no thread war)
│   │   ├── browser_tracker.py      ← REWRITE: osascript AppleScript per browser
│   │   ├── screenshot.py           ← REUSE (mss is cross-platform, add permission check)
│   │   ├── screen_recorder.py      ← REUSE (mss + OpenCV cross-platform)
│   │   ├── clipboard.py            ← REUSE (pyperclip cross-platform)
│   │   ├── keylogger.py            ← REWRITE: remove win32 calls, pynput works on macOS
│   │   ├── data_cleaner.py         ← REUSE 100% identical
│   │   └── permissions.py          ← NEW: TCC check + guided user flow (critical)
│   ├── resources/
│   │   └── entitlements.plist      ← NEW: required for code signing
│   ├── requirements.txt            ← NEW: pyobjc replaces pywin32/uiautomation
│   └── enterprise_monitor_backend_mac.spec  ← NEW: PyInstaller spec for macOS
│
├── electron-app/                   ← REUSE entirely. Zero changes to IPC, API client, renderer.
│   ├── build/
│   │   └── entitlements.mac.plist  ← ADD: Electron's own entitlements for macOS build
│   └── package.json                ← MINOR: change build target from nsis → dmg
│
└── scripts/
    └── setup-mac.sh                ← NEW: replaces setup-windows.bat
```

---

## 4. What Each Module Does on macOS — The Honest Technical Detail

### 4.1 `permissions.py` — Run This First, Before Any Thread Starts

This is the module your company's raw Python did NOT have. It is the most important new file.

**At backend startup, before `api_server.py` starts any monitoring thread:**
1. Check Screen Recording permission using `CGPreflightScreenCaptureAccess()` via pyobjc-framework-Quartz
2. Check Accessibility permission using `AXIsProcessTrusted()` via pyobjc-framework-ApplicationServices
3. Check Input Monitoring — there is no programmatic check API; pynput will simply fail silently if denied
4. If permission missing: request it (triggers the system dialog), log the state, and **disable only that specific monitor** — do not crash, do not block other monitors

```python
# How to check Screen Recording (safe to call from main thread at startup):
from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

def check_screen_recording() -> bool:
    return CGPreflightScreenCaptureAccess()

def request_screen_recording():
    CGRequestScreenCaptureAccess()  # Shows system dialog

# How to check Accessibility:
from ApplicationServices import AXIsProcessTrusted

def check_accessibility() -> bool:
    return AXIsProcessTrusted()
```

These calls are safe on the main thread at startup. Do this in `main.py` before spawning any monitoring threads.

### 4.2 `app_tracker.py` — osascript Strategy (Thread-Safe)

**Do NOT use pyobjc `NSWorkspace` from a `threading.Thread`.** Use osascript subprocess. It is slightly slower (50–100ms per call) but safe, and your poll interval is 5 seconds anyway so it does not matter.

```python
import subprocess, json

def _get_active_app_info() -> tuple[str, str]:
    # JXA script — returns JSON, safe from any thread via subprocess
    script = '''
    const app = Application("System Events").applicationProcesses.where({frontmost: true})[0];
    JSON.stringify({
        app: app.name(),
        title: app.windows.length > 0 ? app.windows[0].name() : ""
    })
    '''
    result = subprocess.run(
        ['osascript', '-l', 'JavaScript', '-e', script],
        capture_output=True, text=True, timeout=3
    )
    if result.returncode == 0:
        data = json.loads(result.stdout.strip())
        return data['app'], data['title']
    return None, None
```

**Requires:** Accessibility permission (System Settings → Privacy & Security → Accessibility). Without it, `windows[0].name()` returns empty. App name still works.

### 4.3 `browser_tracker.py` — AppleScript per Browser (No Permission Needed)

This is **simpler than the Windows approach**. No UI Automation COM required. AppleScript can directly ask the browser app for its current URL.

```python
BROWSER_SCRIPTS = {
    'Google Chrome': 'tell application "Google Chrome" to return URL of active tab of front window',
    'Safari':        'tell application "Safari" to return URL of front document',
    'Microsoft Edge':'tell application "Microsoft Edge" to return URL of active tab of front window',
    'Brave Browser': 'tell application "Brave Browser" to return URL of active tab of front window',
    'Firefox':       'tell application "Firefox" to return URL of active tab of front window',
    'Arc':           'tell application "Arc" to return URL of active tab of front window',
}

def get_browser_url(browser_name: str) -> str:
    script = BROWSER_SCRIPTS.get(browser_name)
    if not script:
        return None
    result = subprocess.run(['osascript', '-e', script],
                            capture_output=True, text=True, timeout=3)
    return result.stdout.strip() if result.returncode == 0 else None
```

**Note on Firefox:** Firefox requires `Allow JavaScript from Apple Events` to be enabled in Firefox Developer menu. Chrome and Safari work out of the box.

### 4.4 `keylogger.py` — pynput, Remove All win32 Calls

pynput works on macOS natively. The only changes:
- Remove all `win32gui` / `win32process` imports and calls
- Replace `_get_active_window_info()` with the osascript version from app_tracker
- The `pynput.keyboard.Listener` internally manages its own NSRunLoop thread — do not interfere with it

**TCC requirement:** Input Monitoring permission. If denied, `pynput.keyboard.Listener` starts without error but receives no events. Check this by testing after a few seconds — if zero events received, log a warning and mark the module as permission-denied.

### 4.5 `screenshot.py` / `screen_recorder.py` — mss Works, Add Permission Check

`mss` uses `CGWindowListCreateImage` under the hood on macOS. This requires Screen Recording permission. If denied, `mss` returns a black frame (no error raised). Check `permissions.py` result at startup and skip if denied.

No code changes needed in these modules beyond removing any Windows-specific path logic.

### 4.6 `config_manager.py` — One Path Change

```python
# Windows:
BASE_DIR = Path(os.environ.get('LOCALAPPDATA', '')) / 'EnterpriseMonitor'

# macOS:
BASE_DIR = Path.home() / 'Library' / 'Application Support' / 'EnterpriseMonitor'
```

### 4.7 `autostart_manager.py` — LaunchAgent Replaces Registry

```python
PLIST_PATH = Path.home() / 'Library' / 'LaunchAgents' / 'com.yourcompany.enterprisemonitor.plist'

PLIST_CONTENT = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.yourcompany.enterprisemonitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/enterprise_monitor_backend</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardErrorPath</key>
    <string>{log_path}/backend.log</string>
</dict>
</plist>'''
```

The Electron `main.ts` still spawns the backend via `child_process.spawn` on startup — same as Windows. The LaunchAgent is only the fallback auto-start if the user logs in without opening Electron first. Your primary lifecycle (Electron spawns backend) is unchanged.

### 4.8 `main.py` — Remove Windows Mutex, Use File Lock

```python
# Windows: Named Mutex via win32event
# macOS: File lock via fcntl — standard POSIX, no dependency

import fcntl

LOCK_FILE = BASE_DIR / 'backend.lock'

def acquire_single_instance_lock():
    lock_fd = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd  # Keep fd open — lock released when fd closed
    except BlockingIOError:
        print("Another instance is running. Exiting.")
        sys.exit(1)
```

---

## 5. requirements.txt — macOS Backend

```
# ── Web Framework ─────────────────────────────────────────────────
fastapi
uvicorn[standard]

# ── Auth ──────────────────────────────────────────────────────────
python-jose[cryptography]
passlib[bcrypt]

# ── Screenshot & Recording ────────────────────────────────────────
mss
Pillow
opencv-python
numpy

# ── System (cross-platform) ───────────────────────────────────────
psutil
pyperclip
requests
tzdata

# ── Keylogger ─────────────────────────────────────────────────────
pynput

# ── macOS Permissions Check (replaces pywin32 + uiautomation) ────
pyobjc-framework-Quartz          # CGPreflightScreenCaptureAccess
pyobjc-framework-ApplicationServices  # AXIsProcessTrusted

# ── Build ─────────────────────────────────────────────────────────
pyinstaller

# REMOVED vs Windows:
# pywin32          ← Windows-only
# uiautomation     ← Windows COM only
```

---

## 6. entitlements.plist — Required for Code Signing

This file must exist and be referenced in your PyInstaller spec. Without it, TCC denies all sensitive calls silently after Hardened Runtime is enabled.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <!-- Required for PyInstaller + NumPy/OpenCV — Python needs executable memory -->
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
  <true/>

  <!-- Screen Recording: screenshots and screen recorder -->
  <key>com.apple.security.screen-capture</key>
  <true/>

  <!-- Accessibility: window title via osascript System Events -->
  <!-- Note: This entitlement alone does not grant access — user must approve in System Settings -->
</dict>
</plist>
```

**Critical note:** `com.apple.security.cs.allow-unsigned-executable-memory` is mandatory for any PyInstaller app using NumPy or OpenCV. Without it, the app crashes at import with a `MemoryError` inside the PyInstaller bootstrap.

---

## 7. PyInstaller Spec for macOS

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
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pywin32', 'win32api', 'win32gui', 'uiautomation'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='enterprise_monitor_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,        # UPX breaks macOS code signing — never use on macOS
    console=True,
    target_arch='arm64',   # or 'x86_64' or 'universal2' for fat binary
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='enterprise_monitor_backend',
)
```

Build command:
```bash
python -m PyInstaller enterprise_monitor_backend_mac.spec

# Then code sign (requires Apple Developer ID — for internal distribution use ad-hoc):
codesign --deep --force --options=runtime \
  --entitlements resources/entitlements.plist \
  --sign "Developer ID Application: YourName (TEAMID)" \
  --timestamp \
  dist/enterprise_monitor_backend/enterprise_monitor_backend
```

**For internal/enterprise distribution without Apple Developer ID:** Use ad-hoc signing (`--sign -`). Users will need to run `xattr -rd com.apple.quarantine /path/to/app` or you can provide a script that does this. Document this in your deployment guide.

---

## 8. Electron Changes for macOS

### `package.json` — build target

```json
{
  "build": {
    "mac": {
      "target": "dmg",
      "category": "public.app-category.business",
      "entitlementsInherit": "build/entitlements.mac.plist",
      "hardenedRuntime": true,
      "gatekeeperAssess": false
    },
    "extraResources": [
      {
        "from": "../backend-mac/dist/enterprise_monitor_backend",
        "to": "backend"
      }
    ]
  }
}
```

### `build/entitlements.mac.plist` — Electron's entitlements

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.security.cs.allow-jit</key>
  <true/>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
  <true/>
</dict>
</plist>
```

### `main.ts` — backend binary path change

```typescript
// Windows:
const backendPath = path.join(process.resourcesPath, 'backend', 'enterprise_monitor_backend.exe');

// macOS:
const backendPath = path.join(process.resourcesPath, 'backend', 'enterprise_monitor_backend');
// No .exe extension. Mark it executable if needed:
fs.chmodSync(backendPath, '755');
```

Everything else in `main.ts` — the port handshake, IPC handlers, tray management — is identical.

---

## 9. TCC Permission Flow at First Launch

This is the user experience you must design before writing monitoring code:

```
App launches (Electron spawns backend)
         │
         ▼
backend/main.py: permissions.py checks TCC state
         │
         ├─ Screen Recording denied?
         │    → CGRequestScreenCaptureAccess()  (shows dialog)
         │    → If still denied: disable screenshot + screen_recorder
         │    → Log: "Screen Recording denied — screenshot disabled"
         │
         ├─ Accessibility denied?
         │    → Open System Settings URL: x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility
         │    → Cannot auto-request — user must manually add the app
         │    → If denied: app_tracker returns app name only (no window title)
         │
         ├─ Input Monitoring (no programmatic check API):
         │    → Start pynput listener
         │    → After 5 seconds, check if any events received
         │    → If zero: log warning, mark keylogger as permission-denied
         │
         ▼
API server starts → monitoring threads start with correct enabled/disabled state
         │
         ▼
Electron renderer: show permission status in dashboard
(add a "Permissions" card showing which monitors are active)
```

---

## 10. Startup Order (Critical — Do Not Change This)

```
1. Electron main.ts launches
2. main.ts checks for stale port.info → deletes it
3. main.ts spawns backend binary (child_process.spawn)
4. backend/main.py runs:
   a. acquire_single_instance_lock() — fcntl file lock
   b. permissions.py.check_all() — TCC checks on main thread
   c. db_manager.initialize() — SQLite WAL mode
   d. config_manager.load()
   e. Write port.info atomically (tmp → rename)
   f. Start FastAPI/Uvicorn
5. main.ts polls port.info → reads port → initializes ApiClient
6. ApiClient authenticates → JWT token stored
7. Renderer loads dashboard
8. api_server.py starts monitoring threads (only those with permissions)
```

---

## 11. What You Do NOT Need

- **Swift:** Not needed. osascript subprocess handles window/app tracking safely.
- **PyObjC AppKit from threads:** Avoid. Use osascript subprocess instead.
- **App Sandbox:** Enterprise apps distributed outside the App Store do not need sandboxing. Do not enable `com.apple.security.app-sandbox` — it will block your monitoring calls entirely and is incompatible with your use case.
- **Mac App Store:** Not applicable for enterprise monitoring software.
- **Notarization:** Required only for public distribution. For internal enterprise deployment via MDM or direct DMG, ad-hoc signing + quarantine removal script is sufficient.

---

## 12. Known Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| pyobjc C API version mismatch on macOS update | High (ActivityWatch hit this) | Pin exact `pyobjc` version in requirements.txt. Test on each macOS minor update. |
| osascript timeout on heavy system load | Medium | Wrap all osascript calls in `timeout=3`. On timeout, return last known value. |
| pynput Input Monitoring silently denied | High on first run | Check event count after 5s, log and disable gracefully |
| mss returns black frames if Screen Recording denied | Certain | Check permission before starting screenshot thread |
| LaunchAgent path wrong in built app | Medium | Use `sys.executable` resolved path at install time, not hardcoded path |
| Electron binary not executable after extraction | Low | `fs.chmodSync(backendPath, '755')` in main.ts before spawn |
| Apple Silicon vs Intel binary mismatch | High if not handled | Build `--target-arch arm64` for M-series Macs. For mixed fleet: `universal2`. |
