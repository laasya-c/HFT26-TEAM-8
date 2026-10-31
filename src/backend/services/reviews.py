"""Review Service — Human Review & Auditability (F20).

Scientific & Architecture Responsibilities:
1. Append-only human review events (ReviewEvent records are never edited or deleted).
2. Scientific prediction immutability: Raw vision predictions remain untampered;
   only review_status on Detection transitions.
3. Monotonic atomic dataset revision tracking on dataset_revisions table.
4. Optimistic concurrency control: Stale expected_revision submissions abort
   with HTTP 409 Conflict without mutating state.
5. Encounter aggregation: Derives aggregate encounter review status
   (pending, partially_reviewed, reviewed) based on member detection statuses.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
import uuid

from sqlalchemy.orm import Session

from contracts.schemas import ReviewStatusEnum
from src.backend.core.exceptions import ConflictException, EntityNotFoundException, ValidationException
from src.backend.models.encounter import Encounter
from src.backend.models.prediction import Detection
from src.backend.models.review import DatasetRevision, ReviewEvent


REVIEWED_STATUSES = {
    ReviewStatusEnum.CONFIRMED.value,
    ReviewStatusEnum.CORRECTED.value,
    ReviewStatusEnum.REJECTED.value,
    ReviewStatusEnum.DEFERRED.value,
}


class ReviewService:
    """Manages human review events, dataset revisions, and encounter aggregation."""

    def get_current_revision(self, db: Session) -> int:
        """Retrieves the current monotonic dataset revision (singleton row id=1).
        
        Initializes row id=1 if not yet created.
        """
        record = db.query(DatasetRevision).filter(DatasetRevision.id == 1).first()
        if not record:
            record = DatasetRevision(
                id=1,
                current_revision=1,
                updated_at=datetime.now(timezone.utc),
                change_reason="Initial dataset revision baseline",
            )
            db.add(record)
            db.commit()
            db.refresh(record)
        return record.current_revision

    def compute_encounter_review_status(self, detections: Sequence[Detection]) -> str:
        """Computes aggregate encounter review status from member detections.
        
        Aggregation rules:
        - If encounter has no detections: 'pending'
        - If all detections are 'pending': 'pending'
        - If all detections are in reviewed states: 'reviewed'
        - Otherwise (mixed pending and reviewed): 'partially_reviewed'
        """
        if not detections:
            return "pending"

        statuses = [d.review_status for d in detections]
        if all(s == ReviewStatusEnum.PENDING.value for s in statuses):
            return "pending"
        elif all(s in REVIEWED_STATUSES for s in statuses):
            return "reviewed"
        else:
            return "partially_reviewed"

    def submit_review(
        self,
        db: Session,
        review_data: Dict[str, Any],
    ) -> Tuple[ReviewEvent, int]:
        """Submits an append-only human review event with optimistic concurrency.
        
        Args:
            db: Active database session.
            review_data: Validated review payload containing:
                - detection_id (str)
                - decision (str or ReviewStatusEnum)
                - corrected_taxon_id (Optional[str])
                - reason (str)
                - reviewer_id (str)
                - expected_revision (int)
                - provenance (Optional[str])

        Returns:
            Tuple of (persisted ReviewEvent, resulting_revision: int).

        Raises:
            ConflictException: If expected_revision is stale or race collision occurs (409).
            EntityNotFoundException: If detection does not exist (404).
            ValidationException: If review payload fails domain constraints (422).
        """
        detection_id = review_data.get("detection_id")
        decision_raw = review_data.get("decision")
        decision = decision_raw.value if hasattr(decision_raw, "value") else str(decision_raw)
        corrected_taxon_id = review_data.get("corrected_taxon_id")
        reason = (review_data.get("reason") or "").strip()
        reviewer_id = (review_data.get("reviewer_id") or "").strip()
        expected_revision = review_data.get("expected_revision")
        provenance = review_data.get("provenance")
        if hasattr(provenance, "value"):
            provenance = provenance.value
        provenance = provenance or "observed"

        # 1. Basic validation
        if not reason:
            raise ValidationException("Review justification reason cannot be empty.")
        if not reviewer_id:
            raise ValidationException("Reviewer ID cannot be empty.")
        if expected_revision is None or expected_revision < 1:
            raise ValidationException("expected_revision must be a positive integer >= 1.")

        valid_decisions = {e.value for e in ReviewStatusEnum if e != ReviewStatusEnum.PENDING}
        if decision not in valid_decisions:
            raise ValidationException(
                f"Invalid review decision '{decision}'. Must be one of: {sorted(list(valid_decisions))}."
            )

        if decision == ReviewStatusEnum.CORRECTED.value and (not corrected_taxon_id or not corrected_taxon_id.strip()):
            raise ValidationException("corrected_taxon_id is required when decision is 'corrected'.")

        # 2. Fetch Detection
        detection = db.query(Detection).filter(Detection.id == detection_id).first()
        if not detection:
            raise EntityNotFoundException("Detection", str(detection_id))

        # 3. Optimistic Concurrency & Revision Check
        revision_record = db.query(DatasetRevision).filter(DatasetRevision.id == 1).first()
        if not revision_record:
            # Initialize if missing
            revision_record = DatasetRevision(
                id=1,
                current_revision=1,
                updated_at=datetime.now(timezone.utc),
                change_reason="Initial baseline revision",
            )
            db.add(revision_record)
            db.flush()

        if revision_record.current_revision != expected_revision:
            raise ConflictException(
                message=(
                    f"Stale dataset revision conflict: submitted expected_revision={expected_revision}, "
                    f"but current_revision={revision_record.current_revision}. Refresh dataset and retry."
                ),
                expected_revision=expected_revision,
                current_revision=revision_record.current_revision,
            )

        # Atomic conditional update to guard against race conditions
        updated_count = db.query(DatasetRevision).filter(
            DatasetRevision.id == 1,
            DatasetRevision.current_revision == expected_revision,
        ).update(
            {
                DatasetRevision.current_revision: DatasetRevision.current_revision + 1,
                DatasetRevision.updated_at: datetime.now(timezone.utc),
                DatasetRevision.change_reason: f"Review {decision} on detection {detection.id} by {reviewer_id}",
            },
            synchronize_session="fetch",
        )

        if updated_count == 0:
            db.rollback()
            actual_rev = db.query(DatasetRevision.current_revision).filter(DatasetRevision.id == 1).scalar()
            raise ConflictException(
                message=f"Dataset revision conflict detected during concurrent update. Expected {expected_revision}, actual {actual_rev}.",
                expected_revision=expected_revision,
                current_revision=actual_rev,
            )

        resulting_revision = expected_revision + 1

        # 4. Append-Only Review Event
        review_event = ReviewEvent(
            id=str(uuid.uuid4()),
            detection_id=detection.id,
            decision=decision,
            corrected_taxon_id=corrected_taxon_id.strip() if corrected_taxon_id else None,
            reason=reason,
            reviewer_id=reviewer_id,
            expected_revision=expected_revision,
            resulting_revision=resulting_revision,
            provenance=provenance,
            created_at=datetime.now(timezone.utc),
        )
        db.add(review_event)

        # 5. Transition Detection review_status (raw predictions remain untouched)
        detection.review_status = decision

        # 6. Re-evaluate Encounter review_status if detection belongs to an encounter
        if detection.encounter_id:
            encounter = db.query(Encounter).filter(Encounter.id == detection.encounter_id).first()
            if encounter:
                member_detections = db.query(Detection).filter(Detection.encounter_id == encounter.id).all()
                encounter.review_status = self.compute_encounter_review_status(member_detections)

        # 7. Commit transaction
        db.commit()
        db.refresh(review_event)

        return review_event, resulting_revision

    def get_review_history(self, db: Session, detection_id: str) -> List[ReviewEvent]:
        """Retrieves append-only review history for a given detection ordered chronologically."""
        return (
            db.query(ReviewEvent)
            .filter(ReviewEvent.detection_id == detection_id)
            .order_by(ReviewEvent.created_at.asc())
            .all()
        )


review_service = ReviewService()
