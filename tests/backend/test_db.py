"""Tests for Database Models and SQLAlchemy Persistence."""
from datetime import datetime, timezone
import pytest

try:
    from sqlalchemy.orm import Session
    from src.backend.models import (
        Camera,
        CameraTelemetry,
        Detection,
        Encounter,
        ImageFrame,
        MediaAsset,
        PredictionRun,
        ReviewEvent,
    )
    HAS_DB = True
except ImportError:
    HAS_DB = False


@pytest.mark.integration
def test_camera_and_telemetry_persistence(db_session: "Session"):
    """Verify persisting a Camera and linked CameraTelemetry records."""
    if not HAS_DB:
        pytest.skip("SQLAlchemy not installed")

    camera = Camera(
        id="CAM-DB-01",
        label="Waterhole 1",
        timezone="Asia/Kolkata",
        telemetry_status="unknown",
        provenance="observed",
    )
    db_session.add(camera)
    db_session.commit()

    retrieved = db_session.query(Camera).filter_by(id="CAM-DB-01").first()
    assert retrieved is not None
    assert retrieved.label == "Waterhole 1"
    assert retrieved.telemetry_status == "unknown"


@pytest.mark.integration
def test_immutable_detection_and_review_append(db_session: "Session"):
    """Verify that adding a ReviewEvent does not overwrite original Detection values."""
    if not HAS_DB:
        pytest.skip("SQLAlchemy not installed")

    # 1. Setup Camera
    cam = Camera(id="CAM-REV-01", label="Camp", provenance="observed")
    db_session.add(cam)

    # 2. Setup MediaAsset and ImageFrame
    media = MediaAsset(
        id="MED-01",
        type="image",
        camera_id="CAM-REV-01",
        storage_key="media/test.jpg",
        content_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        provenance="observed",
    )
    db_session.add(media)
    db_session.flush()

    frame = ImageFrame(
        id="FRM-01",
        source_media_id="MED-01",
        content_url="/api/v1/images/FRM-01/content",
        quality_flags=[],
        provenance="observed",
    )
    db_session.add(frame)

    # 3. Setup PredictionRun
    run = PredictionRun(
        id="RUN-01",
        model_name="MegaDetector",
        model_version="v5a",
        device="cpu",
    )
    db_session.add(run)
    db_session.flush()

    # 4. Setup Detection with original model label
    detection = Detection(
        id="DET-REV-01",
        image_id="FRM-01",
        run_id="RUN-01",
        bbox_x=0.1,
        bbox_y=0.2,
        bbox_w=0.3,
        bbox_h=0.4,
        raw_label="dog 0.72",
        label="Dog",
        score=0.72,
        model_version=run.model_version,
        review_status="pending",
        provenance="inferred",
    )
    db_session.add(detection)
    db_session.commit()

    # 5. Append Human Review (F20) correcting to Wolf
    review = ReviewEvent(
        id="REV-01",
        detection_id="DET-REV-01",
        decision="corrected",
        corrected_taxon_id="canis_lupus",
        reason="Ear shape and size clearly identify Indian Grey Wolf, not domestic dog.",
        reviewer_id="expert_wildlife_biologist",
        expected_revision=1,
        resulting_revision=2,
    )
    db_session.add(review)
    # Update review_status flag on detection, but preserve original raw_label and score!
    detection.review_status = "corrected"
    db_session.commit()

    # Verify original prediction is preserved
    det_check = db_session.query(Detection).filter_by(id="DET-REV-01").first()
    assert det_check.raw_label == "dog 0.72"
    assert det_check.score == 0.72
    assert det_check.review_status == "corrected"
    assert len(det_check.review_events) == 1
    assert det_check.review_events[0].corrected_taxon_id == "canis_lupus"
