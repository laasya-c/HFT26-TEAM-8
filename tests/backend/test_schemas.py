"""Tests for Pydantic Shared Data Contracts."""
import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
from pydantic import ValidationError

from contracts.schemas import (
    CameraContract,
    DetectionContract,
    EncounterContract,
    ImageFrameContract,
    ProvenanceEnum,
    ReviewEventContract,
    ReviewStatusEnum,
    TelemetryStatusEnum,
)


@pytest.mark.contract
def test_bounding_box_validation():
    """Verify that bounding boxes must be normalized between 0.0 and 1.0."""
    valid_detection = DetectionContract(
        id="DET-TEST-01",
        image_id="IMG-001",
        bbox=(0.1, 0.2, 0.3, 0.4),
        raw_label="tiger",
        label="Tiger",
        score=0.95,
        model_version="v1",
        provenance=ProvenanceEnum.INFERRED,
    )
    assert valid_detection.bbox == (0.1, 0.2, 0.3, 0.4)

    # Negative coordinate rejected
    with pytest.raises(ValidationError):
        DetectionContract(
            id="DET-TEST-02",
            image_id="IMG-001",
            bbox=(-0.1, 0.2, 0.3, 0.4),
            raw_label="tiger",
            label="Tiger",
            score=0.95,
            model_version="v1",
            provenance=ProvenanceEnum.INFERRED,
        )

    # Box extends outside frame (> 1.0)
    with pytest.raises(ValidationError):
        DetectionContract(
            id="DET-TEST-03",
            image_id="IMG-001",
            bbox=(0.8, 0.8, 0.5, 0.5),
            raw_label="tiger",
            label="Tiger",
            score=0.95,
            model_version="v1",
            provenance=ProvenanceEnum.INFERRED,
        )


@pytest.mark.contract
def test_timezone_normalization_rule():
    """Verify that naive datetimes are rejected and UTC timestamps are preserved."""
    # Naive timestamp should be rejected
    naive_dt = datetime(2026, 10, 30, 10, 0, 0)
    with pytest.raises(ValidationError):
        ImageFrameContract(
            id="IMG-001",
            camera_id="CAM-01",
            captured_at=naive_dt,
            content_url="/api/v1/images/1/content",
            provenance=ProvenanceEnum.OBSERVED,
        )

    # Timezone-aware UTC timestamp is accepted
    utc_dt = datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc)
    frame = ImageFrameContract(
        id="IMG-001",
        camera_id="CAM-01",
        captured_at=utc_dt,
        content_url="/api/v1/images/1/content",
        provenance=ProvenanceEnum.OBSERVED,
    )
    assert frame.captured_at == utc_dt

    # Scientific Rule: Unknown timestamp remains None (never fabricated)
    unknown_frame = ImageFrameContract(
        id="IMG-002",
        camera_id="CAM-01",
        captured_at=None,
        content_url="/api/v1/images/2/content",
        provenance=ProvenanceEnum.OBSERVED,
    )
    assert unknown_frame.captured_at is None


@pytest.mark.contract
def test_camera_telemetry_defaults_to_unknown():
    """Verify that cameras without telemetry default to 'unknown' (never dead)."""
    camera = CameraContract(
        id="CAM-01",
        label="Ridge Camera",
        provenance=ProvenanceEnum.OBSERVED,
    )
    assert camera.telemetry_status == TelemetryStatusEnum.UNKNOWN
    assert camera.last_heartbeat_at is None


@pytest.mark.contract
def test_demo_fixture_validates_against_contracts():
    """Verify that fixtures/demo.json strictly conforms to Pydantic shared schemas."""
    fixture_path = Path(__file__).resolve().parent.parent.parent / "fixtures" / "demo.json"
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Validate Cameras
    for cam in data["cameras"]:
        CameraContract.model_validate(cam)

    # Validate Images
    for img in data["images"]:
        ImageFrameContract.model_validate(img)

    # Validate Detections
    for det in data["detections"]:
        DetectionContract.model_validate(det)

    # Validate Encounters
    for enc in data["encounters"]:
        EncounterContract.model_validate(enc)

    # Validate Reviews
    for rev in data["reviews"]:
        ReviewEventContract.model_validate(rev)
