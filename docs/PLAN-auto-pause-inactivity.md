# PLAN-auto-pause-inactivity

## Context
The system currently captures periodic screenshots and video even when the local user has not interacted with the mouse or keyboard for an extended duration (e.g. watching a video or away from keyboard). We need an intelligent mechanism to automatically pause monitoring after 10 minutes of complete inactivity and silently resume it as soon as the user returns.

## Core Requirements
1. **Activity Detection**: Strictly based on system input (mouse click / keyboard press) using Electron's native `powerMonitor.getSystemIdleTime()`.
2. **Auto-Resume**: Immediately resume monitoring when inactivity drops back to zero.
3. **Silent Operation**: State changes should happen invisibly to the user without UI interruption.
4. **Immediate Sync**: The backend must instantly notify the ERP server of the paused/resumed status.

## Task Breakdown

### Phase 1: Internal API Endpoints (`backend-windows/api_server.py` & `backend-macos/api_server.py`)
- **Implement Internal Pause/Resume**: Create `/api/internal/monitoring/pause` and `/api/internal/monitoring/resume` endpoints below the authenticated endpoints.
- **Localhost Gating**: Restrict access to `127.0.0.1` and `::1` only, rejecting external requests with 403 Forbidden.
- **JWT Bypass**: Call the underlying `pause_monitoring` and `resume_monitoring` functions with a mock user (e.g. `{"sub": "_idle_system"}`) to bypass the standard 5-minute JWT expiry that would otherwise log the user out during idle sessions.

### Phase 2: Electron Main Process Upgrades (`electron-app/src/main/main.ts`)
- **Implement Idle Tracker Loop**: Create a `setInterval` hook (e.g. running every 10 seconds) that checks `powerMonitor.getSystemIdleTime()`.
- **State Management**: Introduce an `isAutoPaused` variable to differentiate between user-invoked manual pauses and system-invoked auto pauses.
- **Trigger Pause State**: When `idle_time >= 600` seconds (10 minutes) and `!isAutoPaused` and `monitoring is currently active`, invoke the local backend's `/api/internal/monitoring/pause` endpoint (no payload/token required) and set `isAutoPaused = true`.
- **Trigger Resume State**: When `idle_time < 600` seconds and `isAutoPaused == true`, invoke the backend's `/api/internal/monitoring/resume` endpoint and set `isAutoPaused = false`.
- **Edge-Case Handling**: Ensure that if the user *manually* pauses monitoring, the auto-resume loop does not falsely resume it.

### Phase 3: Remote Notification Verification
- Confirm that the existing `/api/monitoring/pause` and `/api/monitoring/resume` endpoints in both `backend-windows` and `backend-macos` actually trigger `sync_service._notify_server_sync` so the remote ERP server reflects the new state immediately without waiting for the full sync interval.
- Review `backend-windows/api_server.py` and `backend-macos/api_server.py` to ensure calling these endpoints silently updates the configuration state correctly on the backend database.

## Automation & Extensibility Note
The timeout is currently proposed as a hardcoded 10-minute threshold (`600` seconds). In the future, this value can be moved into the backend sqlite `device_config` and pulled into Electron alongside the `screenshot_interval` if the dashboard allows customizable lengths.

## Verification Checklist
- [ ] Leaving the PC untouched for >10 minutes successfully halts new screenshots and video chunks.
- [ ] ERP Remote DB shows the status as gracefully paused.
- [ ] Wiggling the mouse seamlessly re-enables collection without popping up a message.
- [ ] Manual pausing by the admin in the dashboard is not overridden by the mouse-wiggling auto-resume loop.
