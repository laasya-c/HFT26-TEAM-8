"""Encounter and Encounter Membership ORM Models.

Encounters represent spatio-temporal groupings of animal observations at a camera trap.
"""
import uuid
from datetime import datetime, timezone
from src.backend.db.base import Base, UTCDatetime

try:
    from sqlalchemy import Column, ForeignKey, String
    from sqlalchemy.orm import relationship
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


if HAS_SQLALCHEMY:
    class Encounter(Base):
        """Temporal or sequence grouping of detections at a single camera trap."""
        __tablename__ = "encounters"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        camera_id = Column(String(36), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
        start_at = Column(UTCDatetime, nullable=True)
        end_at = Column(UTCDatetime, nullable=True)
        grouping_rule_version = Column(String(100), nullable=False)  # e.g., 'timegap_60s_v1'
        review_status = Column(String(50), nullable=False, default="pending")  # pending, partially_reviewed, reviewed
        provenance = Column(String(50), nullable=False, default="inferred")
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))

        # Relationships
        camera = relationship("Camera", back_populates="encounters")
        detections = relationship("Detection", back_populates="encounter")
        members = relationship("EncounterMember", back_populates="encounter", cascade="all, delete-orphan")

        def compute_aggregate_review_status(self) -> str:
            """Derives aggregate review status from member detections."""
            if not self.detections:
                return "pending"
            statuses = [d.review_status for d in self.detections]
            reviewed_states = {"confirmed", "corrected", "rejected", "deferred"}
            if all(s == "pending" for s in statuses):
                return "pending"
            elif all(s in reviewed_states for s in statuses):
                return "reviewed"
            else:
                return "partially_reviewed"

    class EncounterMember(Base):
        """Associative membership link between Encounter, Detection, and ImageFrame."""
        __tablename__ = "encounter_members"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        encounter_id = Column(String(36), ForeignKey("encounters.id", ondelete="CASCADE"), nullable=False)
        detection_id = Column(String(36), ForeignKey("detections.id", ondelete="CASCADE"), nullable=False)
        image_id = Column(String(36), ForeignKey("image_frames.id", ondelete="CASCADE"), nullable=False)
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))

        # Relationships
        encounter = relationship("Encounter", back_populates="members")
