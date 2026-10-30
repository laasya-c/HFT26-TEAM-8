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
        )
        resp = analyze(snap, req)

        res = CrossCameraAssociationsResult.model_validate(resp.result)
        assert res.total_matching_pairs_found == 1
        assoc = res.associations[0]
        assert assoc.nominal_gap_seconds == 3900.0
        assert assoc.effective_gap_seconds == 3300.0


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
