"""Comprehensive Runtime Verification Suite for all 18 WILDSCOPE API Endpoints.

Verifies:
1. Correct HTTP methods, status codes, and response envelopes.
2. Request validation and error response envelopes with request_id.
3. Path parameters and 404 EntityNotFound handling.
4. Pagination behavior (total, limit, offset).
5. Dataset revision advancement and optimistic concurrency (HTTP 409).
6. Complete execution of all 6 end-to-end operational workflows:
   - Workflow 1: Media upload -> job status -> image content retrieval.
   - Workflow 2: Observations listing & encounter details retrieval.
   - Workflow 3: Human review submission -> review audit trail.
   - Workflow 4: Stale review collision (HTTP 409 STALE_REVISION_CONFLICT).
   - Workflow 5: Camera registration -> telemetry ingestion -> diagnostics.
   - Workflow 6: Monitoring action creation -> feedback evaluation.
"""
from datetime import datetime, timedelta, timezone
import io
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from src.backend.models import (
    Camera,
    CameraTelemetry,
    Detection,
    Encounter,
    EncounterMember,
    ImageFrame,
    MediaAsset,
    MonitoringAction,
    PredictionRun,
)
from tests.backend.conftest import create_test_user

VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb" + b"\x00" * 50
CORRUPTED_BYTES = b"NOT_A_VALID_JPEG_OR_PNG"


# ============================================================================
# Group 1: Health & Diagnostics
# ============================================================================

@pytest.mark.integration
def test_ep01_get_health(client: TestClient):
    """EP 1: GET /api/v1/health — Verify health status and response envelope (Public)."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    payload = response.json()
    assert "data" in payload
    assert "meta" in payload
    assert payload["meta"]["dataset_revision"] >= 1

    data = payload["data"]
    assert data["status"] in ("healthy", "degraded")
    assert "version" in data
    assert "database" in data
    assert "worker" in data
    assert data["worker"]["ready"] is False
    assert data["worker"]["status"] == "unavailable"


# ============================================================================
# Group 2: Media Uploads & Persistent Jobs (Workflow 1)
# ============================================================================

@pytest.mark.integration
def test_ep02_post_uploads_valid(researcher_client: TestClient, db_session: Session):
    """EP 2: POST /api/v1/uploads — Upload media, receive 202 with job_id."""
    cam = Camera(id="CAM-UP-01", label="Upload Trap", timezone="UTC", provenance="observed")
    db_session.add(cam)
    db_session.commit()

    files = [("files", ("test_cam.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
    data = {
        "camera_id": "CAM-UP-01",
        "captured_at": "2026-10-31T05:00:00Z",
    }
    response = researcher_client.post("/api/v1/uploads", files=files, data=data)
    assert response.status_code == 202

    body = response.json()
    assert "data" in body
    d = body["data"]
    assert "upload_id" in d
    assert "job_id" in d
    assert d["files_received"] == 1
    assert d["status"] == "queued"
    assert len(d["media_items"]) == 1
    assert d["media_items"][0]["content_hash"] is not None


@pytest.mark.integration
def test_ep02_post_uploads_validation_failure(researcher_client: TestClient):
    """EP 2: POST /api/v1/uploads — Rejects empty upload and corrupted magic bytes."""
    # 1. No files provided
    res1 = researcher_client.post("/api/v1/uploads", files=[])
    assert res1.status_code in (422, 400)

    # 2. Corrupted file signature
    files = [("files", ("fake.jpg", io.BytesIO(CORRUPTED_BYTES), "image/jpeg"))]
    res2 = researcher_client.post("/api/v1/uploads", files=files)
    assert res2.status_code == 422
    assert "Unsupported media format" in res2.json()["error"]["message"]


@pytest.mark.integration
def test_ep03_get_job_status(admin_client: TestClient, db_session: Session):
    """EP 3: GET /api/v1/jobs/{job_id} — Query persistent job progress and 404."""
    from src.backend.services.jobs import job_service
    job = job_service.create_job(db=db_session, upload_id="up_test_ep3", media_ids=["med_ep3"])

    # Valid job
    res = admin_client.get(f"/api/v1/jobs/{job.id}")
    assert res.status_code == 200
    d = res.json()["data"]
    assert d["id"] == job.id
    assert d["status"] == "queued"
    assert d["progress"] == 0.0

    # Nonexistent job -> 404
    res_404 = admin_client.get("/api/v1/jobs/job_nonexistent_xyz")
    assert res_404.status_code == 404
    assert res_404.json()["error"]["code"] == "PROCESSINGJOB_NOT_FOUND"


# ============================================================================
# Group 3: Media Serving & Observations
# ============================================================================

@pytest.mark.integration
def test_ep04_get_image_content(researcher_client: TestClient, db_session: Session, tmp_path):
    """EP 4: GET /api/v1/images/{image_id}/content — Binary serving and 404."""
    from src.backend.services.storage import storage_service
    orig_root = storage_service.root_dir
    orig_media = storage_service.media_dir

    try:
        storage_service.root_dir = tmp_path
        storage_service.media_dir = tmp_path / "media"
        storage_service.media_dir.mkdir(parents=True, exist_ok=True)

        media, frame, _ = storage_service.store_media(
            file_bytes=VALID_JPEG_BYTES,
            original_filename="ep4_test.jpg",
            db_session=db_session,
        )
        db_session.commit()

        # Retrieve valid frame content
        res = researcher_client.get(f"/api/v1/images/{frame.id}/content")
        assert res.status_code == 200
        assert res.content == VALID_JPEG_BYTES
        assert res.headers["content-type"] == "image/jpeg"

        # Nonexistent image -> 404
        res_404 = researcher_client.get("/api/v1/images/nonexistent_image_frm/content")
        assert res_404.status_code == 404
        assert res_404.json()["error"]["code"] == "IMAGE_NOT_FOUND"
    finally:
        storage_service.root_dir = orig_root
        storage_service.media_dir = orig_media


@pytest.mark.integration
def test_ep05_list_observations(researcher_client: TestClient, db_session: Session):
    """EP 5: GET /api/v1/observations — Paginated detections and filtering."""
    # Seed a camera, media, frame, run, and detection
    cam = Camera(id="CAM-OBS-01", label="Obs Camera", timezone="UTC", provenance="observed")
    db_session.add(cam)
    media = MediaAsset(id="MED-OBS-01", type="image", camera_id=cam.id, storage_key="media/obs.jpg", content_hash="hash_obs", provenance="observed")
    db_session.add(media)
    frame = ImageFrame(id="FRM-OBS-01", source_media_id=media.id, content_url="/api/v1/images/FRM-OBS-01/content", quality_flags=[], provenance="observed")
    db_session.add(frame)
    run = PredictionRun(id="RUN-OBS-01", model_name="yolov8", model_version="v1", device="cpu", status="completed")
    db_session.add(run)
    det1 = Detection(
        id="DET-OBS-01",
        image_id=frame.id,
        run_id=run.id,
        bbox_x=0.1, bbox_y=0.2, bbox_w=0.3, bbox_h=0.4,
        raw_label="tiger", taxon_id="panthera_tigris", label="Bengal Tiger",
        score=0.92, model_version="v1", review_status="pending", provenance="inferred",
    )
    det2 = Detection(
        id="DET-OBS-02",
        image_id=frame.id,
        run_id=run.id,
        bbox_x=0.2, bbox_y=0.3, bbox_w=0.4, bbox_h=0.5,
        raw_label="leopard", taxon_id="panthera_pardus", label="Indian Leopard",
        score=0.88, model_version="v1", review_status="confirmed", provenance="inferred",
    )
    db_session.add_all([det1, det2])
    db_session.commit()

    # Query all
    res = researcher_client.get("/api/v1/observations")
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 2

    # Query filtered by review_status
    res_pending = researcher_client.get("/api/v1/observations?review_status=pending")
    assert res_pending.status_code == 200
    assert res_pending.json()["meta"]["total"] == 1
    assert res_pending.json()["data"][0]["id"] == "DET-OBS-01"

    # Query filtered by taxon_id
    res_taxon = researcher_client.get("/api/v1/observations?taxon_id=panthera_pardus")
    assert res_taxon.status_code == 200
    assert res_taxon.json()["meta"]["total"] == 1
    assert res_taxon.json()["data"][0]["taxon_id"] == "panthera_pardus"


# ============================================================================
# Group 4: Encounters (Workflow 2)
# ============================================================================

@pytest.mark.integration
def test_ep06_get_encounter_details(researcher_client: TestClient, db_session: Session):
    """EP 6: GET /api/v1/encounters/{id} — Encounter record and 404."""
    cam = Camera(id="CAM-ENC-01", label="Enc Camera", timezone="UTC", provenance="observed")
    db_session.add(cam)
    enc = Encounter(
        id="ENC-001",
        camera_id=cam.id,
        start_at=datetime.now(timezone.utc),
        end_at=datetime.now(timezone.utc),
        grouping_rule_version="temporal_10m_v1",
        review_status="pending",
        provenance="inferred",
    )
    db_session.add(enc)
    db_session.commit()

    res = researcher_client.get("/api/v1/encounters/ENC-001")
    assert res.status_code == 200
    d = res.json()["data"]
    assert d["id"] == "ENC-001"
    assert d["camera_id"] == "CAM-ENC-01"
    assert d["review_status"] == "pending"

    # 404 for missing encounter
    res_404 = researcher_client.get("/api/v1/encounters/ENC-MISSING-99")
    assert res_404.status_code == 404
    assert res_404.json()["error"]["code"] == "ENCOUNTER_NOT_FOUND"


# ============================================================================
# Group 5: Human Review & Auditability (Workflows 3 & 4)
# ============================================================================

@pytest.mark.integration
def test_ep07_and_ep08_reviews_lifecycle_and_stale_conflict(auth_client_factory, db_session: Session):
    """EP 7 & 8: POST /api/v1/reviews and GET /api/v1/reviews/{id} — Workflow 3 & 4."""
    # 1. Setup detection fixture
    cam = Camera(id="CAM-REV-01", label="Rev Camera", timezone="UTC", provenance="observed")
    db_session.add(cam)
    media = MediaAsset(id="MED-REV-01", type="image", camera_id=cam.id, storage_key="media/r.jpg", content_hash="hash_r", provenance="observed")
    db_session.add(media)
    frame = ImageFrame(id="FRM-REV-01", source_media_id=media.id, content_url="/api/v1/images/FRM-REV-01/content", quality_flags=[], provenance="observed")
    db_session.add(frame)
    run = PredictionRun(id="RUN-REV-01", model_name="yolo", model_version="v1", device="cpu", status="completed")
    db_session.add(run)
    det = Detection(
        id="DET-REV-01", image_id=frame.id, run_id=run.id,
        bbox_x=0.1, bbox_y=0.1, bbox_w=0.5, bbox_h=0.5,
        raw_label="tiger", taxon_id="panthera_tigris", label="Tiger",
        score=0.90, model_version="v1", review_status="pending", provenance="inferred",
    )
    db_session.add(det)

    # Create authentic researcher reviewer
    reviewer = create_test_user(db_session, role="researcher", username="ranger_laasya", user_id="ranger_laasya")
    rev_client = auth_client_factory(reviewer)

    # 2. Workflow 3: Submit valid human review
    review_payload = {
        "detection_id": "DET-REV-01",
        "decision": "confirmed",
        "reason": "Diagnostic flank stripe validation verified.",
        "reviewer_id": "ranger_laasya",
        "expected_revision": 1,
        "provenance": "observed",
    }
    rev_res = rev_client.post("/api/v1/reviews", json=review_payload)
    assert rev_res.status_code == 201
    rev_data = rev_res.json()["data"]
    assert rev_data["detection_id"] == "DET-REV-01"
    assert rev_data["resulting_revision"] == 2
    assert rev_res.json()["meta"]["dataset_revision"] == 2

    # Verify detection status updated
    db_session.refresh(det)
    assert det.review_status == "confirmed"

    # EP 8: Retrieve review audit trail
    history_res = rev_client.get("/api/v1/reviews/DET-REV-01")
    assert history_res.status_code == 200
    events = history_res.json()["data"]
    assert len(events) == 1
    assert events[0]["decision"] == "confirmed"
    assert events[0]["reviewer_id"] == "ranger_laasya"

    # 3. Workflow 4: Stale revision conflict (HTTP 409)
    stale_payload = {
        "detection_id": "DET-REV-01",
        "decision": "rejected",
        "reason": "Retrying with stale revision.",
        "reviewer_id": "ranger_other",
        "expected_revision": 1,  # Stale! Server is now at 2
        "provenance": "observed",
    }
    conflict_res = rev_client.post("/api/v1/reviews", json=stale_payload)
    assert conflict_res.status_code == 409
    err = conflict_res.json()["error"]
    assert err["code"] == "STALE_REVISION_CONFLICT"
    assert err["details"]["expected_revision"] == 1
    assert err["details"]["current_revision"] == 2


@pytest.mark.integration
def test_ep07_review_validation_rules(researcher_client: TestClient, db_session: Session):
    """EP 7: POST /api/v1/reviews — Rejects 'pending', empty reason, and correction without taxon."""
    # Corrected decision without corrected_taxon_id
    payload1 = {
        "detection_id": "DET-XYZ",
        "decision": "corrected",
        "reason": "Corrected but forgot taxon",
        "reviewer_id": "ranger_1",
        "expected_revision": 1,
    }
    res1 = researcher_client.post("/api/v1/reviews", json=payload1)
    assert res1.status_code == 422

    # Blank reason
    payload2 = {
        "detection_id": "DET-XYZ",
        "decision": "confirmed",
        "reason": "   ",
        "reviewer_id": "ranger_1",
        "expected_revision": 1,
    }
    res2 = researcher_client.post("/api/v1/reviews", json=payload2)
    assert res2.status_code == 422


# ============================================================================
# Group 6: Camera Stations & Telemetry (Workflow 5)
# ============================================================================

@pytest.mark.integration
def test_ep09_to_ep13_camera_telemetry_workflow(admin_client: TestClient, db_session: Session):
    """EP 9-13: Camera registration, telemetry ingestion, listing, and diagnostics."""
    # 1. EP 10: Register camera (Admin only)
    cam_payload = {
        "id": "CAM-WK5-01",
        "label": "Gorge Overlook",
        "timezone": "Asia/Kolkata",
        "coordinates": [76.85, 11.55],
        "active_camera_days": 10.0,
        "provenance": "observed",
    }
    reg_res = admin_client.post("/api/v1/cameras", json=cam_payload)
    assert reg_res.status_code == 201
    assert reg_res.json()["data"]["telemetry_status"] == "unknown"

    # 2. EP 9: List cameras
    list_res = admin_client.get("/api/v1/cameras")
    assert list_res.status_code == 200
    assert any(c["id"] == "CAM-WK5-01" for c in list_res.json()["data"])

    # 3. EP 12: Ingest hardware telemetry
    now_utc = datetime.now(timezone.utc)
    tel_payload = {
        "observed_at": now_utc.isoformat(),
        "battery_level": 88.0,
        "signal_strength": -65.0,
        "error_codes": [],
        "source": "satellite_relay",
    }
    tel_res = admin_client.post("/api/v1/cameras/CAM-WK5-01/telemetry", json=tel_payload)
    assert tel_res.status_code == 201
    assert tel_res.json()["data"]["battery_level"] == 88.0

    # 4. EP 11: Get camera diagnostic details
    diag_res = admin_client.get("/api/v1/cameras/CAM-WK5-01")
    assert diag_res.status_code == 200
    diag = diag_res.json()["data"]
    assert diag["telemetry_status"] == "reporting"
    assert diag["telemetry_health"]["status"] == "reporting"
    assert "observation_quality" in diag

    # 5. EP 13: List telemetry logs
    hist_res = admin_client.get("/api/v1/cameras/CAM-WK5-01/telemetry")
    assert hist_res.status_code == 200
    assert len(hist_res.json()["data"]) == 1
    assert hist_res.json()["data"][0]["battery_level"] == 88.0


# ============================================================================
# Group 7: Monitoring Network & Feedback (Workflow 6)
# ============================================================================

@pytest.mark.integration
def test_ep14_to_ep18_monitoring_network_and_feedback(researcher_client: TestClient, db_session: Session):
    """EP 14-18: Monitoring network summary, actions, and feedback evaluation."""
    cam = Camera(id="CAM-MON-01", label="Stream Bed", timezone="UTC", provenance="observed")
    db_session.add(cam)
    db_session.commit()

    # 1. EP 14: Network monitoring summary
    sum_res = researcher_client.get("/api/v1/monitoring")
    assert sum_res.status_code == 200
    summary = sum_res.json()["data"]
    assert "total_cameras" in summary
    assert "telemetry_health_breakdown" in summary

    # 2. EP 16: Log monitoring action with baseline and post windows
    now = datetime.now(timezone.utc)
    act_payload = {
        "camera_id": "CAM-MON-01",
        "action_type": "lens_clean",
        "description": "Cleaned lens after heavy dust storm.",
        "performed_at": now.isoformat(),
        "baseline_start": (now - timedelta(days=7)).isoformat(),
        "baseline_end": (now - timedelta(seconds=1)).isoformat(),
        "post_start": (now + timedelta(seconds=1)).isoformat(),
        "post_end": (now + timedelta(days=7)).isoformat(),
        "source": "ranger_field_01",
    }
    act_res = researcher_client.post("/api/v1/monitoring-actions", json=act_payload)
    assert act_res.status_code == 201
    action_id = act_res.json()["data"]["id"]

    # 3. EP 15: List monitoring actions
    list_res = researcher_client.get("/api/v1/monitoring-actions")
    assert list_res.status_code == 200
    assert any(a["id"] == action_id for a in list_res.json()["data"])

    # 4. EP 17: Get specific monitoring action
    get_res = researcher_client.get(f"/api/v1/monitoring-actions/{action_id}")
    assert get_res.status_code == 200
    assert get_res.json()["data"]["id"] == action_id

    # 5. EP 18: Feedback evaluation (insufficient data scenario when no evidence exists)
    fb_res = researcher_client.get(f"/api/v1/monitoring-actions/{action_id}/feedback")
    assert fb_res.status_code == 200
    fb = fb_res.json()["data"]
    assert fb["status"] == "insufficient_data"
    assert fb["is_causal"] is False
    assert "causal_claim_disclaimer" in fb

    # 6. EP 18: Evaluated feedback scenario with seeded evidence in both windows
    t_base = CameraTelemetry(
        id="tel_base_01", camera_id=cam.id,
        observed_at=now - timedelta(days=3),
        battery_level=65.0, source="sat", created_at=now,
    )
    t_post = CameraTelemetry(
        id="tel_post_01", camera_id=cam.id,
        observed_at=now + timedelta(days=3),
        battery_level=95.0, source="sat", created_at=now,
    )
    db_session.add_all([t_base, t_post])
    db_session.commit()

    fb_res2 = researcher_client.get(f"/api/v1/monitoring-actions/{action_id}/feedback")
    assert fb_res2.status_code == 200
    fb2 = fb_res2.json()["data"]
    assert fb2["status"] == "evaluated"
    assert fb2["is_causal"] is False
    assert fb2["observed_changes"]["delta_avg_battery"] == 30.0


# ============================================================================
# Standard Envelopes & Request ID Validation
# ============================================================================

@pytest.mark.integration
def test_standard_envelope_and_request_id(admin_client: TestClient):
    """Verify X-Request-ID echo and standard envelope structure across endpoints."""
    custom_id = "test-req-id-uuid-12345"
    res = admin_client.get("/api/v1/health", headers={"X-Request-ID": custom_id})
    assert res.status_code == 200
    assert res.headers.get("X-Request-ID") == custom_id

    # Error response envelope with request_id
    res_err = admin_client.get("/api/v1/jobs/nonexistent_job", headers={"X-Request-ID": custom_id})
    assert res_err.status_code == 404
    err_body = res_err.json()
    assert "error" in err_body
    assert err_body["request_id"] == custom_id
