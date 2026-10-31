"""Tests for Media Storage Service, Magic Bytes, and Path Traversal Protection."""
import pytest
from src.backend.core.exceptions import ValidationException
from src.backend.services.storage import (
    MAX_UPLOAD_SIZE_BYTES,
    StorageService,
    compute_sha256,
    detect_media_format,
)

# Minimal valid magic byte headers
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb" + b"\x00" * 50
VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 50
VALID_MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 50
FAKE_JPEG_TEXT = b"This is a text file renamed to fake_camera_trap.jpg"


@pytest.mark.unit
def test_detect_media_format_valid():
    """Verify that genuine JPEG, PNG, and MP4 signatures are recognized."""
    media_type, ext = detect_media_format(VALID_JPEG_BYTES)
    assert media_type == "image"
    assert ext == "jpg"

    media_type, ext = detect_media_format(VALID_PNG_BYTES)
    assert media_type == "image"
    assert ext == "png"

    media_type, ext = detect_media_format(VALID_MP4_BYTES)
    assert media_type == "video"
    assert ext == "mp4"


@pytest.mark.unit
def test_detect_media_format_rejects_fake_extension():
    """Verify that text files disguised with a .jpg extension are strictly rejected."""
    with pytest.raises(ValidationException) as exc_info:
        detect_media_format(FAKE_JPEG_TEXT)
    assert "Unsupported media format" in str(exc_info.value)


@pytest.mark.unit
def test_compute_sha256_deterministic():
    """Verify SHA-256 computation is deterministic and accurate."""
    digest1 = compute_sha256(VALID_JPEG_BYTES)
    digest2 = compute_sha256(VALID_JPEG_BYTES)
    assert digest1 == digest2
    assert len(digest1) == 64


@pytest.mark.unit
def test_path_traversal_protection(tmp_path):
    """Verify that attempting to resolve a path outside storage root raises ValidationException."""
    service = StorageService(root_dir=str(tmp_path))

    # Safe path succeeds
    safe_path = service.resolve_safe_path("media/ab/cd/sample.jpg")
    assert str(safe_path).startswith(str(tmp_path))

    # Directory traversal is strictly rejected
    with pytest.raises(ValidationException) as exc_info:
        service.resolve_safe_path("../../Windows/System32/cmd.exe")
    assert "directory traversal attempt detected" in str(exc_info.value)


@pytest.mark.integration
def test_storage_service_save_and_deduplicate(tmp_path, db_session):
    """Verify storing media writes bytes and deduplicates identical uploads."""
    service = StorageService(root_dir=str(tmp_path))

    # 0. Setup Camera fixture to satisfy foreign-key constraint on media_assets.camera_id
    from src.backend.models.camera import Camera
    camera = Camera(
        id="CAM-01",
        label="Ridge Trail Camera",
        timezone="Asia/Kolkata",
        telemetry_status="unknown",
        provenance="observed",
    )
    db_session.add(camera)
    db_session.commit()

    # 1. First upload
    asset1, frame1, is_dup1 = service.store_media(
        file_bytes=VALID_JPEG_BYTES,
        original_filename="tiger_01.jpg",
        db_session=db_session,
        camera_id="CAM-01",
    )
    db_session.commit()

    assert is_dup1 is False
    assert asset1.content_hash == compute_sha256(VALID_JPEG_BYTES)
    assert asset1.camera_id == "CAM-01"
    assert frame1.content_url == f"/api/v1/images/{frame1.id}/content"

    # Verify file exists on disk
    disk_path = service.resolve_safe_path(asset1.storage_key)
    assert disk_path.exists()
    assert disk_path.read_bytes() == VALID_JPEG_BYTES

    # 2. Second upload with identical bytes but different filename
    asset2, frame2, is_dup2 = service.store_media(
        file_bytes=VALID_JPEG_BYTES,
        original_filename="renamed_tiger.jpg",
        db_session=db_session,
        camera_id="CAM-01",
    )
    assert is_dup2 is True
    assert asset2.id == asset1.id  # Same asset reused per deduplication policy
    assert asset2.camera_id == "CAM-01"
    assert frame2.id == frame1.id


@pytest.mark.unit
def test_storage_service_rejects_empty_file(tmp_path, db_session):
    """Verify empty upload (0 bytes) is rejected."""
    service = StorageService(root_dir=str(tmp_path))
    with pytest.raises(ValidationException) as exc_info:
        service.store_media(
            file_bytes=b"",
            original_filename="empty.jpg",
            db_session=db_session,
        )
    assert "Empty upload" in str(exc_info.value)
