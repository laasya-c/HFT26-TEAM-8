"""FastAPI Authentication and Authorization Dependencies.

Provides:
- OAuth2 Bearer token extraction and JWT validation.
- Current active user resolution against database.
- Role-based authorization guard factories.
"""
from datetime import datetime, timezone
from typing import Any, List, Optional, Set, Union
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from src.backend.config import settings
from src.backend.core.exceptions import AuthenticationException, ForbiddenException
from src.backend.core.security import decode_access_token, hash_refresh_token
from src.backend.db.session import get_db
from src.backend.models.auth import ApiKey, User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
    auto_error=False,
)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Extracts and verifies JWT Bearer token, returning the authenticated User."""
    if not token or not token.strip():
        raise AuthenticationException(
            "Authentication credentials were not provided.",
            code="AUTHENTICATION_REQUIRED",
        )

    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationException(
            "Access token payload is missing subject claim.",
            code="INVALID_TOKEN",
        )

    user = db.query(User).filter_by(id=user_id).first()
    if user is None:
        raise AuthenticationException(
            "User referenced in access token does not exist.",
            code="USER_NOT_FOUND",
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Verifies that the authenticated user account is in an active (non-disabled) state."""
    if not current_user.is_active:
        raise ForbiddenException(
            "User account is disabled. Access denied.",
            code="ACCOUNT_DISABLED",
        )
    return current_user


def require_role(allowed_roles: Union[str, List[str], Set[str]]):
    """Dependency factory checking that the current active user possesses an authorized role."""
    if isinstance(allowed_roles, str):
        roles_set = {allowed_roles}
    else:
        roles_set = set(allowed_roles)

    async def role_checker(current_user: User = Depends(get_current_active_user)) -> User:
        if current_user.role not in roles_set:
            raise ForbiddenException(
                f"Role '{current_user.role}' is not authorized to access this resource. Required: {', '.join(sorted(roles_set))}.",
                code="INSUFFICIENT_PERMISSIONS",
            )
        return current_user

    return role_checker


async def verify_telemetry_auth(
    camera_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Union[ApiKey, User]:
    """Authenticates field telemetry requests via station-isolated API Key or authorized User token.
    
    Invariants:
    1. Field-device API keys are verified via SHA-256 hash.
    2. Station isolation: API key registered for CAM-X is strictly prohibited from posting telemetry to CAM-Y (HTTP 403).
    3. Active sanctuary Administrators and Researchers can submit telemetry via JWT Bearer token.
    4. Viewers or unauthenticated callers are rejected.
    """
    api_key_header = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    auth_header = request.headers.get("Authorization")

    # 1. API Key Authentication (Field Devices)
    if api_key_header:
        raw_key = api_key_header.strip()
        key_hash = hash_refresh_token(raw_key)
        api_key_rec = db.query(ApiKey).filter_by(key_hash=key_hash).first()

        if not api_key_rec or not api_key_rec.is_active or api_key_rec.revoked_at is not None:
            raise AuthenticationException("Invalid or inactive API key.", code="INVALID_API_KEY")

        now_utc = datetime.now(timezone.utc)
        if api_key_rec.expires_at is not None and api_key_rec.expires_at <= now_utc:
            raise AuthenticationException("API key has expired.", code="INVALID_API_KEY")

        # Station Isolation Invariant: Device API key is strictly locked to its assigned camera station
        if api_key_rec.camera_id != camera_id:
            raise ForbiddenException(
                f"Station isolation violation: API key registered for camera '{api_key_rec.camera_id}' cannot submit telemetry for camera '{camera_id}'.",
                code="DEVICE_STATION_MISMATCH",
            )

        api_key_rec.last_used_at = now_utc
        db.commit()
        return api_key_rec

    # 2. Bearer JWT Authentication (Sanctuary Administrators & Researchers)
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationException("Access token missing subject claim.", code="INVALID_TOKEN")

        user = db.query(User).filter_by(id=user_id).first()
        if user is None:
            raise AuthenticationException("User referenced in access token does not exist.", code="USER_NOT_FOUND")
        if not user.is_active:
            raise ForbiddenException("User account is disabled.", code="ACCOUNT_DISABLED")
        if user.role not in {"admin", "researcher"}:
            raise ForbiddenException(
                f"Role '{user.role}' is not authorized to submit camera telemetry. Required: admin, researcher.",
                code="INSUFFICIENT_PERMISSIONS",
            )
        return user

    # 3. Neither valid API Key nor Bearer Token provided
    raise AuthenticationException(
        "Authentication required. Provide a valid field device API key (X-API-Key) or researcher Bearer token.",
        code="AUTHENTICATION_REQUIRED",
    )
