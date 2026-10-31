"""
Tests for WILDSCOPE Shared Data Contracts - Phase 1
Validates entity schemas, Pydantic field constraints, enums,
and serialization/deserialization round trips.
"""

from datetime import datetime, timezone
import math
import pytest
from pydantic import ValidationError

from wildscope_analytics.contracts.entities import (
    Camera,
    Detection,
    Encounter,
    MediaAsset,
    MonitoringEffort,
    NormalizedBBox,
    Observation,
    PredictionRun,
    ReviewEvent,
    SpatialContext,
    SpatialZone,
    TaxonAlternative,
    TimeInterval,
)
from wildscope_analytics.contracts.enums import (
    AnalysisMetric,
    CalibrationStatus,
    InclusionPolicy,
    MediaType,
    PredictionStatus,
    ResponseStatus,
    ReviewDecision,
    ScoreType,
    TriageState,
    ValidationErrorCode,
)
from wildscope_analytics.contracts.requests import AnalysisRequest, ReviewRankingRequest
from wildscope_analytics.contracts.responses import (
    AnalysisResponseEnvelope,
    ValidationErrorDetail,
)
from wildscope_analytics.contracts.snapshot import (
    CURRENT_SCHEMA_VERSION,
    Snapshot,
    SnapshotMetadata,
)


class TestCameraContract:
    """Verifies Camera entity validation rules."""

    def test_valid_camera_with_coordinates(self):
        cam = Camera(
            id="cam_01",
            site_id="site_alpha",
            latitude=17.3850,
            longitude=78.4867,
            timezone="Asia/Kolkata",
            provenance="SYNTHETIC TEST FIXTURE",
        )
        assert cam.id == "cam_01"
        assert cam.latitude == 17.3850
        assert cam.longitude == 78.4867

    def test_valid_camera_without_coordinates(self):
        cam = Camera(
            id="cam_02",
            site_id="site_beta",
            latitude=None,
            longitude=None,
            timezone="UTC",
        )
        assert cam.latitude is None
        assert cam.longitude is None

    def test_camera_partial_coordinates_rejected(self):
        # Latitude present, longitude absent
        with pytest.raises(ValidationError, match="Both latitude and longitude must be provided together"):
            Camera(id="cam_err_1", latitude=15.0, longitude=None)

        # Longitude present, latitude absent
        with pytest.raises(ValidationError, match="Both latitude and longitude must be provided together"):
            Camera(id="cam_err_2", latitude=None, longitude=75.0)

    def test_camera_out_of_bounds_coordinates(self):
        with pytest.raises(ValidationError, match="out of bounds"):
            Camera(id="cam_err_3", latitude=95.0, longitude=75.0)

        with pytest.raises(ValidationError, match="out of bounds"):
            Camera(id="cam_err_4", latitude=-95.0, longitude=75.0)

        with pytest.raises(ValidationError, match="out of bounds"):
            Camera(id="cam_err_5", latitude=10.0, longitude=185.0)

    def test_camera_non_finite_coordinates(self):
        with pytest.raises(ValidationError, match="finite"):
            Camera(id="cam_nan", latitude=float("nan"), longitude=75.0)

        with pytest.raises(ValidationError, match="finite"):
            Camera(id="cam_inf", latitude=10.0, longitude=float("inf"))


class TestDetectionAndBBoxContract:
    """Verifies Detection and NormalizedBBox constraints."""

    def test_valid_normalized_bbox(self):
        bbox = NormalizedBBox(x_min=0.1, y_min=0.2, x_max=0.8, y_max=0.9)
        assert bbox.x_min == 0.1
        assert bbox.y_max == 0.9

    def test_invalid_bbox_coords(self):
        # Coordinates out of [0, 1]
        with pytest.raises(ValidationError, match="in \\[0.0, 1.0\\]"):
            NormalizedBBox(x_min=-0.1, y_min=0.0, x_max=0.5, y_max=0.5)

        with pytest.raises(ValidationError, match="in \\[0.0, 1.0\\]"):
            NormalizedBBox(x_min=0.0, y_min=0.0, x_max=1.2, y_max=0.5)

        # Inverted coordinates
        with pytest.raises(ValidationError, match="cannot exceed x_max"):
            NormalizedBBox(x_min=0.8, y_min=0.2, x_max=0.3, y_max=0.9)

        with pytest.raises(ValidationError, match="cannot exceed y_max"):
            NormalizedBBox(x_min=0.1, y_min=0.9, x_max=0.8, y_max=0.2)

    def test_detection_confidence_bounds(self):
        det = Detection(
            id="det_01",
            observation_id="obs_01",
            animal_detection_confidence=0.95,
            classification_confidence=0.88,
            predicted_taxon_id="panthera_tigris",
            raw_label="tiger",
            score_type=ScoreType.SOFTMAX,
            calibration_status=CalibrationStatus.UNCALIBRATED,
            alternatives=[
                TaxonAlternative(taxon_id="panthera_pardus", score=0.07, raw_label="leopard")
            ],
        )
        assert det.animal_detection_confidence == 0.95
        assert len(det.alternatives) == 1

        # Out of bounds confidence
        with pytest.raises(ValidationError, match="finite number in \\[0.0, 1.0\\]"):
            Detection(id="det_bad", observation_id="obs_01", animal_detection_confidence=1.5)

        with pytest.raises(ValidationError, match="finite number in \\[0.0, 1.0\\]"):
            Detection(id="det_bad2", observation_id="obs_01", animal_detection_confidence=-0.1)

        # NaN confidence
        with pytest.raises(ValidationError, match="finite"):
            Detection(id="det_nan", observation_id="obs_01", animal_detection_confidence=float("nan"))

    def test_empty_frame_vs_unknown_species(self):
        # Empty frame detection: low confidence, likely_empty triage state, no species
        empty_det = Detection(
            id="det_empty",
            observation_id="obs_01",
            triage_state=TriageState.LIKELY_EMPTY,
            animal_detection_confidence=0.02,
            predicted_taxon_id=None,
            classification_confidence=None,
        )
        assert empty_det.triage_state == TriageState.LIKELY_EMPTY
        assert empty_det.predicted_taxon_id is None

        # Unknown species detection: high animal confidence, triage state animal_detected, taxon is unknown
        unknown_det = Detection(
            id="det_unk",
            observation_id="obs_01",
            triage_state=TriageState.ANIMAL_DETECTED,
            animal_detection_confidence=0.94,
            predicted_taxon_id="unknown_species",
            raw_label="unidentified_mammal",
            classification_confidence=0.45,
        )
        assert unknown_det.triage_state == TriageState.ANIMAL_DETECTED
        assert unknown_det.predicted_taxon_id == "unknown_species"


class TestEncounterContract:
    """Verifies Encounter temporal and membership rules."""

    def test_valid_encounter(self):
        start = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
        end = datetime(2026, 10, 30, 8, 15, tzinfo=timezone.utc)
        enc = Encounter(
            id="enc_01",
            camera_id="cam_01",
            member_observation_ids=["obs_01", "obs_02"],
            start_time=start,
            end_time=end,
            rule_version="v1_time_gap",
        )
        assert enc.id == "enc_01"
        assert len(enc.member_observation_ids) == 2

    def test_inverted_encounter_timestamps(self):
        start = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="cannot be after end_time"):
            Encounter(
                id="enc_inv",
                camera_id="cam_01",
                member_observation_ids=["obs_01"],
                start_time=start,
                end_time=end,
            )

    def test_encounter_empty_members_rejected(self):
        with pytest.raises(ValidationError, match="must contain at least one member"):
            Encounter(
                id="enc_empty",
                camera_id="cam_01",
                member_observation_ids=[],
                member_detection_ids=[],
            )

    def test_encounter_naive_timestamp_rejected(self):
        naive_dt = datetime(2026, 10, 30, 8, 0)
        with pytest.raises(ValidationError, match="must be timezone-aware"):
            Encounter(
                id="enc_naive",
                camera_id="cam_01",
                member_observation_ids=["obs_01"],
                start_time=naive_dt,
            )


class TestReviewEventContract:
    """Verifies ReviewEvent decision consistency and immutability."""

    def test_valid_confirm_species(self):
        rev = ReviewEvent(
            id="rev_01",
            target_id="det_01",
            decision=ReviewDecision.CONFIRM_SPECIES,
            reviewer="alice",
            created_at=datetime.now(timezone.utc),
        )
        assert rev.decision == ReviewDecision.CONFIRM_SPECIES

    def test_correct_species_requires_corrected_taxon(self):
        # Missing corrected_taxon_id
        with pytest.raises(ValidationError, match="corrected_taxon_id is required"):
            ReviewEvent(
                id="rev_02",
                target_id="det_01",
                decision=ReviewDecision.CORRECT_SPECIES,
                corrected_taxon_id=None,
                reviewer="alice",
                created_at=datetime.now(timezone.utc),
            )

        # Valid with corrected_taxon_id
        rev_ok = ReviewEvent(
            id="rev_02",
            target_id="det_01",
            decision=ReviewDecision.CORRECT_SPECIES,
            corrected_taxon_id="panthera_pardus",
            reviewer="alice",
            created_at=datetime.now(timezone.utc),
        )
        assert rev_ok.corrected_taxon_id == "panthera_pardus"

    def test_reject_detection_forbids_corrected_taxon(self):
        with pytest.raises(ValidationError, match="must not be specified when decision is REJECT_DETECTION"):
            ReviewEvent(
                id="rev_03",
                target_id="det_01",
                decision=ReviewDecision.REJECT_DETECTION,
                corrected_taxon_id="panthera_tigris",
                reviewer="alice",
                created_at=datetime.now(timezone.utc),
            )


class TestMonitoringEffortContract:
    """Verifies MonitoringEffort and overlapping interval detection."""

    def test_valid_effort_disjoint_intervals(self):
        t1 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
        t4 = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)
        effort = MonitoringEffort(
            id="eff_01",
            camera_id="cam_01",
            active_intervals=[
                TimeInterval(start=t1, end=t2),
                TimeInterval(start=t3, end=t4),
            ],
            source="ranger_log",
        )
        assert len(effort.active_intervals) == 2

    def test_overlapping_effort_intervals_rejected(self):
        t1 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
        t4 = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="Overlapping monitoring intervals detected"):
            MonitoringEffort(
                id="eff_overlap",
                camera_id="cam_01",
                active_intervals=[
                    TimeInterval(start=t1, end=t2),
                    TimeInterval(start=t3, end=t4),
                ],
            )


class TestSerializationRoundTrip:
    """Verifies complete Pydantic model serialization and deserialization."""

    def test_snapshot_roundtrip(self):
        now = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=5,
            created_at=now,
            source_system="WILDSCOPE_BACKEND",
        )
        cam = Camera(id="cam_1", latitude=15.0, longitude=75.0, timezone="Asia/Kolkata")
        obs = Observation(
            id="obs_1",
            camera_id="cam_1",
            source_media_id="med_1",
            captured_at=now,
            detection_ids=["det_1"],
        )
        det = Detection(
            id="det_1",
            observation_id="obs_1",
            animal_detection_confidence=0.99,
            predicted_taxon_id="panthera_tigris",
            raw_label="tiger",
            classification_confidence=0.95,
        )
        enc = Encounter(
            id="enc_1",
            camera_id="cam_1",
            member_observation_ids=["obs_1"],
            member_detection_ids=["det_1"],
        )
        snap = Snapshot(
            metadata=meta,
            cameras=[cam],
            observations=[obs],
            detections=[det],
            encounters=[enc],
        )

        json_str = snap.model_dump_json()
        assert "panthera_tigris" in json_str
        assert "cam_1" in json_str

        # Deserialize back
        reloaded = Snapshot.model_validate_json(json_str)
        assert reloaded.metadata.dataset_revision == 5
        assert len(reloaded.cameras) == 1
        assert reloaded.cameras[0].latitude == 15.0
        assert reloaded.detections[0].animal_detection_confidence == 0.99


class TestRequestAndResponseContracts:
    """Verifies typed request models and response envelopes."""

    def test_analysis_request_valid(self):
        req = AnalysisRequest(
            metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            species_ids=["panthera_tigris"],
            min_confidence=0.8,
            inclusion_policy=InclusionPolicy.REVIEWED_ONLY,
            expected_revision=5,
        )
        assert req.metric == AnalysisMetric.SPECIES_ENCOUNTER_COUNTS
        assert req.expected_revision == 5

    def test_analysis_request_inverted_times_rejected(self):
        t1 = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="cannot be later than end_time"):
            AnalysisRequest(
                metric=AnalysisMetric.ACTIVITY_TIME_DISTRIBUTION,
                start_time=t1,
                end_time=t2,
            )

    def test_review_ranking_request_valid(self):
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            top_k_candidates=5,
            score_margin_threshold=0.2,
        )
        assert req.top_k_candidates == 5

    def test_response_envelope_statuses(self):
        # Envelope with unavailable status and limitations
        env = AnalysisResponseEnvelope(
            status=ResponseStatus.UNAVAILABLE,
            schema_version="1.0.0",
            dataset_revision=2,
            metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            limitations=["Engine deferred to Phase 2."],
            warnings=["No GPS coordinates present."],
        )
        assert env.status == ResponseStatus.UNAVAILABLE
        assert env.result is None
        assert len(env.limitations) == 1
