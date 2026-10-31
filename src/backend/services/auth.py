"""Authentication and Token Management Service.

Responsibilities:
1. User credential authentication with constant-time password verification.
2. Dual-token issuance (HS256 access token + cryptographically random refresh token).
3. Single-use refresh token rotation (RTR) and replay attack detection.
4. Token family invalidation on detected reuse.
5. Session revocation on user logout and account deactivation.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import uuid

from sqlalchemy.orm import Session

from src.backend.config import settings
from src.backend.core.exceptions import AuthenticationException, ForbiddenException
from src.backend.core.security import (
    create_access_token,
    generate_raw_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from src.backend.models.auth import RefreshToken, User


class AuthService:
    """Core domain service for user authentication, token issuance, and rotation."""

    def authenticate_user(
        self,
        db: Session,
        username_or_email: str,
        password: str,
    ) -> User:
        """Verifies credentials; raises uniform error to prevent user enumeration."""
        clean_identifier = username_or_email.strip()
        user = (
            db.query(User)
            .filter((User.username == clean_identifier) | (User.email == clean_identifier.lower()))
            .first()
        )

        if user is None:
            # Constant-time dummy verification prevents timing side-channel attacks
            verify_password(password, "$pbkdf2-sha256$i=600000$dummy_salt$dummy_hash")
            raise AuthenticationException(
                "Invalid username or password.",
                code="INVALID_CREDENTIALS",
            )

        if not verify_password(password, user.hashed_password):
            raise AuthenticationException(
                "Invalid username or password.",
                code="INVALID_CREDENTIALS",
            )

        if not user.is_active:
            raise ForbiddenException(
                "User account is disabled. Please contact an administrator.",
                code="ACCOUNT_DISABLED",
            )

        return user

    def issue_tokens(
        self,
        db: Session,
        user: User,
    ) -> Tuple[str, str, int]:
        """Issues access token and hashed refresh token.
        
        Returns:
            Tuple of (access_token: str, raw_refresh_token: str, expires_in_seconds: int)
        """
        now_utc = datetime.now(timezone.utc)
        access_token = create_access_token(
            user_id=user.id,
            role=user.role,
            username=user.username,
            email=user.email,
        )

        raw_refresh_token = generate_raw_refresh_token()
        token_hash = hash_refresh_token(raw_refresh_token)
        family_id = str(uuid.uuid4())
        expires_at = now_utc + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        refresh_record = RefreshToken(
            id=str(uuid.uuid4()),
            user_id=user.id,
            token_hash=token_hash,
            family_id=family_id,
            parent_token_hash=None,
            is_revoked=False,
            expires_at=expires_at,
            created_at=now_utc,
        )
        db.add(refresh_record)
        db.commit()

        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        return access_token, raw_refresh_token, expires_in

    def rotate_refresh_token(
        self,
        db: Session,
        raw_refresh_token: str,
    ) -> Tuple[str, str, int, User]:
        """Rotates a single-use refresh token; detects and neutralizes replay attacks.
        
        Returns:
            Tuple of (new_access_token, new_raw_refresh_token, expires_in_seconds, user)
        """
        if not raw_refresh_token or not raw_refresh_token.strip():
            raise AuthenticationException(
                "Refresh token is missing or malformed.",
                code="MISSING_REFRESH_TOKEN",
            )

        token_hash = hash_refresh_token(raw_refresh_token)
        token_record = db.query(RefreshToken).filter_by(token_hash=token_hash).first()

        if token_record is None:
            raise AuthenticationException(
                "Invalid or unrecognized refresh token.",
                code="INVALID_REFRESH_TOKEN",
            )

        now_utc = datetime.now(timezone.utc)

        # REPLAY ATTACK DETECTION:
        # If an already-revoked refresh token is presented, someone re-submitted a consumed token.
        # Immediately invalidate all active refresh tokens in this token family!
        if token_record.is_revoked:
            db.query(RefreshToken).filter_by(family_id=token_record.family_id).update(
                {"is_revoked": True, "revoked_at": now_utc}
            )
            db.commit()
            raise ForbiddenException(
                "Token replay detected. All active sessions in this family have been revoked.",
                code="TOKEN_REPLAY_DETECTED",
            )

        # Check expiration
        if token_record.expires_at < now_utc:
            token_record.is_revoked = True
            token_record.revoked_at = now_utc
            db.commit()
            raise AuthenticationException(
                "Refresh token has expired. Please log in again.",
                code="REFRESH_TOKEN_EXPIRED",
            )

        # Verify active user
        user = db.query(User).filter_by(id=token_record.user_id).first()
        if user is None or not user.is_active:
            token_record.is_revoked = True
            token_record.revoked_at = now_utc
            db.commit()
            raise ForbiddenException(
                "User account is disabled or deleted.",
                code="ACCOUNT_DISABLED",
            )

        # Single-use rotation: revoke the consumed token
        token_record.is_revoked = True
        token_record.revoked_at = now_utc

        # Issue child refresh token in the same family
        new_raw_token = generate_raw_refresh_token()
        new_token_hash = hash_refresh_token(new_raw_token)
        new_expires_at = now_utc + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        child_record = RefreshToken(
            id=str(uuid.uuid4()),
            user_id=user.id,
            token_hash=new_token_hash,
            family_id=token_record.family_id,
            parent_token_hash=token_record.token_hash,
            is_revoked=False,
            expires_at=new_expires_at,
            created_at=now_utc,
        )
        db.add(child_record)

        # Issue new access token
        new_access_token = create_access_token(
            user_id=user.id,
            role=user.role,
            username=user.username,
            email=user.email,
        )
        db.commit()

        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        return new_access_token, new_raw_token, expires_in, user

    def revoke_refresh_token(
        self,
        db: Session,
        raw_refresh_token: Optional[str] = None,
        raw_token: Optional[str] = None,
    ) -> bool:
        """Revokes a refresh token on user logout.
        
        Accepts either raw_refresh_token or raw_token for API flexibility.
        Ensures plaintext token is hashed with SHA-256 before database lookup.
        """
        token_str = raw_refresh_token or raw_token
        if not token_str:
            return False

        token_hash = hash_refresh_token(token_str)
        token_record = db.query(RefreshToken).filter_by(token_hash=token_hash).first()

        if token_record and not token_record.is_revoked:
            token_record.is_revoked = True
            token_record.revoked_at = datetime.now(timezone.utc)
            db.commit()
            return True

        return False


auth_service = AuthService()
