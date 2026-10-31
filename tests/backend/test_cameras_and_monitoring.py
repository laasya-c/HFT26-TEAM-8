"""Tests for Camera Health, Telemetry, and Monitoring Improvement Feedback (F07 & F11).

Tests:
1. Register camera stations and list cameras with live-evaluated telemetry freshness.
2. Submit hardware telemetry (heartbeat, battery, signal, error_codes) updating status to 'reporting'.
3. Freshness window logic: telemetry older than 24 hours transitions to 'stale'.
4. Scientific rule: Image silence is NEVER treated as camera failure (telemetry status remains reporting).
5. Scientific rule: Camera with images but no telemetry remains 'unknown' (never fabricated).
6. Camera diagnostic details separate hardware telemetry from visual observation quality.
7. Log monitoring actions (lens clean, reposition, battery replace).
8. Missing evaluation windows return status='insufficient_data' with non-causal disclaimer.
9. Zero activity / missing evidence returns status='insufficient_data'.
10. Valid evidence produces evaluated before/after metrics with mandatory non-causal disclaimer.
11. Network monitoring summary aggregates health states across all camera stations.
"""
from datetime import datetime, timedelta, timezone
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from src.backend.models import Camera, CameraTelemetry, ImageFrame, MediaAsset, MonitoringAction


@pytest.mark.integration
def test_create_and_list_cameras(admin_client: TestClient, db_session: Session):
    """Verify registering a camera trap station (Admin only) and retrieving it with 'unknown' telemetry status."""
    payload = {
        "id": "CAM-TEST-01",
        "label": "Waterhole South Station",
        "timezone": "Asia/Kolkata",
        "coordinates": [78.4523, 17.3850],
        "active_camera_days": 14.5,
        "provenance": "observed",
    }
    resp = admin_client.post("/api/v1/cameras", json=payload)
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["id"] == "CAM-TEST-01"
    assert body["label"] == "Waterhole South Station"
    assert body["telemetry_status"] == "unknown"  # No telemetry received yet
    assert body["coordinates"] == [78.4523, 17.3850]

    # List cameras
    list_resp = admin_client.get("/api/v1/cameras")
    assert list_resp.status_code == 200
    cameras = list_resp.json()["data"]
    assert len(cameras) >= 1
    cam = next(c for c in cameras if c["id"] == "CAM-TEST-01")
    assert cam["telemetry_status"] == "unknown"


@pytest.mark.integration
def test_submit_telemetry_updates_heartbeat_and_status(admin_client: TestClient, db_session: Session):
    """Verify hardware telemetry submission updates heartbeat and transitions status to 'reporting'."""
    cam = Camera(id="CAM-TEL-01", label="Ridge Station", timezone="UTC", telemetry_status="unknown")
    db_session.add(cam)
    db_session.commit()

    now_utc = datetime.now(timezone.utc)
    tel_payload = {
        "observed_at": now_utc.isoformat(),
        "battery_level": 92.5,
        "signal_strength": 78.0,
        "error_codes": [],
        "source": "satellite_relay",
    }
    resp = admin_client.post(f"/api/v1/cameras/{cam.id}/telemetry", json=tel_payload)
    assert resp.status_code == 201
    tel_data = resp.json()["data"]
    assert tel_data["camera_id"] == "CAM-TEL-01"
    assert tel_data["battery_level"] == 92.5

    # Check updated camera status
    cam_resp = admin_client.get(f"/api/v1/cameras/{cam.id}")
    assert cam_resp.status_code == 200
    cam_data = cam_resp.json()["data"]
    assert cam_data["telemetry_status"] == "reporting"
    assert cam_data["last_heartbeat_at"] is not None


@pytest.mark.integration
def test_telemetry_freshness_stale_after_threshold(admin_client: TestClient, db_session: Session):
    """Verify telemetry heartbeat older than 24h evaluates to 'stale'."""
    stale_time = datetime.now(timezone.utc) - timedelta(hours=30)
    cam = Camera(
        id="CAM-STALE-01",
        label="Deep Gorge Station",
        timezone="UTC",
        telemetry_status="unknown",
        last_heartbeat_at=stale_time,
    )
    db_session.add(cam)
    db_session.commit()

    cam_resp = admin_client.get(f"/api/v1/cameras/{cam.id}")
    assert cam_resp.status_code == 200
    assert cam_resp.json()["data"]["telemetry_status"] == "stale"


@pytest.mark.integration
def test_image_silence_never_treated_as_dead(admin_client: TestClient, db_session: Session):
    """Scientific Rule: Image silence alone does not prove hardware failure."""
    # Camera with 0 media images, but active telemetry
    cam = Camera(id="CAM-SILENT-01", label="Dry Valley Station", timezone="UTC", telemetry_status="unknown")
    db_session.add(cam)
    db_session.commit()

    recent_time = datetime.now(timezone.utc) - timedelta(hours=2)
    admin_client.post(f"/api/v1/cameras/{cam.id}/telemetry", json={
        "observed_at": recent_time.isoformat(),
        "battery_level": 85.0,
        "signal_strength": 60.0,
        "error_codes": [],
    })

    # Verify status is 'reporting', NOT dead or failed
    cam_resp = admin_client.get(f"/api/v1/cameras/{cam.id}")
    assert cam_resp.status_code == 200
    data = cam_resp.json()["data"]
    assert data["telemetry_status"] == "reporting"
    assert data["observation_quality"]["total_images"] == 0


@pytest.mark.integration
def test_camera_with_images_but_no_telemetry_is_unknown(admin_client: TestClient, db_session: Session):
    """Scientific Rule: Camera uploading images without telemetry remains 'unknown'."""
    cam = Camera(id="CAM-NO-TEL", label="Trail Station", timezone="UTC", telemetry_status="unknown")
    db_session.add(cam)
    db_session.commit()

    # Add media image for this camera
    media = MediaAsset(
        id="MED-NO-TEL",
        type="image",
        camera_id=cam.id,
        storage_key="media/sample.jpg",
        content_hash="sample_hash",
        provenance="observed",
    )
    db_session.add(media)
    db_session.flush()

    frame = ImageFrame(
        id="FRM-NO-TEL",
        source_media_id=media.id,
        content_url="/api/v1/images/FRM-NO-TEL/content",
        quality_flags=["low_light"],
        provenance="observed",
    )
    db_session.add(frame)
    db_session.commit()

    cam_resp = admin_client.get(f"/api/v1/cameras/{cam.id}")
    assert cam_resp.status_code == 200
    data = cam_resp.json()["data"]
    # Telemetry health remains unknown
    assert data["telemetry_status"] == "unknown"
    # Observation quality accurately reflects the media
    assert data["observation_quality"]["total_images"] == 1
    assert data["observation_quality"]["quality_flags_summary"]["low_light"] == 1


@pytest.mark.integration
def test_log_monitoring_action(researcher_client: TestClient, db_session: Session):
    """Verify logging a field maintenance action (F11)."""
    cam = Camera(id="CAM-MAINT-01", label="Riverbed Camera", timezone="UTC")
    db_session.add(cam)
    db_session.commit()

    now = datetime.now(timezone.utc)
    action_payload = {
        "camera_id": cam.id,
        "action_type": "lens_clean",
        "description": "Cleaned dried mud splatters and insect debris from front optical lens.",
        "performed_at": now.isoformat(),
        "baseline_start": (now - timedelta(days=7)).isoformat(),
        "baseline_end": now.isoformat(),
        "post_start": now.isoformat(),
        "post_end": (now + timedelta(days=7)).isoformat(),
        "source": "field_ranger_dan",
    }
    resp = researcher_client.post("/api/v1/monitoring-actions", json=action_payload)
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["camera_id"] == "CAM-MAINT-01"
    assert data["action_type"] == "lens_clean"
    assert data["source"] == "field_ranger_dan"


@pytest.mark.integration
def test_feedback_insufficient_data_missing_windows(researcher_client: TestClient, db_session: Session):
    """Verify feedback returns 'insufficient_data' when evaluation windows are undefined."""
    cam = Camera(id="CAM-NODATA-01", label="Gully Camera", timezone="UTC")
    db_session.add(cam)
    db_session.commit()

    action = MonitoringAction(
        id="ACT-NOWINDOWS",
        camera_id=cam.id,
        action_type="reposition",
        description="Shifted camera 5 meters north to avoid direct sun glare",
        performed_at=datetime.now(timezone.utc),
        baseline_start=None,  # Missing baseline window
        baseline_end=None,
        post_start=None,
        post_end=None,
        source="ranger",
    )
    db_session.add(action)
    db_session.commit()

    resp = researcher_client.get(f"/api/v1/monitoring-actions/{action.id}/feedback")
    assert resp.status_code == 200
    feedback = resp.json()["data"]
    assert feedback["status"] == "insufficient_data"
    assert feedback["is_causal"] is False
    assert "causal_claim_disclaimer" in feedback


@pytest.mark.integration
def test_feedback_insufficient_data_zero_evidence(researcher_client: TestClient, db_session: Session):
    """Verify feedback returns 'insufficient_data' when defined windows have zero recorded activity."""
    cam = Camera(id="CAM-ZERO-01", label="Ridge North", timezone="UTC")
    db_session.add(cam)
    db_session.commit()

    now = datetime.now(timezone.utc)
    action = MonitoringAction(
        id="ACT-ZEROEVID",
        camera_id=cam.id,
        action_type="battery_replace",
        description="Replaced lead-acid pack with LiFePO4 battery",
        performed_at=now,
        baseline_start=now - timedelta(days=5),
        baseline_end=now,
        post_start=now,
        post_end=now + timedelta(days=5),
        source="ranger",
    )
    db_session.add(action)
    db_session.commit()

    resp = researcher_client.get(f"/api/v1/monitoring-actions/{action.id}/feedback")
    assert resp.status_code == 200
    feedback = resp.json()["data"]
    assert feedback["status"] == "insufficient_data"
    assert "Insufficient telemetry or media evidence" in feedback["reason"]
    assert feedback["is_causal"] is False


@pytest.mark.integration
def test_feedback_evaluation_with_evidence_and_non_causal_guarantee(researcher_client: TestClient, db_session: Session):
    """Verify before/after comparison calculates metrics and strictly enforces non-causal claims."""
    cam = Camera(id="CAM-EVAL-01", label="Corridor Station", timezone="UTC")
    db_session.add(cam)
    db_session.commit()

    t_now = datetime.now(timezone.utc)
    t_base_start = t_now - timedelta(days=6)
    t_base_end = t_now
    t_post_start = t_now
    t_post_end = t_now + timedelta(days=6)

    # 1. Baseline Telemetry (Low battery)
    tel_base = CameraTelemetry(
        camera_id=cam.id,
        observed_at=t_base_start + timedelta(days=2),
        battery_level=22.0,
        signal_strength=50.0,
    )
    db_session.add(tel_base)

    # 2. Post Telemetry (Replaced battery -> High battery)
    tel_post = CameraTelemetry(
        camera_id=cam.id,
        observed_at=t_post_start + timedelta(days=2),
        battery_level=98.0,
        signal_strength=55.0,
    )
    db_session.add(tel_post)

    # 3. Action
    action = MonitoringAction(
        id="ACT-EVAL-01",
        camera_id=cam.id,
        action_type="battery_replace",
        description="Replaced depleted battery cell",
        performed_at=t_now,
        baseline_start=t_base_start,
        baseline_end=t_base_end,
        post_start=t_post_start,
        post_end=t_post_end,
        source="solar_technician",
    )
    db_session.add(action)
    db_session.commit()

    resp = researcher_client.get(f"/api/v1/monitoring-actions/{action.id}/feedback")
    assert resp.status_code == 200
    data = resp.json()["data"]

    # Verify status and values
    assert data["status"] == "evaluated"
    assert data["baseline_metrics"]["avg_battery_level"] == 22.0
    assert data["post_metrics"]["avg_battery_level"] == 98.0
    assert data["observed_changes"]["delta_avg_battery"] == 76.0

    # SCIENTIFIC INTEGRITY ENFORCEMENT
    assert data["is_causal"] is False
    assert "Observational before/after comparison only" in data["causal_claim_disclaimer"]
    assert len(data["limitations"]) > 0


@pytest.mark.integration
def test_network_monitoring_summary(researcher_client: TestClient, db_session: Session):
    """Verify network monitoring overview aggregates health counts and recent actions."""
    # Setup cameras with diverse states
    now = datetime.now(timezone.utc)
    c1 = Camera(id="CAM-NET-1", label="Net 1", timezone="UTC", last_heartbeat_at=now)  # reporting
    c2 = Camera(id="CAM-NET-2", label="Net 2", timezone="UTC", last_heartbeat_at=now - timedelta(hours=48))  # stale
    c3 = Camera(id="CAM-NET-3", label="Net 3", timezone="UTC", last_heartbeat_at=None)  # unknown
    db_session.add_all([c1, c2, c3])
    db_session.commit()

    resp = researcher_client.get("/api/v1/monitoring")
    assert resp.status_code == 200
    summary = resp.json()["data"]
    assert summary["total_cameras"] >= 3
    breakdown = summary["telemetry_health_breakdown"]
    assert breakdown["reporting"] >= 1
    assert breakdown["stale"] >= 1
    assert breakdown["unknown"] >= 1
    assert summary["freshness_threshold_hours"] == 24.0
