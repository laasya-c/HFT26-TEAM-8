"""Authentication and Session Management API Endpoints.

Implements:
- POST /api/v1/auth/login: Authenticate user, issue access token, and set HttpOnly refresh cookie.
- POST /api/v1/auth/refresh: Single-use refresh token rotation with CSRF protection and replay detection.
- POST /api/v1/auth/logout: Revoke active refresh token and delete cookie.
- GET /api/v1/auth/me: Retrieve current authenticated user profile and permissions.
"""
from typing import Any, Dict, Optional
from fastapi import APIRouter, Cookie, Depends, Header, Request, Response, status
from sqlalchemy.orm import Session

from src.backend.config import settings
from src.backend.core.auth_deps import get_current_active_user
from src.backend.core.exceptions import AuthenticationException, ForbiddenException
from src.backend.core.responses import success_response
from src.backend.db.session import get_db
from src.backend.models.auth import User
from src.backend.schemas.auth import LoginRequest, RefreshTokenRequest
from src.backend.services.auth import auth_service
from src.backend.services.reviews import review_service

router = APIRouter()


def _verify_csrf_for_cookie_request(request: Request, raw_token_from_body: Optional[str] = None) -> None:
    """Enforces CSRF mitigation for cookie-based authentication requests."""
    # If the client provides the refresh token in JSON body, pre-flighted CORS already protects it
    if raw_token_from_body:
        return

    # For browser cookie authentication, require custom anti-CSRF header or verified origin
    csrf_header = request.headers.get(settings.CSRF_HEADER_NAME) or request.headers.get("x-csrf-token")
    origin_header = request.headers.get("origin") or request.headers.get("referer")

    has_custom_header = bool(csrf_header and csrf_header.strip())
    has_valid_origin = False
    if origin_header:
        has_valid_origin = any(origin_header.startswith(allowed) for allowed in settings.CORS_ORIGINS)

    if not (has_custom_header or has_valid_origin):
        raise ForbiddenException(
            "CSRF protection check failed. Cookie-authenticated requests require an anti-CSRF header (X-Requested-With) or recognized Origin.",
            code="CSRF_VALIDATION_FAILED",
        )


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    """Configures secure, HttpOnly refresh token cookie on response."""
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path=f"{settings.API_V1_STR}/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Deletes the refresh token cookie."""
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=f"{settings.API_V1_STR}/auth",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )


@router.post("/auth/login", status_code=status.HTTP_200_OK, summary="User Authentication & Token Issuance")
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Authenticates credentials, issues access token, and sets HttpOnly refresh cookie."""
    user = auth_service.authenticate_user(
        db=db,
        username_or_email=payload.username_or_email,
        password=payload.password,
    )

    access_token, raw_refresh_token, expires_in = auth_service.issue_tokens(db=db, user=user)
    _set_refresh_cookie(response, raw_refresh_token)

    current_rev = review_service.get_current_revision(db)
    user_data = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }

    return success_response(
        data={
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in_seconds": expires_in,
            "user": user_data,
        },
        dataset_revision=current_rev,
    )


@router.post("/auth/refresh", status_code=status.HTTP_200_OK, summary="Rotate Refresh Token")
def refresh_token(
    request: Request,
    response: Response,
    payload: Optional[RefreshTokenRequest] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Rotates refresh token and issues new access token. Detects replay attacks."""
    cookie_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    body_token = payload.refresh_token if payload else None

    # Enforce CSRF check if utilizing cookie
    if cookie_token and not body_token:
        _verify_csrf_for_cookie_request(request, raw_token_from_body=body_token)

    raw_token = body_token or cookie_token
    if not raw_token:
        raise AuthenticationException(
            "No refresh token provided in cookie or payload.",
            code="MISSING_REFRESH_TOKEN",
        )

    new_access_token, new_raw_token, expires_in, user = auth_service.rotate_refresh_token(
        db=db,
        raw_refresh_token=raw_token,
    )

    _set_refresh_cookie(response, new_raw_token)

    current_rev = review_service.get_current_revision(db)
    user_data = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "full_name": user.full_name,
        "is_active": user.is_active,
    }

    return success_response(
        data={
            "access_token": new_access_token,
            "token_type": "bearer",
            "expires_in_seconds": expires_in,
            "user": user_data,
        },
        dataset_revision=current_rev,
    )


@router.post("/auth/logout", status_code=status.HTTP_200_OK, summary="User Logout & Token Revocation")
def logout(
    request: Request,
    response: Response,
    payload: Optional[RefreshTokenRequest] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Revokes active refresh token and clears HttpOnly session cookie."""
    cookie_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    body_token = payload.refresh_token if payload else None

    if cookie_token and not body_token:
        _verify_csrf_for_cookie_request(request, raw_token_from_body=body_token)

    raw_token = body_token or cookie_token
    if raw_token:
        auth_service.revoke_refresh_token(db=db, raw_refresh_token=raw_token)

    _clear_refresh_cookie(response)

    current_rev = review_service.get_current_revision(db)
    return success_response(
        data={"message": "Successfully logged out. Session revoked."},
        dataset_revision=current_rev,
    )


@router.get("/auth/me", status_code=status.HTTP_200_OK, summary="Get Current User Profile")
def get_me(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Returns profile and authorized scopes for the currently authenticated user."""
    current_rev = review_service.get_current_revision(db)
    user_data = {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
        "full_name": current_user.full_name,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "updated_at": current_user.updated_at.isoformat() if current_user.updated_at else None,
    }
    return success_response(data=user_data, dataset_revision=current_rev)
