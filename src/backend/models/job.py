"""Persistent Processing Job ORM Model.

Tracks asynchronous vision processing jobs across restarts:
- queued -> running -> completed / partial / failed
- Never loses status on backend restart.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from src.backend.db.base import Base, PortableJSON, UTCDatetime

try:
    from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text
    from sqlalchemy.orm import relationship
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


class JobStatus(str, Enum):
    """Lifecycle states for persistent jobs."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    PARTIALLY_COMPLETED = "partial"  # Alias accepted per specification
    FAILED = "failed"


# Valid state transitions
VALID_TRANSITIONS = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.FAILED},
    JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED},
    JobStatus.COMPLETED: set(),  # Terminal
    JobStatus.PARTIAL: set(),    # Terminal
    JobStatus.FAILED: set(),     # Terminal
}


if HAS_SQLALCHEMY:
    class ProcessingJob(Base):
        """Persistent background processing job record."""
        __tablename__ = "processing_jobs"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        upload_id = Column(String(36), nullable=False, index=True)
        status = Column(String(50), nullable=False, default=JobStatus.QUEUED.value)
        progress = Column(Float, nullable=False, default=0.0)  # Percentage 0.0 - 100.0
        total_items = Column(Integer, nullable=False, default=0)
        processed_items = Column(Integer, nullable=False, default=0)
        media_ids = Column(PortableJSON, nullable=False, default=list)
        run_id = Column(String(36), ForeignKey("prediction_runs.id", ondelete="SET NULL"), nullable=True)
        created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
        failures = Column(PortableJSON, nullable=False, default=list)
        error_message = Column(Text, nullable=True)

        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))
        updated_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))
        completed_at = Column(UTCDatetime, nullable=True)

        # Relationships
        prediction_run = relationship("PredictionRun")
        creator = relationship("User", back_populates="processing_jobs")

        def transition_to(self, new_status: JobStatus, error_message: Optional[str] = None) -> None:
            """Safely transitions job state or raises ValueError on invalid transition."""
            current_enum = JobStatus(self.status)
            if new_status not in VALID_TRANSITIONS.get(current_enum, set()):
                raise ValueError(
                    f"Illegal job state transition from '{self.status}' to '{new_status.value}'."
                )
            self.status = new_status.value
            self.updated_at = datetime.now(timezone.utc)
            if error_message:
                self.error_message = error_message
            if new_status in {JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED}:
                self.completed_at = datetime.now(timezone.utc)
