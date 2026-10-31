"""Media and ImageFrame ORM Models.

Stores file metadata, content hashes, and safe references on disk outside database rows.
"""
import uuid
from datetime import datetime, timezone
from src.backend.db.base import Base, PortableJSON, UTCDatetime

try:
    from sqlalchemy import Column, ForeignKey, Index, Integer, String
    from sqlalchemy.orm import relationship
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


if HAS_SQLALCHEMY:
    class MediaAsset(Base):
        """Original uploaded image or video file."""
        __tablename__ = "media_assets"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        type = Column(String(20), nullable=False)  # 'image' or 'video'
        camera_id = Column(String(36), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True)
        uploader_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
        storage_key = Column(String(512), nullable=False)  # Safe relative path on disk
        content_hash = Column(String(64), nullable=False, index=True)  # SHA-256 for duplicate detection
        raw_timestamp = Column(String(100), nullable=True)  # As extracted from file EXIF
        captured_at = Column(UTCDatetime, nullable=True)  # Normalized UTC, or NULL if unknown
        timezone_source = Column(String(100), nullable=True)
        provenance = Column(String(50), nullable=False, default="observed")
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))

        # Relationships
        frames = relationship("ImageFrame", back_populates="media_asset", cascade="all, delete-orphan")
        camera = relationship("Camera", back_populates="media_assets")
        uploader = relationship("User", back_populates="uploaded_media")

    class ImageFrame(Base):
        """Derived frame from an image or video with content URL and quality flags."""
        __tablename__ = "image_frames"
        __table_args__ = (
            Index("ix_image_frames_source_media", "source_media_id"),
        )

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        source_media_id = Column(String(36), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False)
        frame_offset_ms = Column(Integer, nullable=True)  # Millisecond timestamp for video frames
        width = Column(Integer, nullable=True)
        height = Column(Integer, nullable=True)
        orientation = Column(Integer, nullable=False, default=1)
        content_url = Column(String(512), nullable=False)  # Safe API route to retrieve bytes
        quality_flags = Column(PortableJSON, nullable=False, default=list)  # e.g. ['low_light']
        provenance = Column(String(50), nullable=False, default="observed")
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))

        # Relationships
        media_asset = relationship("MediaAsset", back_populates="frames")
        detections = relationship("Detection", back_populates="frame", cascade="all, delete-orphan")
