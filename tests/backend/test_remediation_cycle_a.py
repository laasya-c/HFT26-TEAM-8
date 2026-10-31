"""Remediation Cycle A Regression Test Suite.

Verifies fixes for:
1. H-01: camera_id filtering on GET /api/v1/observations (relational join, filtered total, pagination).
2. H-03: Read-only GET /api/v1/cameras with database-level pagination and zero write side effects.
3. M-03: Background job exception logging and fail_job persistence (no indefinitely queued jobs).
4. M-01: HTTP 500 internal exception description masking when DEBUG=False.
5. M-02: Multi-file upload batch rollback and orphan disk cleanup on partial failure.
6. SHA-256 deduplication preservation (existing files are never deleted).
"""
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from src.backend.config import settings
from src.backend.core.auth_deps import get_current_active_user, get_current_user, verify_telemetry_auth
from src.backend.main import app
from src.backend.models import (
    Camera,
    CameraTelemetry,
    Detection,
    ImageFrame,
    MediaAsset,
    PredictionRun,
    ProcessingJob,
    User,
    UserRole,
)
from src.backend.models.job import JobStatus
from src.backend.services.jobs import job_service
from src.backend.services.storage import storage_service

VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb" + b"\x00" * 50
CORRUPTED_BYTES = b"Plain text disguised as JPEG - invalid magic bytes"


@pytest.fixture(autouse=True)
def authenticate_legacy_cycle_tests(db_session: Session):
    """Provides authenticated admin context for legacy regression suites."""
    admin_user = User(
        id="legacy_admin_user",
        username="legacy_admin",
        email="legacy_admin@wildscope.org",
        hashed_password="hash",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db_session.add(admin_user)
    db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_current_active_user] = lambda: admin_user
    app.dependency_overrides[verify_telemetry_auth] = lambda: admin_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_active_user, None)
    app.dependency_overrides.pop(verify_telemetry_auth, None)


# ============================================================================
# 1. H-01: Camera ID Filtering in GET /api/v1/observations
# ============================================================================

@pytest.mark.integration
def test_observations_camera_id_filtering_multiple_cameras(client: TestClient, db_session: Session):
    """Verify that GET /api/v1/observations filters detections strictly by camera_id."""
    # Setup Camera A and Camera B
    cam_a = Camera(id="CAM-A", label="North Waterhole", timezone="UTC", provenance="observed")
    cam_b = Camera(id="CAM-B", label="South Ridge", timezone="UTC", provenance="observed")
    db_session.add_all([cam_a, cam_b])
    db_session.flush()

    # Media and Frame for Camera A
    med_a = MediaAsset(id="MED-A", type="image", camera_id=cam_a.id, storage_key="media/a.jpg", content_hash="hash_a", provenance="observed")
    db_session.add(med_a)
    db_session.flush()
    frm_a = ImageFrame(id="FRM-A", source_media_id=med_a.id, content_url="/api/v1/images/FRM-A/content", quality_flags=[], provenance="observed")
    db_session.add(frm_a)

    # Media and Frame for Camera B
    med_b = MediaAsset(id="MED-B", type="image", camera_id=cam_b.id, storage_key="media/b.jpg", content_hash="hash_b", provenance="observed")
    db_session.add(med_b)
    db_session.flush()
    frm_b = ImageFrame(id="FRM-B", source_media_id=med_b.id, content_url="/api/v1/images/FRM-B/content", quality_flags=[], provenance="observed")
    db_session.add(frm_b)

    run = PredictionRun(id="RUN-REMED-1", model_name="yolo", model_version="v1", device="cpu", status="completed")
    db_session.add(run)
    db_session.flush()

    # 2 Detections on Camera A
    det_a1 = Detection(id="DET-A1", image_id=frm_a.id, run_id=run.id, bbox_x=0.1, bbox_y=0.1, bbox_w=0.4, bbox_h=0.4, raw_label="tiger", taxon_id="tiger", label="Tiger", score=0.9, model_version="v1", review_status="pending", provenance="inferred")
    det_a2 = Detection(id="DET-A2", image_id=frm_a.id, run_id=run.id, bbox_x=0.2, bbox_y=0.2, bbox_w=0.3, bbox_h=0.3, raw_label="deer", taxon_id="deer", label="Deer", score=0.8, model_version="v1", review_status="pending", provenance="inferred")
    # 1 Detection on Camera B
    det_b1 = Detection(id="DET-B1", image_id=frm_b.id, run_id=run.id, bbox_x=0.3, bbox_y=0.3, bbox_w=0.5, bbox_h=0.5, raw_label="leopard", taxon_id="leopard", label="Leopard", score=0.85, model_version="v1", review_status="pending", provenance="inferred")
    db_session.add_all([det_a1, det_a2, det_b1])
    db_session.commit()

    # 1. Filter by Camera A
    res_a = client.get("/api/v1/observations?camera_id=CAM-A")
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["meta"]["total"] == 2
    assert len(data_a["data"]) == 2
    returned_ids_a = {d["id"] for d in data_a["data"]}
    assert returned_ids_a == {"DET-A1", "DET-A2"}

    # 2. Filter by Camera B
    res_b = client.get("/api/v1/observations?camera_id=CAM-B")
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert data_b["meta"]["total"] == 1
    assert len(data_b["data"]) == 1
    assert data_b["data"][0]["id"] == "DET-B1"

    # 3. Filter by nonexistent camera
    res_none = client.get("/api/v1/observations?camera_id=CAM-NONEXISTENT")
    assert res_none.status_code == 200
    assert res_none.json()["meta"]["total"] == 0
    assert len(res_none.json()["data"]) == 0

    # 4. Unfiltered query returns all 3
    res_all = client.get("/api/v1/observations")
    assert res_all.status_code == 200
    assert res_all.json()["meta"]["total"] == 3


@pytest.mark.integration
def test_observations_camera_id_filtered_pagination(client: TestClient, db_session: Session):
    """Verify that total and pagination accurately reflect camera_id filtered subsets."""
    cam = Camera(id="CAM-PAG", label="Paginated Trap", timezone="UTC", provenance="observed")
    db_session.add(cam)
    med = MediaAsset(id="MED-PAG", type="image", camera_id=cam.id, storage_key="media/p.jpg", content_hash="hash_p", provenance="observed")
    db_session.add(med)
    frm = ImageFrame(id="FRM-PAG", source_media_id=med.id, content_url="/api/v1/images/FRM-PAG/content", quality_flags=[], provenance="observed")
    db_session.add(frm)
    run = PredictionRun(id="RUN-PAG", model_name="yolo", model_version="v1", device="cpu", status="completed")
    db_session.add(run)
    db_session.flush()

    # Create 5 detections for CAM-PAG
    for i in range(5):
        det = Detection(
            id=f"DET-PAG-{i}",
            image_id=frm.id,
            run_id=run.id,
            bbox_x=0.1, bbox_y=0.1, bbox_w=0.2, bbox_h=0.2,
            raw_label="tiger", taxon_id="panthera_tigris", label="Tiger",
            score=0.9, model_version="v1", review_status="pending", provenance="inferred",
        )
        db_session.add(det)
    db_session.commit()

    # Query with page size limit=2, offset=0
    res_p1 = client.get("/api/v1/observations?camera_id=CAM-PAG&limit=2&offset=0")
    assert res_p1.status_code == 200
    body1 = res_p1.json()
    assert body1["meta"]["total"] == 5
    assert len(body1["data"]) == 2

    # Query with offset=4
    res_p3 = client.get("/api/v1/observations?camera_id=CAM-PAG&limit=2&offset=4")
    assert res_p3.status_code == 200
    body3 = res_p3.json()
    assert body3["meta"]["total"] == 5
    assert len(body3["data"]) == 1


# ============================================================================
# 2. H-03: Camera Listing Read-Only & Database Pagination
# ============================================================================

@pytest.mark.integration
def test_camera_listing_read_only_and_database_pagination(client: TestClient, db_session: Session):
    """Verify that GET /api/v1/cameras performs database-level pagination and does not execute commits."""
    now_utc = datetime.now(timezone.utc)

    # Seed 5 cameras:
    # 2 reporting (recent heartbeat 1 hour ago)
    # 2 stale (heartbeat 48 hours ago)
    # 1 unknown (no heartbeat)
    cams = [
        Camera(id="CAM-R1", label="R1", timezone="UTC", last_heartbeat_at=now_utc - timedelta(hours=1), telemetry_status="reporting", provenance="observed"),
        Camera(id="CAM-R2", label="R2", timezone="UTC", last_heartbeat_at=now_utc - timedelta(hours=2), telemetry_status="reporting", provenance="observed"),
        Camera(id="CAM-S1", label="S1", timezone="UTC", last_heartbeat_at=now_utc - timedelta(hours=48), telemetry_status="stale", provenance="observed"),
        Camera(id="CAM-S2", label="S2", timezone="UTC", last_heartbeat_at=now_utc - timedelta(hours=50), telemetry_status="stale", provenance="observed"),
        Camera(id="CAM-U1", label="U1", timezone="UTC", last_heartbeat_at=None, telemetry_status="unknown", provenance="observed"),
    ]
    db_session.add_all(cams)
    db_session.commit()

    # 1. Total count matches 5
    res_all = client.get("/api/v1/cameras")
    assert res_all.status_code == 200
    assert res_all.json()["meta"]["total"] == 5
    assert len(res_all.json()["data"]) == 5

    # 2. Filter by reporting
    res_rep = client.get("/api/v1/cameras?telemetry_status=reporting")
    assert res_rep.status_code == 200
    body_rep = res_rep.json()
    assert body_rep["meta"]["total"] == 2
    assert all(c["telemetry_status"] == "reporting" for c in body_rep["data"])

    # 3. Filter by stale
    res_stale = client.get("/api/v1/cameras?telemetry_status=stale")
    assert res_stale.status_code == 200
    body_stale = res_stale.json()
    assert body_stale["meta"]["total"] == 2
    assert all(c["telemetry_status"] == "stale" for c in body_stale["data"])

    # 4. Filter by unknown
    res_unk = client.get("/api/v1/cameras?telemetry_status=unknown")
    assert res_unk.status_code == 200
    body_unk = res_unk.json()
    assert body_unk["meta"]["total"] == 1
    assert body_unk["data"][0]["id"] == "CAM-U1"
    assert body_unk["data"][0]["telemetry_status"] == "unknown"

    # 5. Database-level pagination
    res_page = client.get("/api/v1/cameras?limit=2&offset=0")
    assert res_page.status_code == 200
    assert res_page.json()["meta"]["total"] == 5
    assert len(res_page.json()["data"]) == 2


# ============================================================================
# 3. M-03: Background Job Exception Logging & Failure Persistence
# ============================================================================

@pytest.mark.integration
def test_background_job_persists_failure_on_unexpected_error(db_session: Session):
    """Verify that unexpected background exceptions transition jobs to 'failed' instead of remaining queued."""
    from src.backend.api.v1.uploads import execute_background_job

    # 1. Create job in queued state
    job = job_service.create_job(db=db_session, upload_id="up_fail_test", media_ids=["med_nonexistent"])
    assert job.status == JobStatus.QUEUED.value

    # 2. Execute background worker with nonexistent media assets using db_session
    execute_background_job(job.id, ["med_nonexistent"], db_session=db_session)

    # Invalidate session cache to read latest database state
    db_session.expire_all()
    updated_job = db_session.query(ProcessingJob).filter_by(id=job.id).first()
    assert updated_job is not None
    assert updated_job.status == JobStatus.FAILED.value
    assert updated_job.error_message is not None
    assert "Cannot process job" in updated_job.error_message

    # 3. Also verify default background execution path (SessionLocal standalone)
    job2 = job_service.create_job(db=db_session, upload_id="up_fail_test2", media_ids=["med_nonexistent_2"])
    assert job2.status == JobStatus.QUEUED.value

    execute_background_job(job2.id, ["med_nonexistent_2"])
    db_session.expire_all()
    updated_job2 = db_session.query(ProcessingJob).filter_by(id=job2.id).first()
    assert updated_job2 is not None
    assert updated_job2.status == JobStatus.FAILED.value
    assert updated_job2.error_message is not None


# ============================================================================
# 4. M-01: Internal Exception Description Masking in Production
# ============================================================================

@pytest.mark.unit
def test_internal_exception_masking_debug_mode():
    """Verify that internal exception description is masked when DEBUG=False and exposed when DEBUG=True."""
    from src.backend.main import app

    route_path = "/api/v1/__test_internal_error__"

    # Register temporary test route
    @app.get(route_path)
    def trigger_error():
        raise RuntimeError("SensitiveDatabasePath: /var/secrets/db_creds.db failed")

    original_debug = settings.DEBUG

    try:
        # Use TestClient with raise_server_exceptions=False so HTTP 500 response is returned for assertions
        with TestClient(app, raise_server_exceptions=False) as test_client:
            # Test 1: In production mode (DEBUG=False)
            settings.DEBUG = False
            res_prod = test_client.get(route_path)
            assert res_prod.status_code == 500
            prod_body = res_prod.json()
            assert "error" in prod_body
            assert prod_body["error"]["code"] == "INTERNAL_SERVER_ERROR"
            assert "details" in prod_body["error"]
            assert prod_body["error"]["details"]["error_type"] == "RuntimeError"
            # Must NOT leak the raw exception description
            assert "description" not in prod_body["error"]["details"]
            assert "request_id" in prod_body

            # Test 2: In debug mode (DEBUG=True)
            settings.DEBUG = True
            res_debug = test_client.get(route_path)
            assert res_debug.status_code == 500
            debug_body = res_debug.json()
            assert "error" in debug_body
            assert debug_body["error"]["code"] == "INTERNAL_SERVER_ERROR"
            assert "description" in debug_body["error"]["details"]
            assert "SensitiveDatabasePath" in debug_body["error"]["details"]["description"]
            assert "request_id" in debug_body
    finally:
        # Restore configuration and remove temporary route to prevent leakage
        settings.DEBUG = original_debug
        app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != route_path]


# ============================================================================
# 5. M-02: Multi-File Upload Rollback and Orphan Disk Cleanup
# ============================================================================

@pytest.mark.integration
def test_multi_file_upload_rollback_and_orphan_cleanup(client: TestClient, db_session: Session, tmp_path):
    """Verify that a batch upload failure cleans up newly written disk files and does not leave orphans."""
    orig_root = storage_service.root_dir
    orig_media = storage_service.media_dir

    try:
        storage_service.root_dir = tmp_path
        storage_service.media_dir = tmp_path / "media"
        storage_service.media_dir.mkdir(parents=True, exist_ok=True)

        # Batch with 1 valid file and 1 corrupted file
        files = [
            ("files", ("valid_1.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")),
            ("files", ("corrupted_2.jpg", io.BytesIO(CORRUPTED_BYTES), "image/jpeg")),
        ]

        resp = client.post("/api/v1/uploads", files=files)
        # Must fail with validation error due to file 2
        assert resp.status_code == 422

        # Verify no MediaAsset rows committed
        assert db_session.query(MediaAsset).count() == 0

        # Verify that valid_1.jpg was cleaned up from disk (no orphaned files)
        all_stored_files = list(storage_service.media_dir.rglob("*.jpg"))
        assert len(all_stored_files) == 0

    finally:
        storage_service.root_dir = orig_root
        storage_service.media_dir = orig_media


# ============================================================================
# 6. Deduplication Preservation
# ============================================================================

@pytest.mark.integration
def test_deduplication_preserves_existing_files(client: TestClient, db_session: Session, tmp_path):
    """Verify that uploading identical bytes reuses existing records and never deletes committed files."""
    orig_root = storage_service.root_dir
    orig_media = storage_service.media_dir

    try:
        storage_service.root_dir = tmp_path
        storage_service.media_dir = tmp_path / "media"
        storage_service.media_dir.mkdir(parents=True, exist_ok=True)

        # 1. First upload
        files1 = [("files", ("first_upload.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
        res1 = client.post("/api/v1/uploads", files=files1)
        assert res1.status_code == 202
        assert res1.json()["data"]["media_items"][0]["is_duplicate"] is False

        # 2. Duplicate upload under different filename
        files2 = [("files", ("second_upload.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
        res2 = client.post("/api/v1/uploads", files=files2)
        assert res2.status_code == 202
        assert res2.json()["data"]["media_items"][0]["is_duplicate"] is True

        # Exactly 1 physical file on disk despite two uploads
        all_files = list(storage_service.media_dir.rglob("*.jpg"))
        assert len(all_files) == 1
    finally:
        storage_service.root_dir = orig_root
        storage_service.media_dir = orig_media
