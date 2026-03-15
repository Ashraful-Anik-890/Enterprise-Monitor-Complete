# ERP API Specification for Enterprise Monitor

This document outlines the API endpoints that the remote server (ERP/Backend) MUST implement to allow bi-directional synchronization, remote control, and data ingestion from the Enterprise Monitor client.

## Authentication
All requests from the client include an `X-API-Key` header if configured in the client settings.

---

## 1. CONTROL ENDPOINTS (Bi-directional Sync)

### 1.1 Video Recording Settings
**Path**: `/api/pctracking/video-settings`

#### GET
Used by the client to fetch the desired recording status from the server.
- **Query Params**: `pcName`, `macAddress`, `userName`
- **Response**: `{"recordingEnabled": boolean}`

#### POST
Used by the client to notify the server of a local status change.
- **Body (JSON)**:
  ```json
  {
    "pcName": "...",
    "macAddress": "...",
    "userName": "...",
    "recordingEnabled": boolean
  }
  ```
- **Response**: `{"success": true}`

### 1.2 Screenshot Capturing Settings
**Path**: `/api/pctracking/screenshot-settings`

#### GET
Used by the client to fetch the desired screenshot status.
- **Query Params**: `pcName`, `macAddress`, `userName`
- **Response**: `{"screenshotEnabled": boolean}`

#### POST
Used by the client to notify the server of a local status change.
- **Body (JSON)**:
  ```json
  {
    "pcName": "...",
    "macAddress": "...",
    "userName": "...",
    "screenshotEnabled": boolean
  }
  ```
- **Response**: `{"success": true}`

### 1.3 Overall Monitoring Settings (Pause/Resume)
**Path**: `/api/pctracking/monitoring-settings`

#### GET
Used by the client to fetch the desired overall monitoring status.
- **Query Params**: `pcName`, `macAddress`, `userName`
- **Response**: `{"monitoringActive": boolean}`

#### POST
Used by the client to notify the server when a user manually Pauses or Resumes monitoring.
- **Body (JSON)**:
  ```json
  {
    "pcName": "...",
    "macAddress": "...",
    "userName": "...",
    "monitoringActive": boolean
  }
  ```
- **Response**: `{"success": true}`

---

## 2. DATA ENDPOINTS (Telemetry Ingestion)

All data endpoints use **POST** to upload accumulated records.

### 2.1 App Activity
**Path**: `/api/pctracking/appuseage`
- **Format**: JSON
- **Body**:
  ```json
  {
    "pcName": "...",
    "macAddress": "...",
    "userName": "...",
    "appName": "...",
    "windowsTitle": "...",
    "startTime": "ISO-8601",
    "endTime": "ISO-8601",
    "duration": integer,
    "syncTime": "ISO-8601"
  }
  ```

### 2.2 Browser Activity
**Path**: `/api/pctracking/browser`
- **Format**: JSON
- **Body**:
  ```json
  {
    "pcName": "...",
    "macAddress": "...",
    "userName": "...",
    "browserName": "...",
    "url": "...",
    "pageTitle": "...",
    "timestamp": "ISO-8601",
    "syncTime": "ISO-8601"
  }
  ```

### 2.3 Clipboard Events
**Path**: `/api/pctracking/clipboard`
- **Format**: JSON
- **Body**:
  ```json
  {
    "pcName": "...",
    "macAddress": "...",
    "userName": "...",
    "contentType": "...",
    "contentPreview": "...",
    "timestamp": "ISO-8601",
    "syncTime": "ISO-8601"
  }
  ```

### 2.4 Keystrokes
**Path**: `/api/pctracking/keystrokes`
- **Format**: JSON
- **Body**:
  ```json
  {
    "pcName": "...",
    "macAddress": "...",
    "userName": "...",
    "application": "...",
    "windowTitle": "...",
    "content": "...",
    "timestamp": "ISO-8601",
    "syncTime": "ISO-8601"
  }
  ```

### 2.5 Screenshots
**Path**: `/api/pctracking/screenshots`
- **Format**: `multipart/form-data`
- **Fields**: `pcName`, `macAddress`, `userName`, `timestamp`, `activeWindow`, `activeApp`, `syncTime`
- **File Field**: `file` (PNG)

### 2.6 Screen Recordings
**Path**: `/api/pctracking/videos`
- **Format**: `multipart/form-data`
- **Fields**: `pcName`, `macAddress`, `userName`, `timestamp`, `durationSeconds`, `syncTime`
- **File Field**: `file` (MP4)

