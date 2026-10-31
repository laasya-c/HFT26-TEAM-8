"""Media Storage and Validation Service.

Responsibilities:
1. Validate file size and strict magic bytes (rejects extensions-only trust).
2. Compute SHA-256 content hashes.
3. Content-addressed safe storage outside database rows.
4. Path traversal protection.
5. Deduplication: avoids rewriting identical byte payloads while preserving metadata.
6. Atomic file writing to prevent corrupt/partial files on disk.
"""
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from src.backend.config import settings
from src.backend.core.exceptions import ValidationException
from src.backend.models.media import ImageFrame, MediaAsset

# Allowed magic bytes signatures
# Do not trust client-supplied Content-Type or file extensions
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MP4_FTYP = b"ftyp"  # Located at bytes 4..8 in standard ISO MP4

# Default 50MB file size limit
MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024


def detect_media_format(header: bytes) -> Tuple[str, str]:
    """Inspects file signature (magic bytes) to determine genuine media format.
    
    Returns:
        Tuple of (media_type, file_extension): e.g. ("image", "jpg")
        
    Raises:
        ValidationException if signature is unrecognized or suspicious.
    """
    if len(header) < 12:
        raise ValidationException("File is too small or truncated to contain a valid media header.")

    if header.startswith(JPEG_MAGIC):
        return "image", "jpg"
    elif header.startswith(PNG_MAGIC):
        return "image", "png"
    elif len(header) >= 8 and header[4:8] == MP4_FTYP:
        return "video", "mp4"
    else:
        raise ValidationException(
            "Unsupported media format. Only genuine JPEG, PNG, and MP4 files are accepted. "
            "File signature did not match supported wildlife media types."
        )


def compute_sha256(data: bytes) -> str:
    """Calculates deterministic SHA-256 digest of file bytes."""
    hasher = hashlib.sha256()
    hasher.update(data)
    return hasher.hexdigest()


class StorageService:
    """Encapsulates safe media storage operations and database persistence."""

    def __init__(self, root_dir: Optional[str] = None):
        self.root_dir = Path(root_dir or settings.STORAGE_ROOT).resolve()
        self.media_dir = (self.root_dir / "media").resolve()
        self.media_dir.mkdir(parents=True, exist_ok=True)

    def resolve_safe_path(self, relative_storage_key: str) -> Path:
        """Resolves a storage key and guarantees it remains inside the root directory.
        
        Prevents directory traversal attacks (e.g. '../../etc/passwd').
        """
        # Normalize relative path separators
        normalized_key = relative_storage_key.replace("\\", "/").lstrip("/")
        target_path = (self.root_dir / normalized_key).resolve()
        try:
            target_path.relative_to(self.root_dir)
        except ValueError:
            raise ValidationException("Invalid storage key: directory traversal attempt detected.")
        return target_path

    def store_media(
        self,
        file_bytes: bytes,
        original_filename: str,
        db_session,
        camera_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
        timezone_source: Optional[str] = None,
        uploader_id: Optional[str] = None,
    ) -> Tuple[MediaAsset, ImageFrame, bool]:
        """Validates, hashes, stores bytes on disk, and persists database records.
        
        Deduplication Policy:
        - If content_hash matches an existing record AND file exists on disk:
          Reuses existing MediaAsset and ImageFrame. Does not duplicate disk bytes or rows.
          Returns is_duplicate=True.
        - If filename is identical but bytes differ:
          Stored independently under its own unique content hash (is_duplicate=False).
        
        Returns:
            Tuple of (MediaAsset, ImageFrame, is_duplicate: bool)
        """
        # 1. Enforce size limits
        if len(file_bytes) == 0:
            raise ValidationException("Empty upload: file contains 0 bytes.")
        if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
            raise ValidationException(
                f"File size ({len(file_bytes)} bytes) exceeds the maximum allowed limit of {MAX_UPLOAD_SIZE_BYTES} bytes (50MB)."
            )

        # 2. Validate file signature (magic bytes)
        media_type, extension = detect_media_format(file_bytes[:32])

        # 3. Compute deterministic hash
        content_hash = compute_sha256(file_bytes)

        # 4. Content-addressed storage path: media/{hash[:2]}/{hash[2:4]}/{hash}.{ext}
        subdir = self.media_dir / content_hash[:2] / content_hash[2:4]
        subdir.mkdir(parents=True, exist_ok=True)
        final_filename = f"{content_hash}.{extension}"
        final_path = (subdir / final_filename).resolve()
        relative_key = str(final_path.relative_to(self.root_dir)).replace("\\", "/")

        # 5. Check for existing media asset (Deduplication)
        existing_asset = db_session.query(MediaAsset).filter_by(content_hash=content_hash).first()
        if existing_asset is not None:
            # Check if file physically exists on disk
            try:
                disk_path = self.resolve_safe_path(existing_asset.storage_key)
                file_on_disk = disk_path.exists() and disk_path.is_file()
            except Exception:
                file_on_disk = False

            if file_on_disk:
                primary_frame = (
                    db_session.query(ImageFrame)
                    .filter_by(source_media_id=existing_asset.id)
                    .first()
                )
                if primary_frame is not None:
                    return existing_asset, primary_frame, True

        # 6. Atomic write: write to temp file then rename to prevent partial writes
        temp_path = subdir / f"{content_hash}_{uuid.uuid4().hex[:8]}.tmp"
        try:
            with open(temp_path, "wb") as f:
                f.write(file_bytes)
            # Atomic rename (overwrites if duplicate on disk)
            os.replace(temp_path, final_path)
        except Exception as exc:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Storage failure writing file to disk: {exc}")

        # If asset already existed in DB but was missing on disk, update storage_key and return
        if existing_asset is not None:
            existing_asset.storage_key = relative_key
            primary_frame = (
                db_session.query(ImageFrame)
                .filter_by(source_media_id=existing_asset.id)
                .first()
            )
            if primary_frame is None:
                frame_id = str(uuid.uuid4())
                primary_frame = ImageFrame(
                    id=frame_id,
                    source_media_id=existing_asset.id,
                    frame_offset_ms=None,
                    orientation=1,
                    content_url=f"/api/v1/images/{frame_id}/content",
                    quality_flags=[],
                    provenance="observed",
                )
                db_session.add(primary_frame)
                db_session.flush()
            return existing_asset, primary_frame, False

        # 7. Persist MediaAsset record
        media_id = str(uuid.uuid4())
        media_asset = MediaAsset(
            id=media_id,
            type=media_type,
            camera_id=camera_id,
            uploader_id=uploader_id,
            storage_key=relative_key,
            content_hash=content_hash,
            raw_timestamp=original_filename,  # Retain original filename as metadata only
            captured_at=captured_at,
            timezone_source=timezone_source,
            provenance="observed",
        )
        db_session.add(media_asset)
        db_session.flush()

        # 8. Create primary ImageFrame record
        frame_id = str(uuid.uuid4())
        image_frame = ImageFrame(
            id=frame_id,
            source_media_id=media_id,
            frame_offset_ms=None,
            orientation=1,
            content_url=f"/api/v1/images/{frame_id}/content",
            quality_flags=[],
            provenance="observed",
        )
        db_session.add(image_frame)
        db_session.flush()

        return media_asset, image_frame, False

    async def store_media_stream(
        self,
        upload_file: Any,
        original_filename: str,
        db_session,
        camera_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
        timezone_source: Optional[str] = None,
        chunk_size: int = 64 * 1024,
        uploader_id: Optional[str] = None,
    ) -> Tuple[MediaAsset, ImageFrame, bool]:
        """Streams upload file in bounded chunks, enforcing 50MB limit and computing hash on the fly.
        
        Guarantees:
        - Bounded memory usage (reads in 64KB chunks).
        - Enforces MAX_UPLOAD_SIZE_BYTES (50MB) during streaming.
        - Immediate cleanup of partial/temp files on size, validation, or storage failures.
        - Deduplication and atomic file writes.
        """
        temp_dir = self.media_dir / "_tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"stream_{uuid.uuid4().hex}.tmp"

        hasher = hashlib.sha256()
        total_bytes = 0
        header_bytes = b""

        try:
            with open(temp_path, "wb") as f:
                while True:
                    chunk = await upload_file.read(chunk_size)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > MAX_UPLOAD_SIZE_BYTES:
                        raise ValidationException(
                            f"File size exceeds the maximum allowed limit of {MAX_UPLOAD_SIZE_BYTES} bytes (50MB)."
                        )
                    hasher.update(chunk)
                    f.write(chunk)
                    if len(header_bytes) < 32:
                        header_bytes += chunk[: 32 - len(header_bytes)]
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

        # Check empty upload
        if total_bytes == 0:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise ValidationException("Empty upload: file contains 0 bytes.")

        # Validate magic bytes
        try:
            media_type, extension = detect_media_format(header_bytes)
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

        content_hash = hasher.hexdigest()

        # Content-addressed destination path
        subdir = self.media_dir / content_hash[:2] / content_hash[2:4]
        subdir.mkdir(parents=True, exist_ok=True)
        final_filename = f"{content_hash}.{extension}"
        final_path = (subdir / final_filename).resolve()
        relative_key = str(final_path.relative_to(self.root_dir)).replace("\\", "/")

        # Check deduplication
        existing_asset = db_session.query(MediaAsset).filter_by(content_hash=content_hash).first()
        if existing_asset is not None:
            try:
                disk_path = self.resolve_safe_path(existing_asset.storage_key)
                file_on_disk = disk_path.exists() and disk_path.is_file()
            except Exception:
                file_on_disk = False

            if file_on_disk:
                # Deduplicated: clean up temp file and reuse existing records
                temp_path.unlink(missing_ok=True)
                primary_frame = (
                    db_session.query(ImageFrame)
                    .filter_by(source_media_id=existing_asset.id)
                    .first()
                )
                if primary_frame is not None:
                    return existing_asset, primary_frame, True

        # Atomic move to final content-addressed location
        try:
            os.replace(temp_path, final_path)
        except Exception as exc:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Storage failure moving file to disk: {exc}")

        # If asset already existed in DB but was missing on disk
        if existing_asset is not None:
            existing_asset.storage_key = relative_key
            primary_frame = (
                db_session.query(ImageFrame)
                .filter_by(source_media_id=existing_asset.id)
                .first()
            )
            if primary_frame is None:
                frame_id = str(uuid.uuid4())
                primary_frame = ImageFrame(
                    id=frame_id,
                    source_media_id=existing_asset.id,
                    frame_offset_ms=None,
                    orientation=1,
                    content_url=f"/api/v1/images/{frame_id}/content",
                    quality_flags=[],
                    provenance="observed",
                )
                db_session.add(primary_frame)
                db_session.flush()
            return existing_asset, primary_frame, False

        # Persist new MediaAsset record
        media_id = str(uuid.uuid4())
        media_asset = MediaAsset(
            id=media_id,
            type=media_type,
            camera_id=camera_id,
            uploader_id=uploader_id,
            storage_key=relative_key,
            content_hash=content_hash,
            raw_timestamp=original_filename,
            captured_at=captured_at,
            timezone_source=timezone_source,
            provenance="observed",
        )
        db_session.add(media_asset)
        db_session.flush()

        # Persist new primary ImageFrame record
        frame_id = str(uuid.uuid4())
        image_frame = ImageFrame(
            id=frame_id,
            source_media_id=media_id,
            frame_offset_ms=None,
            orientation=1,
            content_url=f"/api/v1/images/{frame_id}/content",
            quality_flags=[],
            provenance="observed",
        )
        db_session.add(image_frame)
        db_session.flush()

        return media_asset, image_frame, False


# Global service singleton
storage_service = StorageService()
