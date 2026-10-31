# WILDSCOPE AI — Remediation Cycle B: Performance & Storage Reliability Report

**Module:** WILDSCOPE AI Backend API (`src/backend`)  
**Accountable Backend Architect:** Santosh Yuvaraj  
**Repository:** `HFT26-TEAM-8`  
**Git Branch:** `santosh`  
**Audit Reference:** [`docs/backend/reliability-audit-report.md`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/docs/backend/reliability-audit-report.md)  
**Contract Reference:** [`docs/api-contract.md`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/docs/api-contract.md)  
**Date:** October 31, 2026  
**Status:** **REMEDIATION CYCLE B COMPLETE & VERIFIED**

---

## Executive Summary

Remediation Cycle B resolves four critical findings identified in the Backend Reliability and Security Audit ([`docs/backend/reliability-audit-report.md`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/docs/backend/reliability-audit-report.md)):
1. **H-02 (Stream upload files):** Unbounded in-memory file reading replaced with bounded chunked streaming (64 KB chunks), on-the-fly 50 MB limit enforcement, incremental SHA-256 calculation, and immediate temporary staging file cleanup on failures.
2. **M-04 (Add database indexes):** High-frequency query patterns indexed on `detections` (`review_status`, `taxon_id`, `image_id`, `encounter_id`), `review_events` (`detection_id`, `created_at`), and `image_frames` (`source_media_id`) via a new non-destructive Alembic migration (`004_add_performance_and_query_indexes.py`) and corresponding ORM model definitions.
3. **M-05 (Optimize camera diagnostics):** Eliminated full `ImageFrame` ORM model hydration in `get_camera_details()` by introducing dialect-aware SQL aggregation (`json_each` for SQLite, `jsonb_array_elements_text` for PostgreSQL), a column projection fallback, and a zero-image fast path, while preserving scientific decoupling between telemetry and visual flags.
4. **L-01 (Database session safety):** Fortified FastAPI `get_db()` dependency with explicit transaction rollback on unhandled exceptions and nested exception handling guaranteeing session closure even if rollback itself fails.

---

## 1. Remediation Matrix

| Finding ID | Severity | Problem Summary | Files Modified | Solution Summary | Status |
|:---:|:---:|:---|:---|:---|:---:|
| **H-02** | **HIGH** | Unbounded `await uploaded_file.read()` loaded up to 50 MB per file into server RAM, risking memory exhaustion under concurrent uploads. | [`src/backend/services/storage.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/services/storage.py)<br>[`src/backend/api/v1/uploads.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/api/v1/uploads.py) | Implemented `store_media_stream()` reading in 64 KB chunks, enforcing 50 MB limit during stream, hashing on the fly, atomic rename, and temp file unlinking. | **RESOLVED** |
| **M-04** | **MEDIUM** | Missing indexes on frequently filtered foreign keys and status columns (`review_status`, `taxon_id`, `image_id`, `encounter_id`, `detection_id`, `source_media_id`). | [`migrations/versions/004_add_performance_and_query_indexes.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/migrations/versions/004_add_performance_and_query_indexes.py)<br>[`src/backend/models/prediction.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/models/prediction.py)<br>[`src/backend/models/review.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/models/review.py)<br>[`src/backend/models/media.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/models/media.py) | Created migration 004 without modifying prior migrations; updated ORM `__table_args__` on `Detection`, `ReviewEvent`, and `ImageFrame`. | **RESOLVED** |
| **M-05** | **MEDIUM** | `get_camera_details()` loaded all `ImageFrame` ORM models into Python memory via `image_query.all()` to aggregate quality flags. | [`src/backend/services/camera.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/services/camera.py) | Introduced dialect-aware SQL aggregation (`json_each` / `jsonb_array_elements_text`), column-only projection fallback, and 0-image early return. | **RESOLVED** |
| **L-01** | **LOW** | `get_db()` generator relied on `finally: db.close()` without explicit `db.rollback()` on route exceptions; unhandled errors could leak dirty transaction state back to connection pools. | [`src/backend/db/session.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/db/session.py) | Added explicit `try: db.rollback() except: pass` on route exceptions; wrapped `db.close()` in `finally:` to guarantee closure. | **RESOLVED** |

---

## 2. Detailed Technical Implementation

### 1. H-02 — Stream Upload Files (Bounded Memory & Safe Streaming)
- **Files Modified:**
  - [`src/backend/services/storage.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/services/storage.py)
  - [`src/backend/api/v1/uploads.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/api/v1/uploads.py)
- **Problem:**
  The original upload handler used `file_bytes = await uploaded_file.read()`, reading the entire file contents directly into RAM before size validation or file signature checking. For multiple concurrent uploads or 50 MB video files, this caused severe memory pressure and vulnerability to resource exhaustion.
- **Resolution:**
  1. Implemented `async def store_media_stream(...)` in `StorageService`:
     - Reads data in bounded chunks (default `64 KB`).
     - Maintains an active byte counter; raises `ValidationException` (HTTP 422) immediately once `total_bytes > 50 MB`, aborting further chunk reads.
     - Computes SHA-256 hash incrementally via `hasher.update(chunk)` during streaming.
     - Collects the first 32 bytes for magic-byte file signature validation (`detect_media_format()`).
     - Streams incoming chunks into a staging file located at `media/_tmp/stream_{uuid}.tmp` on the same disk filesystem.
     - On any validation error, size violation, or disk failure, immediately unlinks `temp_path` via `temp_path.unlink(missing_ok=True)`.
  2. Preserved SHA-256 content-addressing and deduplication:
     - If the computed hash matches an existing `MediaAsset` on disk, the temporary file is unlinked immediately, and the existing asset and frame are reused (`is_duplicate=True`).
     - If new, the temporary staging file is atomically moved to `media/{hash[:2]}/{hash[2:4]}/{hash}.{ext}` via `os.replace()`.
  3. Preserved backward compatibility:
     - Retained `store_media(file_bytes=...)` for legacy synchronous callers while updating `POST /api/v1/uploads` to use `store_media_stream()`.

---

### 2. M-04 — Database Performance and Query Indexes
- **Files Created/Modified:**
  - [`migrations/versions/004_add_performance_and_query_indexes.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/migrations/versions/004_add_performance_and_query_indexes.py) *(New Migration)*
  - [`src/backend/models/prediction.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/models/prediction.py)
  - [`src/backend/models/review.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/models/review.py)
  - [`src/backend/models/media.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/models/media.py)
- **Problem:**
  High-traffic query patterns lacked indexes:
  - Filtering observations by `review_status` and sorting by `created_at`.
  - Filtering observations by `taxon_id` and sorting by `created_at`.
  - Relational joins between `ImageFrame` and `Detection` (`detections.image_id`).
  - Encounter membership queries (`detections.encounter_id`).
  - Review event audit trail lookups (`review_events.detection_id`, `review_events.created_at`).
  - Camera joins to image frames (`image_frames.source_media_id`).
- **Resolution:**
  1. Created migration `004_add_performance_and_query_indexes.py` with `down_revision = "003_phase3_audit_and_indexes"` (preserving migrations `001-003` unchanged):
     - `ix_detections_review_status_created` on `detections (review_status, created_at)`
     - `ix_detections_taxon_id_created` on `detections (taxon_id, created_at)`
     - `ix_detections_image_id` on `detections (image_id)`
     - `ix_detections_encounter_id` on `detections (encounter_id)`
     - `ix_review_events_detection_created` on `review_events (detection_id, created_at)`
     - `ix_image_frames_source_media` on `image_frames (source_media_id)`
  2. Updated ORM Declarative Models with corresponding `Index` objects in `__table_args__` on `Detection`, `ReviewEvent`, and `ImageFrame`.

---

### 3. M-05 — Optimize Camera Diagnostics (SQL Aggregation & Decoupling)
- **File Modified:** [`src/backend/services/camera.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/services/camera.py)
- **Problem:**
  `get_camera_details()` executed `image_query.all()`, instantiating every single `ImageFrame` ORM model into Python memory solely to loop over and count strings in `quality_flags`. For active camera trap stations with thousands of frames, this caused excessive memory allocation and query latency.
- **Resolution:**
  1. Added zero-image fast path:
     - `total_images = image_count_query.scalar() or 0`.
     - If `total_images == 0`, immediately returns empty `quality_flags_summary = {}` without executing subsequent frame queries.
  2. Implemented dialect-aware SQL aggregation:
     - **SQLite:** Uses `json_each` with `json_valid` safety check:
       ```sql
       SELECT j.value AS flag, COUNT(*) AS cnt
       FROM image_frames f
       JOIN media_assets m ON f.source_media_id = m.id
       CROSS JOIN json_each(
           CASE WHEN f.quality_flags IS NOT NULL AND json_valid(f.quality_flags) = 1 
                THEN f.quality_flags ELSE '[]' END
       ) j
       WHERE m.camera_id = :camera_id
       GROUP BY j.value
       ```
     - **PostgreSQL:** Uses `jsonb_array_elements_text`:
       ```sql
       SELECT j AS flag, COUNT(*) AS cnt
       FROM image_frames f
       JOIN media_assets m ON f.source_media_id = m.id
       CROSS JOIN jsonb_array_elements_text(
           CASE WHEN jsonb_typeof(to_jsonb(f.quality_flags)) = 'array' 
                THEN to_jsonb(f.quality_flags) ELSE '[]'::jsonb END
       ) j
       WHERE m.camera_id = :camera_id
       GROUP BY j
       ```
  3. Isolated dialect detection and column-only projection fallback:
     - Encapsulated dialect inspection inside `camera_service.get_database_dialect(db)`.
     - If the SQL JSON engine throws an exception or runs on an unsupported dialect, the service falls back to querying `db.query(ImageFrame.quality_flags)` only, completely avoiding full ORM model instantiation.
  4. Preserved scientific integrity decoupling:
     - Camera hardware telemetry state (`reporting`, `stale`, `unknown`) remains decoupled from observation quality flags or image silence.

---

### 4. L-01 — Database Session Safety & Explicit Rollback in `get_db()`
- **File Modified:** [`src/backend/db/session.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/db/session.py)
- **Problem:**
  `get_db()` yielded a session in a `try...finally: db.close()` block. If an unhandled exception occurred during route execution, uncommitted pending ORM objects or dirty transaction states were not explicitly rolled back prior to closing or returning the connection to the connection pool.
- **Resolution:**
  Updated `get_db()` with explicit exception handling and defensive nested rollback:
  ```python
  def get_db() -> Generator[Session, None, None]:
      """FastAPI dependency yielding a clean database session per request.

      Guarantees explicit rollback on unhandled exceptions and safe session closure.
      """
      db = SessionLocal()
      try:
          yield db
      except Exception:
          try:
              db.rollback()
          except Exception:
              pass
          raise
      finally:
          try:
              db.close()
          except Exception:
              pass
  ```
  - Unhandled exceptions trigger `db.rollback()`.
  - If `db.rollback()` itself fails (e.g., dropped connection), the exception is safely caught so the primary route exception is preserved and re-raised.
  - `finally:` ensures `db.close()` is always executed.

---

### 5. Additional Cleanup — RFC 9110 HTTP 422 Status Code Deprecation
- **File Modified:** [`src/backend/core/exceptions.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/src/backend/core/exceptions.py)
- **Problem:**
  Starlette deprecated `HTTP_422_UNPROCESSABLE_ENTITY` in favor of RFC 9110 `HTTP_422_UNPROCESSABLE_CONTENT`, emitting two `StarletteDeprecationWarning` notices during test runs.
- **Resolution:**
  Introduced `HTTP_422_UNPROCESSABLE = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", status.HTTP_422_UNPROCESSABLE_ENTITY)` in `exceptions.py`, updating `ValidationException` and `validation_exception_handler`. Both status code constants represent integer `422`, maintaining identical API behavior while eliminating deprecation warnings.

---

## 3. Regression Test Coverage

A dedicated regression test suite was created in [`tests/backend/test_remediation_cycle_b.py`](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/tests/backend/test_remediation_cycle_b.py):

| Test Function | Target Finding | Verification Scenario |
|:---|:---:|:---|
| `test_stream_upload_success_chunked` | **H-02** | Verifies multipart streaming upload completes in bounded chunks, writes atomic file, creates DB records, and returns HTTP 202 without temp file residue. |
| `test_stream_upload_exceeds_max_size_aborts_early` | **H-02** | Verifies streaming aborts immediately when exceeding 50 MB, raises `ValidationException`, and unlinks temporary files. |
| `test_stream_upload_corrupted_magic_bytes_cleanup` | **H-02** | Verifies invalid magic bytes return HTTP 422, unlinks temporary files in `_tmp/`, and leaves 0 files in media storage. |
| `test_stream_upload_preserves_deduplication` | **H-02** | Verifies duplicate byte streams reuse existing records (`is_duplicate=True`), retain exactly 1 physical file on disk, and clean up temporary staging files. |
| `test_database_indexes_on_tables` | **M-04** | Inspects DB tables using SQLAlchemy inspector to verify that all 6 performance indexes exist on `detections`, `review_events`, and `image_frames`. |
| `test_alembic_migration_004_definition` | **M-04** | Validates Alembic migration 004 revision ID (`004_add_performance_and_query_indexes`), down_revision linkage (`003_phase3_audit_and_indexes`), and callable hooks. |
| `test_camera_details_aggregation_with_frames` | **M-05** | Seeds frames with multiple quality flags; verifies SQL aggregation accurately computes flag totals while preserving telemetry decoupling. |
| `test_camera_details_zero_images_fast_path` | **M-05** | Verifies zero-image camera executes fast path without query overhead and returns empty flag summary. |
| `test_camera_diagnostics_fallback_projection` | **M-05** | Isolates and mocks `camera_service.get_database_dialect` to simulate an unsupported dialect; verifies that the real SQLite session executes column-only projection fallback and accurately tallies flags. |
| `test_get_db_explicit_rollback_on_exception` | **L-01** | Throws unhandled exception into `get_db()` generator; verifies uncommitted pending changes are rolled back and not persisted. |
| `test_get_db_guarantees_session_close_even_if_rollback_fails` | **L-01** | Mocks `db.rollback` to raise an error; verifies `db.close()` is still executed and original exception propagates. |

---

## 4. Local Execution & Verification Instructions

To execute the test suites locally on your Windows terminal:

```powershell
# 1. Activate project virtual environment
.\.venv\Scripts\Activate.ps1

# 2. Run Remediation Cycle B test suite
python -m pytest tests/backend/test_remediation_cycle_b.py -v

# 3. Run full backend regression suite (Cycles A + B + Schemas)
python -m pytest tests/backend/test_remediation_cycle_a.py tests/backend/test_remediation_cycle_b.py tests/backend/test_schemas.py -v
```

---

## 5. Teammate Scope & Safety Compliance Statement

- **Branch Preservation:** Strictly maintained on branch `santosh`. No branch switching, rebasing, committing, pushing, or worktree creation was performed.
- **Teammate Folder Isolation:** Zero modifications were made to `src/frontend/` (Aarav), `src/inference/` (Harsh), `src/intelligence/` (Diya), or `wildscope_analytics/`.
- **Scientific Immutability:** Raw model predictions (`Detection`) remain strictly immutable. Human review decisions remain append-only in `review_events`. Dataset revisions continue to track optimistic concurrency monotonically.
- **Audit Permanence:** Review events cannot be updated or deleted. Cascade deletions from parent tables remain restricted (`ON DELETE RESTRICT`).
