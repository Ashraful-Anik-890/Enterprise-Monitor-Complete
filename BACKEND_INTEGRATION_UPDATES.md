
## 1. Identity & Credential Confirmation
The client now includes a "First-Run" and "Identity Confirmation" workflow to prevent data drift and ensure every device is properly labeled before synchronization begins.

### New Identity Fields
The server's device/client schema should be updated to include:
- `location` (String): The physical/departmental location of the device (e.g., "Main Office", "Home", "Floor 2").
- `isConfirmed` (Boolean): A flag indicating if an administrator has verified the device's identity aliases.

### New Registry Endpoint
**Path**: `/api/pctracking/confirm-identity` 
- **Method**: `POST`
- **When**: Automatically called (fire-and-forget, background thread) after the admin clicks "Confirm Credential" in the Electron dashboard.
- **Payload**:
  ```json
  {
    "pcName": "...",        // device_alias set by user
    "macAddress": "...",    // hardware MAC (unique key)
    "userName": "...",      // user_alias set by user
    "location": "...",      // user-provided location
    "osUser": "...",        // raw OS username
    "machineId": "..."      // raw hostname
  }
  ```
- **Action**: The server should register or update the device record and mark it as confirmed. Syncing is now blocked on the client side until this confirmation is successful.
- **Client Config**: URL is resolved from `config_manager.get("url_confirm_identity")` or `BASE_URL + PATH_CONFIRM_IDENTITY`.

---

## 2. Real-time Monitoring Controls
The client now notifies the remote server immediately when a user manually toggles monitoring states. This enables bi-directional control (Admin can see local status and override it).

### State Change Endpoints
The server must implement `POST` handlers for the following (already in `erp_api_spec.md` but now critical for real-time feedback):

1. **Overall Monitoring** (`/api/pctracking/monitoring-settings`)
   - **Payload**: `{"monitoringActive": boolean, "pcName": "...", "macAddress": "..."}`
2. **Screenshots** (`/api/pctracking/screenshot-settings`)
   - **Payload**: `{"screenshotEnabled": boolean, "pcName": "...", "macAddress": "..."}`
3. **Screen Recording** (`/api/pctracking/video-settings`)
   - **Payload**: `{"recordingEnabled": boolean, "pcName": "...", "macAddress": "..."}`

> [!IMPORTANT]
> The server should store these values per device. If the server's `GET` response for these endpoints differs from the client's local state, the client will eventually sync to the server's desired state unless the local user makes a manual override.

---

## 3. Telemetry Payload Updates
The data ingestion endpoints for apps, browser, clipboard, and keystrokes should now expect the `location` field to be included in the headers or payload to allow for easier filtering in the monitoring dashboard.

### Example Updated Payload (App Activity)
```json
{
  "pcName": "Marketing-PC-01",
  "macAddress": "00:0a:95:9d:68:16",
  "userName": "John Doe",
  "location": "New York Office", // <--- NEW FIELD
  "appName": "Chrome",
  "windowsTitle": "Google Search",
  "startTime": "2024-04-18T10:00:00Z",
  "endTime": "2024-04-18T10:05:00Z",
  "duration": 300
}
```

---

## 4. Admin API Token Expiry Handling
The client now implements an active countdown based on the `exp` claim in the JWT token.
- **Requirement**: Ensure the `X-API-Key` or `Bearer` token provided by the server includes a standard `exp` timestamp.
- **Handling**: The server should return a `401 Unauthorized` status code when a token expires. The client is now wired to catch this and force a logout to protect the dashboard data.

---

## 5. Sync Conflict Strategy
With the addition of `credential_drifted` detection:
- If a device's `pcName` or `userName` changes (e.g., the machine is renamed), the client flags this as "Drifted".
- **Server action**: When receiving data from a known `macAddress` but with different `pcName`/`userName`, the server should either update the record (if trusted) or flag the device for re-confirmation in the Admin Panel.

---

## 6. Timezone Persistence
The client now supports a user-defined display timezone (IANA string, e.g., "America/New_York").
- **Requirement**: The server should store the `timezone` preference per device or per user.
- **Sync**: When the client fetches configuration via `GET /api/pctracking/settings`, the server should include the last saved `timezone` so the client can apply it to charts and logs.

---

## 7. Device Status Reporting (v5.3.0)

The client now reports its operational status to the server on every sync cycle via `POST /api/pctracking/device-status`.

### Status Lifecycle
| Status | Trigger |
|--------|---------|
| `ACTIVE` | App start, user returns from idle, resume from sleep |
| `PAUSED` | Admin manually pauses monitoring via dashboard |
| `AUTO_PAUSED` | 5-minute idle timeout (Electron `powerMonitor`) |
| `SLEEP` | OS suspend/hibernate event |
| `SHUTDOWN` | App quits via authenticated quit |
| `GRACEFUL_OFF` | OS shutdown/restart/logout signal |

### Server Requirements
1. **New endpoint**: `POST /api/pctracking/device-status` (see `erp_api_spec.md` §3.1)
2. Store the latest status + timestamp per device (keyed by `macAddress`)
3. Display in admin dashboard "Status" column (replace hardcoded "ACTIVE")
4. **Recommended**: Auto-mark `OFFLINE` if no heartbeat for 10+ minutes

### Internal Client Endpoints
These localhost-only endpoints allow the Electron process to set device status without JWT:
- `POST /api/internal/device-status` — set status (body: `{"status": "SLEEP"}`)
- `GET  /api/device/status` — get current status (JWT required, for renderer)

---

## 8. MAC Address Sanitization (v5.3.0)

### Problem
`uuid.getnode()` returns different MAC addresses depending on which network interface is active (Wi-Fi vs Ethernet vs VPN). On machines with Docker, Hyper-V, or VPN adapters, this led to duplicate device entries on the server after a local DB reset.

### Solution — Soft Migration
- **macOS**: Reads `ifconfig en0` to get the built-in NIC's MAC. Fallback: `en1` → `uuid.getnode()`.
- **Windows**: Parses `getmac /fo csv /nh /v` and selects the first non-virtual adapter (excludes Hyper-V, Docker, VPN, VMware, etc.).
- **Soft migration**: Existing stored MACs are **never overwritten**. The improved detection only runs on first install or after a local DB deletion.
- **No server-side changes required** — existing devices continue using their stored MAC.

---

## 9. Sync Marker Reset (v5.3.0)

### Problem
After a server-side DB reset, the client's local SQLite still has `synced = 1` on old records. The sync service only queries `synced = 0`, so previously synced data (browser, clipboard, etc.) was never re-uploaded.

### Solution
- New endpoint: `POST /api/sync/reset-markers` (JWT required)
- Resets all `synced` / `is_synced` flags to `0` across all data tables
- Available from the Electron dashboard as "Re-sync All Data"
- On the next sync cycle, all data will be re-uploaded to the server
