# WILDSCOPE AI — Backend API Contract (v1.0 Frozen)

**Document Status:** FROZEN & AUTHORITATIVE  
**Version:** 1.0.0  
**Effective Date:** October 31, 2026  
**Accountable Backend Architect:** Santosh Yuvaraj (`santosh` branch)  
**Target Consumers:** Frontend Engineering (Laasya), Model Workers (Harsh), Intelligence & Analytics (Shravan)  
**Base URL:** `http://127.0.0.1:8000/api/v1`

---

## Table of Contents

1. [Architectural Overview & Shared Conventions](#1-architectural-overview--shared-conventions)
   - [Base URL & Protocol](#base-url--protocol)
   - [CORS Configuration](#cors-configuration)
   - [Request ID Tracking](#request-id-tracking)
   - [Standard Response Envelope](#standard-response-envelope)
   - [Standard Error Envelope](#standard-error-envelope)
   - [Pagination Parameters](#pagination-parameters)
   - [Optimistic Concurrency & Dataset Revisions](#optimistic-concurrency--dataset-revisions)
   - [Scientific Invariants & Immutability Rules](#scientific-invariants--immutability-rules)
2. [Endpoint Directory & Group Summary](#2-endpoint-directory--group-summary)
3. [Group 1: Health & System Diagnostics](#group-1-health--system-diagnostics)
   - [`GET /api/v1/health`](#get-apiv1health)
4. [Group 2: Media Uploads & Persistent Jobs](#group-2-media-uploads--persistent-jobs)
   - [`POST /api/v1/uploads`](#post-apiv1uploads)
   - [`GET /api/v1/jobs/{job_id}`](#get-apiv1jobsjob_id)
5. [Group 3: Media Serving & Detections](#group-3-media-serving--detections)
   - [`GET /api/v1/images/{image_id}/content`](#get-apiv1imagesimage_idcontent)
   - [`GET /api/v1/observations`](#get-apiv1observations)
6. [Group 4: Wildlife Encounters](#group-4-wildlife-encounters)
   - [`GET /api/v1/encounters/{encounter_id}`](#get-apiv1encountersencounter_id)
7. [Group 5: Human Review & Auditability (F20)](#group-5-human-review--auditability-f20)
   - [`POST /api/v1/reviews`](#post-apiv1reviews)
   - [`GET /api/v1/reviews/{detection_id}`](#get-apiv1reviewsdetection_id)
8. [Group 6: Camera Stations & Telemetry (F07)](#group-6-camera-stations--telemetry-f07)
   - [`GET /api/v1/cameras`](#get-apiv1cameras)
   - [`POST /api/v1/cameras`](#post-apiv1cameras)
   - [`GET /api/v1/cameras/{camera_id}`](#get-apiv1camerascamera_id)
   - [`POST /api/v1/cameras/{camera_id}/telemetry`](#post-apiv1camerascamera_idtelemetry)
   - [`GET /api/v1/cameras/{camera_id}/telemetry`](#get-apiv1camerascamera_idtelemetry)
9. [Group 7: Monitoring Network & Feedback (F11)](#group-7-monitoring-network--feedback-f11)
   - [`GET /api/v1/monitoring`](#get-apiv1monitoring)
   - [`GET /api/v1/monitoring-actions`](#get-apiv1monitoring-actions)
   - [`POST /api/v1/monitoring-actions`](#post-apiv1monitoring-actions)
   - [`GET /api/v1/monitoring-actions/{action_id}`](#get-apiv1monitoring-actionsaction_id)
   - [`GET /api/v1/monitoring-actions/{action_id}/feedback`](#get-apiv1monitoring-actionsaction_idfeedback)
10. [Discrepancies & Unimplemented Planned Endpoints](#10-discrepancies--unimplemented-planned-endpoints)
11. [Frontend Integration Guide (For Laasya)](#11-frontend-integration-guide-for-laasya)
    - [API Client Helper (`apiClient.js`)](#api-client-helper-apiclientjs)
    - [Background Job Polling Pattern](#background-job-polling-pattern)
    - [Handling Revision Conflicts (HTTP 409)](#handling-revision-conflicts-http-409)
    - [Interpreting Camera Health vs. Observation Silence](#interpreting-camera-health-vs-observation-silence)

---

## 1. Architectural Overview & Shared Conventions

### Base URL & Protocol
- **Local Development:** `http://127.0.0.1:8000/api/v1`
- **Network Interface:** `http://localhost:8000/api/v1`
- **Interactive Documentation:**
  - Swagger UI: `http://127.0.0.1:8000/api/v1/docs`
  - ReDoc: `http://127.0.0.1:8000/api/v1/redoc`
  - OpenAPI JSON: `http://127.0.0.1:8000/api/v1/openapi.json`

### CORS Configuration
Cross-Origin Resource Sharing is enabled for standard frontend development ports:
- `http://localhost:3000` (Next.js / Vite / CRA default)
- `http://localhost:5173` (Vite modern default)
- `http://127.0.0.1:3000`
- `http://127.0.0.1:5173`
- Headers: `*` (All allowed)
- Methods: `*` (GET, POST, PUT, DELETE, OPTIONS, etc.)
- Credentials: `true` (Supports future session cookies / authorization headers)

### Request ID Tracking
Every request processed by the backend receives a unique identifier:
- Clients may supply an existing UUID via the `X-Request-ID` HTTP header.
- If omitted, the backend generates a random `uuid4`.
- The resolved `X-Request-ID` is **always returned** in the HTTP response headers.
- On error, `request_id` is embedded in the JSON body for zero-friction debugging and log correlation.

### Standard Response Envelope
All successful API responses return JSON wrapped in an envelope containing a `meta` block:

#### Single Object Envelope
```json
{
  "data": {
    "id": "det_8f93a10c",
    "label": "Tiger"
  },
  "meta": {
    "dataset_revision": 4
  }
}
```

#### Paginated List Envelope
```json
{
  "data": [
    { "id": "CAM-01", "label": "Waterhole North" },
    { "id": "CAM-02", "label": "Ridge Trail East" }
  ],
  "meta": {
    "dataset_revision": 4,
    "total": 38,
    "limit": 20,
    "offset": 0
  }
}
```

### Standard Error Envelope
All error responses (4xx and 5xx) strictly adhere to this envelope schema:
```json
{
  "error": {
    "code": "ERROR_CODE_STRING",
    "message": "Human-readable description of the failure condition.",
    "details": {}
  },
  "request_id": "8b5a034f-0112-4eb9-bf53-73130452d7e8"
}
```

#### Standard Error Codes Table
| HTTP Code | Error Code (`code`) | Meaning & Typical Cause |
| :--- | :--- | :--- |
| **400** | `DOMAIN_VALIDATION_ERROR` | Semantic violation (e.g. baseline date after post date). |
| **401** | `AUTHENTICATION_REQUIRED` | Missing or malformed Bearer token / missing API key. |
| **401** | `INVALID_TOKEN` / `TOKEN_EXPIRED` | Expired, tampered, or invalid JWT access token signature. |
| **401** | `INVALID_API_KEY` | Inactive, expired, revoked, or unrecognized field-device API key. |
| **403** | `INSUFFICIENT_PERMISSIONS` | Caller's role does not possess the required RBAC persona privileges, or an IDOR violation occurred. |
| **403** | `ACCOUNT_DISABLED` | Authenticated user account has been deactivated in the database. |
| **403** | `DEVICE_STATION_MISMATCH` | Hardware API key attempted to ingest telemetry for a different camera station (Station Isolation violation). |
| **403** | `CSRF_VALIDATION_FAILED` | Cookie-authenticated request lacked an anti-CSRF header (`X-Requested-With`) or authorized Origin. |
| **404** | `<ENTITY>_NOT_FOUND` | Resource does not exist (`CAMERA_NOT_FOUND`, `DETECTION_NOT_FOUND`, `ENCOUNTER_NOT_FOUND`, `JOB_NOT_FOUND`, `IMAGE_NOT_FOUND`, `MONITORINGACTION_NOT_FOUND`, `USER_NOT_FOUND`). |
| **409** | `STALE_REVISION_CONFLICT` | Optimistic concurrency collision during human review. The submitted `expected_revision` does not match the server's current dataset revision. |
| **422** | `REQUEST_VALIDATION_FAILED` | Pydantic schema validation error (missing required fields, incorrect datatypes, out-of-range coordinates). Details contain field-specific errors. |
| **500** | `INTERNAL_SERVER_ERROR` | Unhandled server exception. Contains error type and description. |
| **503** | `MODULE_UNAVAILABLE` | External component offline (e.g., inference worker process unlinked). |

### Pagination Parameters
All listing endpoints support standard offset-based pagination:
- `limit` (integer, query param): Number of records to return. Default: `20` (or `50` for telemetry). Bounds: `1 <= limit <= 100`.
- `offset` (integer, query param): Number of records to skip. Default: `0`. Bounds: `offset >= 0`.

### Optimistic Concurrency & Dataset Revisions
WILDSCOPE manages collaborative expert review using a monotonic integer: `dataset_revision`.
1. The dataset revision begins at `1`.
2. When reviewers query observations (`GET /api/v1/observations`), the response `meta.dataset_revision` provides the current version.
3. Submitting a review (`POST /api/v1/reviews`) requires passing `expected_revision: <integer>`.
4. If another reviewer committed a decision in the interim, the server detects `expected_revision != current_revision` and immediately rejects the submission with **HTTP 409 Conflict** (`STALE_REVISION_CONFLICT`).
5. On successful review submission, `dataset_revision` is atomically incremented by `+1`, and the resulting revision is returned.

### Scientific Invariants & Immutability Rules
The backend enforces core ecological and scientific integrity rules at the database and application levels:
1. **Raw Model Prediction Immutability:** Once a `Detection` row is created by the inference worker, its bounding box (`bbox_x`, `bbox_y`, `bbox_w`, `bbox_h`), raw confidence score (`score`), and raw label (`raw_label`) can **never** be edited or overwritten. Only the `review_status` column transitions.
2. **Permanent Audit Log:** Review events are stored append-only in `review_events`. Rows cannot be updated or deleted. Database foreign keys use `ON DELETE RESTRICT` to prevent accidental deletion of audited detections.
3. **Decoupling Telemetry from Observation Silence:** A camera trap station that has not transmitted animal images is **not** dead. Telemetry status (`reporting`, `stale`, `unknown`) is computed strictly from hardware heartbeat logs (`last_heartbeat_at`) against a configurable 24-hour freshness window.
4. **Non-Causal Monitoring Evaluation:** Maintenance intervention feedback (`/feedback`) explicitly disclaims causal inference (`is_causal: false`). When evaluation windows are missing or lack activity, the endpoint returns `status: "insufficient_data"`.
5. **Timezone Integrity:** All timestamps accepted and emitted by the API are normalized to **UTC**. Naive local timestamps without timezone offsets are rejected to prevent diurnal/nocturnal activity corruption.

---

## 2. Endpoint Directory & Group Summary

The WILDSCOPE AI backend exposes **22 fully functional endpoints** across 8 operational groups with strictly enforced Role-Based Access Control (RBAC):

| # | Method | Path | Group | Allowed Personas | Description |
|---|:---|:---|:---|:---|:---|
| 1 | `POST` | `/api/v1/auth/login` | Authentication & Identity | Public | Authenticate credentials; return JWT and Set-Cookie |
| 2 | `POST` | `/api/v1/auth/refresh` | Authentication & Identity | Public / Cookie | Single-use rotation; issue new access token |
| 3 | `POST` | `/api/v1/auth/logout` | Authentication & Identity | Public / Cookie | Revoke refresh token lineage; clear cookie |
| 4 | `GET` | `/api/v1/auth/me` | Authentication & Identity | Viewer, Researcher, Admin | Retrieve profile of authenticated user |
| 5 | `GET` | `/api/v1/health` | Health & Diagnostics | Public | System health, database connectivity, honest worker status |
| 6 | `POST` | `/api/v1/uploads` | Uploads & Ingestion | Researcher, Admin | Multipart media streaming, deduplication, queue job |
| 7 | `GET` | `/api/v1/jobs/{job_id}` | Persistent Jobs | Job Owner, Admin | Background job progress, per-item errors (IDOR protected) |
| 8 | `GET` | `/api/v1/images/{image_id}/content` | Media Serving | Viewer, Researcher, Admin | Safe binary streaming of images and video frames |
| 9 | `GET` | `/api/v1/observations` | Observations | Viewer, Researcher, Admin | Paginated detections; coordinates obfuscated for Viewers |
| 10 | `GET` | `/api/v1/encounters/{encounter_id}` | Encounters | Viewer, Researcher, Admin | Temporal grouping details, member media links |
| 11 | `POST` | `/api/v1/reviews` | Human Review (F20) | Researcher, Admin | Append-only review decision (reviewer_id bound to token) |
| 12 | `GET` | `/api/v1/reviews/{detection_id}` | Human Review (F20) | Viewer, Researcher, Admin | Chronological audit trail for a specific detection |
| 13 | `GET` | `/api/v1/cameras` | Camera Health (F07) | Viewer, Researcher, Admin | Camera list; coordinates obfuscated for Viewers |
| 14 | `POST` | `/api/v1/cameras` | Camera Health (F07) | Admin only | Register a new camera trap station (HTTP 201) |
| 15 | `GET` | `/api/v1/cameras/{camera_id}` | Camera Health (F07) | Viewer, Researcher, Admin | Diagnostics; coordinates obfuscated for Viewers |
| 16 | `POST` | `/api/v1/cameras/{camera_id}/telemetry` | Camera Health (F07) | Device API Key, Admin, Researcher | Ingest telemetry (enforces station isolation) |
| 17 | `GET` | `/api/v1/cameras/{camera_id}/telemetry` | Camera Health (F07) | Viewer, Researcher, Admin | Paginated telemetry logs for a station |
| 18 | `GET` | `/api/v1/monitoring` | Monitoring Network (F11) | Viewer, Researcher, Admin | Holistic network health summary & recent interventions |
| 19 | `GET` | `/api/v1/monitoring-actions` | Monitoring Actions (F11) | Viewer, Researcher, Admin | Paginated list of field interventions |
| 20 | `POST` | `/api/v1/monitoring-actions` | Monitoring Actions (F11) | Researcher, Admin | Log field maintenance action; stamps created_by_user_id |
| 21 | `GET` | `/api/v1/monitoring-actions/{action_id}` | Monitoring Actions (F11) | Viewer, Researcher, Admin | Retrieve specific intervention details |
| 22 | `GET` | `/api/v1/monitoring-actions/{action_id}/feedback` | Monitoring Actions (F11) | Viewer, Researcher, Admin | Effort-qualified before/after comparison metrics |

---

## Group 0: Authentication & Identity Management

### `POST /api/v1/auth/login`
Authenticates a user using username or email and plaintext password. Enforces Argon2id verification with PBKDF2 fallback.

- **HTTP Method:** `POST`
- **Path:** `/api/v1/auth/login`
- **Authentication:** Public
- **Request Body:**
  ```json
  {
    "username_or_email": "researcher_elena",
    "password": "StrongPassword123!"
  }
  ```
- **Response: HTTP 200 OK**
  - **Headers:** `Set-Cookie: wildscope_refresh_token=<token>; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth`
  - **Body:**
    ```json
    {
      "data": {
        "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
        "token_type": "bearer",
        "expires_in": 1800,
        "user": {
          "id": "u_8f93a10c",
          "username": "researcher_elena",
          "email": "elena@wildscope.org",
          "role": "researcher",
          "full_name": "Elena Researcher",
          "is_active": true
        }
      },
      "meta": { "dataset_revision": 1 }
    }
    ```

### `POST /api/v1/auth/refresh`
Performs single-use refresh token rotation (RTR). Invalidates the old token, issues a fresh access token, and sets a new rotated refresh cookie. Detects replay attacks and revokes the entire token family upon reuse attempt.

- **HTTP Method:** `POST`
- **Path:** `/api/v1/auth/refresh`
- **Authentication:** HttpOnly Cookie (or JSON body `refresh_token`)
- **Headers:** `X-Requested-With: XMLHttpRequest` (anti-CSRF header for cookie requests)
- **Response: HTTP 200 OK**

### `POST /api/v1/auth/logout`
Revokes the caller's active refresh token in the database and explicitly clears the HttpOnly session cookie.

- **HTTP Method:** `POST`
- **Path:** `/api/v1/auth/logout`
- **Authentication:** HttpOnly Cookie (or JSON body `refresh_token`)
- **Response: HTTP 200 OK**

### `GET /api/v1/auth/me`
Retrieves the profile and authorization scope of the currently authenticated caller.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/auth/me`
- **Authentication:** Bearer JWT (`Viewer`, `Researcher`, or `Admin`)
- **Response: HTTP 200 OK**

---

## Group 1: Health & System Diagnostics

### `GET /api/v1/health`
Retrieves overall system status, verifies live SQLite database connectivity, and performs an honest inspection of inference worker readiness.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/health`
- **Authentication:** Unauthenticated
- **Headers:** Optional `X-Request-ID`

#### Request Parameters
None.

#### Response: HTTP 200 OK
```json
{
  "data": {
    "status": "healthy",
    "version": "0.1.0",
    "environment": "development",
    "database": {
      "status": "healthy",
      "dialect": "sqlite"
    },
    "worker": {
      "ready": false,
      "status": "unavailable",
      "details": "Inference worker process is not connected. Media will be queued in SQLite."
    }
  },
  "meta": {
    "dataset_revision": 1
  }
}
```

#### Possible Errors
- **500 Internal Server Error:** Database connectivity failure or engine configuration fault.

---

## Group 2: Media Uploads & Persistent Jobs

### `POST /api/v1/uploads`
Uploads one or more camera-trap images or videos. Validates magic bytes (JPEG, PNG, MP4), computes deterministic SHA-256 hashes, stores binaries in content-addressed storage outside the database, creates a persistent job in SQLite, and schedules asynchronous inference.

- **HTTP Method:** `POST`
- **Path:** `/api/v1/uploads`
- **Content-Type:** `multipart/form-data`
- **Status Code on Success:** `202 Accepted`

#### Request Parameters
- **Form Data:**
  - `files` (required, `file[]`): One or more image or video files.
  - `camera_id` (optional, `string`): Camera station identifier where media was captured. If provided, must match an existing registered camera station.
  - `captured_at` (optional, `string`): ISO-8601 UTC timestamp of media capture (e.g. `2026-10-31T08:30:00Z`).

#### Response: HTTP 202 Accepted
```json
{
  "data": {
    "upload_id": "up_a9f182c03d12",
    "job_id": "job_01hgb72k904f",
    "files_received": 1,
    "status": "queued",
    "media_items": [
      {
        "media_id": "med_3f2b1a8c90de",
        "frame_id": "frm_7e6d5c4b3a21",
        "filename": "camera_trap_01.jpg",
        "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "is_duplicate": false,
        "content_url": "/api/v1/images/frm_7e6d5c4b3a21/content"
      }
    ]
  },
  "meta": {
    "dataset_revision": 1
  }
}
```

#### Possible Errors
- **404 Not Found (`CAMERA_NOT_FOUND`):** The provided `camera_id` does not exist in the database.
- **422 Unprocessable Entity (`DOMAIN_VALIDATION_ERROR`):** Zero files uploaded, or invalid ISO-8601 timestamp string.
- **422 Unprocessable Entity (`REQUEST_VALIDATION_FAILED`):** Unsupported media signature (magic bytes do not match JPEG, PNG, or MP4).

---

### `GET /api/v1/jobs/{job_id}`
Retrieves the persistent state and progress percentage of a background ingestion/inference job.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/jobs/{job_id}`

#### Path Parameters
- `job_id` (string, required): Unique job identifier returned by `POST /api/v1/uploads`.

#### Response: HTTP 200 OK
```json
{
  "data": {
    "id": "job_01hgb72k904f",
    "upload_id": "up_a9f182c03d12",
    "status": "completed",
    "progress": 100.0,
    "total_items": 1,
    "processed_items": 1,
    "media_ids": [
      "med_3f2b1a8c90de"
    ],
    "run_id": "run_98234ab1c",
    "failures": [],
    "error_message": null,
    "created_at": "2026-10-31T04:15:00Z",
    "updated_at": "2026-10-31T04:15:04Z",
    "completed_at": "2026-10-31T04:15:04Z"
  },
  "meta": {
    "dataset_revision": 1
  }
}
```

#### Job Status Lifecycle
- `queued`: Media is stored; awaiting worker pickup. Progress: `0.0%`.
- `running`: Inference worker is processing frames. Progress: `0.0% - 99.9%`.
- `completed`: All frames processed successfully. Progress: `100.0%`.
- `partial`: Some frames succeeded, but others encountered worker errors. `failures` array populated.
- `failed`: Job aborted due to critical worker crash or missing media file. `error_message` populated.

#### Possible Errors
- **404 Not Found (`JOB_NOT_FOUND`):** Job ID not found in database.

---

## Group 3: Media Serving & Detections

### `GET /api/v1/images/{image_id}/content`
Safely streams raw binary media content (JPEG, PNG, MP4) directly from content-addressed storage. Prevents path traversal and never exposes internal host paths.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/images/{image_id}/content`

#### Path Parameters
- `image_id` (string, required): Either an `ImageFrame.id` or a parent `MediaAsset.id`.

#### Response: HTTP 200 OK
- **Headers:**
  - `Content-Type`: `image/jpeg`, `image/png`, or `video/mp4`
  - `Content-Disposition`: `inline; filename="frm_7e6d5c4b3a21.jpg"`
- **Body:** Binary byte stream.

#### Possible Errors
- **404 Not Found (`IMAGE_NOT_FOUND`):** Specified ID not found in database.
- **404 Not Found (`IMAGECONTENT_NOT_FOUND`):** Media record exists, but binary is missing on disk.

---

### `GET /api/v1/observations`
Retrieves a paginated list of wildlife detections produced by inference workers, complete with normalized bounding boxes, confidence scores, species taxonomy mappings, and review statuses.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/observations`

#### Query Parameters
- `camera_id` (optional, string): Filter detections captured at a specific camera station.
- `taxon_id` (optional, string): Filter by standardized taxonomy identifier (e.g. `panthera_tigris`).
- `review_status` (optional, string): Filter by review state (`pending`, `confirmed`, `corrected`, `rejected`, `deferred`).
- `limit` (optional, int, default `20`, max `100`): Page size.
- `offset` (optional, int, default `0`): Page offset.

#### Response: HTTP 200 OK
```json
{
  "data": [
    {
      "id": "det_9823a01f",
      "image_id": "frm_7e6d5c4b3a21",
      "encounter_id": "enc_5521b44c",
      "bbox": [0.125, 0.334, 0.450, 0.520],
      "raw_label": "tiger",
      "taxon_id": "panthera_tigris",
      "label": "Bengal Tiger",
      "score": 0.942,
      "detection_score": 0.965,
      "classification_score": 0.942,
      "score_type": "softmax_probability",
      "calibration_status": "uncalibrated",
      "alternatives": {
        "panthera_pardus": 0.041,
        "cuon_alpinus": 0.012
      },
      "model_version": "yolov8x-wildlife-v2.1",
      "review_status": "pending",
      "provenance": "inferred",
      "created_at": "2026-10-31T04:15:03Z"
    }
  ],
  "meta": {
    "dataset_revision": 3,
    "total": 1,
    "limit": 20,
    "offset": 0
  }
}
```

#### Field Notes for Frontend Display
- `bbox`: Array of `[x_min, y_min, width, height]` normalized between `0.0` and `1.0`. Multiply by image dimensions to render bounding boxes over canvas/DOM.
- `score`: Primary model confidence score bounded `[0.0, 1.0]`.
- `review_status`: State of human expert review. Unreviewed detections have `review_status: "pending"`.

---

## Group 4: Wildlife Encounters

### `GET /api/v1/encounters/{encounter_id}`
Retrieves a spatio-temporal encounter record grouping related images and detections, along with its dynamically aggregated review status.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/encounters/{encounter_id}`

#### Path Parameters
- `encounter_id` (string, required): Stable encounter identifier (e.g. `enc_5521b44c`).

#### Response: HTTP 200 OK
```json
{
  "data": {
    "id": "enc_5521b44c",
    "camera_id": "CAM-01",
    "start_at": "2026-10-31T04:12:10Z",
    "end_at": "2026-10-31T04:15:30Z",
    "grouping_rule_version": "temporal_window_10m_v1",
    "review_status": "pending",
    "provenance": "inferred",
    "image_ids": [
      "frm_7e6d5c4b3a21",
      "frm_8f7e6d5c4b32"
    ],
    "detection_ids": [
      "det_9823a01f",
      "det_9823a020"
    ]
  },
  "meta": {
    "dataset_revision": 3
  }
}
```

#### Encounter Review Status Aggregation Logic
The encounter's `review_status` is automatically derived from member detections:
- **`pending`**: All member detections are in `pending` review state.
- **`partially_reviewed`**: Some detections reviewed, but at least one remains `pending`.
- **`reviewed`**: All member detections have been reviewed (`confirmed`, `corrected`, `rejected`, or `deferred`).

#### Possible Errors
- **404 Not Found (`ENCOUNTER_NOT_FOUND`):** Specified encounter ID does not exist.

---

## Group 5: Human Review & Auditability (F20)

### `POST /api/v1/reviews`
Submits an append-only human review decision for a model detection. Enforces raw prediction immutability, checks optimistic concurrency, updates the detection review status, updates the parent encounter status, and atomically increments the dataset revision.

- **HTTP Method:** `POST`
- **Path:** `/api/v1/reviews`
- **Status Code on Success:** `201 Created`

#### Request Body Schema (`ReviewCreateRequest`)
```json
{
  "detection_id": "det_9823a01f",
  "decision": "confirmed",
  "corrected_taxon_id": null,
  "reason": "Clear diagnostic flank stripe patterns visible in daylight.",
  "reviewer_id": "laasya_reviewer_01",
  "expected_revision": 3,
  "provenance": "observed"
}
```

#### Request Validation Rules
- `decision` (required, string): Must be one of `"confirmed"`, `"corrected"`, `"rejected"`, or `"deferred"`. Submitting `"pending"` is strictly rejected with HTTP 422.
- `corrected_taxon_id` (conditional, string): Required if `decision == "corrected"`. Must be omitted or null for other decisions.
- `reason` (required, string): Non-empty justification text. Blank whitespace is rejected.
- `reviewer_id` (required, string): Identity of the reviewer.
- `expected_revision` (required, integer >= 1): The dataset revision the reviewer saw when loading the observation.

#### Response: HTTP 201 Created
```json
{
  "data": {
    "id": "rev_01hb98c11aa",
    "detection_id": "det_9823a01f",
    "decision": "confirmed",
    "corrected_taxon_id": null,
    "reason": "Clear diagnostic flank stripe patterns visible in daylight.",
    "reviewer_id": "laasya_reviewer_01",
    "expected_revision": 3,
    "resulting_revision": 4,
    "provenance": "observed",
    "created_at": "2026-10-31T04:22:15Z"
  },
  "meta": {
    "dataset_revision": 4
  }
}
```

#### Possible Errors
- **404 Not Found (`DETECTION_NOT_FOUND`):** `detection_id` does not match an existing detection.
- **409 Conflict (`STALE_REVISION_CONFLICT`):** `expected_revision` does not match server dataset revision:
  ```json
  {
    "error": {
      "code": "STALE_REVISION_CONFLICT",
      "message": "Stale dataset revision conflict. Please refresh and retry.",
      "details": {
        "expected_revision": 2,
        "current_revision": 3
      }
    },
    "request_id": "e0a1b2c3-4d5e-6f7a-8b9c-0d1e2f3a4b5c"
  }
  ```
- **422 Unprocessable Entity (`DOMAIN_VALIDATION_ERROR` or `REQUEST_VALIDATION_FAILED`):** Missing `corrected_taxon_id` when `decision == "corrected"`, or empty reason.

---

### `GET /api/v1/reviews/{detection_id}`
Retrieves the complete chronological, immutable audit log of all human review events for a detection.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/reviews/{detection_id}`

#### Path Parameters
- `detection_id` (string, required): Stable detection identifier.

#### Response: HTTP 200 OK
```json
{
  "data": [
    {
      "id": "rev_01hb98c11aa",
      "detection_id": "det_9823a01f",
      "decision": "confirmed",
      "corrected_taxon_id": null,
      "reason": "Clear diagnostic flank stripe patterns visible in daylight.",
      "reviewer_id": "laasya_reviewer_01",
      "expected_revision": 3,
      "resulting_revision": 4,
      "provenance": "observed",
      "created_at": "2026-10-31T04:22:15Z"
    }
  ],
  "meta": {
    "dataset_revision": 4
  }
}
```

#### Possible Errors
- **404 Not Found (`DETECTION_NOT_FOUND`):** Specified detection does not exist.

---

## Group 6: Camera Stations & Telemetry (F07)

### `GET /api/v1/cameras`
Retrieves a paginated list of camera trap stations with dynamically computed hardware telemetry freshness.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/cameras`

#### Query Parameters
- `telemetry_status` (optional, string): Filter by telemetry state: `"reporting"`, `"stale"`, or `"unknown"`.
- `limit` (optional, int, default `20`, max `100`): Page size.
- `offset` (optional, int, default `0`): Page offset.

#### Response: HTTP 200 OK
```json
{
  "data": [
    {
      "id": "CAM-01",
      "label": "Waterhole Ridge South",
      "timezone": "Asia/Kolkata",
      "coordinates": [76.952, 11.662],
      "telemetry_status": "reporting",
      "last_heartbeat_at": "2026-10-31T04:00:00Z",
      "active_camera_days": 45.5,
      "provenance": "observed",
      "created_at": "2026-09-15T00:00:00Z"
    }
  ],
  "meta": {
    "dataset_revision": 4,
    "total": 1,
    "limit": 20,
    "offset": 0
  }
}
```

---

### `POST /api/v1/cameras`
Registers a new camera trap monitoring station.

- **HTTP Method:** `POST`
- **Path:** `/api/v1/cameras`
- **Status Code on Success:** `201 Created`

#### Request Body Schema (`CameraCreateRequest`)
```json
{
  "id": "CAM-03",
  "label": "Bamboo Valley Crossing",
  "timezone": "Asia/Kolkata",
  "coordinates": [76.945, 11.658],
  "active_camera_days": 12.0,
  "provenance": "observed"
}
```

#### Request Validation Rules
- `id` (required, string, 1-36 chars): Unique station ID. Cannot be blank.
- `label` (required, string, 1-200 chars): Descriptive station label.
- `coordinates` (optional, `[longitude, latitude]`): WGS84 coordinates. Longitude must be `[-180, 180]`; Latitude must be `[-90, 90]`.
- `active_camera_days` (optional, float >= 0.0): Effort baseline in operational trap-days.

#### Response: HTTP 201 Created
```json
{
  "data": {
    "id": "CAM-03",
    "label": "Bamboo Valley Crossing",
    "timezone": "Asia/Kolkata",
    "coordinates": [76.945, 11.658],
    "telemetry_status": "unknown",
    "last_heartbeat_at": null,
    "active_camera_days": 12.0,
    "provenance": "observed",
    "created_at": "2026-10-31T04:30:00Z"
  },
  "meta": {
    "dataset_revision": 4
  }
}
```

#### Possible Errors
- **422 Unprocessable Entity (`DOMAIN_VALIDATION_ERROR`):** Camera station ID already exists.
- **422 Unprocessable Entity (`REQUEST_VALIDATION_FAILED`):** Coordinates out of geographic bounds.

---

### `GET /api/v1/cameras/{camera_id}`
Retrieves deep diagnostic metrics for a specific camera station. Explicitly decouples hardware telemetry health from visual observation quality.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/cameras/{camera_id}`

#### Path Parameters
- `camera_id` (string, required): Camera station ID.

#### Response: HTTP 200 OK
```json
{
  "data": {
    "id": "CAM-01",
    "label": "Waterhole Ridge South",
    "timezone": "Asia/Kolkata",
    "coordinates": [76.952, 11.662],
    "telemetry_status": "reporting",
    "last_heartbeat_at": "2026-10-31T04:00:00Z",
    "active_camera_days": 45.5,
    "provenance": "observed",
    "telemetry_health": {
      "status": "reporting",
      "freshness_threshold_hours": 24.0,
      "latest_telemetry": {
        "id": "tel_01hgb89a",
        "observed_at": "2026-10-31T04:00:00Z",
        "battery_level": 84.5,
        "signal_strength": -72.0,
        "error_codes": [],
        "source": "satellite_relay"
      }
    },
    "observation_quality": {
      "total_images": 142,
      "quality_flags_summary": {
        "low_light": 28,
        "lens_obscured": 4
      },
      "scientific_rule": "Visual quality flags and image silence are decoupled from hardware telemetry state."
    }
  },
  "meta": {
    "dataset_revision": 4
  }
}
```

#### Possible Errors
- **404 Not Found (`CAMERA_NOT_FOUND`):** Camera ID does not exist.

---

### `POST /api/v1/cameras/{camera_id}/telemetry`
Ingests a hardware telemetry event log (heartbeat, battery level, cellular signal, error codes) for a camera station. Updates the camera's `last_heartbeat_at` timestamp and recalculates freshness.

- **HTTP Method:** `POST`
- **Path:** `/api/v1/cameras/{camera_id}/telemetry`
- **Status Code on Success:** `201 Created`

#### Path Parameters
- `camera_id` (string, required): Camera station ID.

#### Request Body Schema (`TelemetryCreateRequest`)
```json
{
  "observed_at": "2026-10-31T04:00:00Z",
  "battery_level": 84.5,
  "signal_strength": -72.0,
  "error_codes": [],
  "raw_payload": {
    "firmware": "v2.4.1",
    "solar_charge_mv": 12400
  },
  "source": "satellite_relay"
}
```

#### Response: HTTP 201 Created
```json
{
  "data": {
    "id": "tel_01hgb89a",
    "camera_id": "CAM-01",
    "observed_at": "2026-10-31T04:00:00Z",
    "battery_level": 84.5,
    "signal_strength": -72.0,
    "error_codes": [],
    "raw_payload": {
      "firmware": "v2.4.1",
      "solar_charge_mv": 12400
    },
    "source": "satellite_relay",
    "created_at": "2026-10-31T04:01:00Z"
  },
  "meta": {
    "dataset_revision": 4
  }
}
```

#### Possible Errors
- **404 Not Found (`CAMERA_NOT_FOUND`):** Camera station does not exist.
- **422 Unprocessable Entity (`REQUEST_VALIDATION_FAILED`):** Naive non-UTC datetime string.

---

### `GET /api/v1/cameras/{camera_id}/telemetry`
Retrieves paginated historical telemetry logs for a camera station.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/cameras/{camera_id}/telemetry`

#### Path Parameters
- `camera_id` (string, required): Camera station ID.

#### Query Parameters
- `limit` (optional, int, default `50`, max `100`): Page size.
- `offset` (optional, int, default `0`): Page offset.

#### Response: HTTP 200 OK
```json
{
  "data": [
    {
      "id": "tel_01hgb89a",
      "camera_id": "CAM-01",
      "observed_at": "2026-10-31T04:00:00Z",
      "battery_level": 84.5,
      "signal_strength": -72.0,
      "error_codes": [],
      "raw_payload": { "firmware": "v2.4.1" },
      "source": "satellite_relay",
      "created_at": "2026-10-31T04:01:00Z"
    }
  ],
  "meta": {
    "dataset_revision": 4,
    "total": 1,
    "limit": 50,
    "offset": 0
  }
}
```

---

## Group 7: Monitoring Network & Feedback (F11)

### `GET /api/v1/monitoring`
Provides a holistic camera network monitoring health summary across all deployed stations.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/monitoring`

#### Response: HTTP 200 OK
```json
{
  "data": {
    "total_cameras": 3,
    "telemetry_health_breakdown": {
      "reporting": 2,
      "stale": 1,
      "unknown": 0
    },
    "total_telemetry_logs": 84,
    "total_monitoring_actions": 6,
    "freshness_threshold_hours": 24.0,
    "recent_actions": [
      {
        "id": "act_8821a0",
        "camera_id": "CAM-02",
        "action_type": "lens_clean",
        "description": "Cleaned thick mud spatters after monsoon rains.",
        "performed_at": "2026-10-30T10:00:00Z",
        "source": "field_ranger_anil"
      }
    ]
  },
  "meta": {
    "dataset_revision": 4
  }
}
```

---

### `GET /api/v1/monitoring-actions`
Retrieves a paginated list of field interventions (maintenance actions).

- **HTTP Method:** `GET`
- **Path:** `/api/v1/monitoring-actions`

#### Query Parameters
- `camera_id` (optional, string): Filter actions for a single camera station.
- `limit` (optional, int, default `20`, max `100`): Page size.
- `offset` (optional, int, default `0`): Page offset.

#### Response: HTTP 200 OK
```json
{
  "data": [
    {
      "id": "act_8821a0",
      "camera_id": "CAM-02",
      "action_type": "lens_clean",
      "description": "Cleaned thick mud spatters after monsoon rains.",
      "performed_at": "2026-10-30T10:00:00Z",
      "baseline_start": "2026-10-15T00:00:00Z",
      "baseline_end": "2026-10-30T09:59:59Z",
      "post_start": "2026-10-30T10:00:01Z",
      "post_end": "2026-11-14T23:59:59Z",
      "source": "field_ranger_anil",
      "created_at": "2026-10-30T10:15:00Z"
    }
  ],
  "meta": {
    "dataset_revision": 4,
    "total": 1,
    "limit": 20,
    "offset": 0
  }
}
```

---

### `POST /api/v1/monitoring-actions`
Logs a new field intervention, such as lens cleaning, battery replacement, repositioning, or firmware upgrades. Supports defining baseline and post-intervention observation windows for feedback analysis.

- **HTTP Method:** `POST`
- **Path:** `/api/v1/monitoring-actions`
- **Status Code on Success:** `201 Created`

#### Request Body Schema (`MonitoringActionCreateRequest`)
```json
{
  "camera_id": "CAM-02",
  "action_type": "lens_clean",
  "description": "Cleaned thick mud spatters after monsoon rains.",
  "performed_at": "2026-10-30T10:00:00Z",
  "baseline_start": "2026-10-15T00:00:00Z",
  "baseline_end": "2026-10-30T09:59:59Z",
  "post_start": "2026-10-30T10:00:01Z",
  "post_end": "2026-11-14T23:59:59Z",
  "source": "field_ranger_anil"
}
```

#### Request Validation Rules
- `camera_id` (required, string): Must match an existing registered camera.
- `action_type` (required, string): e.g. `lens_clean`, `battery_replace`, `reposition`, `firmware_update`.
- `description` (required, string): Non-blank operational notes.
- `performed_at` (required, UTC datetime): When the intervention occurred.
- `baseline_start` & `baseline_end` (optional, UTC datetime): Pre-intervention comparison window. If both provided, `baseline_start <= baseline_end`.
- `post_start` & `post_end` (optional, UTC datetime): Post-intervention comparison window. If both provided, `post_start <= post_end`.

#### Response: HTTP 201 Created
```json
{
  "data": {
    "id": "act_8821a0",
    "camera_id": "CAM-02",
    "action_type": "lens_clean",
    "description": "Cleaned thick mud spatters after monsoon rains.",
    "performed_at": "2026-10-30T10:00:00Z",
    "baseline_start": "2026-10-15T00:00:00Z",
    "baseline_end": "2026-10-30T09:59:59Z",
    "post_start": "2026-10-30T10:00:01Z",
    "post_end": "2026-11-14T23:59:59Z",
    "source": "field_ranger_anil",
    "created_at": "2026-10-30T10:15:00Z"
  },
  "meta": {
    "dataset_revision": 4
  }
}
```

#### Possible Errors
- **404 Not Found (`CAMERA_NOT_FOUND`):** Associated camera does not exist.
- **422 Unprocessable Entity (`DOMAIN_VALIDATION_ERROR`):** Window inversion (`baseline_start > baseline_end`).

---

### `GET /api/v1/monitoring-actions/{action_id}`
Retrieves a specific field intervention record by ID.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/monitoring-actions/{action_id}`

#### Path Parameters
- `action_id` (string, required): Intervention ID.

#### Response: HTTP 200 OK
Returns the single monitoring action object wrapped in `data`.

#### Possible Errors
- **404 Not Found (`MONITORINGACTION_NOT_FOUND`):** Action ID does not exist.

---

### `GET /api/v1/monitoring-actions/{action_id}/feedback`
Evaluates effort-qualified before/after uptime and visual observation quality differences across the configured baseline and post windows.

- **HTTP Method:** `GET`
- **Path:** `/api/v1/monitoring-actions/{action_id}/feedback`

#### Scenario A: Evaluated Feedback (Sufficient Evidence)
```json
{
  "data": {
    "action_id": "act_8821a0",
    "camera_id": "CAM-02",
    "action_type": "lens_clean",
    "status": "evaluated",
    "is_causal": false,
    "causal_claim_disclaimer": "Observational before/after comparison only. Does not establish causal intervention impact. Environmental variability, seasonal animal movements, and local weather may confound metric differences.",
    "baseline_metrics": {
      "window_days": 15.42,
      "heartbeat_count": 36,
      "heartbeat_rate_per_day": 2.33,
      "avg_battery_level": 74.2,
      "image_count": 48,
      "image_rate_per_day": 3.11,
      "flagged_degraded_images": 21,
      "degradation_ratio": 0.438
    },
    "post_metrics": {
      "window_days": 15.58,
      "heartbeat_count": 38,
      "heartbeat_rate_per_day": 2.44,
      "avg_battery_level": 72.8,
      "image_count": 52,
      "image_rate_per_day": 3.34,
      "flagged_degraded_images": 2,
      "degradation_ratio": 0.038
    },
    "observed_changes": {
      "delta_avg_battery": -1.4,
      "delta_heartbeat_rate_per_day": 0.11,
      "delta_image_rate_per_day": 0.23,
      "delta_degradation_ratio": -0.400
    },
    "limitations": [
      "Observational study only; does not isolate natural environmental variations from intervention.",
      "Non-randomized intervention timing.",
      "Wildlife encounter rates depend on seasonal animal presence, not merely camera functioning."
    ]
  },
  "meta": {
    "dataset_revision": 4
  }
}
```

#### Scenario B: Insufficient Data (Missing Windows or Zero Activity)
When windows are omitted or zero telemetry/imagery exists in either window:
```json
{
  "data": {
    "action_id": "act_9912b3",
    "camera_id": "CAM-01",
    "action_type": "battery_replace",
    "status": "insufficient_data",
    "reason": "Pre-intervention baseline or post-intervention observation window is undefined.",
    "is_causal": false,
    "causal_claim_disclaimer": "Observational before/after comparison only. Does not establish causal intervention impact. Environmental variability, seasonal animal movements, and local weather may confound metric differences.",
    "limitations": [
      "Cannot evaluate intervention impact without both baseline and post-intervention time bounds."
    ]
  },
  "meta": {
    "dataset_revision": 4
  }
}
```

---

## 10. Discrepancies & Unimplemented Planned Endpoints

The following endpoints were proposed in early design briefs, conceptual workflows, or older solution guide drafts, but are **NOT implemented in the current backend**.

Frontend developers must **not** attempt to call these routes directly; handle their absence gracefully as outlined below:

| Proposed Route | Status | Reason & Module Dependency | Recommended Frontend Fallback |
| :--- | :--- | :--- | :--- |
| `GET /api/v1/analytics/*` | **NOT IMPLEMENTED** | Belongs to Shravan's Intelligence & Analytics module (`src/intelligence/`, `wildscope_analytics/`). Requires full dataset aggregation algorithms. | Render mock dashboard widgets or show a "Analytics Module Pending Integration" banner. |
| `GET /api/v1/review-priorities` | **NOT IMPLEMENTED** | Active Learning prioritization (F04) is pending Harsh/Shravan's uncertainty scoring pipeline. | Fetch `GET /api/v1/observations?review_status=pending` and sort client-side by `score ASC` (low-confidence first). |
| `POST /api/v1/spatial/analyze` | **NOT IMPLEMENTED** | Spatial GIS cluster analysis requires unlinked GeoSpatial backend services. | Render camera stations directly on Leaflet/Mapbox using `coordinates: [lon, lat]` from `GET /api/v1/cameras`. |
| `POST /api/v1/assistant` | **NOT IMPLEMENTED** | Conversational LLM assistant interface (F19) requires LLM API key and external orchestration agent. | Disable the assistant chat tab or display a pre-scripted demonstration FAQ interface. |
| `GET /api/v1/media/{media_id}/content` | **ROUTE VARIATION** | Legacy URL path. The backend routes binary retrieval through `GET /api/v1/images/{image_id}/content`. | Call `/api/v1/images/{id}/content` (the endpoint transparently accepts either `ImageFrame.id` or `MediaAsset.id`). |

---

## 11. Frontend Integration Guide (For Laasya)

### API Client Helper (`apiClient.js`)
Use this production-tested vanilla JavaScript module for interacting with the WILDSCOPE API:

```javascript
/**
 * WILDSCOPE AI — Frontend API Client
 * Compatible with modern browser ES6+ and Node.js fetch.
 */
const API_BASE_URL = "http://127.0.0.1:8000/api/v1";

class WildscopeApiClient {
  constructor(baseUrl = API_BASE_URL) {
    this.baseUrl = baseUrl;
    this.currentDatasetRevision = 1;
  }

  async request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const headers = {
      Accept: "application/json",
      "X-Request-ID": crypto.randomUUID(),
      ...options.headers,
    };

    if (options.body && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }

    const response = await fetch(url, { ...options, headers });
    const responseData = await response.json().catch(() => null);

    if (!response.ok) {
      const error = new Error(responseData?.error?.message || `HTTP ${response.status} Error`);
      error.status = response.status;
      error.code = responseData?.error?.code || "HTTP_ERROR";
      error.details = responseData?.error?.details || {};
      error.requestId = responseData?.request_id || response.headers.get("X-Request-ID");
      throw error;
    }

    // Keep track of the latest dataset revision
    if (responseData?.meta?.dataset_revision) {
      this.currentDatasetRevision = responseData.meta.dataset_revision;
    }

    return responseData;
  }

  // --- Health ---
  getHealth() {
    return this.request("/health");
  }

  // --- Uploads & Jobs ---
  async uploadMedia(fileList, cameraId = null, capturedAt = null) {
    const formData = new FormData();
    for (const file of fileList) {
      formData.append("files", file);
    }
    if (cameraId) formData.append("camera_id", cameraId);
    if (capturedAt) formData.append("captured_at", capturedAt);

    return this.request("/uploads", {
      method: "POST",
      body: formData,
    });
  }

  getJobStatus(jobId) {
    return this.request(`/jobs/${jobId}`);
  }

  // --- Observations & Reviews ---
  getObservations(params = {}) {
    const query = new URLSearchParams(params).toString();
    return this.request(`/observations${query ? `?${query}` : ""}`);
  }

  submitReview({ detectionId, decision, correctedTaxonId = null, reason, reviewerId }) {
    return this.request("/reviews", {
      method: "POST",
      body: {
        detection_id: detectionId,
        decision,
        corrected_taxon_id: correctedTaxonId,
        reason,
        reviewer_id: reviewerId,
        expected_revision: this.currentDatasetRevision,
        provenance: "observed",
      },
    });
  }

  // --- Cameras & Telemetry ---
  getCameras(params = {}) {
    const query = new URLSearchParams(params).toString();
    return this.request(`/cameras${query ? `?${query}` : ""}`);
  }

  getCameraDetails(cameraId) {
    return this.request(`/cameras/${cameraId}`);
  }

  // --- Media URL Helper ---
  getImageUrl(imageId) {
    return `${this.baseUrl}/images/${imageId}/content`;
  }
}

export const wildscopeApi = new WildscopeApiClient();
```

---

### Background Job Polling Pattern
When uploading media files via `POST /api/v1/uploads`, the server responds with `HTTP 202 Accepted` and a `job_id`. The client must poll until the status transitions to `completed`:

```javascript
import { wildscopeApi } from "./apiClient.js";

async function uploadAndAwaitInference(files, onProgress) {
  // 1. Submit upload
  const uploadResponse = await wildscopeApi.uploadMedia(files);
  const jobId = uploadResponse.data.job_id;

  onProgress({ status: "queued", progress: 0 });

  // 2. Poll job status
  const maxPolls = 60; // 60 attempts * 1500ms = 90s timeout
  for (let attempt = 0; attempt < maxPolls; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 1500));

    const job = (await wildscopeApi.getJobStatus(jobId)).data;
    onProgress({ status: job.status, progress: job.progress });

    if (job.status === "completed") {
      return job; // Inference completed; observations are now ready!
    }

    if (job.status === "failed") {
      throw new Error(`Inference job failed: ${job.error_message}`);
    }

    if (job.status === "partial") {
      console.warn("Job completed with partial failures:", job.failures);
      return job;
    }
  }

  throw new Error("Inference processing timed out after 90 seconds.");
}
```

---

### Handling Revision Conflicts (HTTP 409)
In collaborative multi-expert review sessions, two reviewers might submit verdicts simultaneously. The second submission receives `HTTP 409 Conflict`. Handle it smoothly without losing reviewer comments:

```javascript
import { wildscopeApi } from "./apiClient.js";

async function handleReviewSubmission(reviewPayload, showConflictModal) {
  try {
    const res = await wildscopeApi.submitReview(reviewPayload);
    alert(`Review confirmed! Dataset revision is now ${res.meta.dataset_revision}`);
  } catch (err) {
    if (err.status === 409 && err.code === "STALE_REVISION_CONFLICT") {
      // 1. Prompt user: dataset was modified by another reviewer
      const shouldReload = await showConflictModal({
        message: "Another ranger just submitted a review. Refresh to view the latest changes?",
        serverRevision: err.details.current_revision,
      });

      if (shouldReload) {
        // 2. Fetch fresh observations (this updates client revision automatically)
        await refreshObservations();
        // 3. User can now re-submit with the updated revision
      }
    } else {
      alert(`Review submission error: ${err.message}`);
    }
  }
}
```

---

### Interpreting Camera Health vs. Observation Silence
Frontends must accurately reflect camera health without jumping to false conclusions:

```javascript
function renderCameraStatusBadge(camera) {
  // RULE: Decouple telemetry from observation activity
  // Telemetry reflects whether hardware transmits heartbeats.
  switch (camera.telemetry_status) {
    case "reporting":
      return { badge: "Reporting", color: "green", tooltip: "Hardware heartbeat received within 24h" };
    case "stale":
      return { badge: "Stale Telemetry", color: "amber", tooltip: "No heartbeat received in over 24h" };
    case "unknown":
    default:
      return { badge: "No Telemetry", color: "gray", tooltip: "Station does not transmit telemetry logs" };
  }
}

// SCIENTIFIC INTEGRITY RULE:
// If camera.telemetry_status is "reporting" but total_images == 0:
// Do NOT display "Camera Dead" or "Camera Failed"!
// Animals simply may not have walked past the camera.
```

---

**End of API Contract Specification.**  
For discrepancies or backend change requests, contact **Santosh Yuvaraj** on Team ByteStrom.