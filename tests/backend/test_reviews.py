"""Tests for Human Review, Prediction Immutability, and Auditability (F20).

Tests:
1. POST /api/v1/reviews confirms prediction, increments monotonic dataset_revision.
2. POST /api/v1/reviews corrects taxon, preserves raw prediction, records corrected_taxon_id.
3. Stale expected_revision is rejected with HTTP 409 Conflict without state mutation.
4. Nonexistent detection ID returns HTTP 404 EntityNotFound.
5. Invalid payloads (blank reason, missing corrected taxon, invalid revision) return HTTP 422.
6. Scientific immutability: Directly mutating raw Detection fields raises ValidationException.
7. Append-only audit integrity: Directly updating or deleting ReviewEvent raises ValidationException.
8. Deleting a Detection with ReviewEvents is restricted (ON DELETE RESTRICT).
9. Encounter review status aggregation (pending -> partially_reviewed -> reviewed).
10. GET /api/v1/reviews/{id} retrieves complete chronological audit trail.
"""
from datetime import datetime, timezone
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.backend.core.exceptions import ValidationException
from src.backend.models import (
    Camera,
    Detection,
    Encounter,
    ImageFrame,
    MediaAsset,
    PredictionRun,
    ReviewEvent,
)
from src.backend.models.review import DatasetRevision
from tests.backend.conftest import create_test_user


def _create_detection_fixture(
    db_session: Session,
    detection_id: str = "DET-F20-01",
    camera_id: str = "CAM-F20-01",
    raw_label: str = "tiger 0.91",
    score: float = 0.91,
    encounter_id: str = None,
) -> Detection:
    """Helper fixture to insert valid camera, media, frame, run, and detection."""
    # Camera
    cam = db_session.query(Camera).filter_by(id=camera_id).first()
    if not cam:
        cam = Camera(id=camera_id, label="Ridge Camera", timezone="UTC", provenance="observed")
        db_session.add(cam)

    # Media Asset
    media = MediaAsset(
        id=f"MED-{detection_id}",
        type="image",
        camera_id=camera_id,
        storage_key=f"media/{detection_id}.jpg",
        content_hash=f"hash_{detection_id}",
        provenance="observed",
    )
    db_session.add(media)
    db_session.flush()

    # Image Frame
    frame = ImageFrame(
        id=f"FRM-{detection_id}",
        source_media_id=media.id,
        content_url=f"/api/v1/images/FRM-{detection_id}/content",
        quality_flags=[],
        provenance="observed",
    )
    db_session.add(frame)

    # Prediction Run
    run = db_session.query(PredictionRun).filter_by(id="RUN-F20").first()
    if not run:
        run = PredictionRun(
            id="RUN-F20",
            model_name="MegaDetector",
            model_version="v5a",
            device="cpu",
            status="completed",
        )
        db_session.add(run)
        db_session.flush()

    # Detection
    detection = Detection(
        id=detection_id,
        image_id=frame.id,
        run_id=run.id,
        encounter_id=encounter_id,
        bbox_x=0.1,
        bbox_y=0.2,
        bbox_w=0.3,
        bbox_h=0.4,
        raw_label=raw_label,
        taxon_id="panthera_tigris",
        label="Tiger",
        score=score,
        model_version=run.model_version,
        review_status="pending",
        provenance="inferred",
    )
    db_session.add(detection)
    db_session.commit()
    return detection


@pytest.mark.integration
def test_submit_review_confirmed(auth_client_factory, db_session: Session):
    """Verify confirming a detection creates ReviewEvent, increments revision, preserves raw prediction."""
    det = _create_detection_fixture(db_session, detection_id="DET-CONFIRM-01")

    # Authenticate as the designated reviewer
    reviewer = create_test_user(db_session, role="researcher", username="field_biologist_1", user_id="field_biologist_1")
    rev_client = auth_client_factory(reviewer)

    payload = {
        "detection_id": det.id,
        "decision": "confirmed",
        "reason": "Clear visible lateral stripe pattern of Panthera tigris.",
        "reviewer_id": "field_biologist_1",
        "expected_revision": 1,
        "provenance": "observed",
    }

    response = rev_client.post("/api/v1/reviews", json=payload)
    assert response.status_code == 201

    body = response.json()
    assert body["meta"]["dataset_revision"] == 2
    data = body["data"]
    assert data["decision"] == "confirmed"
    assert data["reviewer_id"] == "field_biologist_1"
    assert data["expected_revision"] == 1
    assert data["resulting_revision"] == 2
    assert data["provenance"] == "observed"

    # Database verification
    db_session.expire_all()
    updated_det = db_session.query(Detection).filter_by(id="DET-CONFIRM-01").first()
    assert updated_det.review_status == "confirmed"
    assert updated_det.raw_label == "tiger 0.91"
    assert updated_det.score == 0.91
    assert updated_det.bbox_x == 0.1

    # Revision record
    rev = db_session.query(DatasetRevision).filter_by(id=1).first()
    assert rev.current_revision == 2


@pytest.mark.integration
def test_submit_review_corrected(auth_client_factory, db_session: Session):
    """Verify correcting taxon persists corrected_taxon_id without modifying raw prediction."""
    det = _create_detection_fixture(db_session, detection_id="DET-CORRECT-01")

    # Authenticate as the designated taxonomist
    taxonomist = create_test_user(db_session, role="researcher", username="taxonomist_02", user_id="taxonomist_02")
    rev_client = auth_client_factory(taxonomist)

    payload = {
        "detection_id": det.id,
        "decision": "corrected",
        "corrected_taxon_id": "panthera_pardus",
        "reason": "Rosette coat patterns confirm Indian Leopard rather than Tiger.",
        "reviewer_id": "taxonomist_02",
        "expected_revision": 1,
    }

    response = rev_client.post("/api/v1/reviews", json=payload)
    assert response.status_code == 201

    body = response.json()
    assert body["meta"]["dataset_revision"] == 2
    assert body["data"]["corrected_taxon_id"] == "panthera_pardus"

    # Verify detection review_status changed to 'corrected', but raw prediction fields remain untouched
    db_session.expire_all()
    det_check = db_session.query(Detection).filter_by(id="DET-CORRECT-01").first()
    assert det_check.review_status == "corrected"
    assert det_check.taxon_id == "panthera_tigris"  # Raw inferred prediction preserved!
    assert det_check.raw_label == "tiger 0.91"


@pytest.mark.integration
def test_stale_expected_revision_conflict(researcher_client: TestClient, db_session: Session):
    """Verify submitting with stale expected_revision returns HTTP 409 and aborts mutation."""
    det = _create_detection_fixture(db_session, detection_id="DET-STALE-01")

    # Current revision is 1, client sends expected_revision=5
    payload = {
        "detection_id": det.id,
        "decision": "confirmed",
        "reason": "Valid tiger observation",
        "reviewer_id": "ranger_01",
        "expected_revision": 5,
    }

    response = researcher_client.post("/api/v1/reviews", json=payload)
    assert response.status_code == 409

    err = response.json()["error"]
    assert err["code"] == "STALE_REVISION_CONFLICT"
    assert err["details"]["current_revision"] == 1
    assert err["details"]["expected_revision"] == 5

    # Verify no mutation occurred
    db_session.expire_all()
    det_check = db_session.query(Detection).filter_by(id="DET-STALE-01").first()
    assert det_check.review_status == "pending"
    assert len(det_check.review_events) == 0
    rev = db_session.query(DatasetRevision).filter_by(id=1).first()
    assert rev.current_revision == 1


@pytest.mark.integration
def test_review_nonexistent_detection(researcher_client: TestClient):
    """Verify attempting to review a missing detection returns HTTP 404."""
    payload = {
        "detection_id": "nonexistent-det-id",
        "decision": "confirmed",
        "reason": "Testing 404 error",
        "reviewer_id": "tester",
        "expected_revision": 1,
    }
    response = researcher_client.post("/api/v1/reviews", json=payload)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DETECTION_NOT_FOUND"


@pytest.mark.integration
def test_review_validation_rules(researcher_client: TestClient, db_session: Session):
    """Verify semantic domain validations return HTTP 422 with JSON-safe error details."""
    det = _create_detection_fixture(db_session, detection_id="DET-VAL-01")

    # 1. Blank reason (ensures custom ValueError in ctx is JSON-serialized without HTTP 500)
    resp = researcher_client.post("/api/v1/reviews", json={
        "detection_id": det.id,
        "decision": "confirmed",
        "reason": "   ",
        "reviewer_id": "tester",
        "expected_revision": 1,
    })
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert "details" in data["error"]
    assert "errors" in data["error"]["details"]
    assert len(data["error"]["details"]["errors"]) > 0

    # 2. Corrected decision without corrected_taxon_id
    resp = researcher_client.post("/api/v1/reviews", json={
        "detection_id": det.id,
        "decision": "corrected",
        "corrected_taxon_id": None,
        "reason": "Correction reason",
        "reviewer_id": "tester",
        "expected_revision": 1,
    })
    assert resp.status_code == 422

    # 3. Decision submitted as 'pending'
    resp = researcher_client.post("/api/v1/reviews", json={
        "detection_id": det.id,
        "decision": "pending",
        "reason": "Cannot decide yet",
        "reviewer_id": "tester",
        "expected_revision": 1,
    })
    assert resp.status_code == 422

    # 4. Invalid expected_revision
    resp = researcher_client.post("/api/v1/reviews", json={
        "detection_id": det.id,
        "decision": "confirmed",
        "reason": "Valid reason",
        "reviewer_id": "tester",
        "expected_revision": 0,
    })
    assert resp.status_code == 422


@pytest.mark.unit
def test_validation_error_json_serialization(researcher_client: TestClient):
    """Regression test: Ensure custom Pydantic ValueError in ctx is JSON-serializable (HTTP 422, not 500)."""
    resp = researcher_client.post("/api/v1/reviews", json={
        "detection_id": "test-det",
        "decision": "confirmed",
        "reason": "   ",
        "reviewer_id": "tester",
        "expected_revision": 1,
    })
    assert resp.status_code == 422
    payload = resp.json()
    assert payload["error"]["code"] == "REQUEST_VALIDATION_FAILED"
    errors = payload["error"]["details"]["errors"]
    assert isinstance(errors, list)
    assert len(errors) > 0


@pytest.mark.integration
def test_raw_prediction_immutability_enforced(db_session: Session):
    """Verify that ORM before_update listener strictly prevents modifying raw prediction fields."""
    det = _create_detection_fixture(db_session, detection_id="DET-IMMUTABLE-01")

    # Attempt to tamper with raw_label
    det.raw_label = "tampered_tiger 0.99"
    with pytest.raises(ValidationException) as exc_info:
        db_session.commit()
    assert "Raw model prediction fields are scientifically immutable" in str(exc_info.value)
    db_session.rollback()

    # Attempt to tamper with confidence score
    det = db_session.query(Detection).filter_by(id="DET-IMMUTABLE-01").first()
    det.score = 0.999
    with pytest.raises(ValidationException) as exc_info:
        db_session.commit()
    assert "score" in str(exc_info.value)
    db_session.rollback()

    # Attempt to tamper with bounding box
    det = db_session.query(Detection).filter_by(id="DET-IMMUTABLE-01").first()
    det.bbox_x = 0.55
    with pytest.raises(ValidationException) as exc_info:
        db_session.commit()
    assert "bbox_x" in str(exc_info.value)
    db_session.rollback()

    # Permitted change: review_status
    det = db_session.query(Detection).filter_by(id="DET-IMMUTABLE-01").first()
    det.review_status = "confirmed"
    db_session.commit()
    assert det.review_status == "confirmed"


@pytest.mark.integration
def test_review_event_append_only_and_restrict(db_session: Session):
    """Verify ReviewEvent records cannot be edited or deleted, and protect detection deletion."""
    from sqlalchemy import text

    # Explicitly verify SQLite foreign key enforcement is active
    fk_check = db_session.execute(text("PRAGMA foreign_keys;")).scalar()
    assert fk_check == 1, "SQLite foreign key pragma must be active"

    det = _create_detection_fixture(db_session, detection_id="DET-AUDIT-01")

    review = ReviewEvent(
        id="REV-AUDIT-01",
        detection_id=det.id,
        decision="confirmed",
        reason="Initial expert signoff",
        reviewer_id="expert_audit",
        expected_revision=1,
        resulting_revision=2,
        provenance="observed",
    )
    db_session.add(review)
    db_session.commit()

    # 1. Attempt to update ReviewEvent: blocked by before_update listener
    review.reason = "Altered after the fact"
    with pytest.raises(ValidationException) as exc_info:
        db_session.commit()
    assert "ReviewEvent records are append-only audit logs" in str(exc_info.value)
    db_session.rollback()

    # 2. Attempt to delete ReviewEvent directly: blocked by before_delete listener
    review = db_session.query(ReviewEvent).filter_by(id="REV-AUDIT-01").first()
    db_session.delete(review)
    with pytest.raises(ValidationException) as exc_info:
        db_session.commit()
    assert "ReviewEvent records are permanent audit evidence" in str(exc_info.value)
    db_session.rollback()

    # 3. Attempt to delete Detection while referenced by ReviewEvent:
    # Foreign key ON DELETE RESTRICT enforced by database raises IntegrityError
    det = db_session.query(Detection).filter_by(id="DET-AUDIT-01").first()
    db_session.delete(det)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # 4. Verify review history and detection remain completely intact
    det_persisted = db_session.query(Detection).filter_by(id="DET-AUDIT-01").first()
    assert det_persisted is not None
    review_persisted = db_session.query(ReviewEvent).filter_by(id="REV-AUDIT-01").first()
    assert review_persisted is not None
    assert review_persisted.reason == "Initial expert signoff"


@pytest.mark.integration
def test_encounter_review_status_aggregation(researcher_client: TestClient, db_session: Session):
    """Verify encounter review status aggregation: pending -> partially_reviewed -> reviewed."""
    # 1. Setup Camera and Encounter
    cam = Camera(id="CAM-ENC-01", label="Waterhole Encounter", timezone="UTC", provenance="observed")
    db_session.add(cam)
    encounter = Encounter(
        id="ENC-AGG-01",
        camera_id="CAM-ENC-01",
        grouping_rule_version="timegap_60s_v1",
        review_status="pending",
        provenance="inferred",
    )
    db_session.add(encounter)
    db_session.commit()

    # 2. Add two detections to encounter
    det1 = _create_detection_fixture(db_session, detection_id="DET-ENC-1", encounter_id="ENC-AGG-01")
    det2 = _create_detection_fixture(db_session, detection_id="DET-ENC-2", encounter_id="ENC-AGG-01")

    # Initial state: Both pending -> encounter is pending
    resp = researcher_client.get(f"/api/v1/encounters/{encounter.id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["review_status"] == "pending"

    # Review first detection -> encounter transitions to partially_reviewed
    rev_resp1 = researcher_client.post("/api/v1/reviews", json={
        "detection_id": det1.id,
        "decision": "confirmed",
        "reason": "First animal confirmed",
        "reviewer_id": "biologist",
        "expected_revision": 1,
    })
    assert rev_resp1.status_code == 201

    resp = researcher_client.get(f"/api/v1/encounters/{encounter.id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["review_status"] == "partially_reviewed"

    # Review second detection -> encounter transitions to reviewed
    rev_resp2 = researcher_client.post("/api/v1/reviews", json={
        "detection_id": det2.id,
        "decision": "corrected",
        "corrected_taxon_id": "panthera_pardus",
        "reason": "Second animal corrected to leopard",
        "reviewer_id": "biologist",
        "expected_revision": 2,
    })
    assert rev_resp2.status_code == 201

    resp = researcher_client.get(f"/api/v1/encounters/{encounter.id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["review_status"] == "reviewed"


@pytest.mark.integration
def test_review_history_retrieval(auth_client_factory, db_session: Session):
    """Verify GET /api/v1/reviews/{detection_id} returns chronological audit history."""
    det = _create_detection_fixture(db_session, detection_id="DET-HIST-01")

    # Create distinct reviewers
    junior = create_test_user(db_session, role="researcher", username="junior_reviewer", user_id="junior_reviewer")
    senior = create_test_user(db_session, role="researcher", username="senior_reviewer", user_id="senior_reviewer")
    junior_client = auth_client_factory(junior)
    senior_client = auth_client_factory(senior)

    # First review: deferred
    junior_client.post("/api/v1/reviews", json={
        "detection_id": det.id,
        "decision": "deferred",
        "reason": "Needs senior biologist second opinion due to night IR glare",
        "reviewer_id": "junior_reviewer",
        "expected_revision": 1,
    })

    # Second review: confirmed
    senior_client.post("/api/v1/reviews", json={
        "detection_id": det.id,
        "decision": "confirmed",
        "reason": "Confirmed as adult male tiger after enhancement",
        "reviewer_id": "senior_reviewer",
        "expected_revision": 2,
    })

    # Retrieve history
    resp = junior_client.get(f"/api/v1/reviews/{det.id}")
    assert resp.status_code == 200
    history = resp.json()["data"]
    assert len(history) == 2
    assert history[0]["decision"] == "deferred"
    assert history[0]["reviewer_id"] == "junior_reviewer"
    assert history[1]["decision"] == "confirmed"
    assert history[1]["reviewer_id"] == "senior_reviewer"
