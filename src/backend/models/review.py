"""ReviewEvent and DatasetRevision ORM Models (F20).

Scientific & Architecture Rules:
- Append-only review history: never destructive, never overwrites original model predictions.
- Revision management: Review mutations increment dataset_revision transactionally.
- Stale expected_revision submissions are rejected with HTTP 409.
"""
import uuid
from datetime import datetime, timezone
from src.backend.db.base import Base, UTCDatetime

try:
    from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text, event
    from sqlalchemy.orm import relationship, foreign
    from src.backend.core.exceptions import ValidationException
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


if HAS_SQLALCHEMY:
    class ReviewEvent(Base):
        """Append-only audit record of human expert review decisions."""
        __tablename__ = "review_events"
        __table_args__ = (
            Index("ix_review_events_detection_created", "detection_id", "created_at"),
        )

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        detection_id = Column(String(36), ForeignKey("detections.id", ondelete="RESTRICT"), nullable=False)
        decision = Column(String(50), nullable=False)  # confirmed, corrected, rejected, deferred
        corrected_taxon_id = Column(String(100), nullable=True)  # Mapped taxon ID if corrected
        reason = Column(Text, nullable=False)  # Traceable scientific justification
        reviewer_id = Column(String(100), nullable=False)  # Authenticated researcher ID
        expected_revision = Column(Integer, nullable=False)
        resulting_revision = Column(Integer, nullable=False)
        provenance = Column(String(50), nullable=False, default="observed")
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))

        # Relationships
        detection = relationship("Detection", back_populates="review_events")
        reviewer = relationship(
            "User",
            primaryjoin="foreign(ReviewEvent.reviewer_id) == User.id",
            viewonly=True,
        )

    @event.listens_for(ReviewEvent, "before_update")
    def prevent_review_event_update(mapper, connection, target):
        raise ValidationException("ReviewEvent records are append-only audit logs and cannot be modified.")

    @event.listens_for(ReviewEvent, "before_delete")
    def prevent_review_event_delete(mapper, connection, target):
        raise ValidationException("ReviewEvent records are permanent audit evidence and cannot be deleted.")

    class DatasetRevision(Base):
        """Monotonic dataset revision tracker for optimistic concurrency and cache invalidation."""
        __tablename__ = "dataset_revisions"

        id = Column(Integer, primary_key=True)  # Single-row tracker (id=1)
        current_revision = Column(Integer, nullable=False, default=1)
        updated_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))
        change_reason = Column(String(255), nullable=True)
