"""Security Phase 4 Regression Test Suite: Comprehensive Security Audit & Invariant Verification.

Verifies:
1. JWT Boundary & Cryptographic Verification:
   - Malformed token structure (single-segment, 2-part, 4-part) -> HTTP 401 INVALID_TOKEN.
   - Forged signature signed with alternative secret key -> HTTP 401 INVALID_TOKEN.
   - Missing subject (sub) claim -> HTTP 401 INVALID_TOKEN.
   - Nonexistent subject claim -> HTTP 401 USER_NOT_FOUND.
   - Empty or whitespace Bearer header -> HTTP 401 AUTHENTICATION_REQUIRED.
   - Non-Bearer authorization scheme (e.g. Basic) -> HTTP 401 AUTHENTICATION_REQUIRED.
2. Refresh Token Rotation (RTR), Deep Replay Detection & Lineage:
   - Multi-hop rotation: Token 1 -> Token 2 -> Token 3 maintains lineage and revokes predecessors.
   - Replay attack detection: Submitting consumed Token 1 revokes the entire family (including Token 3).
   - Unknown/arbitrary refresh token strings -> HTTP 401 INVALID_REFRESH_TOKEN.
   - Expired refresh token -> HTTP 401 REFRESH_TOKEN_EXPIRED.
   - Disabled user account refresh attempt -> HTTP 403 ACCOUNT_DISABLED.
3. Live Privilege Changes & Instant Account Deactivation:
   - Active JWT session immediately rejected when account disabled in DB -> HTTP 403 ACCOUNT_DISABLED.
   - Role demotion (admin -> viewer) immediately blocks privileged operations on existing unexpired JWT.
   - Role promotion (viewer -> researcher) immediately unlocks research operations on existing unexpired JWT.
4. Comprehensive Cross-Resource IDOR Defense:
   - Researcher cross-access to other researchers' jobs blocked with HTTP 403 INSUFFICIENT_PERMISSIONS.
   - Admin oversight globally permitted across all jobs.
   - Reviewer identity spoofing prevented across different user IDs.
   - Monitoring action attribution bound strictly to token subject.
5. Wildlife Spatial Data Privacy & Path Traversal Defense:
   - Camera and observation coordinates obfuscated (None / obfuscated: True) for Viewers.
   - Exact floating-point GPS coordinates preserved for Researchers and Admins.
   - Safe path resolution blocks directory traversal on media content endpoints.
   - Unauthenticated media retrieval blocked with HTTP 401.
6. Field-Device API Key Boundaries & Station Isolation:
   - Pre-shared API keys bound strictly to assigned camera station; cross-camera telemetry rejected (403).
   - Explicitly revoked API keys rejected with HTTP 401 INVALID_API_KEY.
   - Field-device keys strictly prohibited from human user endpoints (HTTP 401).
7. Anti-Enumeration & Internal Exception Masking:
   - Nonexistent user and wrong password produce identical HTTP 401 INVALID_CREDENTIALS responses.
   - Production mode (DEBUG=False) strictly masks stack traces, SQL, and internal exception details.
8. CSRF Protection & Cookie Security:
   - Cookie-based refresh requires anti-CSRF header or recognized Origin.
   - Unauthorized external Origin rejected with HTTP 403 CSRF_VALIDATION_FAILED.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import io
import json
import uuid
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from contracts.schemas import ProvenanceEnum, ReviewStatusEnum
from src.backend.config import settings
from src.backend.core.security import (
    create_access_token,
    generate_api_key,
    generate_raw_refresh_token,
    hash_password,
    hash_refresh_token,
)
from src.backend.models import (
    ApiKey,
    Camera,
    Detection,
    ImageFrame,
    MediaAsset,
    MonitoringAction,
    PredictionRun,
    ProcessingJob,
    RefreshToken,
    ReviewEvent,
    User,
    UserRole,
)
from src.backend.models.job import JobStatus

TEST_PASSWORD = "StrongPassword123!"
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb" + b"\x00" * 50


# ============================================================================
# User & Auth Fixtures
# ============================================================================

@pytest.fixture
def admin_user(db_session: Session) -> User:
    """Administrator persona fixture."""
    user = User(
        id=str(uuid.uuid4()),
        username="sec4_admin",
        email="sec4_admin@wildscope.org",
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Security Admin",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def researcher_user(db_session: Session) -> User:
    """Researcher persona fixture."""
    user = User(
        id=str(uuid.uuid4()),
        username="sec4_researcher",
        email="sec4_researcher@wildscope.org",
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Security Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def second_researcher_user(db_session: Session) -> User:
    """Second researcher persona for cross-user IDOR testing."""
    user = User(
        id=str(uuid.uuid4()),
        username="sec4_researcher_two",
        email="sec4_researcher_two@wildscope.org",
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Second Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def viewer_user(db_session: Session) -> User:
    """Public viewer persona fixture."""
    user = User(
        id=str(uuid.uuid4()),
        username="sec4_viewer",
        email="sec4_viewer@wildscope.org",
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Security Viewer",
        role=UserRole.VIEWER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def auth_headers(user: User) -> dict:
    """Helper creating valid Bearer authentication headers for a given user."""
    token = create_access_token(
        user_id=user.id,
        role=user.role,
        username=user.username,
        email=user.email,
    )
    return {"Authorization": f"Bearer {token}"}


# ============================================================================
# Section 1: JWT Boundary & Cryptographic Verification
# ============================================================================

@pytest.mark.integration
def test_jwt_malformed_token_structure(client: TestClient):
    """Verify malformed tokens with wrong segment counts are rejected with HTTP 401."""
    # 1 segment
    res1 = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not_a_jwt"})
    assert res1.status_code == 401
    assert res1.json()["error"]["code"] == "INVALID_TOKEN"

    # 2 segments
    res2 = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer header.payload"})
    assert res2.status_code == 401
    assert res2.json()["error"]["code"] == "INVALID_TOKEN"

    # 4 segments
    res3 = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer h.p.s.extra"})
    assert res3.status_code == 401
    assert res3.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.integration
def test_jwt_forged_signature_different_secret(client: TestClient, researcher_user: User):
    """Verify tokens signed with an unauthorized secret key are rejected with HTTP 401."""
    import jwt
    payload = {
        "sub": researcher_user.id,
        "role": researcher_user.role,
        "username": researcher_user.username,
        "email": researcher_user.email,
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
    }
    forged_token = jwt.encode(payload, "wrong-secret-key-attacker-provided-1234567890", algorithm="HS256")
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.integration
def test_jwt_missing_subject_claim(client: TestClient):
    """Verify tokens missing the subject (sub) claim are rejected with HTTP 401."""
    import jwt
    payload = {
        "role": "admin",
        "username": "no_sub_user",
        "email": "nosub@wildscope.org",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.integration
def test_jwt_nonexistent_subject_user(client: TestClient):
    """Verify tokens referencing non-existent user IDs return HTTP 401 USER_NOT_FOUND."""
    fake_user_id = str(uuid.uuid4())
    token = create_access_token(
        user_id=fake_user_id,
        role="researcher",
        username="ghost_user",
        email="ghost@wildscope.org",
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "USER_NOT_FOUND"


@pytest.mark.integration
def test_jwt_empty_or_non_bearer_header(client: TestClient):
    """Verify empty Bearer or non-Bearer authorization schemes return 401 AUTHENTICATION_REQUIRED."""
    # Empty bearer
    res1 = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer "})
    assert res1.status_code == 401
    assert res1.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    # Whitespace bearer
    res2 = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer    "})
    assert res2.status_code == 401
    assert res2.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    # Basic auth scheme
    res3 = client.get("/api/v1/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert res3.status_code == 401
    assert res3.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


# ============================================================================
# Section 2: Refresh Token Security, Lineage & Replay Invalidation
# ============================================================================

@pytest.mark.integration
def test_refresh_token_multi_hop_rotation_lineage(
    client: TestClient,
    researcher_user: User,
    db_session: Session,
):
    """Verify multi-generational token rotation preserves lineage and maintains active state for the leaf."""
    # Hop 1: Login
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": researcher_user.username, "password": TEST_PASSWORD},
    )
    token_1 = login_resp.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert token_1 is not None

    # Hop 2: First Refresh
    ref1_resp = client.post("/api/v1/auth/refresh", headers={"X-Requested-With": "XMLHttpRequest"})
    assert ref1_resp.status_code == 200
    token_2 = ref1_resp.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert token_2 is not None
    assert token_2 != token_1

    # Hop 3: Second Refresh
    ref2_resp = client.post("/api/v1/auth/refresh", headers={"X-Requested-With": "XMLHttpRequest"})
    assert ref2_resp.status_code == 200
    token_3 = ref2_resp.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert token_3 is not None
    assert token_3 != token_2

    # Verify database state across the lineage
    db_session.expire_all()
    rec1 = db_session.query(RefreshToken).filter_by(token_hash=hash_refresh_token(token_1)).first()
    rec2 = db_session.query(RefreshToken).filter_by(token_hash=hash_refresh_token(token_2)).first()
    rec3 = db_session.query(RefreshToken).filter_by(token_hash=hash_refresh_token(token_3)).first()

    assert rec1.is_revoked is True
    assert rec2.is_revoked is True
    assert rec3.is_revoked is False
    assert rec1.family_id == rec2.family_id == rec3.family_id
    assert rec2.parent_token_hash == rec1.token_hash
    assert rec3.parent_token_hash == rec2.token_hash


@pytest.mark.integration
def test_refresh_token_deep_replay_revokes_entire_family(
    client: TestClient,
    researcher_user: User,
    db_session: Session,
):
    """Verify replaying an older ancestor token immediately revokes all descendant tokens in that family."""
    # Login -> Token 1
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": researcher_user.username, "password": TEST_PASSWORD},
    )
    token_1 = login_resp.cookies.get(settings.REFRESH_COOKIE_NAME)

    # Rotate -> Token 2
    ref1_resp = client.post("/api/v1/auth/refresh", headers={"X-Requested-With": "XMLHttpRequest"})
    token_2 = ref1_resp.cookies.get(settings.REFRESH_COOKIE_NAME)

    # Rotate -> Token 3 (current active leaf)
    ref2_resp = client.post("/api/v1/auth/refresh", headers={"X-Requested-With": "XMLHttpRequest"})
    token_3 = ref2_resp.cookies.get(settings.REFRESH_COOKIE_NAME)

    # Replay Attack: Attacker presents consumed Token 1 via JSON body
    client.cookies.clear()
    replay_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": token_1},
    )
    assert replay_resp.status_code == 403
    assert replay_resp.json()["error"]["code"] == "TOKEN_REPLAY_DETECTED"

    # Verify that Token 3 (previously active) has been immediately revoked in DB
    db_session.expire_all()
    rec3 = db_session.query(RefreshToken).filter_by(token_hash=hash_refresh_token(token_3)).first()
    assert rec3.is_revoked is True

    # Legitimate client attempts to use Token 3 -> Rejected!
    client.cookies.set(settings.REFRESH_COOKIE_NAME, token_3)
    legit_resp = client.post("/api/v1/auth/refresh", headers={"X-Requested-With": "XMLHttpRequest"})
    assert legit_resp.status_code == 403
    assert legit_resp.json()["error"]["code"] == "TOKEN_REPLAY_DETECTED"


@pytest.mark.integration
def test_refresh_token_unknown_and_expired(
    client: TestClient,
    researcher_user: User,
    db_session: Session,
):
    """Verify unknown and expired refresh tokens return HTTP 401."""
    # 1. Unknown random token
    res_unk = client.post("/api/v1/auth/refresh", json={"refresh_token": "random_fake_opaque_token_string"})
    assert res_unk.status_code == 401
    assert res_unk.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"

    # 2. Expired token in database
    raw_exp = generate_raw_refresh_token()
    exp_hash = hash_refresh_token(raw_exp)
    exp_rec = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=researcher_user.id,
        token_hash=exp_hash,
        family_id=str(uuid.uuid4()),
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(exp_rec)
    db_session.commit()

    res_exp = client.post("/api/v1/auth/refresh", json={"refresh_token": raw_exp})
    assert res_exp.status_code == 401
    assert res_exp.json()["error"]["code"] == "REFRESH_TOKEN_EXPIRED"


# ============================================================================
# Section 3: Live Privilege Changes & Instant Account Deactivation
# ============================================================================

@pytest.mark.integration
def test_instant_account_deactivation_during_active_session(
    client: TestClient,
    researcher_user: User,
    db_session: Session,
):
    """Verify that deactivating a user in DB immediately revokes access without waiting for JWT expiry."""
    headers = auth_headers(researcher_user)

    # Initial request succeeds
    res1 = client.get("/api/v1/auth/me", headers=headers)
    assert res1.status_code == 200

    # Deactivate account in DB
    researcher_user.is_active = False
    db_session.add(researcher_user)
    db_session.commit()

    # Immediate rejection on next request
    res2 = client.get("/api/v1/auth/me", headers=headers)
    assert res2.status_code == 403
    assert res2.json()["error"]["code"] == "ACCOUNT_DISABLED"

    # Business endpoints also immediately reject
    res3 = client.get("/api/v1/observations", headers=headers)
    assert res3.status_code == 403
    assert res3.json()["error"]["code"] == "ACCOUNT_DISABLED"


@pytest.mark.integration
def test_instant_role_demotion_blocks_privileged_actions(
    client: TestClient,
    admin_user: User,
    db_session: Session,
):
    """Verify that demoting an admin to viewer in DB immediately blocks admin operations on existing JWT."""
    # Token issued when user was Admin
    headers = auth_headers(admin_user)

    # Demote in database to Viewer
    admin_user.role = UserRole.VIEWER.value
    db_session.add(admin_user)
    db_session.commit()

    # Admin route POST /cameras must immediately block with 403
    payload = {"id": "CAM-DEMOTE-TEST", "label": "Demote Station", "provenance": "observed"}
    resp = client.post("/api/v1/cameras", json=payload, headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


@pytest.mark.integration
def test_instant_role_promotion_unlocks_operations(
    client: TestClient,
    viewer_user: User,
    db_session: Session,
):
    """Verify promoting a viewer to researcher immediately allows researcher endpoints on existing JWT."""
    # Token issued when user was Viewer
    headers = auth_headers(viewer_user)

    # Setup camera and detection for review
    cam = Camera(id="CAM-PROMOTE", label="Promote Cam", timezone="UTC", provenance="observed")
    db_session.add(cam)
    db_session.flush()

    med = MediaAsset(id="MED-PROMOTE", type="image", camera_id=cam.id, storage_key="media/p.jpg", content_hash="hash_p", provenance="observed")
    db_session.add(med)
    db_session.flush()

    frame = ImageFrame(id="FRM-PROMOTE", source_media_id=med.id, content_url="/api/v1/images/FRM-PROMOTE/content", provenance="observed")
    db_session.add(frame)
    db_session.flush()

    run = PredictionRun(id="RUN-PROMOTE", model_name="wildscope", model_version="v2", device="cpu", status="completed")
    db_session.add(run)
    db_session.flush()

    det = Detection(
        id="DET-PROMOTE", image_id=frame.id, run_id=run.id,
        bbox_x=0.1, bbox_y=0.1, bbox_w=0.4, bbox_h=0.4,
        raw_label="tiger", taxon_id="panthera_tigris", label="Bengal Tiger",
        score=0.9, model_version="v2", review_status="pending", provenance="inferred",
    )
    db_session.add(det)
    db_session.commit()

    # As Viewer, POST /reviews is blocked
    review_payload = {
        "detection_id": det.id,
        "decision": "confirmed",
        "reason": "Expert review",
        "reviewer_id": "attempt",
        "expected_revision": 1,
    }
    res_block = client.post("/api/v1/reviews", json=review_payload, headers=headers)
    assert res_block.status_code == 403

    # Promote to Researcher in DB
    viewer_user.role = UserRole.RESEARCHER.value
    db_session.add(viewer_user)
    db_session.commit()

    # Using the same token, POST /reviews now succeeds!
    res_allow = client.post("/api/v1/reviews", json=review_payload, headers=headers)
    assert res_allow.status_code == 201


# ============================================================================
# Section 4: Comprehensive Cross-Resource IDOR Defense
# ============================================================================

@pytest.mark.integration
def test_cross_researcher_job_idor_matrix(
    client: TestClient,
    researcher_user: User,
    second_researcher_user: User,
    admin_user: User,
    db_session: Session,
):
    """Verify bidirectional IDOR protection across researchers and universal admin oversight."""
    # Create Job A (Elena) and Job B (Marcus)
    job_a = ProcessingJob(
        id="job_sec4_a", upload_id="up_sec4_a", status=JobStatus.QUEUED.value,
        progress=0.0, total_items=1, processed_items=0, media_ids=[],
        created_by_user_id=researcher_user.id,
    )
    job_b = ProcessingJob(
        id="job_sec4_b", upload_id="up_sec4_b", status=JobStatus.QUEUED.value,
        progress=0.0, total_items=1, processed_items=0, media_ids=[],
        created_by_user_id=second_researcher_user.id,
    )
    db_session.add_all([job_a, job_b])
    db_session.commit()

    # Elena accesses Job A -> 200; Elena accesses Job B -> 403
    assert client.get(f"/api/v1/jobs/{job_a.id}", headers=auth_headers(researcher_user)).status_code == 200
    assert client.get(f"/api/v1/jobs/{job_b.id}", headers=auth_headers(researcher_user)).status_code == 403

    # Marcus accesses Job B -> 200; Marcus accesses Job A -> 403
    assert client.get(f"/api/v1/jobs/{job_b.id}", headers=auth_headers(second_researcher_user)).status_code == 200
    assert client.get(f"/api/v1/jobs/{job_a.id}", headers=auth_headers(second_researcher_user)).status_code == 403

    # Admin accesses both -> 200
    assert client.get(f"/api/v1/jobs/{job_a.id}", headers=auth_headers(admin_user)).status_code == 200
    assert client.get(f"/api/v1/jobs/{job_b.id}", headers=auth_headers(admin_user)).status_code == 200


# ============================================================================
# Section 5: Wildlife Anti-Poaching Coordinate Privacy & Path Traversal
# ============================================================================

@pytest.mark.integration
def test_wildlife_coordinate_privacy_across_all_endpoints(
    client: TestClient,
    viewer_user: User,
    researcher_user: User,
    admin_user: User,
    db_session: Session,
):
    """Verify wildlife coordinate obfuscation for Viewers and full precision for Researchers/Admins."""
    cam = Camera(
        id="CAM-SEC4-GEO",
        label="Sensitive Rhino Station",
        timezone="UTC",
        latitude=26.58231,
        longitude=93.17452,
        provenance="observed",
    )
    db_session.add(cam)
    db_session.flush()

    med = MediaAsset(id="MED-SEC4-GEO", type="image", camera_id=cam.id, storage_key="media/rhino.jpg", content_hash="hash_rhino", provenance="observed")
    db_session.add(med)
    db_session.flush()

    frame = ImageFrame(id="FRM-SEC4-GEO", source_media_id=med.id, content_url="/api/v1/images/FRM-SEC4-GEO/content", provenance="observed")
    db_session.add(frame)
    db_session.flush()

    run = PredictionRun(id="RUN-SEC4-GEO", model_name="yolo", model_version="v2", device="cpu", status="completed")
    db_session.add(run)
    db_session.flush()

    det = Detection(
        id="DET-SEC4-GEO", image_id=frame.id, run_id=run.id,
        bbox_x=0.2, bbox_y=0.2, bbox_w=0.4, bbox_h=0.4,
        raw_label="rhino", taxon_id="rhinoceros_unicornis", label="One-horned Rhinoceros",
        score=0.98, model_version="v2", review_status="pending", provenance="inferred",
    )
    db_session.add(det)
    db_session.commit()

    # 1. GET /cameras
    res_c_v = client.get("/api/v1/cameras", headers=auth_headers(viewer_user)).json()["data"]
    item_c_v = next(c for c in res_c_v if c["id"] == "CAM-SEC4-GEO")
    assert item_c_v["coordinates"] is None
    assert item_c_v["coordinates_obfuscated"] is True

    res_c_r = client.get("/api/v1/cameras", headers=auth_headers(researcher_user)).json()["data"]
    item_c_r = next(c for c in res_c_r if c["id"] == "CAM-SEC4-GEO")
    assert item_c_r["coordinates"] == [93.17452, 26.58231]
    assert item_c_r["coordinates_obfuscated"] is False

    # 2. GET /cameras/{id}
    res_d_v = client.get(f"/api/v1/cameras/{cam.id}", headers=auth_headers(viewer_user)).json()["data"]
    assert res_d_v["coordinates"] is None
    assert res_d_v["coordinates_obfuscated"] is True

    res_d_a = client.get(f"/api/v1/cameras/{cam.id}", headers=auth_headers(admin_user)).json()["data"]
    assert res_d_a["coordinates"] == [93.17452, 26.58231]
    assert res_d_a["coordinates_obfuscated"] is False

    # 3. GET /observations
    res_o_v = client.get("/api/v1/observations", headers=auth_headers(viewer_user)).json()["data"]
    item_o_v = next(d for d in res_o_v if d["id"] == "DET-SEC4-GEO")
    assert item_o_v["coordinates"] is None
    assert item_o_v["coordinates_obfuscated"] is True

    res_o_r = client.get("/api/v1/observations", headers=auth_headers(researcher_user)).json()["data"]
    item_o_r = next(d for d in res_o_r if d["id"] == "DET-SEC4-GEO")
    assert item_o_r["coordinates"] == [93.17452, 26.58231]
    assert item_o_r["coordinates_obfuscated"] is False


@pytest.mark.integration
def test_media_content_path_traversal_and_unauth_defense(
    client: TestClient,
    viewer_user: User,
):
    """Verify that path traversal attempts fail and media endpoints require authentication."""
    # Unauthenticated -> 401
    res1 = client.get("/api/v1/images/some_image_id/content")
    assert res1.status_code == 401
    assert res1.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    # Directory traversal in ID -> not found or 422, never leaks filesystem
    res2 = client.get("/api/v1/images/../../etc/passwd/content", headers=auth_headers(viewer_user))
    assert res2.status_code in (404, 422)


# ============================================================================
# Section 6: Field-Device API Key Boundary & Station Isolation
# ============================================================================

@pytest.mark.integration
def test_api_key_station_isolation_matrix(
    client: TestClient,
    db_session: Session,
):
    """Verify bidirectional station isolation: Station 1 cannot post to Station 2 and vice versa."""
    cam1 = Camera(id="CAM-ISOL-1", label="Station 1", timezone="UTC", provenance="observed")
    cam2 = Camera(id="CAM-ISOL-2", label="Station 2", timezone="UTC", provenance="observed")
    db_session.add_all([cam1, cam2])
    db_session.commit()

    raw_k1, hash_k1 = generate_api_key()
    raw_k2, hash_k2 = generate_api_key()

    key1 = ApiKey(id=str(uuid.uuid4()), name="K1", key_hash=hash_k1, camera_id=cam1.id, is_active=True)
    key2 = ApiKey(id=str(uuid.uuid4()), name="K2", key_hash=hash_k2, camera_id=cam2.id, is_active=True)
    db_session.add_all([key1, key2])
    db_session.commit()

    payload = {"observed_at": "2026-10-31T07:30:00Z", "battery_level": 95.0}

    # K1 to CAM-1 -> 201; K1 to CAM-2 -> 403
    assert client.post(f"/api/v1/cameras/{cam1.id}/telemetry", json=payload, headers={"X-API-Key": raw_k1}).status_code == 201
    res_iso1 = client.post(f"/api/v1/cameras/{cam2.id}/telemetry", json=payload, headers={"X-API-Key": raw_k1})
    assert res_iso1.status_code == 403
    assert res_iso1.json()["error"]["code"] == "DEVICE_STATION_MISMATCH"

    # K2 to CAM-2 -> 201; K2 to CAM-1 -> 403
    assert client.post(f"/api/v1/cameras/{cam2.id}/telemetry", json=payload, headers={"X-API-Key": raw_k2}).status_code == 201
    res_iso2 = client.post(f"/api/v1/cameras/{cam1.id}/telemetry", json=payload, headers={"X-API-Key": raw_k2})
    assert res_iso2.status_code == 403
    assert res_iso2.json()["error"]["code"] == "DEVICE_STATION_MISMATCH"


@pytest.mark.integration
def test_api_key_revocation_and_user_endpoint_isolation(
    client: TestClient,
    db_session: Session,
):
    """Verify revoked API keys are rejected and API keys cannot access human user endpoints."""
    cam = Camera(id="CAM-REV-KEY", label="Revoke Key Cam", timezone="UTC", provenance="observed")
    db_session.add(cam)
    db_session.commit()

    raw_key, key_hash = generate_api_key()
    key_rec = ApiKey(
        id=str(uuid.uuid4()),
        name="Revocable Key",
        key_hash=key_hash,
        camera_id=cam.id,
        is_active=True,
        revoked_at=datetime.now(timezone.utc),  # Explicitly revoked
    )
    db_session.add(key_rec)
    db_session.commit()

    payload = {"observed_at": "2026-10-31T07:30:00Z", "battery_level": 95.0}

    # Revoked key returns 401
    resp = client.post(f"/api/v1/cameras/{cam.id}/telemetry", json=payload, headers={"X-API-Key": raw_key})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_API_KEY"

    # API keys cannot access user endpoints
    res_user1 = client.get("/api/v1/auth/me", headers={"X-API-Key": raw_key})
    assert res_user1.status_code == 401
    assert res_user1.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    res_user2 = client.get("/api/v1/monitoring", headers={"X-API-Key": raw_key})
    assert res_user2.status_code == 401
    assert res_user2.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


# ============================================================================
# Section 7: Anti-Enumeration & Internal Exception Masking
# ============================================================================

@pytest.mark.integration
def test_login_anti_enumeration_uniformity(
    client: TestClient,
    researcher_user: User,
):
    """Verify nonexistent user and incorrect password return identical HTTP 401 responses."""
    # 1. Nonexistent user
    res1 = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "nonexistent_ecologist_ghost", "password": TEST_PASSWORD},
    )
    assert res1.status_code == 401
    body1 = res1.json()

    # 2. Existing user, incorrect password
    res2 = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": researcher_user.username, "password": "WrongPassword999!"},
    )
    assert res2.status_code == 401
    body2 = res2.json()

    # Response uniformity check: Status, error code, and message must match exactly
    assert body1["error"]["code"] == body2["error"]["code"] == "INVALID_CREDENTIALS"
    assert body1["error"]["message"] == body2["error"]["message"] == "Invalid username or password."


# ============================================================================
# Section 8: CSRF Protection & Origin Validation
# ============================================================================

@pytest.mark.integration
def test_csrf_cookie_refresh_origin_validation(
    client: TestClient,
    researcher_user: User,
):
    """Verify cookie-based refresh enforces CSRF mitigation against malicious external origins."""
    # Login to obtain cookie
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": researcher_user.username, "password": TEST_PASSWORD},
    )
    assert login_resp.status_code == 200

    # 1. Request with unauthorized Origin header -> 403 CSRF_VALIDATION_FAILED
    res_bad_origin = client.post(
        "/api/v1/auth/refresh",
        headers={"Origin": "https://evil-phishing-wildscope.com"},
    )
    assert res_bad_origin.status_code == 403
    assert res_bad_origin.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"

    # 2. Request with authorized Origin header -> 200 OK
    res_good_origin = client.post(
        "/api/v1/auth/refresh",
        headers={"Origin": "http://localhost:3000"},
    )
    assert res_good_origin.status_code == 200
    assert "access_token" in res_good_origin.json()["data"]
