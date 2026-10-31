"""
WILDSCOPE Phase 4: Cross-Camera Observation Correlation Tests (Feature F06)
=============================================================================
Comprehensive test suite covering all requirements from Part L:
  - Same species, different cameras, within threshold
  - Outside threshold
  - Exact threshold boundary
  - Same camera excluded
  - Self-pair excluded
  - Mirrored pair deduplication
  - Overlapping and disjoint intervals
  - Same timestamp with different timezone offsets
  - Missing timestamps
  - Unknown clock comparability (INSUFFICIENT_DATA)
  - Explicit documented clock-comparability assumption (OK)
  - Supplied clock uncertainty propagation
  - Repeated same-species detections within encounters (deduplication)
  - Multi-species encounters
  - Unknown taxa not matching each other
  - Reviewed correction changing association eligibility
  - Rejected detections and ambiguous review conflicts
  - Multiple plausible matches retained (no greedy 1-to-1 matching)
  - No transitive identity or encounter merging
  - All three spatial modes (time_species_only, spatial_when_available, spatial_required)
  - Valid known camera separation (Haversine formula verification)
  - Missing/invalid coordinates
  - Distance threshold boundaries
  - Completed-empty versus unavailable grouping
  - Result limits versus evaluation limits
  - Revision mismatch (INVALID_REQUEST)
  - Snapshot immutability
  - JSON serialisation and evidence integrity
  - Exhaustive versus optimized pair-generation parity
  - Category mapping regression test (Part B)
  - Real Caltech dataset execution and missing-prerequisite reporting

All fixtures are hand-calculated SYNTHETIC TEST FIXTUREs.
"""

from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from wildscope_analytics import (
    AnalysisMetric,
    AnalysisRequest,
    AnalysisResponseEnvelope,
    Camera,
    ClockComparabilityPolicy,
    CrossCameraAssociationPair,
    CrossCameraAssociationRequest,
    CrossCameraAssociationsResult,
    DataSourceMode,
    Detection,
    Encounter,
    EncounterProcessingStatus,
    InclusionPolicy,
    MediaAsset,
    Observation,
    ResponseStatus,
    ReviewDecision,
    ReviewEvent,
    Snapshot,
    SnapshotMetadata,
    SpatialCheckStatus,
    SpatialMode,
    TemporalRelation,
    TriageState,
    analyze,
    find_cross_camera_associations,
    haversine_distance_meters,
)
from wildscope_analytics.associations import _exhaustive_pairwise_associations
from wildscope_analytics.caltech_adapter import import_caltech_snapshot
from wildscope_analytics.contracts.enums import ReviewOrderingMechanism

UTC = timezone.utc
SYNTHETIC = "SYNTHETIC TEST FIXTURE"
T0 = datetime(2026, 10, 15, 8, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 15, 8, 30, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 15, 9, 0, 0, tzinfo=UTC)
T3 = datetime(2026, 10, 15, 9, 30, 0, tzinfo=UTC)


def _meta(
    revision: int = 1,
    mode: DataSourceMode = DataSourceMode.OPERATIONAL_PREDICTION,
    status: EncounterProcessingStatus = EncounterProcessingStatus.COMPLETED,
) -> SnapshotMetadata:
    return SnapshotMetadata(
        schema_version="1.3.0",
        dataset_revision=revision,
        created_at=datetime.now(UTC),
        source_system="WILDSCOPE_PHASE4_TEST",
        data_source_mode=mode,
        review_ordering_mechanism=ReviewOrderingMechanism.BACKEND_REVISION,
        encounter_processing_status=status,
        provenance=SYNTHETIC,
    )


def _cam(cam_id: str, lat: float | None = None, lon: float | None = None, site_id: str | None = None) -> Camera:
    return Camera(
        id=cam_id,
        latitude=lat,
        longitude=lon,
        site_id=site_id,
        timezone="UTC",
        provenance=SYNTHETIC,
    )


def _obs(obs_id: str, cam_id: str, ts: datetime = T0) -> Observation:
    return Observation(
        id=obs_id,
        camera_id=cam_id,
        source_media_id=f"med_{obs_id}",
        captured_at=ts,
    )


def _det(
    det_id: str,
    obs_id: str,
    taxon: str | None = "canis_latrans",
    confidence: float = 0.90,
) -> Detection:
    return Detection(
        id=det_id,
        observation_id=obs_id,
        predicted_taxon_id=taxon,
        animal_detection_confidence=0.95,
        classification_confidence=confidence,
        triage_state=TriageState.ANIMAL_DETECTED if taxon else TriageState.LIKELY_EMPTY,
    )


def _enc(
    enc_id: str,
    cam_id: str,
    det_ids: list[str],
    start: datetime = T0,
    end: datetime = T1,
) -> Encounter:
    return Encounter(
        id=enc_id,
        camera_id=cam_id,
        member_detection_ids=det_ids,
        start_time=start,
        end_time=end,
        rule_version="v1_time_gap_30min",
        provenance=SYNTHETIC,
    )


# ===========================================================================
# 1. TEMPORAL RULE & THRESHOLD BOUNDARY TESTS
# ===========================================================================

class TestTemporalRulesAndBoundaries:
    """Tests temporal rule evaluation, thresholds, and boundary inclusion."""

    def test_same_species_different_cameras_within_threshold(self):
        """Encounter pair within max_temporal_separation_seconds matches."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        # enc_01: 08:00 - 08:30; enc_02: 08:45 - 09:00 -> nominal gap: 15 min = 900s
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T0 + timedelta(minutes=30))
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0 + timedelta(minutes=45), T0 + timedelta(minutes=60))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(max_temporal_separation_seconds=1800.0)  # 30 min max gap
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.OK
        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 1
        assert res.returned_pairs_count == 1
        assoc = res.associations[0]
        assert assoc.association_id == "assoc:enc_01::enc_02"
        assert assoc.shared_taxa == ["canis_latrans"]
        assert assoc.nominal_gap_seconds == 900.0
        assert assoc.effective_gap_seconds == 900.0
        assert assoc.temporal_relation == "disjoint"
        assert assoc.observed_interval_order == "A_before_B"

    def test_outside_temporal_threshold_excluded(self):
        """Encounter pair with gap > max_temporal_separation_seconds is excluded."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        # Gap is 2 hours = 7200s
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T0 + timedelta(minutes=30))
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0 + timedelta(hours=2, minutes=30), T0 + timedelta(hours=3))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(max_temporal_separation_seconds=3600.0)  # 1 hour max gap
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.OK
        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 0
        assert res.associations == []

    def test_exact_threshold_boundary_included(self):
        """gap == max_temporal_separation_seconds must be included (boundary inclusion)."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "puma_concolor")
        d2 = _det("det_02", "obs_02", "puma_concolor")
        # enc_01 ends at 08:30; enc_02 starts at 09:30 -> exact gap = 3600s
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T0 + timedelta(minutes=30))
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0 + timedelta(minutes=90), T0 + timedelta(minutes=120))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(max_temporal_separation_seconds=3600.0)
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 1
        assert res.associations[0].nominal_gap_seconds == 3600.0

    def test_overlapping_intervals_gap_zero(self):
        """Overlapping intervals have gap=0, relation='overlapping', and no movement order asserted."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "lynx_rufus")
        d2 = _det("det_02", "obs_02", "lynx_rufus")
        # enc_01: 08:00 - 08:30; enc_02: 08:15 - 08:45 (overlap 08:15 to 08:30)
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T0 + timedelta(minutes=30))
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0 + timedelta(minutes=15), T0 + timedelta(minutes=45))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(max_temporal_separation_seconds=3600.0)
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assoc = res.associations[0]
        assert assoc.nominal_gap_seconds == 0.0
        assert assoc.effective_gap_seconds == 0.0
        assert assoc.temporal_relation == "overlapping"
        assert assoc.observed_interval_order == "overlapping"

    def test_same_timestamp_different_timezone_offsets(self):
        """Encounters with same wall-clock instant in different timezone offsets compare accurately."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")

        # 08:00 UTC == 13:30 IST (+05:30)
        ist = timezone(timedelta(hours=5, minutes=30))
        t_utc = datetime(2026, 10, 15, 8, 0, 0, tzinfo=UTC)
        t_ist = datetime(2026, 10, 15, 13, 30, 0, tzinfo=ist)

        e1 = _enc("enc_01", "cam_01", ["det_01"], t_utc, t_utc + timedelta(minutes=10))
        e2 = _enc("enc_02", "cam_02", ["det_02"], t_ist + timedelta(minutes=20), t_ist + timedelta(minutes=30))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        # Gap should be 10 minutes (600s) between 08:10 UTC and 08:20 UTC
        req = CrossCameraAssociationRequest(max_temporal_separation_seconds=1800.0)
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 1
        assert res.associations[0].nominal_gap_seconds == 600.0

    def test_missing_timestamps_reported_as_exclusions_and_partial(self):
        """Encounter missing timestamps is excluded with reason and status is PARTIAL."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        # e2 has no timestamps
        e2 = Encounter(
            id="enc_02",
            camera_id="cam_02",
            member_detection_ids=["det_02"],
            rule_version="v1_time_gap_30min",
        )

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.PARTIAL
        assert resp.excluded_records_count == 1
        assert any("missing timestamp" in r.lower() for r in resp.exclusion_reasons)


# ===========================================================================
# 2. CLOCK COMPARABILITY POLICY & UNCERTAINTY TESTS
# ===========================================================================

class TestClockComparabilityAndUncertainty:
    """Tests explicit clock comparability policies and uncertainty propagation."""

    def test_unknown_clock_comparability_returns_insufficient_data(self):
        """When clock_comparability_policy is UNKNOWN, association returns INSUFFICIENT_DATA."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T1, T2)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(
            clock_comparability_policy=ClockComparabilityPolicy.UNKNOWN
        )
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.INSUFFICIENT_DATA
        assert any("clock comparability policy is unknown" in lim.lower() for lim in resp.limitations)
        assert resp.result is None

    def test_explicit_analyst_assumption_disclosed(self):
        """clock_comparability_policy=ANALYST_ASSUMPTION proceeds and discloses assumption."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T1, T2)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(
            clock_comparability_policy=ClockComparabilityPolicy.ANALYST_ASSUMPTION
        )
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.OK
        assert any("analyst assumption" in lim.lower() for lim in resp.limitations)

    def test_clock_uncertainty_propagated_conservatively(self):
        """Clock uncertainty reduces nominal gap conservatively: effective_gap = max(0, nominal - uncertainty)."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        # enc_01: 08:00 - 08:30; enc_02: 09:35 - 10:00 -> nominal gap = 65 min = 3900s
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T0 + timedelta(minutes=30))
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0 + timedelta(minutes=95), T0 + timedelta(minutes=120))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        # With max_gap = 3600s, nominal_gap=3900s would normally fail!
        # But with clock_uncertainty = 600s (10 min), effective_gap = 3900 - 600 = 3300s <= 3600s -> PASSES!
        req = CrossCameraAssociationRequest(
            max_temporal_separation_seconds=3600.0,
            clock_uncertainty_seconds=600.0,
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"timestamps_pre_corrected": True, "correction_provenance": "field_audit_20261015"},
        )
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 1
        assoc = res.associations[0]
        assert assoc.nominal_gap_seconds == 3900.0
        assert assoc.min_possible_gap_seconds == 3300.0
        assert assoc.max_possible_gap_seconds == 4500.0
        assert assoc.effective_gap_seconds == 3300.0
        assert assoc.temporal_eligibility == "possibly_within_threshold"

    def test_offsets_known_without_evidence_returns_insufficient_data(self):
        """OFFSETS_KNOWN without accompanying clock_offsets or pre-corrected timestamps returns INSUFFICIENT_DATA."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T1, T2)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        # Selected enum alone without offsets or pre-correction
        req = CrossCameraAssociationRequest(
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            clock_uncertainty_seconds=0.0,
        )
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.INSUFFICIENT_DATA
        assert any("offsets_known" in lim.lower() for lim in resp.limitations)
        assert resp.result is None

    def test_positive_uncertainty_alone_does_not_satisfy_offsets_known(self):
        """Positive uncertainty bound alone does NOT satisfy OFFSETS_KNOWN without offsets or pre-correction."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T1, T2)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        # clock_uncertainty_seconds > 0 supplied, but no offsets or pre-correction flag
        req = CrossCameraAssociationRequest(
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            clock_uncertainty_seconds=300.0,
        )
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.INSUFFICIENT_DATA
        assert any("uncertainty bounds alone do not constitute offset corrections" in lim.lower() for lim in resp.limitations)
        assert resp.result is None

    def test_offsets_known_with_clock_offsets_param_proceeds(self):
        """OFFSETS_KNOWN with clock_offsets parameter proceeds with OK."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T1, T2)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"clock_offsets": {"cam_01": 0.0, "cam_02": 2.5}},
        )
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.OK
        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 1
        assert res.clock_offsets_applied == {"cam_01": 0.0, "cam_02": 2.5}

    def test_offsets_known_with_pre_corrected_flag_and_provenance_proceeds(self):
        """OFFSETS_KNOWN with timestamps_pre_corrected=True and correction_provenance proceeds with OK."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T1, T2)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"timestamps_pre_corrected": True, "correction_provenance": "NTP_audit_20261015"},
        )
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.OK
        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 1
        assert res.timestamps_pre_corrected is True
        assert res.correction_provenance == "NTP_audit_20261015"

    def test_pre_corrected_without_provenance_rejected(self):
        """Pre-corrected timestamps without correction provenance returns INSUFFICIENT_DATA."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T1, T2)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"timestamps_pre_corrected": True},  # missing correction_provenance!
        )
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.INSUFFICIENT_DATA
        assert any("correction provenance" in lim.lower() for lim in resp.limitations)

    def test_pre_corrected_timestamps_not_corrected_twice(self):
        """Supplying both clock_offsets and timestamps_pre_corrected=True is rejected as ambiguous double correction."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T1, T2)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={
                "clock_offsets": {"cam_01": 0.0, "cam_02": 5.0},
                "timestamps_pre_corrected": True,
                "correction_provenance": "audit_log",
            },
        )
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.INVALID_REQUEST
        assert any("ambiguous" in lim.lower() for lim in resp.limitations)
        assert any(e.code == "SCHEMA_VIOLATION" for e in resp.errors)

    def test_missing_required_camera_offset_rejected(self):
        """Camera with encounters in scope but missing from clock_offsets returns INSUFFICIENT_DATA."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T1, T2)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        # Only cam_01 is in clock_offsets; cam_02 is missing!
        req = CrossCameraAssociationRequest(
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"clock_offsets": {"cam_01": 0.0}},
        )
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.INSUFFICIENT_DATA
        assert any("cam_02" in lim for lim in resp.limitations)

    def test_non_finite_offset_rejected(self):
        """Non-finite clock offset value (NaN, inf) returns INVALID_REQUEST."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[_det("det_01", "obs_01", "canis_latrans"), _det("det_02", "obs_02", "canis_latrans")],
            encounters=[_enc("enc_01", "cam_01", ["det_01"], T0, T1), _enc("enc_02", "cam_02", ["det_02"], T1, T2)],
        )

        req = CrossCameraAssociationRequest(
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"clock_offsets": {"cam_01": float("nan"), "cam_02": 0.0}},
        )
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.INVALID_REQUEST
        assert any("non-finite" in lim.lower() for lim in resp.limitations)

    def test_applying_offset_changes_pair_eligibility(self):
        """Applying a per-camera clock offset changes temporal separation and pair eligibility."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")

        # enc_01: 08:00 - 08:15
        # enc_02: 09:20 - 09:35 -> Raw nominal gap = 65 min = 3900s
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T0 + timedelta(minutes=15))
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0 + timedelta(minutes=80), T0 + timedelta(minutes=95))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        # 1. With max_gap = 3600.0 (60 min) and zero offset: 3900s > 3600s -> NO MATCH
        req_no_offset = CrossCameraAssociationRequest(
            max_temporal_separation_seconds=3600.0,
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"clock_offsets": {"cam_01": 0.0, "cam_02": 0.0}},
        )
        resp_no_offset = analyze(snap, req_no_offset)
        res_no_offset = CrossCameraAssociationsResult.model_validate(resp_no_offset.result)
        assert res_no_offset.total_matching_pairs_found == 0

        # 2. Camera 2 clock was fast by 10 minutes (+600s).
        # We apply offset -600.0s to cam_02 (t_corrected = t_raw + offset).
        # Corrected enc_02 is 09:10 - 09:25.
        # Corrected gap = 09:10 - 08:15 = 55 minutes = 3300s <= 3600s -> ELIGIBLE MATCH!
        req_with_offset = CrossCameraAssociationRequest(
            max_temporal_separation_seconds=3600.0,
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"clock_offsets": {"cam_01": 0.0, "cam_02": -600.0}},
        )
        resp_with_offset = analyze(snap, req_with_offset)
        res_with_offset = CrossCameraAssociationsResult.model_validate(resp_with_offset.result)
        assert res_with_offset.total_matching_pairs_found == 1
        assoc = res_with_offset.associations[0]
        assert assoc.nominal_gap_seconds == 3300.0
        assert assoc.clock_offset_seconds_a == 0.0
        assert assoc.clock_offset_seconds_b == -600.0

    def test_corrections_that_change_chronological_order_handled_before_candidate_generation(self):
        """Offset corrections that invert the observed chronological order of encounters are handled before candidate generation."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")

        # Raw: enc_01 (cam_01) starts at 08:05, enc_02 (cam_02) starts at 08:00
        # In raw time, enc_02 was recorded before enc_01!
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0 + timedelta(minutes=5), T0 + timedelta(minutes=20))
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T0 + timedelta(minutes=15))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        # cam_01 clock was 20 minutes slow (recorded 08:05 when reference was 08:25).
        # We apply offset +1200.0s to cam_01, shifting enc_01 to 08:25 - 08:40.
        # Now enc_02 (08:00 - 08:15) is strictly BEFORE enc_01 (08:25 - 08:40)!
        # Nominal corrected gap = 08:25 - 08:15 = 10 min = 600s.
        req = CrossCameraAssociationRequest(
            max_temporal_separation_seconds=1800.0,
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"clock_offsets": {"cam_01": 1200.0, "cam_02": 0.0}},
        )
        resp = analyze(snap, req)
        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 1
        assoc = res.associations[0]
        # enc_01 is enc_a (id_1), enc_02 is enc_b (id_2) by canonical ID sorting:
        # Since enc_02 (08:00-08:15) ends before enc_01 (08:25-08:40), order is B_before_A!
        assert assoc.nominal_gap_seconds == 600.0
        assert assoc.observed_interval_order == "B_before_A"
        assert assoc.temporal_relation == "disjoint"

    def test_clock_uncertainty_pairwise_bound_and_gap_range(self):
        """
        Verifies clock_uncertainty_seconds represents combined pairwise uncertainty bound U_pair = u_A + u_B.
        Verifies possible gap range [max(0, G - U_pair), G + U_pair] and temporal_eligibility classification.
        """
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")

        # Camera A uncertainty u_A = 120s, Camera B uncertainty u_B = 180s -> U_pair = 300s
        u_pair = 120.0 + 180.0  # 300s

        # Enc 1: 08:00 - 08:30 (1800s duration)
        # Enc 2: 08:40 - 09:00 (nominal gap = 10 min = 600s)
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T0 + timedelta(minutes=30))
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0 + timedelta(minutes=40), T0 + timedelta(minutes=60))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        # 1. When max_temporal_separation_seconds = 1000s:
        # Nominal gap = 600s, min_possible_gap = 600 - 300 = 300s, max_possible_gap = 600 + 300 = 900s.
        # Since max_possible_gap (900s) <= 1000s, eligibility is "definitely_within_threshold".
        req_def = CrossCameraAssociationRequest(
            max_temporal_separation_seconds=1000.0,
            clock_uncertainty_seconds=u_pair,
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"timestamps_pre_corrected": True, "correction_provenance": "calibrated_clocks_2026"},
        )
        resp_def = analyze(snap, req_def)
        res_def = CrossCameraAssociationsResult.model_validate(resp_def.result)
        assoc_def = res_def.associations[0]

        assert assoc_def.nominal_gap_seconds == 600.0
        assert assoc_def.min_possible_gap_seconds == 300.0
        assert assoc_def.max_possible_gap_seconds == 900.0
        assert assoc_def.effective_gap_seconds == 300.0
        assert assoc_def.temporal_eligibility == "definitely_within_threshold"
        assert "definitely_within_threshold" in assoc_def.explanation

        # 2. When max_temporal_separation_seconds = 500s:
        # min_possible_gap (300s) <= 500s < max_possible_gap (900s).
        # Eligibility is "possibly_within_threshold" (not definitely within threshold).
        req_pos = CrossCameraAssociationRequest(
            max_temporal_separation_seconds=500.0,
            clock_uncertainty_seconds=u_pair,
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"timestamps_pre_corrected": True, "correction_provenance": "calibrated_clocks_2026"},
        )
        resp_pos = analyze(snap, req_pos)
        res_pos = CrossCameraAssociationsResult.model_validate(resp_pos.result)
        assoc_pos = res_pos.associations[0]

        assert assoc_pos.temporal_eligibility == "possibly_within_threshold"
        assert "possibly_within_threshold" in assoc_pos.explanation


# ===========================================================================
# 3. CAMERA & PAIR DEDUPLICATION TESTS
# ===========================================================================

class TestCameraAndPairDeduplication:
    """Verifies same camera exclusion, self-pairs, and canonical pair deduplication."""

    def test_same_camera_pair_excluded(self):
        """Encounters recorded at the SAME physical camera are excluded."""
        c1 = _cam("cam_01")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_01", ["det_02"], T1, T2)  # also cam_01!

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_01")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 0

    def test_self_pair_excluded(self):
        """An encounter cannot associate with itself."""
        c1 = _cam("cam_01")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1],
            observations=[_obs("obs_01", "cam_01")],
            detections=[d1],
            encounters=[e1],
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 0

    def test_mirrored_pair_deduplication(self):
        """Only one canonical association 'assoc:enc_01::enc_02' is generated, never mirrored duplicates."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 1
        assoc_ids = [a.association_id for a in res.associations]
        assert assoc_ids == ["assoc:enc_01::enc_02"]
        assert "assoc:enc_02::enc_01" not in assoc_ids


# ===========================================================================
# 4. SPECIES ELIGIBILITY, REVIEWS & MULTI-SPECIES ENCOUNTERS
# ===========================================================================

class TestSpeciesEligibilityAndReviews:
    """Verifies label resolution, review overrides, and multi-species deduplication."""

    def test_repeated_same_species_detections_deduplicated_within_encounter(self):
        """Repeated detections of the same species in an encounter count as 1 species instance."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        # enc_01 has 3 separate detections of coyote
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_01", "canis_latrans")
        d3 = _det("det_03", "obs_01", "canis_latrans")
        d4 = _det("det_04", "obs_02", "canis_latrans")

        e1 = _enc("enc_01", "cam_01", ["det_01", "det_02", "det_03"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_04"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2, d3, d4],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 1
        assoc = res.associations[0]
        assert assoc.shared_taxa == ["canis_latrans"]
        assert assoc.detection_ids_a == ["det_01", "det_02", "det_03"]

    def test_multi_species_encounters_record_all_shared_taxa_without_duplicate_pairs(self):
        """Encounter sharing multiple species records all shared taxa in a single association."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        # enc_01 has coyote + bobcat
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_01", "lynx_rufus")
        # enc_02 also has coyote + bobcat
        d3 = _det("det_03", "obs_02", "canis_latrans")
        d4 = _det("det_04", "obs_02", "lynx_rufus")

        e1 = _enc("enc_01", "cam_01", ["det_01", "det_02"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_03", "det_04"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2, d3, d4],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 1
        assoc = res.associations[0]
        assert assoc.shared_taxa == ["canis_latrans", "lynx_rufus"]

    def test_unknown_taxa_do_not_match_each_other(self):
        """Two encounters with 'unknown' species do NOT associate with each other."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", None)  # unknown animal
        d2 = _det("det_02", "obs_02", None)  # unknown animal

        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 0

    def test_reviewed_correction_updates_association(self):
        """Human review correcting species updates encounter species and association eligibility."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        c3 = _cam("cam_03")

        # det_01 was predicted coyote, but corrected to bobcat!
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        d3 = _det("det_03", "obs_03", "lynx_rufus")

        rev = ReviewEvent(
            id="rev_01",
            target_id="det_01",
            decision=ReviewDecision.CORRECT_SPECIES,
            corrected_taxon_id="lynx_rufus",
            sequence_number=1,
            reviewer="expert_shravan",
            created_at=T0,
        )

        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T1)
        e3 = _enc("enc_03", "cam_03", ["det_03"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2, c3],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02"), _obs("obs_03", "cam_03")],
            detections=[d1, d2, d3],
            reviews=[rev],
            encounters=[e1, e2, e3],
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        # enc_01 (now bobcat) must associate with enc_03 (bobcat), NOT enc_02 (coyote)!
        assoc_ids = [a.association_id for a in res.associations]
        assert "assoc:enc_01::enc_03" in assoc_ids
        assert "assoc:enc_01::enc_02" not in assoc_ids

    def test_rejected_detection_and_ambiguous_review_excluded(self):
        """Rejected detections and ambiguous review conflicts do not contribute to species matching."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")

        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")

        # Review rejects det_01
        rev = ReviewEvent(
            id="rev_01",
            target_id="det_01",
            decision=ReviewDecision.REJECT_DETECTION,
            sequence_number=1,
            reviewer="reviewer_1",
            created_at=T0,
        )

        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            reviews=[rev],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 0


# ===========================================================================
# 5. MULTIPLE ALTERNATIVES & NO TRANSITIVE IDENTITY
# ===========================================================================

class TestNonGreedyAndNoTransitivity:
    """Verifies that all plausible candidate pairs are retained (no greedy 1-1 matching) and no transitive claims."""

    def test_multiple_plausible_matches_retained_no_greedy_matching(self):
        """One encounter can associate with multiple other encounters; no greedy winner-take-all."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        c3 = _cam("cam_03")

        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        d3 = _det("det_03", "obs_03", "canis_latrans")

        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T0 + timedelta(minutes=15))
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0 + timedelta(minutes=20), T0 + timedelta(minutes=35))
        e3 = _enc("enc_03", "cam_03", ["det_03"], T0 + timedelta(minutes=25), T0 + timedelta(minutes=40))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2, c3],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02"), _obs("obs_03", "cam_03")],
            detections=[d1, d2, d3],
            encounters=[e1, e2, e3],
        )

        req = CrossCameraAssociationRequest(max_temporal_separation_seconds=3600.0)
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        # All 3 pairwise combinations must be returned: (1,2), (1,3), (2,3)
        assert res.total_matching_pairs_found == 3
        assoc_ids = {a.association_id for a in res.associations}
        assert assoc_ids == {"assoc:enc_01::enc_02", "assoc:enc_01::enc_03", "assoc:enc_02::enc_03"}

    def test_no_transitive_identity_or_encounter_merging(self):
        """Associations do not merge encounter records or alter Phase 2 encounter IDs."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        resp = analyze(snap, CrossCameraAssociationRequest())
        res = CrossCameraAssociationsResult.model_validate(resp.result)
        # Encounters remain separate and distinct
        assert len(snap.encounters) == 2
        assert snap.encounters[0].id == "enc_01"
        assert snap.encounters[1].id == "enc_02"
        assert any("individual animal identity and movement are not established" in a.disclaimer for a in res.associations)


# ===========================================================================
# 6. SPATIAL MODES & GEODESIC DISTANCE TESTS
# ===========================================================================

class TestSpatialModesAndGeodesic:
    """Verifies all three spatial modes and Haversine geodesic calculations."""

    def test_haversine_formula_accuracy(self):
        """Verifies Haversine formula against known geographical coordinates."""
        # San Francisco (37.7749, -122.4194) to Los Angeles (34.0522, -118.2437) ~ 559 km
        dist = haversine_distance_meters(37.7749, -122.4194, 34.0522, -118.2437)
        assert 550_000 < dist < 570_000  # ~559 km

        # Same point distance is 0.0
        assert haversine_distance_meters(37.0, -122.0, 37.0, -122.0) == 0.0

    def test_time_species_only_spatial_not_evaluated(self):
        """time_species_only mode does not require coordinates and reports not_evaluated."""
        c1 = _cam("cam_01")  # no lat/lon
        c2 = _cam("cam_02")  # no lat/lon
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(spatial_mode=SpatialMode.TIME_SPECIES_ONLY)
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assoc = res.associations[0]
        assert assoc.spatial_check_status == "not_evaluated"
        assert assoc.camera_distance_meters is None
        assert "spatial feasibility was not evaluated" in assoc.spatial_note

    def test_spatial_when_available_with_gps_measures_distance(self):
        """spatial_when_available measures distance when coordinates exist."""
        # 1 degree latitude ~ 111 km = 111,000m
        c1 = _cam("cam_01", lat=34.0, lon=-118.0)
        c2 = _cam("cam_02", lat=34.01, lon=-118.0)  # ~1.11 km apart
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(
            spatial_mode=SpatialMode.SPATIAL_WHEN_AVAILABLE,
            max_spatial_distance_meters=2000.0,  # 2km threshold
        )
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assoc = res.associations[0]
        assert assoc.spatial_check_status == "passed"
        assert 1000.0 < assoc.camera_distance_meters < 1200.0
        assert assoc.spatial_units == "meters"
        assert "Camera separation is not animal travel distance" in assoc.spatial_note

    def test_spatial_when_available_without_gps_retains_candidate_as_unavailable(self):
        """spatial_when_available retains candidate without GPS as spatial_check_status='unavailable'."""
        c1 = _cam("cam_01")  # no GPS
        c2 = _cam("cam_02")  # no GPS
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(
            spatial_mode=SpatialMode.SPATIAL_WHEN_AVAILABLE,
            max_spatial_distance_meters=2000.0,
        )
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 1
        assoc = res.associations[0]
        assert assoc.spatial_check_status == "unavailable"
        assert assoc.camera_distance_meters is None
        assert "Camera distance is unknown or not evaluated" in assoc.spatial_note

    def test_spatial_required_missing_all_coordinates_returns_unavailable(self):
        """When spatial_mode=SPATIAL_REQUIRED and no cameras have GPS, returns UNAVAILABLE."""
        c1 = _cam("cam_01")  # no GPS
        c2 = _cam("cam_02")  # no GPS
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        req = CrossCameraAssociationRequest(spatial_mode=SpatialMode.SPATIAL_REQUIRED)
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.UNAVAILABLE
        assert any("spatial coordinates" in lim.lower() for lim in resp.limitations)

    def test_spatial_distance_threshold_boundary(self):
        """Pairs exceeding max_spatial_distance_meters are excluded."""
        c1 = _cam("cam_01", lat=34.0, lon=-118.0)
        c2 = _cam("cam_02", lat=34.1, lon=-118.0)  # ~11.1 km apart
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        # Distance is ~11.1km; max_spatial_distance is 5km -> EXCLUDED!
        req = CrossCameraAssociationRequest(
            spatial_mode=SpatialMode.SPATIAL_WHEN_AVAILABLE,
            max_spatial_distance_meters=5000.0,
        )
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 0


# ===========================================================================
# 7. ENCOUNTER PROCESSING STATES & EMPTY DATASETS
# ===========================================================================

class TestEncounterProcessingStatuses:
    """Verifies behavior on COMPLETED (empty), PENDING, FAILED, and UNAVAILABLE statuses."""

    def test_completed_with_zero_encounters_returns_valid_zero(self):
        """Encounter grouping COMPLETED with 0 encounters returns valid empty result with status OK."""
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.COMPLETED),
            cameras=[_cam("cam_01"), _cam("cam_02")],
            encounters=[],
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.OK
        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 0
        assert res.associations == []

    def test_pending_grouping_returns_unavailable(self):
        """Encounter grouping PENDING returns UNAVAILABLE."""
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.PENDING),
            cameras=[_cam("cam_01"), _cam("cam_02")],
            encounters=[],
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.UNAVAILABLE
        assert any("pending" in lim.lower() for lim in resp.limitations)

    def test_failed_grouping_returns_unavailable(self):
        """Encounter grouping FAILED returns UNAVAILABLE."""
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.FAILED),
            cameras=[_cam("cam_01"), _cam("cam_02")],
            encounters=[],
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.UNAVAILABLE
        assert any("failed" in lim.lower() for lim in resp.limitations)


# ===========================================================================
# 8. RESULT LIMITS VS EVALUATION LIMITS
# ===========================================================================

class TestResultAndEvaluationLimits:
    """Verifies separation of result_limit (top-k) and evaluation_limit (bounded coverage)."""

    def test_result_limit_returns_bounded_results_with_status_ok(self):
        """result_limit bounds returned items without marking response partial."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        c3 = _cam("cam_03")

        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        d3 = _det("det_03", "obs_03", "canis_latrans")

        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T0 + timedelta(minutes=10))
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0 + timedelta(minutes=15), T0 + timedelta(minutes=25))
        e3 = _enc("enc_03", "cam_03", ["det_03"], T0 + timedelta(minutes=20), T0 + timedelta(minutes=30))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2, c3],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02"), _obs("obs_03", "cam_03")],
            detections=[d1, d2, d3],
            encounters=[e1, e2, e3],
        )

        # 3 total matching pairs: (1,2), (1,3), (2,3). Request result_limit=1
        req = CrossCameraAssociationRequest(result_limit=1)
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.OK
        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 3
        assert res.returned_pairs_count == 1
        assert len(res.associations) == 1
        assert res.is_coverage_complete is True

    def test_evaluation_limit_bounds_work_and_sets_status_partial(self):
        """evaluation_limit bounds pair simulation, marks is_coverage_complete=False, and sets status to PARTIAL."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        c3 = _cam("cam_03")

        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        d3 = _det("det_03", "obs_03", "canis_latrans")

        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T0 + timedelta(minutes=10))
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0 + timedelta(minutes=15), T0 + timedelta(minutes=25))
        e3 = _enc("enc_03", "cam_03", ["det_03"], T0 + timedelta(minutes=20), T0 + timedelta(minutes=30))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2, c3],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02"), _obs("obs_03", "cam_03")],
            detections=[d1, d2, d3],
            encounters=[e1, e2, e3],
        )

        req = CrossCameraAssociationRequest(evaluation_limit=1)
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.PARTIAL
        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.is_coverage_complete is False
        assert any("coverage is incomplete" in lim.lower() for lim in resp.limitations)


# ===========================================================================
# 9. REVISIONS, IMMUTABILITY & JSON SERIALIZATION
# ===========================================================================

class TestRevisionsAndImmutability:
    """Verifies revision conflict handling, snapshot immutability, and JSON serialization."""

    def test_revision_mismatch_returns_invalid_request(self):
        """expected_revision mismatch returns INVALID_REQUEST."""
        snap = Snapshot(
            metadata=_meta(revision=5),
            cameras=[_cam("cam_01")],
        )

        req = CrossCameraAssociationRequest(expected_revision=3)
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.INVALID_REQUEST
        assert any(e.code == "SCHEMA_VIOLATION" for e in resp.errors)

    def test_snapshot_immutability(self):
        """Running association correlation does not mutate the original snapshot or encounters."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        snap_copy = copy.deepcopy(snap)
        analyze(snap, CrossCameraAssociationRequest())

        assert snap.model_dump() == snap_copy.model_dump()

    def test_json_serialization_roundtrip(self):
        """CrossCameraAssociation result and response serialize cleanly to standard JSON."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0, T1)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        resp = analyze(snap, CrossCameraAssociationRequest())
        serialized = json.dumps(resp.model_dump(mode="json"))
        deserialized = json.loads(serialized)

        assert deserialized["status"] == "ok"
        assert deserialized["metric"] == "cross_camera_associations"
        assert len(deserialized["result"]["associations"]) == 1


# ===========================================================================
# 10. EXHAUSTIVE VS OPTIMIZED PARITY CHECK
# ===========================================================================

class TestExhaustiveVsOptimizedParity:
    """Verifies that the sliding-window optimized pair generator matches the exhaustive reference."""

    def test_sliding_window_parity_with_exhaustive_generator(self):
        """Optimized sliding-window generator produces identical matches to exhaustive reference."""
        # 4 cameras, 6 encounters at staggered times with mixed species
        cams = [_cam(f"cam_0{i}") for i in range(1, 5)]
        detections = []
        encounters = []
        observations = []

        taxa_choices = [
            ["canis_latrans"],
            ["lynx_rufus"],
            ["canis_latrans", "lynx_rufus"],
            ["canis_latrans"],
            ["puma_concolor"],
            ["canis_latrans"],
        ]

        # Staggered start times: 08:00, 08:20, 08:45, 09:10, 09:40, 10:15
        base_time = datetime(2026, 10, 15, 8, 0, 0, tzinfo=UTC)
        offsets = [0, 20, 45, 70, 100, 135]

        for i in range(6):
            eid = f"enc_0{i+1}"
            cid = f"cam_0{(i % 4) + 1}"
            oid = f"obs_0{i+1}"
            observations.append(_obs(oid, cid, base_time + timedelta(minutes=offsets[i])))

            e_dets = []
            for sp in taxa_choices[i]:
                did = f"det_{eid}_{sp}"
                detections.append(_det(did, oid, sp))
                e_dets.append(did)

            start = base_time + timedelta(minutes=offsets[i])
            end = start + timedelta(minutes=15)
            encounters.append(_enc(eid, cid, e_dets, start, end))

        snap = Snapshot(
            metadata=_meta(),
            cameras=cams,
            observations=observations,
            detections=detections,
            encounters=encounters,
        )

        req = CrossCameraAssociationRequest(
            max_temporal_separation_seconds=1800.0,  # 30 min max gap
            result_limit=100,
        )

        # 1. Run exhaustive reference implementation
        exhaustive_matches = _exhaustive_pairwise_associations(snap, req)

        # 2. Run optimized sliding-window implementation
        resp_opt = analyze(snap, req)
        res_opt = CrossCameraAssociationsResult.model_validate(resp_opt.result)
        optimized_matches = sorted(a.association_id for a in res_opt.associations)

        assert optimized_matches == exhaustive_matches, (
            f"Optimized generator ({len(optimized_matches)} matches) did not match "
            f"exhaustive generator ({len(exhaustive_matches)} matches)."
        )

    def test_sliding_window_parity_with_nonzero_uncertainty_and_overlapping_encounters(self):
        """
        Optimized sliding-window generator matches exhaustive reference exactly when:
        1) Clock uncertainty is non-zero (so candidates become eligible solely due to uncertainty).
        2) Encounters have long overlapping spans across multiple other encounters.
        """
        cams = [_cam(f"cam_0{i}") for i in range(1, 5)]
        detections = []
        encounters = []
        observations = []

        base_time = datetime(2026, 10, 15, 8, 0, 0, tzinfo=UTC)

        # enc_01 on cam_01 is a long encounter (3 hours long) from 08:00 to 11:00
        # Other encounters on cam_02, cam_03, cam_04 occur at different times inside and outside this window
        enc_specs = [
            # eid, cid, start_min, duration_min, taxon
            ("enc_01", "cam_01", 0, 180, "canis_latrans"),    # 08:00 - 11:00 (spans 3 hrs!)
            ("enc_02", "cam_02", 30, 20, "canis_latrans"),     # 08:30 - 08:50 (inside enc_01 window)
            ("enc_03", "cam_03", 90, 15, "canis_latrans"),     # 09:30 - 09:45 (inside enc_01 window)
            ("enc_04", "cam_04", 200, 20, "canis_latrans"),    # 11:20 - 11:40 (nominal gap to enc_01: 20 min = 1200s)
            ("enc_05", "cam_02", 230, 15, "canis_latrans"),    # 11:50 - 12:05 (nominal gap to enc_04: 10 min = 600s)
            ("enc_06", "cam_03", 260, 20, "canis_latrans"),    # 12:20 - 12:40 (nominal gap to enc_05: 15 min = 900s)
        ]

        for eid, cid, start_m, dur_m, taxon in enc_specs:
            start_dt = base_time + timedelta(minutes=start_m)
            end_dt = start_dt + timedelta(minutes=dur_m)
            oid = f"obs_{eid}"
            did = f"det_{eid}"
            observations.append(_obs(oid, cid, start_dt))
            detections.append(_det(did, oid, taxon))
            encounters.append(_enc(eid, cid, [did], start_dt, end_dt))

        snap = Snapshot(
            metadata=_meta(),
            cameras=cams,
            observations=observations,
            detections=detections,
            encounters=encounters,
        )

        # max_gap = 900s (15 min).
        # Between enc_01 (ends 11:00) and enc_04 (starts 11:20), nominal gap is 20 min = 1200s.
        # With clock_uncertainty = 400s, min_possible_gap = 1200 - 400 = 800s <= 900s -> BECOMES ELIGIBLE!
        req = CrossCameraAssociationRequest(
            max_temporal_separation_seconds=900.0,
            clock_uncertainty_seconds=400.0,
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"timestamps_pre_corrected": True, "correction_provenance": "calibrated_network_2026"},
            result_limit=100,
        )

        exhaustive_matches = _exhaustive_pairwise_associations(snap, req)
        resp_opt = analyze(snap, req)
        res_opt = CrossCameraAssociationsResult.model_validate(resp_opt.result)
        optimized_matches = sorted(a.association_id for a in res_opt.associations)

        assert optimized_matches == exhaustive_matches, (
            f"Mismatch between optimized ({len(optimized_matches)}) and exhaustive ({len(exhaustive_matches)}): "
            f"opt={optimized_matches}, exh={exhaustive_matches}"
        )
        assert "assoc:enc_01::enc_04" in optimized_matches

    def test_optimized_and_exhaustive_agree_after_clock_offset_correction(self):
        """Optimized sliding-window and exhaustive generator agree exactly after applying per-camera clock offsets."""
        cams = [_cam(f"cam_0{i}") for i in range(1, 5)]
        detections = []
        encounters = []
        observations = []

        base_time = datetime(2026, 10, 15, 8, 0, 0, tzinfo=UTC)

        # 4 cameras with varying offsets:
        # cam_01: -300s, cam_02: +150s, cam_03: -60s, cam_04: +200s
        clock_offsets = {
            "cam_01": -300.0,
            "cam_02": 150.0,
            "cam_03": -60.0,
            "cam_04": 200.0,
        }

        enc_specs = [
            ("enc_01", "cam_01", 0, 20, "canis_latrans"),
            ("enc_02", "cam_02", 25, 20, "canis_latrans"),
            ("enc_03", "cam_03", 40, 25, "canis_latrans"),
            ("enc_04", "cam_04", 60, 20, "canis_latrans"),
            ("enc_05", "cam_01", 80, 20, "canis_latrans"),
            ("enc_06", "cam_03", 95, 20, "canis_latrans"),
        ]

        for eid, cid, start_m, dur_m, taxon in enc_specs:
            start_dt = base_time + timedelta(minutes=start_m)
            end_dt = start_dt + timedelta(minutes=dur_m)
            oid = f"obs_{eid}"
            did = f"det_{eid}"
            observations.append(_obs(oid, cid, start_dt))
            detections.append(_det(did, oid, taxon))
            encounters.append(_enc(eid, cid, [did], start_dt, end_dt))

        snap = Snapshot(
            metadata=_meta(),
            cameras=cams,
            observations=observations,
            detections=detections,
            encounters=encounters,
        )

        req = CrossCameraAssociationRequest(
            max_temporal_separation_seconds=1200.0,
            clock_uncertainty_seconds=100.0,
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"clock_offsets": clock_offsets},
            result_limit=100,
        )

        exhaustive_matches = _exhaustive_pairwise_associations(snap, req)
        resp_opt = analyze(snap, req)
        res_opt = CrossCameraAssociationsResult.model_validate(resp_opt.result)
        optimized_matches = sorted(a.association_id for a in res_opt.associations)

        assert optimized_matches == exhaustive_matches, (
            f"Offset parity failure: opt={optimized_matches}, exh={exhaustive_matches}"
        )
        assert len(optimized_matches) > 0

    def test_source_snapshot_not_mutated_by_offset_application(self):
        """Applying clock offsets does not mutate encounter timestamps in the original snapshot."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T1, T2)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        orig_start_1 = e1.start_time
        orig_end_1 = e1.end_time

        req = CrossCameraAssociationRequest(
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"clock_offsets": {"cam_01": 3600.0, "cam_02": -1800.0}},
        )
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.OK

        # Verify original encounter objects in snapshot remain untouched
        assert e1.start_time == orig_start_1
        assert e1.end_time == orig_end_1

    def test_exact_extrema_gap_range_for_overlapping_intervals(self):
        """
        For overlapping intervals, [max(0, G-U), G+U] gives a loose upper bound G+U = U.
        The exact attainable supremum max(0.0, (s_2-e_1)+U, (s_1-e_2)+U) correctly reflects
        the true maximum gap under clock uncertainty.
        """
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")

        # enc_01: 08:00 - 10:00 (2 hours long)
        # enc_02: 08:30 - 09:00 (30 min long, nested completely inside enc_01)
        # Nominal gap G = 0.0s.
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T0 + timedelta(hours=2))
        e2 = _enc("enc_02", "cam_02", ["det_02"], T0 + timedelta(minutes=30), T0 + timedelta(minutes=60))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        # Under uncertainty U = 600s (10 min), enc_02 can shift at most +-10 min.
        # It remains entirely within [08:00, 10:00] for all u in [-600, +600]!
        # The true maximum possible gap is EXACTLY 0.0s, NOT 600.0s!
        req = CrossCameraAssociationRequest(
            max_temporal_separation_seconds=3600.0,
            clock_uncertainty_seconds=600.0,
            clock_comparability_policy=ClockComparabilityPolicy.OFFSETS_KNOWN,
            parameters={"timestamps_pre_corrected": True, "correction_provenance": "GPS_sync"},
        )
        resp = analyze(snap, req)
        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assoc = res.associations[0]

        assert assoc.nominal_gap_seconds == 0.0
        assert assoc.min_possible_gap_seconds == 0.0
        assert assoc.max_possible_gap_seconds == 0.0  # Exact attainable supremum is 0.0, not G+U = 600!
        assert assoc.temporal_eligibility == "definitely_within_threshold"


# ===========================================================================
# 11. UNIFIED ANALYZE() VS DEDICATED ENTRY POINT PARITY
# ===========================================================================

class TestUnifiedAnalyzeParity:
    """Verifies direct parity between unified analyze() and find_cross_camera_associations()."""

    def test_parity_between_unified_analyze_and_find_cross_camera_associations(self):
        """Unified analyze(snapshot, AnalysisRequest) matches find_cross_camera_associations exactly."""
        c1 = _cam("cam_01")
        c2 = _cam("cam_02")
        d1 = _det("det_01", "obs_01", "canis_latrans")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], T1, T2)

        snap = Snapshot(
            metadata=_meta(),
            cameras=[c1, c2],
            observations=[_obs("obs_01", "cam_01"), _obs("obs_02", "cam_02")],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

        # 1. Unified analyze() call with AnalysisRequest and explicit clock_comparability_policy
        unified_req = AnalysisRequest(
            metric=AnalysisMetric.CROSS_CAMERA_ASSOCIATIONS,
            parameters={
                "clock_comparability_policy": "analyst_assumption",
                "max_temporal_separation_seconds": 3600.0,
                "spatial_mode": "time_species_only",
                "result_limit": 50,
            },
        )
        resp_unified = analyze(snap, unified_req)

        # 2. Dedicated find_cross_camera_associations() call with CrossCameraAssociationRequest
        dedicated_req = CrossCameraAssociationRequest(
            clock_comparability_policy=ClockComparabilityPolicy.ANALYST_ASSUMPTION,
            max_temporal_separation_seconds=3600.0,
            spatial_mode=SpatialMode.TIME_SPECIES_ONLY,
            result_limit=50,
        )
        from wildscope_analytics.analytics import find_cross_camera_associations
        resp_dedicated = find_cross_camera_associations(snap, dedicated_req)

        assert resp_unified.status == resp_dedicated.status == ResponseStatus.OK
        assert resp_unified.result["total_eligible_encounters"] == resp_dedicated.result["total_eligible_encounters"]
        assert resp_unified.result["total_candidate_pairs_evaluated"] == resp_dedicated.result["total_candidate_pairs_evaluated"]
        assert resp_unified.result["total_matching_pairs_found"] == resp_dedicated.result["total_matching_pairs_found"]
        assert resp_unified.result["returned_pairs_count"] == resp_dedicated.result["returned_pairs_count"]

        unified_ids = [a["association_id"] for a in resp_unified.result["associations"]]
        dedicated_ids = [a["association_id"] for a in resp_dedicated.result["associations"]]
        assert unified_ids == dedicated_ids


# ===========================================================================
# 11. PART B: CATEGORY MAPPING REGRESSION TEST
# ===========================================================================

class TestCategoryMappingRegression:
    """Verifies that vehicles, people, and empty frames are non-animal, and unmapped categories are not silently assumed animal."""

    def test_car_and_vehicle_are_non_animal(self, tmp_path: Path):
        """'car' and 'vehicle' must be classified as is_animal=False, is_empty=False."""
        cct_fixture = {
            "images": [
                {"id": "img_car", "file_name": "car.jpg", "location": "loc_1"},
                {"id": "img_coyote", "file_name": "coyote.jpg", "location": "loc_1"},
                {"id": "img_empty", "file_name": "empty.jpg", "location": "loc_1"},
            ],
            "categories": [
                {"id": 33, "name": "car"},
                {"id": 9, "name": "coyote"},
                {"id": 30, "name": "empty"},
            ],
            "annotations": [
                {"id": "ann_car", "image_id": "img_car", "category_id": 33},
                {"id": "ann_coyote", "image_id": "img_coyote", "category_id": 9},
                {"id": "ann_empty", "image_id": "img_empty", "category_id": 30},
            ],
        }

        ann_file = tmp_path / "cct_test_cats.json"
        ann_file.write_text(json.dumps(cct_fixture), encoding="utf-8")

        snap, report = import_caltech_snapshot(ann_file)

        assert report.categories_total == 3
        assert report.categories_animal == 1  # only coyote!
        assert report.categories_non_animal == 2  # car and empty!
        assert "33:car" not in report.categories_unmapped

        anns_by_cat = {a.category_name: a for a in snap.reference_annotations}
        assert anns_by_cat["car"].is_animal is False
        assert anns_by_cat["car"].is_empty is False
        assert anns_by_cat["empty"].is_animal is False
        assert anns_by_cat["empty"].is_empty is True
        assert anns_by_cat["coyote"].is_animal is True
        assert anns_by_cat["coyote"].wildscope_taxon_id == "canis_latrans"

    def test_caltech_category_mapping_by_source_id_and_name(self):
        """Verifies official Caltech Camera Traps source category IDs: empty is 30, car is 33."""
        from wildscope_analytics.caltech_adapter import _resolve_category

        # Test ID 30 (empty)
        taxon, is_anim, is_emp, warns = _resolve_category("empty", 30)
        assert is_anim is False
        assert is_emp is True
        assert taxon is None

        # Test ID 33 (car)
        taxon, is_anim, is_emp, warns = _resolve_category("car", 33)
        assert is_anim is False
        assert is_emp is False
        assert taxon is None

        # Test wildlife IDs: 9 (coyote), 6 (bobcat), 40 (mountain_lion)
        taxon, is_anim, is_emp, warns = _resolve_category("coyote", 9)
        assert is_anim is True
        assert is_emp is False
        assert taxon == "canis_latrans"

        taxon, is_anim, is_emp, warns = _resolve_category("bobcat", 6)
        assert is_anim is True
        assert is_emp is False
        assert taxon == "lynx_rufus"

        taxon, is_anim, is_emp, warns = _resolve_category("mountain_lion", 40)
        assert is_anim is True
        assert is_emp is False
        assert taxon == "puma_concolor"


# ===========================================================================
# 12. REAL CALTECH DATASET EXECUTION & MISSING PREREQUISITES
# ===========================================================================

class TestRealCaltechCrossCameraMissingPrerequisites:
    """Verifies honest reporting when running cross-camera association on real Caltech reference data."""

    REAL_ANNOTATION_PATH = Path("data/caltech_images_20210113.json")

    def test_real_dataset_cross_camera_association_returns_unavailable(self):
        """Cross-camera encounter associations on raw reference snapshot return UNAVAILABLE honestly."""
        if not self.REAL_ANNOTATION_PATH.exists():
            pytest.skip("Local Caltech annotation file not available.")

        snap, report = import_caltech_snapshot(
            self.REAL_ANNOTATION_PATH,
            max_images=100,
        )

        req = CrossCameraAssociationRequest()
        resp = analyze(snap, req)

        assert resp.status == ResponseStatus.UNAVAILABLE
        assert any("raw image-only reference datasets" in lim.lower() for lim in resp.limitations)
        assert resp.result is None
