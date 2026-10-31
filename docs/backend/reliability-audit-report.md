# WILDSCOPE AI — Backend Reliability, Security & Production-Readiness Audit Report

**Module:** WILDSCOPE AI REST API Core (`src/backend`)  
**Accountable Backend Architect:** Santosh Yuvaraj  
**Repository:** `HFT26-TEAM-8`  
**Git Branch:** `santosh`  
**Audit Type:** Comprehensive Technical Audit (Read-Only)  
**Date:** October 31, 2026  
**Status:** **AUDIT COMPLETE — REMEDIATION PLAN PROPOSED**

---

## Executive Summary

A comprehensive, production-readiness, security, and reliability audit of the WILDSCOPE AI backend was conducted. The audit inspected database schemas, ORM models, transaction boundaries, concurrency handling, file storage, API validation, exception propagation, performance characteristics, and test coverage.

### Key Audit Metrics
- **Total Findings:** 11 (1 Critical, 3 High, 5 Medium, 2 Low)
- **Architectural Strengths:** Strong scientific immutability rules, append-only review history, SHA-256 content-addressed deduplication, strict magic-byte verification, path traversal prevention, portable SQLite/PostgreSQL UTC datetimes, and optimistic concurrency via atomic revision updates.
- **Primary Vulnerabilities & Risks:**
  1. *Security:* Endpoints are currently unauthenticated (open to unauthorized review submissions, file uploads, and station creation).
  2. *Functional:* `GET /api/v1/observations` accepts `camera_id` but fails to filter on it due to missing relational joins.
  3. *Performance/DoS:* Memory exhaustion risk from `await uploaded_file.read()` loading entire multi-megabyte files into RAM; in-memory pagination and side-effect database writes on `GET /api/v1/cameras`.
  4. *Performance/Scalability:* Missing database indexes on high-frequency filter columns (`detections.review_status`, `detections.taxon_id`, `detections.created_at`).

---

## 1. Findings Matrix by Severity

| ID | Severity | Category | File & Function | Problem Summary | Impact |
|:---|:---:|:---|:---|:---|:---|
| **C-01** | **CRITICAL** | Security | All API Routers (`src/backend/api/v1/*.py`) | Endpoints lack authentication and authorization middleware. | Any client can submit reviews, alter dataset revisions, upload files, or create cameras. |
| **H-01** | **HIGH** | Functional Defect | `src/backend/api/v1/observations.py` (`list_observations`) | `camera_id` query parameter is accepted but never filtered in SQL. | Passing `?camera_id=CAM-01` returns observations from all cameras in the sanctuary. |
| **H-02** | **HIGH** | Security / DoS | `src/backend/api/v1/uploads.py` (`upload_media`) | Unbounded `await uploaded_file.read()` loads entire upload into RAM. | Concurrent large uploads can cause out-of-memory (OOM) crashes. |
| **H-03** | **HIGH** | Performance | `src/backend/services/camera.py` (`list_cameras`) | In-memory pagination; executes state mutations and `db.commit()` inside GET. | Latency bloat on large networks; write lock contention during read operations. |
| **M-01** | **MEDIUM** | Security | `src/backend/core/exceptions.py` (`general_exception_handler`) | Internal exception details (`str(exc)`) echoed in HTTP 500 responses. | Potential leakage of database table structures, file paths, or internal logic. |
| **M-02** | **MEDIUM** | Storage | `src/backend/api/v1/uploads.py` (`upload_media`) | Multi-file uploads write files to disk before the batch commit completes. | Partial validation failure leaves orphaned binary files on disk. |
| **M-03** | **MEDIUM** | Reliability | `src/backend/api/v1/uploads.py` (`execute_background_job`) | Silent exception swallowing (`except Exception: pass`) outside dispatch. | Background jobs can remain stuck in `queued` state indefinitely without error logs. |
| **M-04** | **MEDIUM** | Performance | `src/backend/models/prediction.py` & `migrations` | Missing indexes on `detections(review_status, taxon_id, created_at)`. | Full table scans on observation queries as detection dataset scales. |
| **M-05** | **MEDIUM** | Performance | `src/backend/services/camera.py` (`get_camera_details`) | Loads all camera `ImageFrame` rows into Python memory to compute flags. | High memory footprint and response latency for high-volume camera stations. |
| **L-01** | **LOW** | Database | `src/backend/db/session.py` (`get_db`) | Session generator lacks explicit `rollback()` in exception/finally blocks. | Relies implicitly on connection close; explicit rollback is safer. |
| **L-02** | **LOW** | Contract | `src/backend/services/jobs.py` (`get_job`) | Entity name in 404 returns `PROCESSINGJOB_NOT_FOUND` instead of `JOB_NOT_FOUND`. | Minor contract naming divergence (already documented in contract v1.0). |

---

## 2. Detailed Technical Findings & Remediation

### Finding C-01: Unauthenticated Endpoints Exposing State Modification
- **Severity:** **CRITICAL**
- **Location:** All route modules in `src/backend/api/v1/`
- **Exact Problem:** There is currently no authentication (API key, Bearer JWT token, or session cookie) or role-based access control (RBAC) protecting endpoints such as `POST /api/v1/reviews`, `POST /api/v1/uploads`, `POST /api/v1/cameras`, or `POST /api/v1/monitoring-actions`.
- **Potential Impact:** Any user or external script can submit unverified review decisions, advance the global dataset revision, register bogus camera stations, or flood the storage system.
- **Recommended Correction:**
  1. For production: Implement a FastAPI security dependency (`HTTPBearer` or `APIKeyHeader`).
  2. For the immediate hackathon stage: Provide an optional demo API key header (e.g. `X-API-Key: wildscope-demo-token`) with a configurable bypass for local testing.
- **Regression Test Needed:** Yes (`test_unauthenticated_requests_rejected_with_401`).

---

### Finding H-01: `camera_id` Filter Defect in Observations API
- **Severity:** **HIGH**
- **Location:** `src/backend/api/v1/observations.py`, lines 24–42:
  ```python
  @router.get("/observations", summary="List Wildlife Observations/Detections")
  def list_observations(
      camera_id: Optional[str] = Query(None, description="Filter by camera ID"),
      taxon_id: Optional[str] = Query(None, description="Filter by mapped taxon ID"),
      review_status: Optional[str] = Query(None, description="Filter by review status"),
      limit: int = Query(20, ge=1, le=100, description="Page limit"),
      offset: int = Query(0, ge=0, description="Page offset"),
      db: Session = Depends(get_db),
  ) -> Dict[str, Any]:
      query = db.query(Detection)

      if taxon_id:
          query = query.filter(Detection.taxon_id == taxon_id)
      if review_status:
          query = query.filter(Detection.review_status == review_status)

      total = query.count()
  ```
- **Exact Problem:** The `camera_id` query parameter is accepted by FastAPI, but the query never applies any filter for `camera_id`.
- **Root Cause:** The `detections` table does not have a direct `camera_id` column. Linkage to camera stations is indirect:
  $$\text{Detection} \longrightarrow \text{ImageFrame} \longrightarrow \text{MediaAsset} \longrightarrow \text{Camera}$$
  Currently, neither `ImageFrame` nor `MediaAsset` is imported or joined in `observations.py`.
- **Potential Impact:** Frontend dashboards and wildlife researchers attempting to filter detections for a specific camera station receive observations from all cameras across the sanctuary.
- **Recommended Correction:**
  Import `ImageFrame` and `MediaAsset` in `src/backend/api/v1/observations.py` and join them when `camera_id` is supplied:
  ```python
  from src.backend.models.media import ImageFrame, MediaAsset

  # Inside list_observations:
  if camera_id:
      query = (
          query.join(ImageFrame, Detection.image_id == ImageFrame.id)
          .join(MediaAsset, ImageFrame.source_media_id == MediaAsset.id)
          .filter(MediaAsset.camera_id == camera_id)
      )
  ```
- **Regression Test Needed:** Yes (`test_list_observations_filters_by_camera_id`).

---

### Finding H-02: Denial of Service via Unbounded In-Memory File Reads
- **Severity:** **HIGH**
- **Location:** `src/backend/api/v1/uploads.py`, line 84:
  ```python
  for uploaded_file in files:
      file_bytes = await uploaded_file.read()
  ```
- **Exact Problem:** `await uploaded_file.read()` reads the entire file payload into a Python `bytes` object in RAM before size verification occurs inside `storage_service.store_media()`.
- **Potential Impact:** If multiple users concurrently upload several 50MB files (or an attacker streams an oversized file), the process memory consumption will spike, triggering the OS Out-Of-Memory (OOM) killer and crashing the backend.
- **Recommended Correction:**
  1. Inspect the `Content-Length` header upfront; reject requests exceeding `MAX_UPLOAD_SIZE_BYTES` before reading.
  2. Read in chunks (e.g. 64KB buffers) and write directly to the temporary file on disk, counting bytes as they arrive. If the byte count exceeds 50MB, abort and delete the temp file immediately.
- **Regression Test Needed:** Yes (`test_upload_file_exceeding_size_limit_aborted_early`).

---

### Finding H-03: In-Memory Pagination and Side-Effect Writes in `GET /api/v1/cameras`
- **Severity:** **HIGH**
- **Location:** `src/backend/services/camera.py`, lines 74–105:
  ```python
  cameras = db.query(Camera).order_by(Camera.created_at.desc()).all()
  ...
  for cam in cameras:
      evaluated_status = self.compute_telemetry_status(cam.last_heartbeat_at, now_utc)
      if cam.telemetry_status != evaluated_status and cam.last_heartbeat_at is not None:
          cam.telemetry_status = evaluated_status
          db.add(cam)
      ...
  db.commit()
  total = len(items)
  paged_items = items[offset : offset + limit]
  ```
- **Exact Problem:**
  1. Every request to `GET /api/v1/cameras` queries **all** camera stations in the database into RAM. Slicing by `offset` and `limit` occurs in Python memory.
  2. A `GET` read endpoint modifies rows (`cam.telemetry_status = evaluated_status`) and executes a transaction commit (`db.commit()`).
- **Potential Impact:**
  - On a camera network with thousands of stations, loading all records causes high latency and memory bloat.
  - Side-effect database writes on `GET` violate REST idempotence and cause SQLite write-lock contention (`database is locked` / `busy_timeout`) during concurrent reads.
- **Recommended Correction:**
  1. Separate read queries from status persistence: Compute status dynamically in Python or via SQL `CASE` expressions without committing DB writes on `GET`.
  2. Apply `offset(offset).limit(limit)` directly in the SQLAlchemy query.
  3. Update persisted `telemetry_status` asynchronously via a background task or during telemetry ingestion (`POST /telemetry`).
- **Regression Test Needed:** Yes (`test_camera_listing_uses_database_pagination`).

---

### Finding M-01: Information Disclosure in General Exception Handler
- **Severity:** **MEDIUM**
- **Location:** `src/backend/core/exceptions.py`, lines 145–150:
  ```python
  @app.exception_handler(Exception)
  async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
      ...
      content={
          "error": {
              "code": "INTERNAL_SERVER_ERROR",
              "message": "An unexpected server error occurred.",
              "details": {"error_type": type(exc).__name__, "description": str(exc)},
          },
          "request_id": request_id,
      }
  ```
- **Exact Problem:** The handler returns `"description": str(exc)` to API callers.
- **Potential Impact:** Database errors (e.g. SQLAlchemy OperationalError) echo table names, column constraints, SQL queries, and local system paths to external clients.
- **Recommended Correction:**
  Condition the details on `settings.DEBUG`:
  ```python
  error_details = (
      {"error_type": type(exc).__name__, "description": str(exc)}
      if settings.DEBUG
      else {"error_type": type(exc).__name__}
  )
  ```
- **Regression Test Needed:** Yes (`test_production_error_handler_masks_sensitive_details`).

---

### Finding M-02: Orphaned Files on Multi-File Upload Failure
- **Severity:** **MEDIUM**
- **Location:** `src/backend/api/v1/uploads.py`, lines 83–106
- **Exact Problem:** In a multi-file upload batch, files are written to disk inside the loop (`storage_service.store_media()`). If file 1 succeeds and file 2 fails validation, the database transaction rolls back, but file 1 remains permanently on disk.
- **Potential Impact:** Accumulation of orphaned, unreferenced binary files on disk over time, consuming storage space.
- **Recommended Correction:**
  Maintain a list of newly created file paths during the batch. In an `except` block before returning the error, delete any newly written files if the database transaction did not commit.
- **Regression Test Needed:** Yes (`test_multi_file_upload_failure_cleans_up_disk_files`).

---

### Finding M-03: Silent Exception Swallowing in `execute_background_job`
- **Severity:** **MEDIUM**
- **Location:** `src/backend/api/v1/uploads.py`, lines 32–47:
  ```python
  def execute_background_job(job_id: str, media_ids: List[str]) -> None:
      db = SessionLocal()
      try:
          media_assets = db.query(MediaAsset).filter(MediaAsset.id.in_(media_ids)).all()
          inference_adapter.dispatch_batch_job(db, job_id, media_assets)
      except Exception as exc:
          # If worker is unavailable or crashed, job_service has already recorded failure
          pass
      finally:
          db.close()
  ```
- **Exact Problem:** The `except Exception: pass` block assumes all failures were already handled. If an unexpected exception occurs outside `dispatch_batch_job` (e.g. DB connection dropped during query), the exception is swallowed silently.
- **Potential Impact:** The job remains stuck in `queued` status indefinitely. The user sees `progress: 0.0` with no error message.
- **Recommended Correction:**
  Log the exception with `logger.exception()` and explicitly ensure `job_service.fail_job(db, job_id, error_message=str(exc))` is executed if the job is not already in a terminal state.
- **Regression Test Needed:** Yes (`test_background_job_marks_failure_on_unhandled_exception`).

---

### Finding M-04: Missing Database Indexes on High-Frequency Columns
- **Severity:** **MEDIUM**
- **Location:** `src/backend/models/prediction.py`, `migrations/versions/001_initial_schema.py`
- **Exact Problem:** The `detections` table lacks indexes on `review_status`, `taxon_id`, `created_at`, and `encounter_id`. The `review_events` table lacks an index on `detection_id`.
- **Potential Impact:**
  - `GET /api/v1/observations?review_status=pending` performs a full table scan and file sort on `created_at DESC`.
  - `GET /api/v1/reviews/{detection_id}` performs a full table scan on `review_events`.
- **Recommended Correction:**
  Add an Alembic migration (`004_add_detection_indexes.py`):
  - Index on `detections (review_status, created_at)`
  - Index on `detections (taxon_id)`
  - Index on `detections (encounter_id)`
  - Index on `review_events (detection_id, created_at)`
- **Regression Test Needed:** Yes (`test_detection_queries_utilize_indexes`).

---

### Finding M-05: High Memory Instantiation in `get_camera_details`
- **Severity:** **MEDIUM**
- **Location:** `src/backend/services/camera.py`, lines 187–197:
  ```python
  image_query = (
      db.query(ImageFrame)
      .join(MediaAsset, ImageFrame.source_media_id == MediaAsset.id)
      .filter(MediaAsset.camera_id == camera.id)
  )
  total_images = image_query.count()
  quality_flags_count: Dict[str, int] = {}
  for frame in image_query.all():
      for flag in frame.quality_flags or []:
          quality_flags_count[flag] = quality_flags_count.get(flag, 0) + 1
  ```
- **Exact Problem:** Loads all `ImageFrame` entities into memory (`image_query.all()`) to calculate the summary dictionary of quality flags.
- **Potential Impact:** On active camera traps with tens of thousands of frames, calling `GET /api/v1/cameras/{id}` instantiates thousands of ORM objects, causing latency spikes and memory bloat.
- **Recommended Correction:**
  Only query `ImageFrame.quality_flags` (e.g. `db.query(ImageFrame.quality_flags)...`) or aggregate in SQL using PostgreSQL JSON operators.
- **Regression Test Needed:** Yes (`test_camera_details_does_not_load_all_frames`).

---

### Finding L-01: Session Generator Lacks Explicit Rollback
- **Severity:** **LOW**
- **Location:** `src/backend/db/session.py`, lines 50–57
- **Exact Problem:** `get_db()` yields the session and closes it in `finally`, but does not issue an explicit `db.rollback()` upon exception.
- **Potential Impact:** In SQLAlchemy, closing an uncommitted session rolls it back automatically. However, explicit rollback guarantees that pending dirty objects or connection pool transactions are reset immediately.
- **Recommended Correction:**
  ```python
  def get_db() -> Generator[Session, None, None]:
      db = SessionLocal()
      try:
          yield db
      except Exception:
          db.rollback()
          raise
      finally:
          db.close()
  ```
- **Regression Test Needed:** No.

---

### Finding L-02: Error Code Naming on Missing Job ID
- **Severity:** **LOW**
- **Location:** `src/backend/services/jobs.py`, line 52
- **Exact Problem:** `EntityNotFoundException("ProcessingJob", job_id)` generates error code `PROCESSINGJOB_NOT_FOUND` rather than `JOB_NOT_FOUND`.
- **Potential Impact:** Minor contract naming inconsistency. Already handled in contract documentation.
- **Recommended Correction:** Align exception instantiation to `EntityNotFoundException("Job", job_id)` if strict naming is desired.
- **Regression Test Needed:** No.

---

## 3. Existing Protections Working Correctly

The audit confirmed that the following critical engineering patterns are implemented correctly and robustly:

1. **Scientific Prediction Immutability:**
   - SQLAlchemy event listeners (`before_update`) on `Detection` strictly block any direct mutation of `bbox_x`, `bbox_y`, `bbox_w`, `bbox_h`, `score`, and `raw_label`.
   - Only `review_status` is permitted to transition.
2. **Permanent Append-Only Review Trail:**
   - `ReviewEvent` models have event listeners rejecting updates and deletes.
   - Database foreign key constraints use `ON DELETE RESTRICT` to prevent accidental deletion of audited detections.
3. **Optimistic Concurrency & Monotonic Revision:**
   - Review submission executes an atomic conditional update (`WHERE id=1 AND current_revision = expected_revision`).
   - Revision increment is monotonic ($+1$). Stale revisions return `HTTP 409 STALE_REVISION_CONFLICT` without modifying database state.
4. **Secure Content-Addressed Storage:**
   - Storage keys are derived deterministically from SHA-256 byte hashes (`media/ab/cd/abcdef...jpg`).
   - Original filenames are never used on disk.
   - Strict magic-byte inspection (JPEG `\xff\xd8\xff`, PNG `\x89PNG`, MP4 `ftyp`) prevents file extension spoofing.
   - Directory traversal protection via `target_path.relative_to(self.root_dir)` rejects `../` traversal attempts.
5. **Decoupled Telemetry vs. Observation Quality:**
   - A camera with zero recorded images is never marked dead. Telemetry status (`reporting`, `stale`, `unknown`) depends purely on hardware heartbeat timestamp against the 24-hour freshness window.
6. **Non-Causal Monitoring Disclaimer:**
   - Monitoring feedback explicitly sets `is_causal: false` and includes a non-causal disclaimer on all observational evaluations.
7. **Portable UTC Datetime Normalization:**
   - `UTCDatetime` rejects naive timestamps and normalizes to UTC, preventing diurnal/nocturnal time corruption across SQLite and PostgreSQL.

---

## 4. Test Coverage Gap Analysis

The existing test suites cover core happy paths, basic validations, and immutability invariants. However, the following test scenarios are currently **missing** from the codebase:

1. **Concurrent Review Submissions:**
   - *Test Needed:* Use `concurrent.futures` to simulate multiple threads submitting reviews for the same detection simultaneously with identical `expected_revision`.
   - *Expected Behavior:* Exactly one submission succeeds (HTTP 201); all others receive HTTP 409 without corrupted revision state.
2. **Duplicate Upload Deduplication:**
   - *Test Needed:* Upload identical JPEG bytes twice under different filenames.
   - *Expected Behavior:* Second upload returns `is_duplicate=True`, reuses existing `MediaAsset` and `ImageFrame`, and does not create duplicate files on disk.
3. **Multi-File Batch Upload Partial Failure:**
   - *Test Needed:* Upload 2 files in one request: file 1 valid JPEG, file 2 corrupted text file.
   - *Expected Behavior:* Returns HTTP 422; no orphaned file left on disk; zero database rows inserted.
4. **Oversized and Empty File Uploads:**
   - *Test Needed:* Upload empty file (0 bytes) and file exceeding 50MB.
   - *Expected Behavior:* Returns HTTP 422 `DOMAIN_VALIDATION_ERROR`.
5. **Interrupted Processing Job Recovery:**
   - *Test Needed:* Simulate worker process crash during `run_batch()`.
   - *Expected Behavior:* Job transitions to `status: "failed"` with clear error message; does not hang in `running`.
6. **Camera Filtering on Observations:**
   - *Test Needed:* Query `GET /api/v1/observations?camera_id=CAM-01`.
   - *Expected Behavior:* Returns only observations from `CAM-01`. (Currently failing due to Finding H-01).
7. **Malformed Request Parameters:**
   - *Test Needed:* Pass negative limit (`?limit=-1`), invalid coordinates (`[200, 100]`), or inverted monitoring windows (`baseline_start > baseline_end`).
   - *Expected Behavior:* Returns uniform HTTP 422 error envelope with `request_id`.

---

## 5. Recommended Remediation Order

To prepare the WILDSCOPE AI backend for production deployment, address the findings in the following prioritized phases:

### Phase 1: High-Priority Functional & Performance Fixes (Immediate)
1. **Fix H-01 (`camera_id` observation filter):** Add `ImageFrame` and `MediaAsset` joins to `observations.py`.
2. **Fix H-03 (Camera pagination & side-effects):** Remove `db.commit()` from `GET /api/v1/cameras`; apply SQL `offset` and `limit`.
3. **Fix M-03 (Background job exception handling):** Ensure `fail_job()` is always called on unexpected background exceptions.

### Phase 2: Security & Storage Hardening (Pre-Production)
4. **Fix H-02 (Upload streaming):** Validate Content-Length upfront; stream bytes to disk in chunks instead of unbounded in-memory `read()`.
5. **Fix M-01 (Error message masking):** Mask raw `str(exc)` details in `general_exception_handler` when `DEBUG == False`.
6. **Fix M-02 (Orphaned file cleanup):** Delete temporary disk files if batch upload transaction aborts.
7. **Implement C-01 (Authentication):** Add API token / JWT authentication middleware before production exposure.

### Phase 3: Database Optimization & Indexing (Scalability)
8. **Implement M-04 (Database indexes):** Add Alembic migration `004_add_detection_indexes.py` for `detections` and `review_events`.
9. **Fix M-05 (Camera details frame query):** Optimize quality flag aggregation to avoid loading all frames into Python memory.
10. **Implement L-01 (Explicit rollback):** Update `get_db()` with explicit `db.rollback()` on exception.

---

## 6. Overall Production-Readiness Assessment

| Category | Readiness Score | Evaluation |
|:---|:---:|:---|
| **Data Integrity & Scientific Modeling** | **95%** | **Excellent.** Immutability, audit trails, and concurrency control are robustly enforced. |
| **Storage Architecture** | **88%** | **Very Good.** SHA-256 deduplication and path traversal protection work as intended; needs streaming uploads and orphaned-file cleanup. |
| **API Contract & Diagnostics** | **92%** | **Very Good.** Uniform envelopes, comprehensive error codes, and honest worker reporting are in place. |
| **Performance & Scalability** | **65%** | **Needs Improvement.** Lacks indexes on key query columns; in-memory pagination and side-effect writes on `GET /cameras`. |
| **Security & Access Control** | **55%** | **Needs Hardening.** Lacks authentication middleware; raw exception details exposed in 500 responses; in-memory file read DoS risk. |
| **OVERALL SYSTEM READINESS** | **78%** | **Production-Capable with Remediations.** Safe for internal beta/hackathon evaluation. Must complete Phase 1 and Phase 2 remediations prior to open network deployment. |

---

**End of Backend Reliability & Security Audit Report.**  
Report authored by: **Santosh Yuvaraj**, Senior Backend API Architect, Team ByteStrom.
