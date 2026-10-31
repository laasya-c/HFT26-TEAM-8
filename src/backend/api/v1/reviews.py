"""Human Review & Auditability API Endpoints (F20).

Implements:
- POST /api/v1/reviews: Append-only human review event with monotonic revision increment (HTTP 201).
- GET /api/v1/reviews/{detection_id}: Audit history of human decisions for a specific detection (HTTP 200).
"""
from typing import Any, Dict
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from contracts.schemas import ReviewCreateRequest, ReviewEventContract
from src.backend.core.auth_deps import get_current_active_user, require_role
from src.backend.core.exceptions import EntityNotFoundException
from src.backend.core.responses import success_response
from src.backend.db.session import get_db
from src.backend.models.auth import User
from src.backend.models.prediction import Detection
from src.backend.services.reviews import review_service

router = APIRouter()


@router.post(
    "/reviews",
    status_code=status.HTTP_201_CREATED,
    summary="Submit Human Review Event",
)
def create_review(
    payload: ReviewCreateRequest,
    current_user: User = Depends(require_role(["admin", "researcher"])),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Submits an append-only human review decision for a model detection.
    
    Guarantees:
    - Atomically increments dataset_revision.
    - Preserves raw prediction immutability (only review_status transitions).
    - Checks expected_revision and returns HTTP 409 if revision is stale.
    - Computes and updates parent Encounter review_status if grouped.
    - Enforces reviewer identity invariant: reviewer_id is strictly derived from the authenticated token.
    """
    review_data = payload.model_dump()
    # Reviewer Identity Invariant: prevent identity spoofing by binding directly to authenticated token ID
    review_data["reviewer_id"] = current_user.id
    review_event, resulting_revision = review_service.submit_review(db, review_data)

    event_data = {
        "id": review_event.id,
        "detection_id": review_event.detection_id,
        "decision": review_event.decision,
        "corrected_taxon_id": review_event.corrected_taxon_id,
        "reason": review_event.reason,
        "reviewer_id": review_event.reviewer_id,
        "expected_revision": review_event.expected_revision,
        "resulting_revision": resulting_revision,
        "provenance": review_event.provenance,
        "created_at": review_event.created_at.isoformat() if review_event.created_at else None,
    }

    return success_response(data=event_data, dataset_revision=resulting_revision)


@router.get(
    "/reviews/{detection_id}",
    status_code=status.HTTP_200_OK,
    summary="Get Detection Review History",
)
def get_detection_reviews(
    detection_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieves the complete chronological review audit log for a detection."""
    detection = db.query(Detection).filter(Detection.id == detection_id).first()
    if not detection:
        raise EntityNotFoundException("Detection", detection_id)

    history = review_service.get_review_history(db, detection_id)
    current_revision = review_service.get_current_revision(db)

    items = [
        {
            "id": r.id,
            "detection_id": r.detection_id,
            "decision": r.decision,
            "corrected_taxon_id": r.corrected_taxon_id,
            "reason": r.reason,
            "reviewer_id": r.reviewer_id,
            "expected_revision": r.expected_revision,
            "resulting_revision": r.resulting_revision,
            "provenance": r.provenance,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in history
    ]

    return success_response(data=items, dataset_revision=current_revision)
