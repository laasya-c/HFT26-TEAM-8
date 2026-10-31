"""Camera Trap & Telemetry API Endpoints (F07).

Implements:
- GET /api/v1/cameras: Paginated list of cameras with live-evaluated telemetry status.
- POST /api/v1/cameras: Register a new camera trap station.
- GET /api/v1/cameras/{camera_id}: Detailed camera diagnostics (telemetry health vs visual observation quality).
- POST /api/v1/cameras/{camera_id}/telemetry: Ingest hardware telemetry event (heartbeat, battery, error codes).
- GET /api/v1/cameras/{camera_id}/telemetry: Paginated history of hardware telemetry logs.
"""
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from contracts.schemas import CameraCreateRequest, TelemetryCreateRequest
from src.backend.core.auth_deps import get_current_active_user, require_role, verify_telemetry_auth
from src.backend.core.responses import paginated_response, success_response
from src.backend.db.session import get_db
from src.backend.models.auth import User
from src.backend.services.camera import camera_service
from src.backend.services.reviews import review_service

router = APIRouter()


@router.get("/cameras", status_code=status.HTTP_200_OK, summary="List Camera Trap Stations")
def list_cameras(
    telemetry_status: Optional[str] = Query(None, description="Filter by telemetry status: reporting, stale, unknown"),
    limit: int = Query(20, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieves paginated camera stations with dynamically calculated telemetry freshness.
    
    Wildlife Data Protection:
    - Viewers receive obfuscated coordinates to protect endangered species from poaching reconnaissance.
    - Researchers and Administrators receive unredacted coordinates.
    """
    items, total = camera_service.list_cameras(
        db=db,
        telemetry_status=telemetry_status,
        limit=limit,
        offset=offset,
    )
    is_viewer = current_user.role == "viewer"
    for item in items:
        if is_viewer:
            item["coordinates"] = None
            item["coordinates_obfuscated"] = True
        else:
            item["coordinates_obfuscated"] = False

    current_rev = review_service.get_current_revision(db)
    return paginated_response(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        dataset_revision=current_rev,
    )


@router.post("/cameras", status_code=status.HTTP_201_CREATED, summary="Register Camera Station")
def create_camera(
    payload: CameraCreateRequest,
    current_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Registers a new camera trap monitoring station (Administrator only)."""
    camera = camera_service.create_camera(db, payload.model_dump())
    current_rev = review_service.get_current_revision(db)
    coords = [camera.longitude, camera.latitude] if camera.latitude is not None and camera.longitude is not None else None
    data = {
        "id": camera.id,
        "label": camera.label,
        "timezone": camera.timezone,
        "coordinates": coords,
        "coordinates_obfuscated": False,
        "telemetry_status": camera.telemetry_status,
        "last_heartbeat_at": camera.last_heartbeat_at.isoformat() if camera.last_heartbeat_at else None,
        "active_camera_days": camera.active_camera_days,
        "provenance": camera.provenance,
        "created_at": camera.created_at.isoformat() if camera.created_at else None,
    }
    return success_response(data=data, dataset_revision=current_rev)


@router.get("/cameras/{camera_id}", status_code=status.HTTP_200_OK, summary="Get Camera Station Details")
def get_camera_details(
    camera_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieves detailed diagnostics, separating hardware telemetry health from observation quality.
    
    Wildlife Data Protection: Obfuscates coordinates for public viewers.
    """
    details = camera_service.get_camera_details(db, camera_id)
    if current_user.role == "viewer":
        details["coordinates"] = None
        details["coordinates_obfuscated"] = True
    else:
        details["coordinates_obfuscated"] = False

    current_rev = review_service.get_current_revision(db)
    return success_response(data=details, dataset_revision=current_rev)


@router.post("/cameras/{camera_id}/telemetry", status_code=status.HTTP_201_CREATED, summary="Submit Camera Telemetry")
def submit_telemetry(
    camera_id: str,
    payload: TelemetryCreateRequest,
    auth_caller: Any = Depends(verify_telemetry_auth),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Ingests a hardware telemetry event, updates heartbeat timestamp, and recalculates freshness.
    
    Protected via station-isolated field-device API key (X-API-Key) or Researcher/Admin credentials.
    """
    log = camera_service.submit_telemetry(db, camera_id, payload.model_dump())
    current_rev = review_service.get_current_revision(db)
    data = {
        "id": log.id,
        "camera_id": log.camera_id,
        "observed_at": log.observed_at.isoformat(),
        "battery_level": log.battery_level,
        "signal_strength": log.signal_strength,
        "error_codes": log.error_codes,
        "raw_payload": log.raw_payload,
        "source": log.source,
        "created_at": log.created_at.isoformat(),
    }
    return success_response(data=data, dataset_revision=current_rev)


@router.get("/cameras/{camera_id}/telemetry", status_code=status.HTTP_200_OK, summary="List Telemetry History")
def list_telemetry_history(
    camera_id: str,
    limit: int = Query(50, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieves paginated hardware telemetry logs for a camera station."""
    items, total = camera_service.list_telemetry_history(db, camera_id, limit=limit, offset=offset)
    current_rev = review_service.get_current_revision(db)
    return paginated_response(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        dataset_revision=current_rev,
    )
