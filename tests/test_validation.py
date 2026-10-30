"""
Tests for WILDSCOPE Validation Engine - Phase 1
Verifies referential integrity, uniqueness, temporal ordering,
advisory warnings for missing optional data, and integration entry points.
"""

from datetime import datetime, timezone
from pathlib import Path
import pytest

from wildscope_analytics import (
    AnalysisMetric,
    AnalysisRequest,
    Camera,
    Detection,
    Encounter,
    MediaAsset,
    MonitoringEffort,
    NormalizedBBox,
    Observation,
    PredictionRun,
    ResponseStatus,
    ReviewDecision,
    ReviewEvent,
    ReviewRankingRequest,
    Snapshot,
    SnapshotMetadata,
    TimeInterval,
    ValidationErrorCode,
    analyze,
    load_and_validate_snapshot,
    rank_review,
    validate_analysis_request,
    validate_review_ranking_request,
    validate_snapshot_data,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


class TestSnapshotValidationFixtures:
    """Verifies standard example fixture files."""

    def test_valid_snapshot_fixture(self):
        valid_path = EXAMPLES_DIR / "valid_snapshot.json"
        snapshot, report = load_and_validate_snapshot(valid_path)
        assert snapshot is not None
        assert report.is_valid is True
        assert len(report.errors) == 0
        assert report.counts["cameras"] == 2
        assert report.counts["detections"] == 3
        assert report.counts["encounters"] == 2
        assert report.counts["reviews"] == 1

    def test_minimal_snapshot_fixture(self):
        minimal_path = EXAMPLES_DIR / "minimal_snapshot.json"
        snapshot, report = load_and_validate_snapshot(minimal_path)
        assert snapshot is not None
        assert report.is_valid is True
        assert len(report.errors) == 0
        # Warnings generated for missing optional fields
        assert any("GPS coordinates" in w for w in report.warnings)
        assert any("monitoring effort" in w.lower() for w in report.warnings)

    def test_invalid_snapshot_fixture(self):
        invalid_path = EXAMPLES_DIR / "invalid_snapshot.json"
        snapshot, report = load_and_validate_snapshot(invalid_path)
        assert report.is_valid is False
        assert len(report.errors) > 0

        error_codes = {e.code for e in report.errors}
        assert ValidationErrorCode.DUPLICATE_ID in error_codes
        assert ValidationErrorCode.BROKEN_REFERENCE in error_codes


class TestEmptySnapshotValidation:
    """Verifies that an empty snapshot with 0 entities is structurally valid."""

    def test_empty_snapshot_valid(self):
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=0,
            created_at=datetime.now(timezone.utc),
        )
        snap = Snapshot(metadata=meta)
        report = validate_snapshot_data(snap)
        assert report.is_valid is True
        assert len(report.errors) == 0
        assert report.counts["cameras"] == 0


class TestDuplicateIDValidation:
    """Verifies duplicate ID detection across entities."""

    def test_duplicate_camera_id(self):
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=1,
            created_at=datetime.now(timezone.utc),
        )
        cam1 = Camera(id="cam_dup")
        cam2 = Camera(id="cam_dup")
        snap = Snapshot(metadata=meta, cameras=[cam1, cam2])
        report = validate_snapshot_data(snap)
        assert report.is_valid is False
        assert any(e.code == ValidationErrorCode.DUPLICATE_ID and "cameras[1].id" == e.field_path for e in report.errors)

    def test_duplicate_observation_id(self):
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=1,
            created_at=datetime.now(timezone.utc),
        )
        cam = Camera(id="cam_01")
        obs1 = Observation(id="obs_dup", camera_id="cam_01", source_media_id="med_01")
        obs2 = Observation(id="obs_dup", camera_id="cam_01", source_media_id="med_01")
        snap = Snapshot(metadata=meta, cameras=[cam], observations=[obs1, obs2])
        report = validate_snapshot_data(snap)
        assert report.is_valid is False
        assert any(e.code == ValidationErrorCode.DUPLICATE_ID and "observations[1].id" == e.field_path for e in report.errors)


class TestReferentialIntegrityValidation:
    """Verifies foreign key references across entities."""

    def test_observation_references_missing_camera(self):
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=1,
            created_at=datetime.now(timezone.utc),
        )
        obs = Observation(id="obs_01", camera_id="missing_cam", source_media_id="med_01")
        snap = Snapshot(metadata=meta, cameras=[], observations=[obs])
        report = validate_snapshot_data(snap)
        assert report.is_valid is False
        assert any(e.code == ValidationErrorCode.BROKEN_REFERENCE and "missing_cam" in e.message for e in report.errors)

    def test_detection_references_missing_observation(self):
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=1,
            created_at=datetime.now(timezone.utc),
        )
        cam = Camera(id="cam_01")
        det = Detection(id="det_01", observation_id="missing_obs", animal_detection_confidence=0.9)
        snap = Snapshot(metadata=meta, cameras=[cam], detections=[det])
        report = validate_snapshot_data(snap)
        assert report.is_valid is False
        assert any(e.code == ValidationErrorCode.BROKEN_REFERENCE and "missing_obs" in e.message for e in report.errors)

    def test_encounter_cross_camera_violation(self):
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=1,
            created_at=datetime.now(timezone.utc),
        )
        cam1 = Camera(id="cam_01")
        cam2 = Camera(id="cam_02")
        obs_on_cam2 = Observation(id="obs_on_cam2", camera_id="cam_02", source_media_id="med_01")
        # Encounter assigned to cam1 but includes observation from cam2
        enc = Encounter(
            id="enc_01",
            camera_id="cam_01",
            member_observation_ids=["obs_on_cam2"],
        )
        snap = Snapshot(
            metadata=meta,
            cameras=[cam1, cam2],
            observations=[obs_on_cam2],
            encounters=[enc],
        )
        report = validate_snapshot_data(snap)
        assert report.is_valid is False
        assert any(e.code == ValidationErrorCode.ENCOUNTER_MEMBERSHIP_VIOLATION for e in report.errors)

    def test_review_references_missing_detection(self):
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=1,
            created_at=datetime.now(timezone.utc),
        )
        rev = ReviewEvent(
            id="rev_01",
            target_id="missing_det",
            decision=ReviewDecision.CONFIRM_SPECIES,
            reviewer="expert_1",
            created_at=datetime.now(timezone.utc),
        )
        snap = Snapshot(metadata=meta, reviews=[rev])
        report = validate_snapshot_data(snap)
        assert report.is_valid is False
        assert any(e.code == ValidationErrorCode.BROKEN_REFERENCE and "missing_det" in e.message for e in report.errors)


class TestCrossRecordEffortOverlap:
    """Verifies overlapping effort across multiple MonitoringEffort records for the same camera."""

    def test_cross_record_effort_overlap(self):
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=1,
            created_at=datetime.now(timezone.utc),
        )
        cam = Camera(id="cam_01")
        t1 = datetime(2026, 10, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 10, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 8, tzinfo=timezone.utc)
        t4 = datetime(2026, 10, 15, tzinfo=timezone.utc)

        eff1 = MonitoringEffort(
            id="eff_01",
            camera_id="cam_01",
            active_intervals=[TimeInterval(start=t1, end=t2)],
        )
        eff2 = MonitoringEffort(
            id="eff_02",
            camera_id="cam_01",
            active_intervals=[TimeInterval(start=t3, end=t4)],
        )
        snap = Snapshot(metadata=meta, cameras=[cam], monitoring_efforts=[eff1, eff2])
        report = validate_snapshot_data(snap)
        assert report.is_valid is False
        assert any(e.code == ValidationErrorCode.OVERLAPPING_EFFORT for e in report.errors)


class TestMissingOptionalDataPreserved:
    """Verifies that missing optional data creates advisory warnings without invalidating the snapshot."""

    def test_missing_optional_data_keeps_snapshot_valid(self):
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=1,
            created_at=datetime.now(timezone.utc),
        )
        # Camera without GPS, observation without timestamp, no effort records
        cam = Camera(id="cam_01", latitude=None, longitude=None, timezone=None)
        obs = Observation(
            id="obs_01",
            camera_id="cam_01",
            source_media_id="med_01",
            captured_at=None,
            detection_ids=["det_01"],
        )
        det = Detection(
            id="det_01",
            observation_id="obs_01",
            animal_detection_confidence=0.88,
            predicted_taxon_id="panthera_tigris",
            bbox=None,
        )
        enc = Encounter(
            id="enc_01",
            camera_id="cam_01",
            member_observation_ids=["obs_01"],
            member_detection_ids=["det_01"],
        )
        snap = Snapshot(
            metadata=meta,
            cameras=[cam],
            observations=[obs],
            detections=[det],
            encounters=[enc],
        )
        report = validate_snapshot_data(snap)
        assert report.is_valid is True
        assert len(report.errors) == 0
        assert len(report.warnings) > 0


class TestIntegrationEntryPoints:
    """Verifies analyze() and rank_review() entry points."""

    def test_analyze_on_valid_snapshot_returns_ok_phase2(self):
        """
        Phase 2: analyze() now computes real results and returns status=OK (not UNAVAILABLE).
        The Phase 1 expectation of UNAVAILABLE is intentionally superseded by working analytics.
        rank_review() still returns UNAVAILABLE (Phase 3 scope).
        """
        valid_path = EXAMPLES_DIR / "valid_snapshot.json"
        snapshot, report = load_and_validate_snapshot(valid_path)
        assert snapshot is not None

        req = AnalysisRequest(
            metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            species_ids=["panthera_tigris"],
            expected_revision=snapshot.metadata.dataset_revision,
        )
        response = analyze(snapshot, req)
        # Phase 2: analyze() produces real results — status must NOT be UNAVAILABLE
        assert response.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        # Result payload must be present and not None
        assert response.result is not None
        # dataset_revision must be preserved
        assert response.dataset_revision == snapshot.metadata.dataset_revision
        # metric must be set
        assert response.metric == AnalysisMetric.SPECIES_ENCOUNTER_COUNTS

    def test_analyze_on_revision_mismatch_returns_invalid_request(self):
        valid_path = EXAMPLES_DIR / "valid_snapshot.json"
        snapshot, _ = load_and_validate_snapshot(valid_path)
        assert snapshot is not None

        # Request expects revision 999 instead of 4
        req = AnalysisRequest(
            metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            expected_revision=999,
        )
        response = analyze(snapshot, req)
        assert response.status == ResponseStatus.INVALID_REQUEST
        assert any("revision" in err.message.lower() for err in response.errors)

    def test_rank_review_on_valid_snapshot_returns_honest_unavailable(self):
        """rank_review() remains UNAVAILABLE until Phase 3."""
        valid_path = EXAMPLES_DIR / "valid_snapshot.json"
        snapshot, _ = load_and_validate_snapshot(valid_path)
        assert snapshot is not None

        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            expected_revision=snapshot.metadata.dataset_revision,
        )
        response = rank_review(snapshot, req)
        assert response.status == ResponseStatus.UNAVAILABLE
        assert response.result is None
        assert any("Phase 3" in lim for lim in response.limitations)
