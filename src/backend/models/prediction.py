"""PredictionRun, Detection, and Reference Annotation ORM Models.

Scientific Integrity Rules:
- Raw model predictions are IMMUTABLE.
- Reference ground truth annotations are stored separately in ground_truth_annotations
  and are never copied directly into prediction outputs or operational summaries.
"""
import uuid
from datetime import datetime, timezone
from src.backend.db.base import Base, PortableJSON, UTCDatetime

try:
    from sqlalchemy import Column, Float, ForeignKey, Index, Integer, String, Text, event, inspect
    from sqlalchemy.orm import relationship
    from src.backend.core.exceptions import ValidationException
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


if HAS_SQLALCHEMY:
    class PredictionRun(Base):
        """Execution audit of an inference batch run by Harsh's GPU worker."""
        __tablename__ = "prediction_runs"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        model_name = Column(String(100), nullable=False)
        model_version = Column(String(100), nullable=False)
        input_content_hash = Column(String(64), nullable=True)
        model_artifact_hash = Column(String(64), nullable=True)
        settings_hash = Column(String(64), nullable=True)
        device = Column(String(50), nullable=False)  # 'cuda' or 'cpu'
        started_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))
        completed_at = Column(UTCDatetime, nullable=True)
        status = Column(String(50), nullable=False, default="running")  # queued, running, completed, failed
        failures = Column(PortableJSON, nullable=True)  # Per-image errors
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))

        # Relationships
        detections = relationship("Detection", back_populates="prediction_run")

    class Detection(Base):
        """Immutable bounding-box detection output from vision model."""
        __tablename__ = "detections"
        __table_args__ = (
            Index("ix_detections_review_status_created", "review_status", "created_at"),
            Index("ix_detections_taxon_id_created", "taxon_id", "created_at"),
            Index("ix_detections_image_id", "image_id"),
            Index("ix_detections_encounter_id", "encounter_id"),
        )

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        image_id = Column(String(36), ForeignKey("image_frames.id", ondelete="CASCADE"), nullable=False)
        run_id = Column(String(36), ForeignKey("prediction_runs.id", ondelete="CASCADE"), nullable=False)
        encounter_id = Column(String(36), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True)

        # Normalized coordinates [0.0, 1.0]
        bbox_x = Column(Float, nullable=False)
        bbox_y = Column(Float, nullable=False)
        bbox_w = Column(Float, nullable=False)
        bbox_h = Column(Float, nullable=False)

        # Labels & Taxonomy
        raw_label = Column(String(100), nullable=False)  # Immutable raw classifier string
        taxon_id = Column(String(100), nullable=True)    # Mapped shared taxonomy ID
        label = Column(String(100), nullable=False)       # Display label

        # Model Scores
        score = Column(Float, nullable=False)  # Primary confidence
        detection_score = Column(Float, nullable=True)
        classification_score = Column(Float, nullable=True)
        score_type = Column(String(50), nullable=True)
        calibration_status = Column(String(50), nullable=True)
        alternatives = Column(PortableJSON, nullable=False, default=dict)

        model_version = Column(String(100), nullable=False)
        review_status = Column(String(50), nullable=False, default="pending")  # pending, confirmed, corrected, rejected, deferred
        provenance = Column(String(50), nullable=False, default="inferred")
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))

        # Relationships
        frame = relationship("ImageFrame", back_populates="detections")
        prediction_run = relationship("PredictionRun", back_populates="detections")
        encounter = relationship("Encounter", back_populates="detections")
        # Review history must be append-only and protected from deletion
        review_events = relationship("ReviewEvent", back_populates="detection", passive_deletes="all")

    # Fields that represent raw inference evidence and must NEVER be modified
    IMMUTABLE_DETECTION_FIELDS = {
        "id",
        "image_id",
        "run_id",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "raw_label",
        "taxon_id",
        "label",
        "score",
        "detection_score",
        "classification_score",
        "score_type",
        "calibration_status",
        "alternatives",
        "model_version",
        "provenance",
        "created_at",
    }

    @event.listens_for(Detection, "before_update")
    def enforce_detection_immutability(mapper, connection, target):
        """Enforces scientific immutability of raw vision model outputs."""
        state = inspect(target)
        for field_name in IMMUTABLE_DETECTION_FIELDS:
            hist = state.get_history(field_name, True)
            if hist.has_changes():
                raise ValidationException(
                    f"Raw model prediction fields are scientifically immutable: field '{field_name}' on Detection '{target.id}' "
                    f"cannot be modified after creation. Original raw predictions are permanent evidence."
                )

    class GroundTruthAnnotation(Base):
        """Evaluation-only ground truth annotations imported from datasets (e.g. Caltech).
        
        Strictly segregated from operational prediction outputs.
        """
        __tablename__ = "ground_truth_annotations"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        source_media_id = Column(String(36), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False)
        dataset_source = Column(String(100), nullable=False)
        bbox_x = Column(Float, nullable=True)
        bbox_y = Column(Float, nullable=True)
        bbox_w = Column(Float, nullable=True)
        bbox_h = Column(Float, nullable=True)
        taxon_id = Column(String(100), nullable=False)
        label = Column(String(100), nullable=False)
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))
