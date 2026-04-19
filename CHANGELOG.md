# Changelog

All notable changes to Enterprise Monitor are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [5.3.1] — 2026-04-19



## [5.3.0] — 2026-04-18

### Added
- **Liquid Glass Design System** — Full UI refactor with a premium glassmorphic aesthetic, animated gradient backgrounds, and frosted glass components.
- **Identity Confirmation Workflow** — New first-run experience that requires admins to verify device/user aliases and specify a physical location before syncing begins.
- **Location Tracking** — Added `location` mapping to all monitoring telemetry, allowing for departmental or office-based data filtering.
- **Consolidated Control Ribbon** — Replaced fragmented control buttons with a unified, responsive ribbon for Monitoring, Screenshots, and Video toggles.
- **Dynamic Timezone Support** — Users can now select and persist their display timezone, which is reflected across all dashboard charts and log timestamps.
- **Real-time Settings Sync** — Local monitoring toggles now trigger immediate status updates to the remote ERP server for bi-directional state reflection.
- **Silent Auto-Pause on Inactivity** — Monitoring now automatically pauses after 5 minutes of inactivity (no key press or mouse click) to prevent storage waste and redundancy.
- **JWT-less Internal Endpoints** — Implemented localhost-only endpoints (`/api/internal/monitoring/pause` and `/resume`) to allow the Electron idle tracker to control status without being affected by 5-minute token expiry.

### Improved
- **Dashboard Responsiveness** — Refactored the identity section and control layouts to prevent overlapping on small windows.
- **Chart.js Scaling** — Improved canvas sizing logic to ensure visualizations remain sharp and well-proportioned across different resolutions.
- **Sync Reachability Logic** — Added atomic port polling and reachability flags to provide clearer network status in the UI.
- **Customizable Inactivity Timeout** — Added a configurable threshold in the main process (defaulted to 5 minutes).

### Fixed
- **Backend Import Stability** — Fixed a `NameError` in the FastAPI backends where `Request` was not imported, ensuring internal API calls succeed silently.

## [5.2.7] — 2026-04-02

### Changed
- **Screenshot Compression Pipeline** — Replaced high-quality JPEG capture (~80KB) with a "resize-first" pipeline. All screenshots are now immediately downscaled to 800px width and target a file size of 10-15KB. This reduces sync bandwidth by 80%.
- **Enhanced Sync Parity** — Synchronized `BATCH_FILES` to **50** for both macOS and Windows to prevent screenshot backlogs.
- **Resource Optimization** — Lowered screen recording `TARGET_FPS` from 10 to **5** to minimize CPU impact on low-powered machines.

### Fixed
- **Electron IPC Race Condition** — Reordered initialization to call `setupIpcHandlers()` before `createWindow()`, eliminating "No handler registered" errors during app startup.
- **macOS ScreenRecorder Crash** — Added missing `pause()` and `resume()` alias methods to fix `AttributeError` during remote sync cycles.
- **Sync Payload Standardization** — Added explicit ISO-8601 UTC normalization (`+00:00`) to screenshots and corrected the multipart MIME type from `image/png` to `image/jpeg`.
- **API Resilience** — Increased `ApiClient` timeout to **30 seconds** and added a graceful fallback for `api:getIdentity` to prevent frontend login timeouts.

## [5.2.6] — 2026-03-29

### Fixed
- **Cleanup Ghost File Prevention** — Refactored the data cleanup service to use a "safety-first" deletion sequence. The physical file on disk is now deleted *before* the database record is removed. If a file is locked or fails to delete, the record is preserved, ensuring the system retries the deletion later and preventing "orphaned" files that take up space without being tracked.
- **Data Cleanup Service** — Added a heartbeat timer to the data cleanup service to ensure that cleanup runs at regular intervals. This is important because the data cleanup service is run in a separate thread and the heartbeat timer is used to ensure that the cleanup runs at regular intervals.
- **Login Credentials** - Solved the racing problem in the app which was causing dissapering credential when typing in the login page.

---

## [5.2.5] — 2026-03-28

### Added
- **Top-Level "Screen Recording" Tab** — Moved Screen Recording from a sub-tab under "Monitor Data" to its own top-level tab for faster access, alongside Dashboard, Monitor Data, and Screenshots.
- **Dynamic Version Display** — The application now pulls its version string directly from `package.json` and displays it in the login footer and the dashboard footer (bottom-left).

### Fixed
- **Fullscreen Layout Fix** — Dashboard now uses 100% width, eliminating sidebar gaps in fullscreen or on Ultrawide monitors.
- **Auto-Update: Post-Install Relaunch** — Corrected `quitAndInstall` flags to ensure the application restarts automatically after a silent update installation.
- **Auto-Update: JWT Expiry during Shutdown** — Added token validation in `killBackend()` to avoid 401 errors when shutting down with an expired session; now defaults to a clean force-kill if the token is invalid.
- **Auto-Update: Install on System Shutdown** — Implemented `installPendingUpdateOnQuit()` to catch updates during Windows shutdown/restart, ensuring pending updates are not lost during power cycles.
- **Auto-Update: Backend Crash Resilience** — Pending updates are now correctly triggered even if the backend process has exited unexpectedly before the user quits the app.

---

## [5.2.4] — 2026-03-25

### Added
- **Silent Auto-Update System (Windows)** — The application now checks GitHub Releases for updates every 4 hours and on every startup. Updates download silently in the background and are installed automatically on the next authenticated quit, or immediately via the new "Install Now" modal. No manual reinstallation is ever required again.
- **Update Notification Modal** — A two-state modal informs the admin when a download is in progress (with live progress bar and MB/s speed) and when the update is ready to install. Monitoring continues uninterrupted throughout.
- **Post-Update Toast** — On the first startup after a successful update, a green confirmation banner shows the version that was installed. Auto-dismisses after 6 seconds.
- **Deferred Install Option** — "Install on Restart" defers the update to the next natural authenticated quit so the admin is never interrupted mid-session.

### Fixed
- **Browser URL Tracking (Windows)** — Fixed `[WinError -2147221008] CoInitialize has not been called` and `Can not load UIAutomationCore.dll` errors that completely prevented browser URL capture in background threads. Root cause: `uiautomation` requires `UIAutomationInitializerInThread` to be instantiated (and kept alive as an instance attribute) in addition to `pythoncom.CoInitialize()`.
- **NSIS File Lock (`EBUSY`) During Updates** — Added `/T` flag to all `taskkill` calls in the installer script, which terminates the entire Python process tree (including COM objects and pynput hooks) rather than just the named executable. Extended post-kill sleep from 1000 ms to 2500 ms to accommodate OpenCV and SQLite WAL checkpoint teardown on loaded machines.
- **Backend Respawn During Installer Pages** — Added a second `taskkill` call immediately before file extraction in `customInstall`. Fixes a race condition where the Windows Registry autostart key could respawn the backend during the 30–60 seconds the user spends clicking through installer pages.

### Changed
- `before-quit` handler now has a dedicated `isSystemUpdate` code path that bypasses the admin password prompt when an update is being installed. The backend is still killed gracefully before NSIS runs.
- `app:quit` IPC handler now detects a pending downloaded update and calls `autoUpdater.quitAndInstall(true, false)` instead of `app.quit()` — every authenticated quit automatically applies a waiting update.
- `package.json` build script `dist:publish` added for one-command GitHub Release publishing.

---

## [5.2.3] — 2026-03-20

### Added
- Cross-platform desktop monitoring for Windows and macOS.
- Electron + Python FastAPI Master/Child process architecture with dynamic port handshake.
- Screenshot capture, screen recording (MP4 chunks), keystroke logging, clipboard monitoring, browser URL tracking, and application activity tracking.
- Bi-directional ERP sync engine — 6 data types + 3 remote control endpoints.
- JWT authentication with 5-minute token expiry, security Q&A password reset flow.
- Credential-protected quit (anti-tamper) — blocks `app.quit()` unless admin password is verified.
- System tray with backend health indicator and auth status.
- NSIS Windows installer with Registry autostart and optional user-data cleanup on uninstall.
- macOS DMG with Hardened Runtime entitlements and TCC permission prompting.
- Timezone-aware dashboard with Chart.js activity visualisations and activity timeline.
- Configurable ERP endpoint URLs with static (compile-time) and dynamic (GUI) modes via `url.py`.

---

## Version Policy

| Segment | When it changes |
|---------|----------------|
| **Major** (X.0.0) | Breaking API changes, platform drops, architectural rewrites |
| **Minor** (5.X.0) | New monitoring features, new ERP endpoints, new UI sections |
| **Patch** (5.2.X) | Bug fixes, performance improvements, update system changes |
