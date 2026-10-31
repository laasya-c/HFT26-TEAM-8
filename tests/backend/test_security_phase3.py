"""Security Phase 3 Regression Test Suite: Business API Protection & RBAC.

Verifies:
1. Public Endpoint Exemption:
   - GET /api/v1/health is strictly public without credentials.
2. Unauthenticated 401 Rejections:
   - All protected endpoints reject requests lacking credentials with HTTP 401 (AUTHENTICATION_REQUIRED).
3. Role-Based Access Control (403 Forbidden):
   - Viewer role cannot create uploads, submit reviews, register cameras, or log monitoring actions.
   - Researcher role cannot register cameras (Admin-only).
4. Resource Ownership & IDOR Protection:
   - Researchers can only access jobs they initiated; accessing other users' jobs returns HTTP 403.
   - Administrators possess global oversight across all processing jobs.
5. Reviewer Identity Spoofing Protection (F20 Invariant):
   - Client-supplied reviewer_id in POST /reviews is ignored and stamped from authenticated user token.
6. Wildlife Spatial Data Protection & Coordinate Obfuscation:
   - Public Viewers receive redacted/null coordinates with coordinates_obfuscated: True.
   - Verified Researchers and Admins receive full-precision geographic coordinates.
7. Field-Device Station Isolation & API Key Scoping:
   - Devices authenticate via X-API-Key against hashed records.
   - Station isolation enforced: key for CAM-01 rejected with HTTP 403 on CAM-02.
   - Revoked, inactive, or expired device keys rejected with HTTP 401.
   - Field device keys rejected on human user endpoints.
8. Monitoring Action User Attribution:
   - POST /monitoring-actions stamps created_by_user_id from the authenticated caller.
"""
from datetime import datetime, timedelta, timezone
import io
import uuid
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from contracts.schemas import ProvenanceEnum, ReviewStatusEnum
from src.backend.config import settings
from src.backend.core.security import (
    create_access_token,
    generate_api_key,
    hash_password,
    hash_refresh_token,
)
from src.backend.models import (
    ApiKey,
    Camera,
    Detection,
    Encounter,
    ImageFrame,
    MediaAsset,
    MonitoringAction,
    PredictionRun,
    ProcessingJob,
    ReviewEvent,
    User,
    UserRole,
)
from src.backend.models.job import JobStatus

TEST_PASSWORD = "StrongPassword123!"
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb" + b"\x00" * 50


# ============================================================================
# Fixtures for Users with RBAC Roles
# ============================================================================

@pytest.fixture
def admin_user(db_session: Session) -> User:
    """Administrator persona fixture."""
    user = User(
        id=str(uuid.uuid4()),
        username="admin_sarah",
        email="admin_sarah@wildscope.org",
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Sarah Administrator",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def researcher_user(db_session: Session) -> User:
    """Primary researcher persona fixture."""
    user = User(
        id=str(uuid.uuid4()),
        username="researcher_elena",
        email="elena@wildscope.org",
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Elena Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def second_researcher_user(db_session: Session) -> User:
    """Secondary researcher persona fixture for IDOR validation."""
    user = User(
        id=str(uuid.uuid4()),
        username="researcher_marcus",
        email="marcus@wildscope.org",
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Marcus Researcher",
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
        username="viewer_leo",
        email="leo@wildscope.org",
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Leo Viewer",
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
# 1. Public Endpoint Exemption (GET /health)
# ============================================================================

@pytest.mark.integration
def test_health_endpoint_is_public(client: TestClient):
    """Verify GET /api/v1/health is accessible without authentication credentials."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "status" in data
    assert "version" in data


# ============================================================================
# 2. Unauthenticated Access Rejections (HTTP 401)
# ============================================================================

@pytest.mark.integration
@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/api/v1/cameras", None),
        ("post", "/api/v1/cameras", {"id": "CAM-TEST", "label": "Test", "provenance": "observed"}),
        ("get", "/api/v1/cameras/CAM-TEST", None),
        ("get", "/api/v1/cameras/CAM-TEST/telemetry", None),
        ("post", "/api/v1/cameras/CAM-TEST/telemetry", {"observed_at": "2026-10-31T00:00:00Z", "battery_level": 95.0}),
        ("get", "/api/v1/observations", None),
        ("get", "/api/v1/encounters/ENC-TEST", None),
        ("post", "/api/v1/reviews", {"detection_id": "DET-1", "decision": "confirmed", "reason": "Verified", "reviewer_id": "someone", "expected_revision": 1}),
        ("get", "/api/v1/reviews/DET-TEST", None),
        ("get", "/api/v1/jobs/JOB-TEST", None),
        ("get", "/api/v1/images/IMG-TEST/content", None),
        ("get", "/api/v1/monitoring", None),
        ("get", "/api/v1/monitoring-actions", None),
        ("post", "/api/v1/monitoring-actions", {"camera_id": "CAM-TEST", "action_type": "lens_cleaning", "description": "clean", "performed_at": "2026-10-31T00:00:00Z"}),
        ("get", "/api/v1/monitoring-actions/ACT-TEST", None),
        ("get", "/api/v1/monitoring-actions/ACT-TEST/feedback", None),
    ],
)
def test_unauthenticated_requests_return_401(client: TestClient, method: str, path: str, body: dict):
    """Verify that every protected endpoint returns HTTP 401 when no token is provided."""
    if method == "get":
        resp = client.get(path)
    elif method == "post":
        resp = client.post(path, json=body)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.integration
def test_unauthenticated_upload_returns_401(client: TestClient):
    """Verify POST /api/v1/uploads returns 401 when unauthenticated."""
    files = [("files", ("test.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
    resp = client.post("/api/v1/uploads", files=files)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


# ============================================================================
# 3. Role-Based Access Control (HTTP 403 Forbidden)
# ============================================================================

@pytest.mark.integration
def test_viewer_cannot_upload_media(client: TestClient, viewer_user: User):
    """Verify Viewer receives 403 Forbidden on POST /api/v1/uploads."""
    files = [("files", ("test.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
    resp = client.post("/api/v1/uploads", files=files, headers=auth_headers(viewer_user))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


@pytest.mark.integration
def test_viewer_cannot_submit_review(client: TestClient, viewer_user: User):
    """Verify Viewer receives 403 Forbidden on POST /api/v1/reviews."""
    payload = {
        "detection_id": "DET-001",
        "decision": "confirmed",
        "reason": "Viewer attempting review",
        "reviewer_id": "viewer_attempt",
        "expected_revision": 1,
    }
    resp = client.post("/api/v1/reviews", json=payload, headers=auth_headers(viewer_user))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


@pytest.mark.integration
def test_viewer_cannot_register_camera(client: TestClient, viewer_user: User):
    """Verify Viewer receives 403 Forbidden on POST /api/v1/cameras."""
    payload = {
        "id": "CAM-VIEWER-TEST",
        "label": "Viewer Station",
        "provenance": "observed",
    }
    resp = client.post("/api/v1/cameras", json=payload, headers=auth_headers(viewer_user))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


@pytest.mark.integration
def test_researcher_cannot_register_camera(client: TestClient, researcher_user: User):
    """Verify Researcher receives 403 Forbidden on POST /api/v1/cameras (Admin only)."""
    payload = {
        "id": "CAM-RESEARCH-TEST",
        "label": "Research Station",
        "provenance": "observed",
    }
    resp = client.post("/api/v1/cameras", json=payload, headers=auth_headers(researcher_user))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


@pytest.mark.integration
def test_admin_can_register_camera(client: TestClient, admin_user: User):
    """Verify Administrator successfully creates a camera station on POST /api/v1/cameras."""
    payload = {
        "id": "CAM-ADMIN-01",
        "label": "Admin Station",
        "timezone": "UTC",
        "coordinates": [-120.5, 38.5],
        "provenance": "observed",
    }
    resp = client.post("/api/v1/cameras", json=payload, headers=auth_headers(admin_user))
    assert resp.status_code == 201
    assert resp.json()["data"]["id"] == "CAM-ADMIN-01"


@pytest.mark.integration
def test_viewer_cannot_create_monitoring_action(client: TestClient, viewer_user: User, db_session: Session):
    """Verify Viewer receives 403 Forbidden on POST /api/v1/monitoring-actions."""
    cam = Camera(id="CAM-M1", label="Station M1", timezone="UTC", provenance="observed")
    db_session.add(cam)
    db_session.commit()

    payload = {
        "camera_id": "CAM-M1",
        "action_type": "lens_cleaning",
        "description": "Cleaned optical glass",
        "performed_at": "2026-10-31T06:00:00Z",
    }
    resp = client.post("/api/v1/monitoring-actions", json=payload, headers=auth_headers(viewer_user))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


# ============================================================================
# 4. Resource Ownership & IDOR Protection (Processing Jobs)
# ============================================================================

@pytest.mark.integration
def test_researcher_cannot_access_other_researcher_job(
    client: TestClient,
    researcher_user: User,
    second_researcher_user: User,
    db_session: Session,
):
    """Verify IDOR prevention: Researcher B cannot inspect Researcher A's job (HTTP 403)."""
    job_a = ProcessingJob(
        id="job_owner_elena",
        upload_id="up_elena",
        status=JobStatus.QUEUED.value,
        progress=0.0,
        total_items=1,
        processed_items=0,
        media_ids=[],
        created_by_user_id=researcher_user.id,
    )
    db_session.add(job_a)
    db_session.commit()

    # Researcher B attempts to access Researcher A's job -> Must be rejected with 403
    resp = client.get(f"/api/v1/jobs/{job_a.id}", headers=auth_headers(second_researcher_user))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    # Researcher A accesses their own job -> 200 OK
    resp_owner = client.get(f"/api/v1/jobs/{job_a.id}", headers=auth_headers(researcher_user))
    assert resp_owner.status_code == 200
    assert resp_owner.json()["data"]["id"] == job_a.id


@pytest.mark.integration
def test_admin_can_access_any_researcher_job(
    client: TestClient,
    admin_user: User,
    researcher_user: User,
    db_session: Session,
):
    """Verify Administrator possesses oversight and can inspect any researcher's job."""
    job = ProcessingJob(
        id="job_owner_elena_2",
        upload_id="up_elena_2",
        status=JobStatus.QUEUED.value,
        progress=0.0,
        total_items=1,
        processed_items=0,
        media_ids=[],
        created_by_user_id=researcher_user.id,
    )
    db_session.add(job)
    db_session.commit()

    resp = client.get(f"/api/v1/jobs/{job.id}", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == job.id


# ============================================================================
# 5. Reviewer Identity Anti-Spoofing (F20 Invariant)
# ============================================================================

@pytest.mark.integration
def test_reviewer_identity_cannot_be_spoofed(
    client: TestClient,
    researcher_user: User,
    db_session: Session,
):
    """Verify POST /api/v1/reviews overrides client-supplied reviewer_id with authenticated user ID."""
    # Setup test detection
    cam = Camera(id="CAM-REV", label="Review Cam", timezone="UTC", provenance="observed")
    db_session.add(cam)
    db_session.flush()

    med = MediaAsset(id="MED-REV", type="image", camera_id=cam.id, storage_key="media/r.jpg", content_hash="hash_r", provenance="observed")
    db_session.add(med)
    db_session.flush()

    frame = ImageFrame(id="FRM-REV", source_media_id=med.id, content_url="/api/v1/images/FRM-REV/content", provenance="observed")
    db_session.add(frame)
    db_session.flush()

    run = PredictionRun(
        id="RUN-REV-01",
        model_name="wildscope-vision-v2",
        model_version="v2.1",
        device="cpu",
        status="completed",
    )
    db_session.add(run)
    db_session.flush()

    det = Detection(
        id="DET-REV-01",
        image_id=frame.id,
        run_id=run.id,
        bbox_x=0.1, bbox_y=0.1, bbox_w=0.4, bbox_h=0.4,
        raw_label="tiger",
        taxon_id="panthera_tigris",
        label="Bengal Tiger",
        score=0.92,
        model_version="v2.1",
        review_status=ReviewStatusEnum.PENDING.value,
        provenance="model_inferred",
    )
    db_session.add(det)
    db_session.commit()

    # Client attempts to spoof reviewer identity
    payload = {
        "detection_id": det.id,
        "decision": "confirmed",
        "reason": "Expert confirmed species identification as Bengal Tiger",
        "reviewer_id": "malicious_spoofed_identity_666",
        "expected_revision": 1,
    }

    resp = client.post("/api/v1/reviews", json=payload, headers=auth_headers(researcher_user))
    assert resp.status_code == 201

    # Response reviewer_id must match authenticated researcher, NOT the spoofed string
    data = resp.json()["data"]
    assert data["reviewer_id"] == researcher_user.id
    assert data["reviewer_id"] != "malicious_spoofed_identity_666"

    # Database event must also record researcher_user.id
    db_session.expire_all()
    event = db_session.query(ReviewEvent).filter_by(detection_id=det.id).first()
    assert event is not None
    assert event.reviewer_id == researcher_user.id


# ============================================================================
# 6. Wildlife Spatial Privacy & Coordinate Obfuscation
# ============================================================================

@pytest.mark.integration
def test_camera_coordinates_obfuscated_for_viewer(
    client: TestClient,
    viewer_user: User,
    researcher_user: User,
    db_session: Session,
):
    """Verify camera GPS coordinates are hidden from Viewers and preserved for Researchers."""
    cam = Camera(
        id="CAM-GPS-01",
        label="Rhino Corridor Station",
        timezone="UTC",
        latitude=26.58231,
        longitude=93.17452,
        provenance="observed",
    )
    db_session.add(cam)
    db_session.commit()

    # 1. Viewer list query -> coordinates are None and coordinates_obfuscated is True
    res_viewer = client.get("/api/v1/cameras", headers=auth_headers(viewer_user))
    assert res_viewer.status_code == 200
    cam_item_viewer = next(c for c in res_viewer.json()["data"] if c["id"] == "CAM-GPS-01")
    assert cam_item_viewer["coordinates"] is None
    assert cam_item_viewer["coordinates_obfuscated"] is True

    # 2. Researcher list query -> exact coordinates preserved
    res_researcher = client.get("/api/v1/cameras", headers=auth_headers(researcher_user))
    assert res_researcher.status_code == 200
    cam_item_res = next(c for c in res_researcher.json()["data"] if c["id"] == "CAM-GPS-01")
    assert cam_item_res["coordinates"] == [93.17452, 26.58231]
    assert cam_item_res["coordinates_obfuscated"] is False

    # 3. Viewer detail query -> coordinates None
    res_detail_viewer = client.get(f"/api/v1/cameras/{cam.id}", headers=auth_headers(viewer_user))
    assert res_detail_viewer.status_code == 200
    assert res_detail_viewer.json()["data"]["coordinates"] is None
    assert res_detail_viewer.json()["data"]["coordinates_obfuscated"] is True

    # 4. Researcher detail query -> exact coordinates
    res_detail_res = client.get(f"/api/v1/cameras/{cam.id}", headers=auth_headers(researcher_user))
    assert res_detail_res.status_code == 200
    assert res_detail_res.json()["data"]["coordinates"] == [93.17452, 26.58231]
    assert res_detail_res.json()["data"]["coordinates_obfuscated"] is False


@pytest.mark.integration
def test_observation_coordinates_obfuscated_for_viewer(
    client: TestClient,
    viewer_user: User,
    researcher_user: User,
    db_session: Session,
):
    """Verify wildlife observation spatial coordinates are obfuscated for Viewers."""
    cam = Camera(
        id="CAM-OBS-GEO",
        label="Tiger Habitat",
        timezone="UTC",
        latitude=27.1234,
        longitude=94.5678,
        provenance="observed",
    )
    db_session.add(cam)
    db_session.flush()

    med = MediaAsset(id="MED-OBS-GEO", type="image", camera_id=cam.id, storage_key="media/geo.jpg", content_hash="hash_geo", provenance="observed")
    db_session.add(med)
    db_session.flush()

    frame = ImageFrame(id="FRM-OBS-GEO", source_media_id=med.id, content_url="/api/v1/images/FRM-OBS-GEO/content", provenance="observed")
    db_session.add(frame)
    db_session.flush()

    run = PredictionRun(
        id="RUN-OBS-GEO",
        model_name="wildscope-vision-v2",
        model_version="v2.1",
        device="cpu",
        status="completed",
    )
    db_session.add(run)
    db_session.flush()

    det = Detection(
        id="DET-OBS-GEO",
        image_id=frame.id,
        run_id=run.id,
        bbox_x=0.2, bbox_y=0.2, bbox_w=0.3, bbox_h=0.3,
        raw_label="tiger",
        taxon_id="panthera_tigris",
        label="Bengal Tiger",
        score=0.96,
        model_version="v2.1",
        review_status=ReviewStatusEnum.PENDING.value,
        provenance="model_inferred",
    )
    db_session.add(det)
    db_session.commit()

    # Viewer -> coordinates None, obfuscated True
    res_viewer = client.get("/api/v1/observations", headers=auth_headers(viewer_user))
    assert res_viewer.status_code == 200
    det_viewer = next(d for d in res_viewer.json()["data"] if d["id"] == "DET-OBS-GEO")
    assert det_viewer["coordinates"] is None
    assert det_viewer["coordinates_obfuscated"] is True

    # Researcher -> exact coordinates
    res_researcher = client.get("/api/v1/observations", headers=auth_headers(researcher_user))
    assert res_researcher.status_code == 200
    det_res = next(d for d in res_researcher.json()["data"] if d["id"] == "DET-OBS-GEO")
    assert det_res["coordinates"] == [94.5678, 27.1234]
    assert det_res["coordinates_obfuscated"] is False


# ============================================================================
# 7. Field-Device Station Isolation & API Key Scoping
# ============================================================================

@pytest.mark.integration
def test_field_device_api_key_telemetry_submission(
    client: TestClient,
    db_session: Session,
):
    """Verify hardware station can submit telemetry using its dedicated API key."""
    cam = Camera(id="CAM-IOT-01", label="IoT Station 1", timezone="UTC", provenance="observed")
    db_session.add(cam)
    db_session.commit()

    raw_key, key_hash = generate_api_key(prefix="ws_live_")
    api_key_rec = ApiKey(
        id=str(uuid.uuid4()),
        name="CAM-IOT-01 Key",
        key_prefix="ws_live_",
        key_hash=key_hash,
        camera_id=cam.id,
        is_active=True,
    )
    db_session.add(api_key_rec)
    db_session.commit()

    payload = {
        "observed_at": "2026-10-31T07:00:00Z",
        "battery_level": 88.5,
        "signal_strength": -75,
        "source": "hardware_heartbeat",
    }

    # Submit with valid X-API-Key
    resp = client.post(
        f"/api/v1/cameras/{cam.id}/telemetry",
        json=payload,
        headers={"X-API-Key": raw_key},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["camera_id"] == cam.id

    # Verify last_used_at was updated in database
    db_session.expire_all()
    updated_key = db_session.query(ApiKey).filter_by(id=api_key_rec.id).first()
    assert updated_key.last_used_at is not None


@pytest.mark.integration
def test_field_device_station_isolation_violation_returns_403(
    client: TestClient,
    db_session: Session,
):
    """Verify station isolation: Key bound to CAM-IOT-01 cannot post telemetry to CAM-IOT-02 (HTTP 403)."""
    cam1 = Camera(id="CAM-IOT-01", label="IoT Station 1", timezone="UTC", provenance="observed")
    cam2 = Camera(id="CAM-IOT-02", label="IoT Station 2", timezone="UTC", provenance="observed")
    db_session.add_all([cam1, cam2])
    db_session.commit()

    # Generate key strictly registered for CAM-IOT-01
    raw_key, key_hash = generate_api_key(prefix="ws_live_")
    api_key_rec = ApiKey(
        id=str(uuid.uuid4()),
        name="Station 1 Key",
        key_prefix="ws_live_",
        key_hash=key_hash,
        camera_id=cam1.id,
        is_active=True,
    )
    db_session.add(api_key_rec)
    db_session.commit()

    payload = {
        "observed_at": "2026-10-31T07:00:00Z",
        "battery_level": 90.0,
    }

    # Attempt to post to Station 2 using Station 1's key -> 403 Forbidden
    resp = client.post(
        f"/api/v1/cameras/{cam2.id}/telemetry",
        json=payload,
        headers={"X-API-Key": raw_key},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "DEVICE_STATION_MISMATCH"


@pytest.mark.integration
def test_inactive_and_expired_api_keys_rejected(
    client: TestClient,
    db_session: Session,
):
    """Verify inactive and expired API keys return HTTP 401."""
    cam = Camera(id="CAM-IOT-KEYTEST", label="IoT Key Test", timezone="UTC", provenance="observed")
    db_session.add(cam)
    db_session.commit()

    # 1. Inactive key
    raw_k1, hash_k1 = generate_api_key()
    key_inactive = ApiKey(
        id=str(uuid.uuid4()),
        name="Inactive Key",
        key_hash=hash_k1,
        camera_id=cam.id,
        is_active=False,
    )
    # 2. Expired key
    raw_k2, hash_k2 = generate_api_key()
    key_expired = ApiKey(
        id=str(uuid.uuid4()),
        name="Expired Key",
        key_hash=hash_k2,
        camera_id=cam.id,
        is_active=True,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add_all([key_inactive, key_expired])
    db_session.commit()

    payload = {"observed_at": "2026-10-31T07:00:00Z", "battery_level": 50.0}

    # Test inactive key
    res_inact = client.post(f"/api/v1/cameras/{cam.id}/telemetry", json=payload, headers={"X-API-Key": raw_k1})
    assert res_inact.status_code == 401
    assert res_inact.json()["error"]["code"] == "INVALID_API_KEY"

    # Test expired key
    res_exp = client.post(f"/api/v1/cameras/{cam.id}/telemetry", json=payload, headers={"X-API-Key": raw_k2})
    assert res_exp.status_code == 401
    assert res_exp.json()["error"]["code"] == "INVALID_API_KEY"


@pytest.mark.integration
def test_device_api_key_rejected_on_user_endpoints(
    client: TestClient,
    db_session: Session,
):
    """Verify field-device API keys cannot be used to authenticate human user endpoints."""
    cam = Camera(id="CAM-IOT-SCOPE", label="IoT Scope", timezone="UTC", provenance="observed")
    db_session.add(cam)
    db_session.commit()

    raw_key, key_hash = generate_api_key()
    api_key_rec = ApiKey(
        id=str(uuid.uuid4()),
        name="Device Key",
        key_hash=key_hash,
        camera_id=cam.id,
        is_active=True,
    )
    db_session.add(api_key_rec)
    db_session.commit()

    # Pass API key header to /reviews -> Must be rejected with 401
    resp = client.post(
        "/api/v1/reviews",
        json={"detection_id": "DET-1", "decision": "confirmed", "reason": "Device review attempt", "reviewer_id": "device", "expected_revision": 1},
        headers={"X-API-Key": raw_key},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


# ============================================================================
# 8. Monitoring Action User Attribution
# ============================================================================

@pytest.mark.integration
def test_monitoring_action_stamps_created_by_user_id(
    client: TestClient,
    researcher_user: User,
    db_session: Session,
):
    """Verify POST /api/v1/monitoring-actions attributes created_by_user_id to authenticated user."""
    cam = Camera(id="CAM-MA-01", label="Station MA-01", timezone="UTC", provenance="observed")
    db_session.add(cam)
    db_session.commit()

    payload = {
        "camera_id": cam.id,
        "action_type": "battery_replacement",
        "description": "Replaced depleted solar battery",
        "performed_at": "2026-10-31T06:30:00Z",
    }

    resp = client.post(
        "/api/v1/monitoring-actions",
        json=payload,
        headers=auth_headers(researcher_user),
    )
    assert resp.status_code == 201
    action_id = resp.json()["data"]["id"]

    db_session.expire_all()
    action = db_session.query(MonitoringAction).filter_by(id=action_id).first()
    assert action is not None
    assert action.created_by_user_id == researcher_user.id
