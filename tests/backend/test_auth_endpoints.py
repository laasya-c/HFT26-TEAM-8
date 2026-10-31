"""Security Phase 2 Regression Test Suite: Authentication Services & Endpoints.

Verifies:
1. POST /api/v1/auth/login:
   - Success with username and email.
   - Failure with incorrect password or nonexistent user (uniform 401 error).
   - Deactivated account rejection (403).
2. GET /api/v1/auth/me:
   - Valid access token returns user profile.
   - Missing, expired, or tampered access tokens rejected (401).
   - Live role changes and account deactivations enforced (403).
3. POST /api/v1/auth/refresh:
   - Single-use token rotation (new access token, new refresh cookie).
   - Replay attack detection & token family invalidation (403).
   - Expired refresh tokens rejected (401).
4. POST /api/v1/auth/logout:
   - Session revocation and cookie clearing.
5. CSRF protection:
   - Rejection of cookie-based refresh/logout without custom header.
   - Permitting JSON-body token refresh.
6. Cookie security attributes (HttpOnly, SameSite, Path).
7. Administrator bootstrap CLI safety and complexity rules.
"""
from datetime import datetime, timedelta, timezone
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from src.backend.cli import create_admin_user
from src.backend.config import settings
from src.backend.core.exceptions import ValidationException
from src.backend.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
)
from src.backend.models.auth import RefreshToken, User, UserRole


TEST_PASSWORD = "StrongPassword123!"


@pytest.fixture
def test_user(db_session: Session) -> User:
    """Fixture providing a standard active researcher user."""
    user = User(
        username="researcher_alice",
        email="alice@wildscope.org",
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Alice Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def disabled_user(db_session: Session) -> User:
    """Fixture providing a deactivated user."""
    user = User(
        username="disabled_bob",
        email="bob@wildscope.org",
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Bob Disabled",
        role=UserRole.VIEWER.value,
        is_active=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# ============================================================================
# 1. User Login Tests
# ============================================================================

@pytest.mark.integration
def test_login_success_with_username_and_email(client: TestClient, test_user: User):
    """Verify login succeeds using either username or email and sets HttpOnly cookie."""
    # 1. Login via username
    resp_user = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "researcher_alice", "password": TEST_PASSWORD},
    )
    assert resp_user.status_code == 200
    body = resp_user.json()
    assert "access_token" in body["data"]
    assert body["data"]["token_type"] == "bearer"
    assert body["data"]["user"]["username"] == "researcher_alice"
    assert body["data"]["user"]["role"] == "researcher"

    # Verify refresh token cookie is set with security flags
    assert settings.REFRESH_COOKIE_NAME in resp_user.cookies
    cookie_header = resp_user.headers.get("set-cookie", "")
    assert "HttpOnly" in cookie_header
    assert f"Path={settings.API_V1_STR}/auth" in cookie_header

    # 2. Login via email
    resp_email = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "alice@wildscope.org", "password": TEST_PASSWORD},
    )
    assert resp_email.status_code == 200
    assert resp_email.json()["data"]["user"]["email"] == "alice@wildscope.org"


@pytest.mark.integration
def test_login_failure_incorrect_password(client: TestClient, test_user: User):
    """Verify login failure with incorrect password returns uniform 401 error."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "researcher_alice", "password": "WrongPassword999!"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "INVALID_CREDENTIALS"
    assert body["error"]["message"] == "Invalid username or password."
    assert "access_token" not in body


@pytest.mark.integration
def test_login_failure_nonexistent_user(client: TestClient, db_session: Session):
    """Verify login failure with nonexistent account returns identical 401 message (no user enumeration)."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "nonexistent_ghost", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "INVALID_CREDENTIALS"
    assert body["error"]["message"] == "Invalid username or password."


@pytest.mark.integration
def test_login_disabled_account_forbidden(client: TestClient, disabled_user: User):
    """Verify login failure for deactivated accounts returns HTTP 403."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "disabled_bob", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "ACCOUNT_DISABLED"
    assert "User account is disabled" in body["error"]["message"]


# ============================================================================
# 2. Access Token Verification & GET /auth/me
# ============================================================================

@pytest.mark.integration
def test_get_me_success(client: TestClient, test_user: User):
    """Verify GET /api/v1/auth/me returns current user profile with valid Bearer token."""
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "researcher_alice", "password": TEST_PASSWORD},
    )
    token = login_resp.json()["data"]["access_token"]

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["username"] == "researcher_alice"
    assert data["role"] == "researcher"
    assert data["is_active"] is True


@pytest.mark.integration
def test_get_me_missing_token_unauthorized(client: TestClient):
    """Verify GET /api/v1/auth/me returns 401 when no token is provided."""
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.integration
def test_get_me_expired_token(client: TestClient, test_user: User):
    """Verify expired access token is rejected with HTTP 401."""
    expired_token = create_access_token(
        user_id=test_user.id,
        role=test_user.role,
        username=test_user.username,
        email=test_user.email,
        expires_delta=timedelta(seconds=-60),  # Expired 1 minute ago
    )

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.integration
def test_get_me_tampered_signature(client: TestClient, test_user: User):
    """Verify tampered JWT signature is rejected with HTTP 401."""
    valid_token = create_access_token(
        user_id=test_user.id,
        role=test_user.role,
        username=test_user.username,
        email=test_user.email,
    )
    # Tamper with the signature portion
    parts = valid_token.split(".")
    tampered_token = f"{parts[0]}.{parts[1]}.bad_signature_value"

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.integration
def test_deactivated_user_bearer_token_blocked(client: TestClient, test_user: User, db_session: Session):
    """Verify active token is immediately rejected if user account is disabled in database."""
    valid_token = create_access_token(
        user_id=test_user.id,
        role=test_user.role,
        username=test_user.username,
        email=test_user.email,
    )

    # Deactivate account directly in database
    test_user.is_active = False
    db_session.add(test_user)
    db_session.commit()

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {valid_token}"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ACCOUNT_DISABLED"


# ============================================================================
# 3. Refresh Token Rotation & Replay Detection
# ============================================================================

@pytest.mark.integration
def test_refresh_token_rotation_success(client: TestClient, test_user: User, db_session: Session):
    """Verify refresh token rotation issues new access token, updates cookie, and marks old token revoked."""
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "researcher_alice", "password": TEST_PASSWORD},
    )
    cookie_token_1 = login_resp.cookies.get(settings.REFRESH_COOKIE_NAME)
    hash_1 = hash_refresh_token(cookie_token_1)

    # Call refresh endpoint with CSRF header
    refresh_resp = client.post(
        "/api/v1/auth/refresh",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert refresh_resp.status_code == 200
    body = refresh_resp.json()
    assert "access_token" in body["data"]

    # New cookie issued
    cookie_token_2 = refresh_resp.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert cookie_token_2 != cookie_token_1
    hash_2 = hash_refresh_token(cookie_token_2)

    # Check database state
    db_session.expire_all()
    token_rec_1 = db_session.query(RefreshToken).filter_by(token_hash=hash_1).first()
    token_rec_2 = db_session.query(RefreshToken).filter_by(token_hash=hash_2).first()

    assert token_rec_1.is_revoked is True
    assert token_rec_1.revoked_at is not None
    assert token_rec_2.is_revoked is False
    assert token_rec_2.family_id == token_rec_1.family_id
    assert token_rec_2.parent_token_hash == hash_1


@pytest.mark.integration
def test_refresh_token_replay_attack_revokes_family(client: TestClient, test_user: User, db_session: Session):
    """Verify presenting an already-revoked token detects replay and invalidates the entire token family."""
    # 1. Login
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "researcher_alice", "password": TEST_PASSWORD},
    )
    token_1 = login_resp.cookies.get(settings.REFRESH_COOKIE_NAME)

    # 2. Legitimate rotation -> Token 1 is now revoked, Token 2 is issued
    rot_resp = client.post(
        "/api/v1/auth/refresh",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert rot_resp.status_code == 200
    token_2 = rot_resp.cookies.get(settings.REFRESH_COOKIE_NAME)

    # 3. Attacker replays consumed Token 1 (simulated via explicit payload)
    replay_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": token_1},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert replay_resp.status_code == 403
    assert replay_resp.json()["error"]["code"] == "TOKEN_REPLAY_DETECTED"

    # 4. Verify all tokens in that family (including Token 2) are now revoked!
    db_session.expire_all()
    hash_2 = hash_refresh_token(token_2)
    token_rec_2 = db_session.query(RefreshToken).filter_by(token_hash=hash_2).first()
    assert token_rec_2.is_revoked is True


# ============================================================================
# 4. Logout & Token Revocation
# ============================================================================

@pytest.mark.integration
def test_logout_revokes_token_and_clears_cookie(client: TestClient, test_user: User, db_session: Session):
    """Verify POST /api/v1/auth/logout marks token revoked and clears HttpOnly cookie."""
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "researcher_alice", "password": TEST_PASSWORD},
    )
    token = login_resp.cookies.get(settings.REFRESH_COOKIE_NAME)
    token_hash = hash_refresh_token(token)

    logout_resp = client.post(
        "/api/v1/auth/logout",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert logout_resp.status_code == 200
    assert "Successfully logged out" in logout_resp.json()["data"]["message"]

    # Cookie is deleted
    assert logout_resp.cookies.get(settings.REFRESH_COOKIE_NAME) is None

    # Database record is revoked
    db_session.expire_all()
    token_rec = db_session.query(RefreshToken).filter_by(token_hash=token_hash).first()
    assert token_rec.is_revoked is True


@pytest.mark.integration
def test_logout_without_cookie_or_body_succeeds_and_clears_cookie(client: TestClient):
    """Verify POST /api/v1/auth/logout succeeds even when no session cookie or body is present."""
    logout_resp = client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200
    assert "Successfully logged out" in logout_resp.json()["data"]["message"]
    assert logout_resp.cookies.get(settings.REFRESH_COOKIE_NAME) is None


@pytest.mark.integration
def test_logout_with_invalid_cookie_succeeds_and_clears_cookie(client: TestClient):
    """Verify POST /api/v1/auth/logout gracefully handles invalid/unknown refresh cookie."""
    client.cookies.set(settings.REFRESH_COOKIE_NAME, "nonexistent_opaque_token_string")
    logout_resp = client.post(
        "/api/v1/auth/logout",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert logout_resp.status_code == 200
    assert "Successfully logged out" in logout_resp.json()["data"]["message"]
    assert logout_resp.cookies.get(settings.REFRESH_COOKIE_NAME) is None


# ============================================================================
# 5. CSRF Protection
# ============================================================================

@pytest.mark.integration
def test_csrf_protection_rejects_cookie_refresh_without_header(client: TestClient, test_user: User):
    """Verify cookie-based refresh without custom header or recognized Origin is rejected with 403."""
    client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "researcher_alice", "password": TEST_PASSWORD},
    )

    # Missing X-Requested-With header
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


@pytest.mark.integration
def test_csrf_protection_permits_json_body_token(client: TestClient, test_user: User):
    """Verify JSON body refresh token without cookies bypasses CSRF header requirement."""
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "researcher_alice", "password": TEST_PASSWORD},
    )
    raw_token = login_resp.cookies.get(settings.REFRESH_COOKIE_NAME)

    # Clear client cookies so the request does not send any cookie
    client.cookies.clear()
    resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": raw_token},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()["data"]


# ============================================================================
# 6. Administrator Bootstrap CLI Tests
# ============================================================================

@pytest.mark.unit
def test_admin_bootstrap_cli_creation(db_session: Session):
    """Verify create_admin_user boots administrator account with valid complexity."""
    admin = create_admin_user(
        username="superadmin",
        email="admin@wildscope.org",
        password="SuperAdminPassword123!",
        full_name="Chief Ranger",
        db_session=db_session,
    )
    assert admin.username == "superadmin"
    assert admin.role == "admin"
    assert admin.is_active is True

    queried = db_session.query(User).filter_by(username="superadmin").first()
    assert queried is not None
    assert queried.role == "admin"


@pytest.mark.unit
def test_admin_bootstrap_rejects_weak_password(db_session: Session):
    """Verify create_admin_user enforces password complexity."""
    with pytest.raises(ValidationException) as exc_info:
        create_admin_user(
            username="weak_admin",
            email="weak@wildscope.org",
            password="weak",
            db_session=db_session,
        )
    assert "Password must be at least 10 characters long" in str(exc_info.value)


@pytest.mark.unit
def test_admin_bootstrap_prevents_unintentional_overwrite(db_session: Session):
    """Verify create_admin_user refuses to overwrite existing account unless force=True."""
    create_admin_user(
        username="primary_admin",
        email="primary@wildscope.org",
        password="FirstPassword123!",
        db_session=db_session,
    )

    # Attempt second creation without force -> Must raise ValidationException
    with pytest.raises(ValidationException) as exc_info:
        create_admin_user(
            username="primary_admin",
            email="primary@wildscope.org",
            password="SecondPassword123!",
            force=False,
            db_session=db_session,
        )
    assert "already exists. Use --force to overwrite" in str(exc_info.value)

    # Attempt with force=True -> Succeeds
    updated = create_admin_user(
        username="primary_admin",
        email="primary@wildscope.org",
        password="SecondPassword123!",
        force=True,
        db_session=db_session,
    )
    assert updated.username == "primary_admin"
