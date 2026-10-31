"""Tests for API v1 Endpoints (Uploads, Jobs, Media Serving, and Observations)."""
import io
import pytest
from starlette.testclient import TestClient

from src.backend.services.jobs import job_service
from src.backend.services.storage import storage_service

VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb" + b"\x00" * 50
FAKE_JPEG_BYTES = b"Plain text disguised as JPEG"


@pytest.mark.integration
def test_upload_valid_media_accepted(researcher_client: TestClient):
    """Verify POST /api/v1/uploads returns 202 with upload_id and job_id."""
    files = [
        ("files", ("camera_trap_1.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))
    ]
    response = researcher_client.post("/api/v1/uploads", files=files)
    assert response.status_code == 202

    payload = response.json()
    assert "data" in payload
    data = payload["data"]
    assert "upload_id" in data
    assert "job_id" in data
    assert data["files_received"] == 1
    assert data["status"] == "queued"
    assert len(data["media_items"]) == 1
    assert data["media_items"][0]["content_hash"] is not None


@pytest.mark.integration
def test_upload_rejects_corrupted_signature(researcher_client: TestClient):
    """Verify POST /api/v1/uploads rejects files with invalid magic bytes."""
    files = [
        ("files", ("corrupted.jpg", io.BytesIO(FAKE_JPEG_BYTES), "image/jpeg"))
    ]
    response = researcher_client.post("/api/v1/uploads", files=files)
    assert response.status_code == 422

    payload = response.json()
    assert "error" in payload
    assert "Unsupported media format" in payload["error"]["message"]


@pytest.mark.integration
def test_get_job_status_existing(admin_client: TestClient, db_session):
    """Verify GET /api/v1/jobs/{id} returns job progress and state."""
    job = job_service.create_job(db=db_session, upload_id="up_api_test", media_ids=["med_1"])

    response = admin_client.get(f"/api/v1/jobs/{job.id}")
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["id"] == job.id
    assert data["status"] == "queued"
    assert data["progress"] == 0.0


@pytest.mark.integration
def test_get_job_status_nonexistent(admin_client: TestClient):
    """Verify GET /api/v1/jobs/{id} returns 404 for unknown job."""
    response = admin_client.get("/api/v1/jobs/nonexistent_job_id")
    assert response.status_code == 404

    payload = response.json()
    assert "error" in payload
    assert payload["error"]["code"] == "PROCESSINGJOB_NOT_FOUND"


@pytest.mark.integration
def test_get_image_content_and_missing(researcher_client: TestClient, db_session, tmp_path):
    """Verify GET /api/v1/images/{id}/content returns binary stream and 404 for missing."""
    original_root = storage_service.root_dir
    original_media = storage_service.media_dir
    sample_bytes = VALID_JPEG_BYTES + b"_sample_test_image"
    try:
        # 1. Store a test image
        storage_service.root_dir = tmp_path
        storage_service.media_dir = tmp_path / "media"
        storage_service.media_dir.mkdir(parents=True, exist_ok=True)

        media, frame, _ = storage_service.store_media(
            file_bytes=sample_bytes,
            original_filename="sample.jpg",
            db_session=db_session,
        )
        db_session.commit()

        # 2. Retrieve image content via frame ID
        response = researcher_client.get(f"/api/v1/images/{frame.id}/content")
        assert response.status_code == 200
        assert response.content == sample_bytes
        assert response.headers["content-type"] == "image/jpeg"

        # 3. Missing image returns 404
        missing_response = researcher_client.get("/api/v1/images/missing_frame_id/content")
        assert missing_response.status_code == 404
    finally:
        storage_service.root_dir = original_root
        storage_service.media_dir = original_media


@pytest.mark.integration
def test_list_observations_empty(researcher_client: TestClient):
    """Verify GET /api/v1/observations returns empty paginated envelope when no detections."""
    response = researcher_client.get("/api/v1/observations")
    assert response.status_code == 200

    payload = response.json()
    assert "data" in payload
    assert isinstance(payload["data"], list)
    assert payload["meta"]["total"] == 0
