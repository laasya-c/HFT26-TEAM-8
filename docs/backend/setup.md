# WILDSCOPE AI — Backend Setup & Developer Guide

**Module**: WILDSCOPE Backend Core (`src/backend`)  
**Accountable Owner**: Santosh Yuvaraj  
**Assigned Branch**: `santosh`  
**Current Phase**: Phase 3 (Human Review F20, Camera Health F07, Monitoring Feedback F11)

---

## 1. Overview and Architecture

WILDSCOPE is an AI-powered wildlife conservation intelligence platform that ingests camera-trap media, tracks wildlife detections, aggregates encounters, and supports human expert review.

Santosh owns and exposes the **only `/api/v1` backend API** for the team.

### Directory Organization

```
HFT26-TEAM-8/
├── .gitignore                      <-- Excludes .venv, desktop.ini, *.db, storage/
├── requirements.txt                <-- Pinned dependencies (FastAPI, Pydantic, SQLAlchemy)
├── pyproject.toml                  <-- Build metadata and pytest settings
│
├── contracts/                      <-- [SHARED / DRAFT] Pydantic contracts & taxonomy
│   ├── schemas.py                  <-- Validated Image, Detection, Encounter, Camera models
│   └── taxonomy.json               <-- Standardized Indian & global wildlife taxonomy
│
├── fixtures/                       <-- [SHARED / DRAFT] Test fixture data
│   └── demo.json                   <-- Valid synthetic records (provenance: "simulated")
│
├── migrations/                     <-- [SANTOSH] Alembic database migration environment
│   ├── env.py                      <-- Migration environment configuration
│   └── versions/                   <-- Schema migration scripts:
│       ├── 001_initial_schema.py   <-- Base platform tables
│       ├── 002_add_processing_jobs.py <-- Persistent background jobs
│       └── 003_phase3_audit_and_indexes.py <-- Audit FKs, indexes, encounter status
│
├── src/backend/                    <-- [SANTOSH] Main backend application
│   ├── main.py                     <-- FastAPI application entrypoint & middleware
│   ├── config.py                   <-- Application settings & environment variables
│   │
│   ├── api/v1/                     <-- API route layer
│   │   ├── router.py               <-- Central v1 router
│   │   ├── health.py               <-- Health check endpoint (GET /api/v1/health)
│   │   ├── uploads.py              <-- Media upload intake (POST /api/v1/uploads)
│   │   ├── jobs.py                 <-- Job progress & status (GET /api/v1/jobs/{id})
│   │   ├── media.py                <-- Safe media binary serving (GET /api/v1/images/{id}/content)
│   │   ├── observations.py         <-- Detections retrieval (GET /api/v1/observations)
│   │   ├── reviews.py              <-- Human review & audit (POST /api/v1/reviews)
│   │   ├── cameras.py              <-- Camera traps & hardware telemetry (F07)
│   │   └── monitoring.py           <-- Monitoring feedback & network health (F11)
│   │
│   ├── core/                       <-- Core utilities & envelopes
│   │   ├── responses.py            <-- Standard response envelope { data, meta }
│   │   └── exceptions.py           <-- Standard error envelope { error, request_id }
│   │
│   ├── db/                         <-- Database session & configuration
│   │   ├── base.py                 <-- DeclarativeBase, UTCDatetime, PortableJSON
│   │   └── session.py              <-- SQLite WAL engine, busy timeout & sessionmaker
│   │
│   ├── models/                     <-- SQLAlchemy ORM models
│   │   ├── camera.py               <-- Camera, CameraTelemetry, MonitoringAction
│   │   ├── encounter.py            <-- Encounter, EncounterMember
│   │   ├── job.py                  <-- ProcessingJob (queued/running/completed/partial/failed)
│   │   ├── media.py                <-- MediaAsset, ImageFrame
│   │   ├── prediction.py           <-- PredictionRun, Detection, GroundTruthAnnotation
│   │   └── review.py               <-- ReviewEvent, DatasetRevision
│   │
│   ├── services/                   <-- Business logic layer
│   │   ├── storage.py              <-- Magic-byte checks, SHA-256 hash, safe disk I/O
│   │   ├── jobs.py                 <-- Persistent background job manager
│   │   ├── reviews.py              <-- Append-only reviews & optimistic concurrency (F20)
│   │   ├── camera.py               <-- Telemetry health & freshness calculator (F07)
│   │   └── monitoring.py           <-- Before/after intervention feedback service (F11)
│   │
│   └── adapters/                   <-- Cross-module boundaries
│       └── inference.py            <-- Adapter for Harsh's run_batch() (honest 503 if unlinked)
│
├── tests/backend/                  <-- [SANTOSH] Automated test suite
│   ├── conftest.py                 <-- TestClient & in-memory SQLite fixtures
│   ├── test_health.py              <-- Health endpoint tests
│   ├── test_schemas.py             <-- Pydantic contract validation tests
│   ├── test_db.py                  <-- Model persistence & immutable prediction tests
│   ├── test_config.py              <-- Configuration tests
│   ├── test_storage.py             <-- Magic-byte & path traversal tests
│   ├── test_jobs.py                <-- Job state machine & persistence tests
│   ├── test_inference_adapter.py   <-- Adapter contract & honest failure tests
│   ├── test_api_v1.py              <-- End-to-end API v1 tests
│   ├── test_reviews.py             <-- Human review, immutability & audit tests (F20)
│   └── test_cameras_and_monitoring.py <-- Camera health (F07) & monitoring feedback (F11) tests
│
└── docs/backend/
    └── setup.md                    <-- This documentation file
```

---

## 2. Python Runtime & Environment Notes

### Runtime Status
* **Local Machine**: Running **Python 3.14.3** with a pre-configured virtual environment in `.venv/`.
* **Team Baseline**: **Python 3.11** (prescribed in project manual for CUDA 12 / RTX 4050 GPU compatibility).

### Compatibility Distinction:
* **Verified on Python 3.14.3**:
  - `fastapi` (0.162.0)
  - `uvicorn` (0.54.0)
  - `pydantic` (2.14.2)
  - `pydantic-core` (2.50.2)
  - `starlette` (1.10.0)
* **Pure Python / Portable (Phase 1 & 2 Baseline)**:
  - `sqlalchemy>=2.0.30` (using Python standard library `sqlite3`)
  - `alembic>=1.13.0`
  - `pytest>=8.0.0`
  - `httpx>=0.27.0`
* **Incompatible on Python 3.14 (Team Boundary Warning)**:
  - Harsh Rao's vision worker (`torch`, `torchvision`, `torchaudio` with CUDA) **does not have pre-built wheels for Python 3.14**. Harsh and Shravan must run in a **Python 3.11** virtual environment.

---

## 3. Local Setup Commands

Run these commands in your **VS Code terminal** (PowerShell or Command Prompt):

### Step 1: Activate Virtual Environment
```powershell
# In PowerShell:
.\.venv\Scripts\Activate.ps1

# Or in Command Prompt:
.\.venv\Scripts\activate.bat
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Run Database Migrations
Initialize or upgrade the local SQLite database (`wildscope.db`) using Alembic:
```bash
alembic -c migrations/alembic.ini upgrade head
```

---

## 4. Phase 2 Features & Endpoints

### 4.1 Media Upload (`POST /api/v1/uploads`)
* Accepts multipart form data with one or more files.
* Validates true magic bytes:
  - **JPEG**: `\xFF\xD8\xFF`
  - **PNG**: `\x89PNG\r\n\x1a\n`
  - **MP4**: `ftyp` box at byte 4
* Enforces 50MB file size limit.
* Calculates SHA-256 content hash.
* Deduplicates uploads: identical bytes reuse the existing `MediaAsset` record without duplicating disk files.
* Returns HTTP `202 Accepted` with `upload_id` and `job_id`.

Example request using curl:
```bash
curl -X POST http://127.0.0.1:8000/api/v1/uploads \
  -F "files=@my_image.jpg" \
  -F "camera_id=CAM-01"
```

### 4.2 Job Status & Progress (`GET /api/v1/jobs/{id}`)
* Returns persistent state: `queued`, `running`, `completed`, `partial`, `failed`.
* Returns progress percentage and item counts.
* Persists across server restarts.

Example response (HTTP 200):
```json
{
  "data": {
    "id": "job_123456789abc",
    "upload_id": "up_123456789abc",
    "status": "completed",
    "progress": 100.0,
    "total_items": 1,
    "processed_items": 1,
    "media_ids": ["med-uuid"],
    "run_id": "run-uuid",
    "failures": [],
    "error_message": null
  },
  "meta": {
    "dataset_revision": 1
  }
}
```

### 4.3 Safe Media Serving (`GET /api/v1/images/{id}/content`)
* Serves the original binary image stream.
* Path traversal protected (strictly verified inside `storage/`).
* Never exposes internal filesystem paths in HTTP responses.

### 4.4 Inference Adapter (`src/backend/adapters/inference.py`)
* Acts as the boundary with Harsh Rao's vision worker.
* When `src.inference` is unavailable, marks the job as `failed` with an explicit reason.
* Never fabricates fake predictions or falls back to fixtures in operational mode.

### 4.5 Human Review & Auditability — F20 (`POST /api/v1/reviews`)
* Submits an append-only human review decision (`confirmed`, `corrected`, `rejected`, `deferred`).
* **Optimistic Concurrency**: Clients submit `expected_revision`. If stale, returns HTTP `409 Conflict` with `STALE_REVISION_CONFLICT`.
* **Atomic Monotonic Increment**: Increments `dataset_revisions` table atomically upon successful review.
* **Scientific Immutability**: Raw vision predictions (`score`, `raw_label`, `bbox_*`, `model_version`) are permanently locked at the ORM layer; only `review_status` transitions.
* **Audit Trail Protection**: `ReviewEvent` records cannot be updated or deleted. `ReviewEvent.detection_id` uses `ON DELETE RESTRICT` to prevent accidental history loss.
* **Encounter Aggregation**: Automatically computes aggregate review state for parent encounters (`pending` -> `partially_reviewed` -> `reviewed`).

Example review submission (HTTP 201 Created):
```bash
curl -X POST http://127.0.0.1:8000/api/v1/reviews \
  -H "Content-Type: application/json" \
  -d '{
    "detection_id": "det-uuid",
    "decision": "confirmed",
    "reason": "Clear stripe pattern matches Panthera tigris",
    "reviewer_id": "wildlife_expert_01",
    "expected_revision": 1
  }'
```

### 4.6 Camera Health & Hardware Telemetry — F07
* **Endpoints**:
  - `GET /api/v1/cameras`: Lists camera stations with live freshness evaluation.
  - `POST /api/v1/cameras`: Registers a new camera trap station.
  - `GET /api/v1/cameras/{id}`: Detailed diagnostics (telemetry health decoupled from visual observation quality).
  - `POST /api/v1/cameras/{id}/telemetry`: Hardware telemetry ingestion (heartbeat, battery, signal, error codes).
  - `GET /api/v1/cameras/{id}/telemetry`: Telemetry history log.
* **Telemetry States**:
  - `reporting`: Telemetry received within the configurable 24-hour window (`CAMERA_TELEMETRY_FRESHNESS_HOURS = 24.0`).
  - `stale`: Last telemetry heartbeat older than 24 hours.
  - `unknown`: No telemetry heartbeat ever received (never fabricated).
* **Scientific Rule**: Image silence does not equal camera failure. A station with 0 uploaded images remains `reporting` if its hardware heartbeat is fresh.

### 4.7 Monitoring Improvement Feedback — F11
* **Endpoints**:
  - `GET /api/v1/monitoring`: Holistic network health and recent intervention summaries.
  - `GET /api/v1/monitoring-actions`: List logged maintenance actions.
  - `POST /api/v1/monitoring-actions`: Log field actions (e.g. lens cleaning, battery replacement, repositioning).
  - `GET /api/v1/monitoring-actions/{id}/feedback`: Before/after uptime and visual observation quality evaluation.
* **Effort & Missing Data**:
  - Returns `status: "insufficient_data"` if baseline or post observation windows are missing or lack activity.
* **Scientific Rule**:
  - **Zero Causal Claims**: Observational comparisons explicitly declare `is_causal: false` and include a non-causal disclaimer noting ecological and seasonal confounders.

---

## 5. Running the Test Suite

Execute the entire backend test suite:
```bash
python -m pytest tests/backend/ -v
```

To run individual test modules:
```bash
# Camera Health (F07) and Monitoring Feedback (F11) tests:
python -m pytest tests/backend/test_cameras_and_monitoring.py -v

# Human Review, Immutability & Audit tests (F20):
python -m pytest tests/backend/test_reviews.py -v

# Database persistence & immutability tests:
python -m pytest tests/backend/test_db.py -v

# Storage & Upload tests:
python -m pytest tests/backend/test_storage.py -v

# Persistent Job lifecycle tests:
python -m pytest tests/backend/test_jobs.py -v

# Inference Adapter boundary tests:
python -m pytest tests/backend/test_inference_adapter.py -v

# End-to-end API v1 tests:
python -m pytest tests/backend/test_api_v1.py -v
```

---

## 6. Starting the Development Server

Start the FastAPI application with Uvicorn:
```bash
uvicorn src.backend.main:app --reload --host 127.0.0.1 --port 8000
```

* Swagger OpenAPI UI: [http://127.0.0.1:8000/api/v1/docs](http://127.0.0.1:8000/api/v1/docs)
* Health Endpoint: [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)
* Complete API Contract Document: [docs/api-contract.md](file:///c:/Users/santosh/OneDrive/Desktop/HFT26-TEAM-8/docs/api-contract.md)
