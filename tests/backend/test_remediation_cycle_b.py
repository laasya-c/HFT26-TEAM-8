"""Remediation Cycle B Regression Test Suite.

Verifies fixes for:
1. H-02: Bounded chunk streaming of uploads, 50MB limit enforcement during streaming,
   cleanup on validation/size failures, atomic file writes, and deduplication preservation.
2. M-04: Database indexes for frequently queried columns on detections, review_events,
   and image_frames via migration 004 and ORM definitions.
3. M-05: SQL aggregation for camera diagnostics quality flags, avoiding full ORM model
   hydration into memory, zero-count fast path, and decoupling telemetry health from image silence.
4. L-01: Explicit database session rollback on unhandled exceptions in get_db() and guaranteed
   session closure even if rollback raises.
"""
import importlib
import io
import os
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from src.backend.config import settings
from src.backend.core.auth_deps import get_current_active_user, get_current_user, verify_telemetry_auth
from src.backend.core.exceptions import ValidationException
from src.backend.db.session import get_db
from src.backend.main import app
from src.backend.models import (
    Camera,
    Detection,
    ImageFrame,
    MediaAsset,
    ReviewEvent,
    User,
    UserRole,
)
from src.backend.services.camera import camera_service
from src.backend.services.storage import MAX_UPLOAD_SIZE_BYTES, storage_service

VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb" + b"\x00" * 50
CORRUPTED_BYTES = b"Plain text disguised as JPEG - invalid magic bytes"


@pytest.fixture(autouse=True)
def authenticate_legacy_cycle_tests(db_session: Session):
    """Provides authenticated admin context for legacy regression suites."""
    admin_user = User(
        id="legacy_admin_user_b",
        username="legacy_admin_b",
        email="legacy_admin_b@wildscope.org",
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
# 1. H-02: Streaming Uploads, Bounded Memory, Size Limits & Temp Cleanup
# ============================================================================

@pytest.mark.integration
def test_stream_upload_success_chunked(client: TestClient, db_session: Session, tmp_path: Path):
    """Verify that uploading via streaming succeeds, writes atomic file, and returns 202."""
    orig_root = storage_service.root_dir
    orig_media = storage_service.media_dir

    try:
        storage_service.root_dir = tmp_path
        storage_service.media_dir = tmp_path / "media"
        storage_service.media_dir.mkdir(parents=True, exist_ok=True)

        files = [("files", ("test_stream.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
        resp = client.post("/api/v1/uploads", files=files)

        assert resp.status_code == 202
        body = resp.json()
        assert body["data"]["files_received"] == 1
        assert body["data"]["media_items"][0]["is_duplicate"] is False
        assert body["data"]["status"] == "queued"

        # Verify physical file written
        all_stored_files = list(storage_service.media_dir.rglob("*.jpg"))
        assert len(all_stored_files) == 1

        # Verify no orphan temporary files in _tmp
        tmp_dir = storage_service.media_dir / "_tmp"
        if tmp_dir.exists():
            assert len(list(tmp_dir.glob("*.tmp"))) == 0

    finally:
        storage_service.root_dir = orig_root
        storage_service.media_dir = orig_media


@pytest.mark.integration
@pytest.mark.anyio
async def test_stream_upload_exceeds_max_size_aborts_early(db_session: Session, tmp_path: Path):
    """Verify that store_media_stream aborts and cleans up when exceeding 50MB during streaming."""
    orig_root = storage_service.root_dir
    orig_media = storage_service.media_dir

    try:
        storage_service.root_dir = tmp_path
        storage_service.media_dir = tmp_path / "media"
        storage_service.media_dir.mkdir(parents=True, exist_ok=True)

        # Mock an upload file yielding chunks that exceed MAX_UPLOAD_SIZE_BYTES
        class MockOverCapacityUpload:
            def __init__(self, target_size: int):
                self.remaining = target_size
                self._buffer = b"\x00" * (64 * 1024)

            async def read(self, size: int = -1) -> bytes:
                if self.remaining <= 0:
                    return b""
                sz = min(len(self._buffer), self.remaining)
                self.remaining -= sz
                return self._buffer[:sz]

        mock_file = MockOverCapacityUpload(target_size=MAX_UPLOAD_SIZE_BYTES + 1024)

        with pytest.raises(ValidationException) as exc_info:
            await storage_service.store_media_stream(
                upload_file=mock_file,
                original_filename="large_file.dat",
                db_session=db_session,
            )

        assert "exceeds the maximum allowed limit" in str(exc_info.value)

        # Verify temporary file was deleted immediately on failure
        tmp_dir = storage_service.media_dir / "_tmp"
        if tmp_dir.exists():
            assert len(list(tmp_dir.glob("*.tmp"))) == 0

    finally:
        storage_service.root_dir = orig_root
        storage_service.media_dir = orig_media


@pytest.mark.integration
def test_stream_upload_corrupted_magic_bytes_cleanup(client: TestClient, db_session: Session, tmp_path: Path):
    """Verify that magic byte validation failure cleans up temporary file and leaves 0 media records."""
    orig_root = storage_service.root_dir
    orig_media = storage_service.media_dir

    try:
        storage_service.root_dir = tmp_path
        storage_service.media_dir = tmp_path / "media"
        storage_service.media_dir.mkdir(parents=True, exist_ok=True)

        files = [("files", ("corrupt.jpg", io.BytesIO(CORRUPTED_BYTES), "image/jpeg"))]
        resp = client.post("/api/v1/uploads", files=files)

        assert resp.status_code == 422
        assert db_session.query(MediaAsset).count() == 0

        # Verify no orphan temporary files in _tmp or media directory
        tmp_dir = storage_service.media_dir / "_tmp"
        if tmp_dir.exists():
            assert len(list(tmp_dir.glob("*.tmp"))) == 0
        assert len(list(storage_service.media_dir.rglob("*.jpg"))) == 0

    finally:
        storage_service.root_dir = orig_root
        storage_service.media_dir = orig_media


@pytest.mark.integration
def test_stream_upload_preserves_deduplication(client: TestClient, db_session: Session, tmp_path: Path):
    """Verify deduplication works properly with streaming uploads without redundant storage."""
    orig_root = storage_service.root_dir
    orig_media = storage_service.media_dir

    try:
        storage_service.root_dir = tmp_path
        storage_service.media_dir = tmp_path / "media"
        storage_service.media_dir.mkdir(parents=True, exist_ok=True)

        # First upload
        files1 = [("files", ("photo1.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
        res1 = client.post("/api/v1/uploads", files=files1)
        assert res1.status_code == 202
        assert res1.json()["data"]["media_items"][0]["is_duplicate"] is False

        # Duplicate upload
        files2 = [("files", ("photo1_dup.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
        res2 = client.post("/api/v1/uploads", files=files2)
        assert res2.status_code == 202
        assert res2.json()["data"]["media_items"][0]["is_duplicate"] is True

        # Exactly 1 physical file on disk
        stored_files = list(storage_service.media_dir.rglob("*.jpg"))
        assert len(stored_files) == 1

        # No temp files left behind
        tmp_dir = storage_service.media_dir / "_tmp"
        if tmp_dir.exists():
            assert len(list(tmp_dir.glob("*.tmp"))) == 0

    finally:
        storage_service.root_dir = orig_root
        storage_service.media_dir = orig_media


# ============================================================================
# 2. M-04: Database Indexes Verification
# ============================================================================

@pytest.mark.unit
def test_database_indexes_on_tables(db_session: Session):
    """Verify that performance and query indexes exist on detections, review_events, and image_frames."""
    bind = db_session.get_bind()
    inspector = inspect(bind)

    # 1. Detection indexes
    detection_indexes = {idx["name"] for idx in inspector.get_indexes("detections")}
    assert "ix_detections_review_status_created" in detection_indexes
    assert "ix_detections_taxon_id_created" in detection_indexes
    assert "ix_detections_image_id" in detection_indexes
    assert "ix_detections_encounter_id" in detection_indexes

    # 2. ReviewEvent indexes
    review_indexes = {idx["name"] for idx in inspector.get_indexes("review_events")}
    assert "ix_review_events_detection_created" in review_indexes

    # 3. ImageFrame indexes
    image_frame_indexes = {idx["name"] for idx in inspector.get_indexes("image_frames")}
    assert "ix_image_frames_source_media" in image_frame_indexes


@pytest.mark.unit
def test_alembic_migration_004_definition():
    """Verify that migration 004 has correct revision metadata, down_revision, and operations."""
    mig004 = importlib.import_module("migrations.versions.004_add_performance_and_query_indexes")

    assert mig004.revision == "004_add_performance_and_query_indexes"
    assert mig004.down_revision == "003_phase3_audit_and_indexes"
    assert callable(mig004.upgrade)
    assert callable(mig004.downgrade)


# ============================================================================
# 3. M-05: Camera Diagnostics SQL Aggregation & Decoupling
# ============================================================================

@pytest.mark.integration
def test_camera_details_aggregation_with_frames(client: TestClient, db_session: Session):
    """Verify that camera diagnostics calculates quality flag counts via SQL aggregation accurately."""
    camera = Camera(
        id="CAM-AGG-1",
        label="Aggregation Test Station",
        timezone="UTC",
        telemetry_status="unknown",
        provenance="observed",
    )
    db_session.add(camera)
    db_session.flush()

    media = MediaAsset(
        id="MED-AGG-1",
        type="image",
        camera_id=camera.id,
        storage_key="media/agg.jpg",
        content_hash="hash_agg_1",
        provenance="observed",
    )
    db_session.add(media)
    db_session.flush()

    # Create 3 frames with various quality flags
    frm1 = ImageFrame(
        id="FRM-AGG-1",
        source_media_id=media.id,
        content_url="/api/v1/images/FRM-AGG-1/content",
        quality_flags=["low_light", "motion_blur"],
        provenance="observed",
    )
    frm2 = ImageFrame(
        id="FRM-AGG-2",
        source_media_id=media.id,
        content_url="/api/v1/images/FRM-AGG-2/content",
        quality_flags=["low_light"],
        provenance="observed",
    )
    frm3 = ImageFrame(
        id="FRM-AGG-3",
        source_media_id=media.id,
        content_url="/api/v1/images/FRM-AGG-3/content",
        quality_flags=["lens_obstruction"],
        provenance="observed",
    )
    db_session.add_all([frm1, frm2, frm3])
    db_session.commit()

    details = camera_service.get_camera_details(db_session, "CAM-AGG-1")

    assert details["id"] == "CAM-AGG-1"
    assert details["observation_quality"]["total_images"] == 3
    assert details["observation_quality"]["quality_flags_summary"] == {
        "low_light": 2,
        "motion_blur": 1,
        "lens_obstruction": 1,
    }
    # Scientific Decoupling check: telemetry status is not marked dead despite visual flags
    assert details["telemetry_status"] == "unknown"


@pytest.mark.integration
def test_camera_details_zero_images_fast_path(db_session: Session):
    """Verify that a camera with zero images executes the fast path returning empty flag counts."""
    camera = Camera(
        id="CAM-EMPTY-1",
        label="Empty Camera Station",
        timezone="UTC",
        telemetry_status="unknown",
        provenance="observed",
    )
    db_session.add(camera)
    db_session.commit()

    details = camera_service.get_camera_details(db_session, "CAM-EMPTY-1")

    assert details["id"] == "CAM-EMPTY-1"
    assert details["observation_quality"]["total_images"] == 0
    assert details["observation_quality"]["quality_flags_summary"] == {}


@pytest.mark.integration
def test_camera_diagnostics_fallback_projection(db_session: Session, monkeypatch):
    """Verify that column projection fallback works if SQL JSON dialect aggregation is unavailable."""
    camera = Camera(
        id="CAM-FB-1",
        label="Fallback Station",
        timezone="UTC",
        telemetry_status="unknown",
        provenance="observed",
    )
    db_session.add(camera)
    db_session.flush()

    media = MediaAsset(
        id="MED-FB-1",
        type="image",
        camera_id=camera.id,
        storage_key="media/fb.jpg",
        content_hash="hash_fb",
        provenance="observed",
    )
    db_session.add(media)
    db_session.flush()

    frm = ImageFrame(
        id="FRM-FB-1",
        source_media_id=media.id,
        content_url="/api/v1/images/FRM-FB-1/content",
        quality_flags=["snow_glare"],
        provenance="observed",
    )
    db_session.add(frm)
    db_session.commit()

    # Simulate an engine dialect without native json functions (e.g. custom or unsupported engine)
    # Isolates dialect selection on camera_service so real SQLite database queries continue working
    monkeypatch.setattr(camera_service, "get_database_dialect", lambda _db=None: "unsupported_dialect")

    details = camera_service.get_camera_details(db_session, "CAM-FB-1")

    assert details["observation_quality"]["total_images"] == 1
    assert details["observation_quality"]["quality_flags_summary"] == {"snow_glare": 1}


# ============================================================================
# 4. L-01: Database Session Safety & Rollback in get_db()
# ============================================================================

@pytest.mark.unit
def test_get_db_explicit_rollback_on_exception():
    """Verify that get_db() explicitly rolls back uncommitted changes when an exception occurs."""
    gen = get_db()
    db = next(gen)

    # Add an uncommitted record
    cam = Camera(
        id="CAM-TEST-ROLLBACK",
        label="Rollback Test Station",
        timezone="UTC",
        telemetry_status="unknown",
        provenance="observed",
    )
    db.add(cam)

    # Simulate unhandled exception thrown into the dependency generator
    with pytest.raises(RuntimeError) as exc_info:
        gen.throw(RuntimeError("Unhandled route crash"))

    assert "Unhandled route crash" in str(exc_info.value)

    # Verify via a fresh session that CAM-TEST-ROLLBACK was never committed
    check_gen = get_db()
    check_db = next(check_gen)
    try:
        found = check_db.query(Camera).filter_by(id="CAM-TEST-ROLLBACK").first()
        assert found is None
    finally:
        check_gen.close()


@pytest.mark.unit
def test_get_db_guarantees_session_close_even_if_rollback_fails():
    """Verify that get_db() guarantees session closure even if rollback itself raises an error."""
    gen = get_db()
    db = next(gen)

    # Mock rollback to raise an error
    original_close = db.close
    close_called = False

    def faulty_rollback():
        raise RuntimeError("Rollback connection lost")

    def tracked_close():
        nonlocal close_called
        close_called = True
        original_close()

    db.rollback = faulty_rollback
    db.close = tracked_close

    with pytest.raises(RuntimeError) as exc_info:
        gen.throw(RuntimeError("Original route error"))

    assert "Original route error" in str(exc_info.value)
    assert close_called is True
