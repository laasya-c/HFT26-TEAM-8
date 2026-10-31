"""Monitoring Improvement Feedback & Network Health API Endpoints (F11 & F07).

Implements:
- GET /api/v1/monitoring: Holistic network monitoring summary across all cameras.
- GET /api/v1/monitoring-actions: Paginated list of field interventions.
- POST /api/v1/monitoring-actions: Log a field intervention / maintenance action.
- GET /api/v1/monitoring-actions/{action_id}: Detailed intervention record.
- GET /api/v1/monitoring-actions/{action_id}/feedback: Before/after effort & quality evaluation.
"""
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from contracts.schemas import MonitoringActionContract, MonitoringActionCreateRequest
from src.backend.core.auth_deps import get_current_active_user, require_role
from src.backend.core.responses import success_response, paginated_response
from src.backend.db.session import get_db
from src.backend.models.auth import User
from src.backend.services.monitoring import monitoring_service
from src.backend.services.reviews import review_service

router = APIRouter()


@router.get("/monitoring", status_code=status.HTTP_200_OK, summary="Get Network Monitoring Summary")
def get_monitoring_summary(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieves holistic camera network monitoring health and recent intervention activity."""
    summary = monitoring_service.get_network_monitoring_summary(db)
    current_rev = review_service.get_current_revision(db)
    return success_response(data=summary, dataset_revision=current_rev)


@router.get("/monitoring-actions", status_code=status.HTTP_200_OK, summary="List Monitoring Actions")
def list_monitoring_actions(
    camera_id: Optional[str] = Query(None, description="Filter actions by camera station ID"),
    limit: int = Query(20, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieves paginated field intervention actions."""
    actions, total = monitoring_service.list_actions(db, camera_id=camera_id, limit=limit, offset=offset)
    current_rev = review_service.get_current_revision(db)

    items = [
        {
            "id": a.id,
            "camera_id": a.camera_id,
            "action_type": a.action_type,
            "description": a.description,
            "performed_at": a.performed_at.isoformat(),
            "baseline_start": a.baseline_start.isoformat() if a.baseline_start else None,
            "baseline_end": a.baseline_end.isoformat() if a.baseline_end else None,
            "post_start": a.post_start.isoformat() if a.post_start else None,
            "post_end": a.post_end.isoformat() if a.post_end else None,
            "source": a.source,
            "created_at": a.created_at.isoformat(),
        }
        for a in actions
    ]
    return paginated_response(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        dataset_revision=current_rev,
    )


@router.post("/monitoring-actions", status_code=status.HTTP_201_CREATED, summary="Log Monitoring Action")
def create_monitoring_action(
    payload: MonitoringActionCreateRequest,
    current_user: User = Depends(require_role(["admin", "researcher"])),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Records a new maintenance, lens cleaning, repositioning, or battery replacement action."""
    action_data = payload.model_dump()
    action_data["created_by_user_id"] = current_user.id
    action = monitoring_service.create_action(db, action_data, created_by_user_id=current_user.id)
    current_rev = review_service.get_current_revision(db)

    data = {
        "id": action.id,
        "camera_id": action.camera_id,
        "action_type": action.action_type,
        "description": action.description,
        "performed_at": action.performed_at.isoformat(),
        "baseline_start": action.baseline_start.isoformat() if action.baseline_start else None,
        "baseline_end": action.baseline_end.isoformat() if action.baseline_end else None,
        "post_start": action.post_start.isoformat() if action.post_start else None,
        "post_end": action.post_end.isoformat() if action.post_end else None,
        "source": action.source,
        "created_at": action.created_at.isoformat(),
    }
    return success_response(data=data, dataset_revision=current_rev)


@router.get("/monitoring-actions/{action_id}", status_code=status.HTTP_200_OK, summary="Get Monitoring Action")
def get_monitoring_action(
    action_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieves a specific field intervention record."""
    action = monitoring_service.get_action(db, action_id)
    current_rev = review_service.get_current_revision(db)
    data = {
        "id": action.id,
        "camera_id": action.camera_id,
        "action_type": action.action_type,
        "description": action.description,
        "performed_at": action.performed_at.isoformat(),
        "baseline_start": action.baseline_start.isoformat() if action.baseline_start else None,
        "baseline_end": action.baseline_end.isoformat() if action.baseline_end else None,
        "post_start": action.post_start.isoformat() if action.post_start else None,
        "post_end": action.post_end.isoformat() if action.post_end else None,
        "source": action.source,
        "created_at": action.created_at.isoformat(),
    }
    return success_response(data=data, dataset_revision=current_rev)


@router.get("/monitoring-actions/{action_id}/feedback", status_code=status.HTTP_200_OK, summary="Get Intervention Feedback")
def get_action_feedback(
    action_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Evaluates before/after uptime and visual observation quality differences.
    
    Returns 'insufficient_data' if windows are missing or lack activity.
    Always includes non-causal disclaimer and declared limitations.
    """
    action = monitoring_service.get_action(db, action_id)
    feedback = monitoring_service.evaluate_feedback(db, action)
    current_rev = review_service.get_current_revision(db)
    return success_response(data=feedback, dataset_revision=current_rev)
