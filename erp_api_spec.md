# ERP API Specification for Remote Monitoring Control

This document outlines the API endpoints that the remote server (ERP/Backend) MUST implement to allow bi-directional synchronization and remote control of the Enterprise Monitor client.

## Authentication
All requests from the client include an `X-API-Key` header if configured in the client settings.

## Endpoints

### 1. Video Recording Settings
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
- **Response**: `{"success": true}` (or error)

---

### 2. Screenshot Capturing Settings
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

---

### 3. Overall Monitoring Settings (Pause/Resume)
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
