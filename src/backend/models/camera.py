"""Camera, Telemetry, and Monitoring Action ORM Models (F07 & F11).

Scientific Rules:
- Image silence alone does not prove camera failure.
- Missing telemetry produces 'unknown', never a fabricated failure state.
- Maintenance improvements must not claim unproven causality.
"""
import uuid
from datetime import datetime, timezone
from src.backend.db.base import Base, PortableJSON, UTCDatetime

try:
    from sqlalchemy import Column, Float, ForeignKey, String, Text
    from sqlalchemy.orm import relationship
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


if HAS_SQLALCHEMY:
    class Camera(Base):
        """Camera trap monitoring station record."""
        __tablename__ = "cameras"

        id = Column(String(36), primary_key=True)  # e.g. 'CAM-01'
        label = Column(String(200), nullable=False)
        timezone = Column(String(100), nullable=False, default="UTC")
        latitude = Column(Float, nullable=True)   # WGS84, NULL if unlocated
        longitude = Column(Float, nullable=True)  # WGS84, NULL if unlocated
        telemetry_status = Column(String(50), nullable=False, default="unknown")  # reporting, stale, unknown
        last_heartbeat_at = Column(UTCDatetime, nullable=True)
        active_camera_days = Column(Float, nullable=True)  # Documented monitoring effort
        provenance = Column(String(50), nullable=False, default="observed")
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))

        # Relationships
        media_assets = relationship("MediaAsset", back_populates="camera")
        encounters = relationship("Encounter", back_populates="camera")
        telemetry_logs = relationship("CameraTelemetry", back_populates="camera", cascade="all, delete-orphan")
        monitoring_actions = relationship("MonitoringAction", back_populates="camera", cascade="all, delete-orphan")
        api_keys = relationship("ApiKey", back_populates="camera", cascade="all, delete-orphan")

    class CameraTelemetry(Base):
        """Hardware telemetry event (battery, solar, errors, heartbeat)."""
        __tablename__ = "camera_telemetry"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        camera_id = Column(String(36), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
        observed_at = Column(UTCDatetime, nullable=False)
        battery_level = Column(Float, nullable=True)  # e.g., percentage 0-100 or voltage
        signal_strength = Column(Float, nullable=True)
        error_codes = Column(PortableJSON, nullable=False, default=list)
        raw_payload = Column(PortableJSON, nullable=True)
        source = Column(String(100), nullable=False, default="satellite_relay")
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))

        # Relationships
        camera = relationship("Camera", back_populates="telemetry_logs")

    class MonitoringAction(Base):
        """Intervention and maintenance logging for feedback analysis (F11)."""
        __tablename__ = "monitoring_actions"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        camera_id = Column(String(36), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
        created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
        action_type = Column(String(100), nullable=False)  # reposition, lens_clean, battery_replace
        description = Column(Text, nullable=False)
        performed_at = Column(UTCDatetime, nullable=False)
        baseline_start = Column(UTCDatetime, nullable=True)  # Pre-intervention baseline window
        baseline_end = Column(UTCDatetime, nullable=True)
        post_start = Column(UTCDatetime, nullable=True)      # Post-intervention observation window
        post_end = Column(UTCDatetime, nullable=True)
        source = Column(String(100), nullable=False, default="field_ranger")
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))

        # Relationships
        camera = relationship("Camera", back_populates="monitoring_actions")
        creator = relationship("User", back_populates="monitoring_actions")
