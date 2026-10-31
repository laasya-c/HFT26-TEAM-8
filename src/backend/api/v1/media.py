"""Safe Media Retrieval API Endpoint.

Implements GET /api/v1/images/{id}/content:
- Resolves media by stable ImageFrame ID (or MediaAsset ID).
- Prevents directory traversal attacks.
- Returns binary stream with appropriate MIME type.
- Never exposes host filesystem paths in error payloads.
"""
from pathlib import Path
from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from src.backend.core.auth_deps import get_current_active_user
from src.backend.core.exceptions import EntityNotFoundException, ValidationException
from src.backend.db.session import get_db
from src.backend.models.auth import User
from src.backend.models.media import ImageFrame, MediaAsset
from src.backend.services.storage import storage_service

router = APIRouter()


@router.get("/images/{image_id}/content", summary="Retrieve Image Content Stream")
def get_image_content(
    image_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Serves the binary image file safely without exposing internal storage paths."""
    # 1. Lookup ImageFrame or MediaAsset
    frame = db.query(ImageFrame).filter_by(id=image_id).first()
    if frame is not None:
        media_asset = (
            frame.media_asset
            or db.query(MediaAsset).filter_by(id=frame.source_media_id).first()
        )
    else:
        media_asset = db.query(MediaAsset).filter_by(id=image_id).first()

    if media_asset is None:
        raise EntityNotFoundException("Image", image_id)

    # 2. Resolve safe disk path
    file_path = storage_service.resolve_safe_path(media_asset.storage_key)
    if not file_path.exists() or not file_path.is_file():
        raise EntityNotFoundException("ImageContent", image_id)

    # 3. Determine MIME type based on media type and file extension
    ext = file_path.suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".mp4": "video/mp4",
    }
    content_type = media_type_map.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        media_type=content_type,
        filename=f"{image_id}{ext}",
    )
