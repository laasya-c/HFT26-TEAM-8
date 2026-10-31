"""Authentication, User RBAC, and Device Credential ORM Models.

Architecture & Security Standards:
1. Passwords are never stored in plaintext; stored as Argon2id/bcrypt hashes.
2. Refresh tokens are stored strictly as SHA-256 hashes with family tracking (RTR).
3. Field-device API keys are scoped to specific camera stations and stored as SHA-256 hashes.
4. Raw tokens or keys are never persisted in database rows.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid

from src.backend.db.base import Base, UTCDatetime

try:
    from sqlalchemy import Boolean, Column, ForeignKey, Index, String, Text
    from sqlalchemy.orm import relationship, foreign
    from src.backend.core.exceptions import ValidationException
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


class UserRole(str, Enum):
    """Platform access control personas."""
    ADMIN = "admin"
    RESEARCHER = "researcher"
    VIEWER = "viewer"


VALID_ROLES = {UserRole.ADMIN.value, UserRole.RESEARCHER.value, UserRole.VIEWER.value}


if HAS_SQLALCHEMY:
    class User(Base):
        """Platform user with role-based access control and credential hashes."""
        __tablename__ = "users"
        __table_args__ = (
            Index("ix_users_username", "username", unique=True),
            Index("ix_users_email", "email", unique=True),
            Index("ix_users_role", "role"),
        )

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        username = Column(String(50), nullable=False)
        email = Column(String(255), nullable=False)
        hashed_password = Column(String(255), nullable=False)
        full_name = Column(String(100), nullable=True)
        role = Column(String(20), nullable=False, default=UserRole.VIEWER.value)
        is_active = Column(Boolean, nullable=False, default=True)
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))
        updated_at = Column(
            UTCDatetime,
            nullable=False,
            default=lambda: datetime.now(timezone.utc),
            onupdate=lambda: datetime.now(timezone.utc),
        )

        # Relationships
        refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
        uploaded_media = relationship("MediaAsset", back_populates="uploader")
        processing_jobs = relationship("ProcessingJob", back_populates="creator")
        monitoring_actions = relationship("MonitoringAction", back_populates="creator")
        review_events = relationship(
            "ReviewEvent",
            primaryjoin="User.id == foreign(ReviewEvent.reviewer_id)",
            viewonly=True,
        )

        def validate_role(self) -> None:
            """Ensures user role belongs to authorized RBAC personas."""
            if self.role not in VALID_ROLES:
                raise ValidationException(
                    f"Invalid role '{self.role}'. Authorized roles are: {', '.join(sorted(VALID_ROLES))}."
                )

    class RefreshToken(Base):
        """Cryptographic refresh token with family tracking for replay attack detection."""
        __tablename__ = "refresh_tokens"
        __table_args__ = (
            Index("ix_refresh_tokens_token_hash", "token_hash", unique=True),
            Index("ix_refresh_tokens_user_id", "user_id"),
            Index("ix_refresh_tokens_family_id", "family_id"),
        )

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
        token_hash = Column(String(64), nullable=False)  # SHA-256 hash of opaque token string
        family_id = Column(String(36), nullable=False)   # UUID grouping for token rotation lineage
        parent_token_hash = Column(String(64), nullable=True)  # Hash of preceding token in rotation
        is_revoked = Column(Boolean, nullable=False, default=False)
        expires_at = Column(UTCDatetime, nullable=False)
        revoked_at = Column(UTCDatetime, nullable=True)
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))

        # Relationships
        user = relationship("User", back_populates="refresh_tokens")

    class ApiKey(Base):
        """Pre-shared API key scoped to a specific camera trap station."""
        __tablename__ = "api_keys"
        __table_args__ = (
            Index("ix_api_keys_key_hash", "key_hash", unique=True),
            Index("ix_api_keys_camera_id", "camera_id"),
            Index("ix_api_keys_is_active", "is_active"),
        )

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        name = Column(String(100), nullable=False)       # Human-readable identifier
        key_prefix = Column(String(16), nullable=False, default="ws_live_")  # Public key prefix
        key_hash = Column(String(64), nullable=False)    # SHA-256 hash of secret key
        camera_id = Column(String(36), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
        role = Column(String(20), nullable=False, default="field_device")
        is_active = Column(Boolean, nullable=False, default=True)
        created_at = Column(UTCDatetime, nullable=False, default=lambda: datetime.now(timezone.utc))
        expires_at = Column(UTCDatetime, nullable=True)
        last_used_at = Column(UTCDatetime, nullable=True)
        revoked_at = Column(UTCDatetime, nullable=True)

        # Relationships
        camera = relationship("Camera", back_populates="api_keys")
