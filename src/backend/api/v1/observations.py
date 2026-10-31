"""Observations and Encounters Retrieval API Endpoints.

Implements:
- GET /api/v1/observations: Paginated list of genuine model detections.
- GET /api/v1/encounters/{id}: Operational encounter record with member links.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from contracts.schemas import DetectionContract, EncounterContract
from src.backend.config import settings
from src.backend.core.auth_deps import get_current_active_user
from src.backend.core.exceptions import EntityNotFoundException
from src.backend.core.responses import paginated_response, success_response
from src.backend.db.session import get_db
from src.backend.models.auth import User
from src.backend.models.camera import Camera
from src.backend.models.encounter import Encounter
from src.backend.models.media import ImageFrame, MediaAsset
from src.backend.models.prediction import Detection
from src.backend.services.reviews import review_service

router = APIRouter()


@router.get("/observations", summary="List Wildlife Observations/Detections")
def list_observations(
    camera_id: Optional[str] = Query(None, description="Filter by camera ID"),
    taxon_id: Optional[str] = Query(None, description="Filter by mapped taxon ID"),
    review_status: Optional[str] = Query(None, description="Filter by review status"),
    limit: int = Query(20, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieves paginated genuine model detections with bounding boxes and confidence scores.
    
    Wildlife Data Protection: Obfuscates camera coordinates for Viewers.
    """
    query = db.query(Detection)

    if camera_id:
        query = (
            query.join(ImageFrame, Detection.image_id == ImageFrame.id)
            .join(MediaAsset, ImageFrame.source_media_id == MediaAsset.id)
            .filter(MediaAsset.camera_id == camera_id)
        )
    if taxon_id:
        query = query.filter(Detection.taxon_id == taxon_id)
    if review_status:
        query = query.filter(Detection.review_status == review_status)

    total = query.count()
    detections = query.order_by(Detection.created_at.desc()).offset(offset).limit(limit).all()
    current_revision = review_service.get_current_revision(db)
    is_viewer = current_user.role == "viewer"

    items = []
    for det in detections:
        cam = None
        if det.frame and det.frame.media_asset and det.frame.media_asset.camera:
            cam = det.frame.media_asset.camera
        raw_coords = [cam.longitude, cam.latitude] if cam and cam.longitude is not None and cam.latitude is not None else None

        if is_viewer:
            coords = None
            obfuscated = True if raw_coords is not None else False
        else:
            coords = raw_coords
            obfuscated = False

        items.append({
            "id": det.id,
            "image_id": det.image_id,
            "encounter_id": det.encounter_id,
            "bbox": [det.bbox_x, det.bbox_y, det.bbox_w, det.bbox_h],
            "raw_label": det.raw_label,
            "taxon_id": det.taxon_id,
            "label": det.label,
            "score": det.score,
            "detection_score": det.detection_score,
            "classification_score": det.classification_score,
            "score_type": det.score_type,
            "calibration_status": det.calibration_status,
            "alternatives": det.alternatives or {},
            "model_version": det.model_version,
            "review_status": det.review_status,
            "provenance": det.provenance,
            "coordinates": coords,
            "coordinates_obfuscated": obfuscated,
            "created_at": det.created_at.isoformat() if det.created_at else None,
        })

    return paginated_response(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        dataset_revision=current_revision,
    )


@router.get("/encounters/{encounter_id}", summary="Get Detailed Encounter")
def get_encounter(
    encounter_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieves an encounter and its member images and detections."""
    encounter = db.query(Encounter).filter_by(id=encounter_id).first()
    if encounter is None:
        raise EntityNotFoundException("Encounter", encounter_id)

    current_revision = review_service.get_current_revision(db)
    image_ids = [m.image_id for m in encounter.members]
    detection_ids = [m.detection_id for m in encounter.members]

    data = {
        "id": encounter.id,
        "camera_id": encounter.camera_id,
        "start_at": encounter.start_at.isoformat() if encounter.start_at else None,
        "end_at": encounter.end_at.isoformat() if encounter.end_at else None,
        "grouping_rule_version": encounter.grouping_rule_version,
        "review_status": encounter.review_status,
        "provenance": encounter.provenance,
        "image_ids": image_ids,
        "detection_ids": detection_ids,
    }
    return success_response(data=data, dataset_revision=current_revision)
