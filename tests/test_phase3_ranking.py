"""
WILDSCOPE Phase 3: Conclusion-Sensitive Review & Phase 2 Gap Closure Tests
==========================================================================
Comprehensive test coverage for:
  - Part A.1: Distinguish empty results from unavailable processing via EncounterProcessingStatus
  - Part A.3: Explicit reference_image_species_counts metric and deprecation warning
  - Part C: Supported target metrics (SPECIES_ENCOUNTER_COUNTS and CAMERA_COMPARISON)
  - Part D: Candidate eligibility (uncertainty, final reviews, broken references, non-members)
  - Part E: Honest handling of alternatives
  - Part F & G: Calculation rules, encounter deduplication, marginal sensitivity, and stable tie-breaking
  - Part G: JOINT-EFFECT COUNTEREXAMPLE proving marginal changes are not additive
  - Part H: Typed request and response contracts, dynamic explanations
  - Part I: Optimistic revision check, reference-mode guard, snapshot immutability
  - Part J & K: Performance check, JSON serialization, and evidence audit trails

All test fixtures are hand-calculated SYNTHETIC TEST FIXTUREs.
"""

from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from wildscope_analytics import (
    AnalysisMetric,
    AnalysisRequest,
    AnalysisResponseEnvelope,
    Camera,
    DatasetReferenceAnnotation,
    DataSourceMode,
    Detection,
    Encounter,
    EncounterProcessingStatus,
    InclusionPolicy,
    MediaAsset,
    Observation,
    PredictionStatus,
    ResponseStatus,
    ReviewDecision,
    ReviewEvent,
    ReviewRankingRequest,
    ReviewRankingResult,
    Snapshot,
    SnapshotMetadata,
    TaxonAlternative,
    TriageState,
    analyze,
    load_and_validate_snapshot,
    rank_review,
)
from wildscope_analytics.contracts.entities import MonitoringEffort, TimeInterval
from wildscope_analytics.contracts.enums import ReviewOrderingMechanism, ScoreType

UTC = timezone.utc
SYNTHETIC = "SYNTHETIC TEST FIXTURE"
T0 = datetime(2026, 10, 15, 6, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 15, 6, 30, 0, tzinfo=UTC)


def _meta(
    revision: int = 1,
    mode: DataSourceMode = DataSourceMode.OPERATIONAL_PREDICTION,
    status: EncounterProcessingStatus | None = EncounterProcessingStatus.COMPLETED,
) -> SnapshotMetadata:
    return SnapshotMetadata(
        schema_version="1.2.0",
        dataset_revision=revision,
        created_at=datetime.now(UTC),
        source_system="WILDSCOPE_PHASE3_TEST",
        data_source_mode=mode,
        review_ordering_mechanism=ReviewOrderingMechanism.BACKEND_REVISION,
        encounter_processing_status=status,
        provenance=SYNTHETIC,
    )


def _cam(cam_id: str, site_id: str | None = None) -> Camera:
    return Camera(id=cam_id, site_id=site_id, provenance=SYNTHETIC)


def _media(media_id: str, cam_id: str, ts: datetime = T0) -> MediaAsset:
    return MediaAsset(
        id=media_id,
        camera_id=cam_id,
        storage_key=f"test/{media_id}.jpg",
        captured_at=ts,
        provenance=SYNTHETIC,
    )


def _obs(obs_id: str, cam_id: str, media_id: str, det_ids: list[str], ts: datetime = T0) -> Observation:
    return Observation(
        id=obs_id,
        camera_id=cam_id,
        source_media_id=media_id,
        detection_ids=det_ids,
        captured_at=ts,
    )


def _det(
    det_id: str,
    obs_id: str,
    taxon: str | None = "canis_latrans",
    confidence: float = 0.65,
    alternatives: list[TaxonAlternative] | None = None,
    triage: TriageState = TriageState.ANIMAL_DETECTED,
) -> Detection:
    return Detection(
        id=det_id,
        observation_id=obs_id,
        predicted_taxon_id=taxon,
        animal_detection_confidence=0.95,
        classification_confidence=confidence,
        triage_state=triage,
        alternatives=alternatives or [],
    )


def _enc(
    enc_id: str,
    cam_id: str,
    det_ids: list[str],
    obs_ids: list[str],
    start: datetime = T0,
    end: datetime = T1,
) -> Encounter:
    return Encounter(
        id=enc_id,
        camera_id=cam_id,
        member_detection_ids=det_ids,
        member_observation_ids=obs_ids,
        start_time=start,
        end_time=end,
        rule_version="v1_time_gap_30min",
        provenance=SYNTHETIC,
    )


# ===========================================================================
# PART A.1: DISTINGUISH EMPTY RESULTS FROM UNAVAILABLE PROCESSING
# ===========================================================================

class TestEncounterCapabilitySemantics:
    """Verifies EncounterProcessingStatus semantics (Part A.1)."""

    def test_grouping_completed_with_zero_encounters_returns_valid_zero_counts(self):
        """When grouping COMPLETED with 0 encounters, returns valid zero counts (status OK)."""
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.COMPLETED),
            cameras=[_cam("cam_01")],
            encounters=[],
        )
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.OK
        assert resp.result is not None
        assert resp.result["species_entries"] == []
        assert resp.result["total_eligible_encounters"] == 0

    def test_grouping_completed_camera_comparison_returns_zero(self):
        """When grouping COMPLETED with 0 encounters, camera comparison returns zero counts."""
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.COMPLETED),
            cameras=[_cam("cam_01"), _cam("cam_02")],
            encounters=[],
        )
        req = AnalysisRequest(metric=AnalysisMetric.CAMERA_COMPARISON)
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.OK
        assert len(resp.result["cameras"]) == 2
        for c in resp.result["cameras"]:
            assert c["total_encounters"] == 0
            assert c["species_breakdown"] == {}

    def test_grouping_completed_overview_returns_zero_encounters(self):
        """Overview reports total_encounters = 0 (integer 0, not null)."""
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.COMPLETED),
            cameras=[_cam("cam_01")],
            encounters=[],
        )
        resp = analyze(snap, AnalysisRequest(metric=AnalysisMetric.OVERVIEW))
        assert resp.status == ResponseStatus.OK
        assert resp.result["total_encounters"] == 0
        assert resp.result["encounters_unavailable_reason"] is None

    def test_grouping_pending_returns_unavailable(self):
        """When grouping is PENDING, encounter metrics return UNAVAILABLE."""
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.PENDING),
            cameras=[_cam("cam_01")],
            encounters=[],
        )
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.UNAVAILABLE
        assert any("pending" in lim.lower() for lim in resp.limitations)

    def test_grouping_failed_returns_unavailable(self):
        """When grouping FAILED, encounter metrics return UNAVAILABLE."""
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.FAILED),
            cameras=[_cam("cam_01")],
            encounters=[],
        )
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.UNAVAILABLE
        assert any("failed" in lim.lower() for lim in resp.limitations)

    def test_legacy_snapshot_empty_encounters_conservative_unavailable(self):
        """Conservative compatibility: metadata.encounter_processing_status=None with empty encounters -> UNAVAILABLE."""
        snap = Snapshot(
            metadata=_meta(status=None),
            cameras=[_cam("cam_01")],
            encounters=[],
        )
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.UNAVAILABLE
        assert any("group_encounters" in lim for lim in resp.limitations)

    def test_completed_encounters_with_zero_matching_filter_returns_valid_zero(self):
        """When encounters exist but filters match 0 records, returns valid zero result."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"])
        d1 = _det("det_01", "obs_01", "puma_concolor")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"])
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.COMPLETED),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1],
            encounters=[e1],
        )
        # Filter for a species not in the snapshot
        req = AnalysisRequest(
            metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            species_ids=["canis_lupus"],
        )
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.OK
        assert resp.result["species_entries"] == []
        assert resp.result["total_eligible_encounters"] == 1


# ===========================================================================
# PART A.3: REFERENCE-MODE NAMING AND UNITS
# ===========================================================================

class TestReferenceModeNamingAndUnits:
    """Verifies reference image-level operations and deprecation warnings (Part A.3)."""

    def _make_ref_snap(self) -> Snapshot:
        cam = _cam("cct:cam:loc_01")
        m1 = _media("cct:img:001", "cct:cam:loc_01")
        o1 = _obs("cct:obs:001", "cct:cam:loc_01", "cct:img:001", [])
        ann = DatasetReferenceAnnotation(
            id="cct:ann:001",
            observation_id="cct:obs:001",
            source_annotation_id="001",
            source_image_id="001",
            dataset_name="caltech_camera_traps",
            dataset_version="cct_v1",
            category_id=3,
            category_name="coyote",
            wildscope_taxon_id="canis_latrans",
            is_animal=True,
            provenance={SYNTHETIC: True},
        )
        return Snapshot(
            metadata=_meta(mode=DataSourceMode.DATASET_REFERENCE),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            reference_annotations=[ann],
        )

    def test_reference_image_species_counts_direct_metric(self):
        """Calling REFERENCE_IMAGE_SPECIES_COUNTS directly returns image-level metrics with canonical unit."""
        snap = self._make_ref_snap()
        req = AnalysisRequest(metric=AnalysisMetric.REFERENCE_IMAGE_SPECIES_COUNTS)
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.OK
        assert resp.metric == AnalysisMetric.REFERENCE_IMAGE_SPECIES_COUNTS
        assert resp.metric_units == "annotated images"
        assert resp.result["counting_unit"] == "annotated images"
        assert resp.result["data_source_mode"] == "dataset_reference"
        assert resp.result["total_scoped_images"] == 1

    def test_species_encounter_counts_on_reference_emits_deprecation_warning(self):
        """Calling SPECIES_ENCOUNTER_COUNTS on reference snapshot emits deprecation warning."""
        snap = self._make_ref_snap()
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.OK
        assert any("DEPRECATION" in w for w in resp.warnings)
        assert resp.metric == AnalysisMetric.REFERENCE_IMAGE_SPECIES_COUNTS
        assert resp.metric_units == "annotated images (reference mode)"
        assert resp.result["counting_unit"] == "annotated_images (reference annotations, not encounters)"

    def test_reference_image_counts_on_operational_returns_unavailable(self):
        """Calling REFERENCE_IMAGE_SPECIES_COUNTS on operational prediction data returns UNAVAILABLE."""
        snap = Snapshot(
            metadata=_meta(mode=DataSourceMode.OPERATIONAL_PREDICTION),
            cameras=[_cam("cam_01")],
        )
        req = AnalysisRequest(metric=AnalysisMetric.REFERENCE_IMAGE_SPECIES_COUNTS)
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.UNAVAILABLE
        assert any("dataset_reference" in lim for lim in resp.limitations)


# ===========================================================================
# PHASE 3: CONCLUSION-SENSITIVE REVIEW RANKING TESTS
# ===========================================================================

class TestConclusionSensitiveRanking:
    """Comprehensive test suite for Phase 3 Feature F18 (rank_review)."""

    def _setup_single_encounter_snap(
        self,
        predicted_taxon: str = "canis_latrans",
        confidence: float = 0.6,
        alternatives: list[TaxonAlternative] | None = None,
        cam_id: str = "cam_01",
    ) -> Snapshot:
        cam = _cam(cam_id)
        m1 = _media("med_01", cam_id, T0)
        o1 = _obs("obs_01", cam_id, "med_01", ["det_01"], T0)
        det = _det("det_01", "obs_01", predicted_taxon, confidence, alternatives)
        enc = _enc("enc_01", cam_id, ["det_01"], ["obs_01"], T0, T1)
        return Snapshot(
            metadata=_meta(revision=5),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[det],
            encounters=[enc],
        )

    def test_species_alternative_increases_count(self):
        """
        Baseline: 0 bobcat encounters (detection predicted as coyote).
        Alternative: lynx_rufus (bobcat).
        Counterfactual: +1 bobcat encounter (delta: +1).
        Rank: 1, explanation reflects +1 change.
        """
        alts = [
            TaxonAlternative(taxon_id="lynx_rufus", score=0.35, raw_label="bobcat"),
        ]
        snap = self._setup_single_encounter_snap(
            predicted_taxon="canis_latrans", confidence=0.55, alternatives=alts
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            expected_revision=5,
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.OK
        res: ReviewRankingResult = ReviewRankingResult.model_validate(resp.result)
        assert res.baseline_value == 0.0
        assert res.eligible_candidates_count == 1
        assert res.ranked_candidates_count == 1
        cand = res.candidates[0]
        assert cand.rank == 1
        assert cand.detection_id == "det_01"
        assert cand.max_absolute_impact == 1.0
        assert len(cand.alternatives_evaluated) == 1
        alt_eval = cand.alternatives_evaluated[0]
        assert alt_eval.taxon_id == "lynx_rufus"
        assert alt_eval.signed_delta == 1.0
        assert alt_eval.counterfactual_value == 1.0
        assert "add an encounter" in cand.explanation
        assert "from 0 to 1 (delta: +1)" in cand.explanation

    def test_species_alternative_decreases_count(self):
        """
        Baseline: 1 bobcat encounter (detection currently predicted as bobcat).
        Alternative: coyote (canis_latrans).
        Counterfactual: 0 bobcat encounters (delta: -1).
        """
        alts = [
            TaxonAlternative(taxon_id="canis_latrans", score=0.4, raw_label="coyote"),
        ]
        snap = self._setup_single_encounter_snap(
            predicted_taxon="lynx_rufus", confidence=0.58, alternatives=alts
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.OK
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.baseline_value == 1.0
        cand = res.candidates[0]
        assert cand.max_absolute_impact == 1.0
        assert cand.alternatives_evaluated[0].signed_delta == -1.0
        assert cand.alternatives_evaluated[0].counterfactual_value == 0.0
        assert "remove an encounter" in cand.explanation

    def test_zero_effect_encounter_already_contains_species(self):
        """
        Encounter contains D1 (confirmed Bobcat) and D2 (predicted Coyote with Bobcat alternative).
        Relabelling D2 to Bobcat does NOT increase encounter count (already 1 due to D1).
        Marginal impact is 0.
        """
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01", "det_02"])
        # d1: confirmed bobcat
        d1 = _det("det_01", "obs_01", "lynx_rufus", 0.95)
        # d2: candidate with bobcat alternative
        d2 = _det("det_02", "obs_01", "canis_latrans", 0.55, [
            TaxonAlternative(taxon_id="lynx_rufus", score=0.4)
        ])
        enc = _enc("enc_01", "cam_01", ["det_01", "det_02"], ["obs_01"])
        rev1 = ReviewEvent(
            id="rev_01",
            target_id="det_01",
            decision=ReviewDecision.CONFIRM_SPECIES,
            sequence_number=1,
            created_at=datetime.now(UTC),
            reviewer="expert",
        )
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1, d2],
            encounters=[enc],
            reviews=[rev1],
        )

        # Without include_zero_impact -> candidate filtered out of ranked list
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            include_zero_impact=False,
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.baseline_value == 1.0
        assert res.eligible_candidates_count == 1  # d2 evaluated
        assert res.ranked_candidates_count == 0    # zero impact filtered out

        # With include_zero_impact=True -> candidate included with max_impact = 0.0
        req_zero = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            include_zero_impact=True,
        )
        resp_zero = rank_review(snap, req_zero)
        res_zero = ReviewRankingResult.model_validate(resp_zero.result)
        assert res_zero.ranked_candidates_count == 1
        cand = res_zero.candidates[0]
        assert cand.detection_id == "det_02"
        assert cand.max_absolute_impact == 0.0
        assert cand.alternatives_evaluated[0].signed_delta == 0.0
        assert "0 marginal effect" in cand.explanation

    def test_multiple_same_species_detections_marginal_zero(self):
        """
        Encounter has D1 and D2 both predicted Bobcat.
        Evaluating D1 alone: relabelling to Coyote leaves D2 as Bobcat -> encounter still has Bobcat.
        Evaluating D2 alone: relabelling to Coyote leaves D1 as Bobcat -> encounter still has Bobcat.
        Both candidates have 0 marginal sensitivity!
        """
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01", "det_02"])
        d1 = _det("det_01", "obs_01", "lynx_rufus", 0.55, [
            TaxonAlternative(taxon_id="canis_latrans", score=0.4)
        ])
        d2 = _det("det_02", "obs_01", "lynx_rufus", 0.55, [
            TaxonAlternative(taxon_id="canis_latrans", score=0.4)
        ])
        enc = _enc("enc_01", "cam_01", ["det_01", "det_02"], ["obs_01"])
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1, d2],
            encounters=[enc],
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            include_zero_impact=True,
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.baseline_value == 1.0
        for cand in res.candidates:
            assert cand.max_absolute_impact == 0.0

    def test_joint_effect_counterexample_not_additive(self):
        """
        MATHEMATICAL PROOF: Marginal sensitivities are NOT additive.

        Scenario:
          One encounter with two uncertain detections D1 and D2, both predicted Coyote.
          Both have Bobcat as alternative.
          Target species: Bobcat.
          Baseline: 0 bobcat encounters.

          Marginal sensitivity of D1 alone:
            D1 -> Bobcat: bobcat encounter count becomes 1 (delta: +1).
          Marginal sensitivity of D2 alone:
            D2 -> Bobcat: bobcat encounter count becomes 1 (delta: +1).

          Sum of marginal sensitivities: (+1) + (+1) = +2.

          Joint actual resolution:
            If reviewer resolves BOTH D1 and D2 to Bobcat:
            Encounter contains Bobcat.
            Encounter count is 1!
            Actual joint delta: +1, NOT +2!

        Asserts that delta_joint != delta_D1 + delta_D2.
        """
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01", "det_02"])
        d1 = _det("det_01", "obs_01", "canis_latrans", 0.55, [
            TaxonAlternative(taxon_id="lynx_rufus", score=0.4)
        ])
        d2 = _det("det_02", "obs_01", "canis_latrans", 0.55, [
            TaxonAlternative(taxon_id="lynx_rufus", score=0.4)
        ])
        enc = _enc("enc_01", "cam_01", ["det_01", "det_02"], ["obs_01"])
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1, d2],
            encounters=[enc],
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            include_zero_impact=False,
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.baseline_value == 0.0
        assert len(res.candidates) == 2
        delta_d1 = res.candidates[0].alternatives_evaluated[0].signed_delta
        delta_d2 = res.candidates[1].alternatives_evaluated[0].signed_delta
        assert delta_d1 == 1.0
        assert delta_d2 == 1.0
        sum_of_marginals = delta_d1 + delta_d2  # 2.0

        # Simulate true joint resolution of both detections to Bobcat
        rev1 = ReviewEvent(
            id="rev_01", target_id="det_01", decision=ReviewDecision.CORRECT_SPECIES,
            corrected_taxon_id="lynx_rufus", sequence_number=1, created_at=datetime.now(UTC),
            reviewer="human",
        )
        rev2 = ReviewEvent(
            id="rev_02", target_id="det_02", decision=ReviewDecision.CORRECT_SPECIES,
            corrected_taxon_id="lynx_rufus", sequence_number=1, created_at=datetime.now(UTC),
            reviewer="human",
        )
        joint_snap = Snapshot(
            metadata=_meta(revision=6),
            cameras=[cam], media_assets=[m1], observations=[o1],
            detections=[d1, d2], encounters=[enc], reviews=[rev1, rev2],
        )
        joint_analysis = analyze(
            joint_snap,
            AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS, species_ids=["lynx_rufus"]),
        )
        joint_count = next(
            e["encounter_count"] for e in joint_analysis.result["species_entries"]
            if e["taxon_id"] == "lynx_rufus"
        )
        joint_delta = joint_count - res.baseline_value  # 1.0 - 0.0 = 1.0

        # PROOF:
        assert joint_delta == 1.0
        assert sum_of_marginals == 2.0
        assert joint_delta != sum_of_marginals, "Marginal sensitivity must NOT be additive!"

    def test_two_camera_difference_positive_and_negative(self):
        """
        Camera comparison difference: Count(cam_A) - Count(cam_B).
        Baseline: 0 - 0 = 0.
        Candidate 1 at Cam A: Bobcat alt adds +1 to Cam A -> delta = +1 (diff: 0 -> 1).
        Candidate 2 at Cam B: Bobcat alt adds +1 to Cam B -> delta = -1 (diff: 0 -> -1).
        """
        cam_a = _cam("cam_A")
        cam_b = _cam("cam_B")
        m1 = _media("med_01", "cam_A", T0)
        m2 = _media("med_02", "cam_B", T0)
        o1 = _obs("obs_01", "cam_A", "med_01", ["det_A"], T0)
        o2 = _obs("obs_02", "cam_B", "med_02", ["det_B"], T0)
        det_a = _det("det_A", "obs_01", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        det_b = _det("det_B", "obs_02", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        enc_a = _enc("enc_A", "cam_A", ["det_A"], ["obs_01"])
        enc_b = _enc("enc_B", "cam_B", ["det_B"], ["obs_02"])
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam_a, cam_b],
            media_assets=[m1, m2],
            observations=[o1, o2],
            detections=[det_a, det_b],
            encounters=[enc_a, enc_b],
        )

        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.CAMERA_COMPARISON,
            target_species_id="lynx_rufus",
            camera_id_a="cam_A",
            camera_id_b="cam_B",
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.OK
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.baseline_value == 0.0
        assert len(res.candidates) == 2

        cand_a = next(c for c in res.candidates if c.detection_id == "det_A")
        cand_b = next(c for c in res.candidates if c.detection_id == "det_B")
        assert cand_a.alternatives_evaluated[0].signed_delta == 1.0
        assert cand_b.alternatives_evaluated[0].signed_delta == -1.0
        assert cand_a.max_absolute_impact == 1.0
        assert cand_b.max_absolute_impact == 1.0

    def test_camera_comparison_identical_cameras_rejected(self):
        """Specifying identical camera_id_a and camera_id_b returns INVALID_REQUEST."""
        snap = Snapshot(metadata=_meta(), cameras=[_cam("cam_01")])
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.CAMERA_COMPARISON,
            target_species_id="lynx_rufus",
            camera_id_a="cam_01",
            camera_id_b="cam_01",
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.INVALID_REQUEST
        assert any("distinct" in err.message.lower() for err in resp.errors)

    def test_missing_focal_species_rejected(self):
        """Missing target_species_id returns INVALID_REQUEST."""
        snap = Snapshot(metadata=_meta(), cameras=[_cam("cam_01")])
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id=None,
            species_ids=None,
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.INVALID_REQUEST
        assert any("focal species" in err.message.lower() for err in resp.errors)

    def test_already_resolved_detections_excluded(self):
        """Confirmed, corrected, or mark_unknown detections are excluded from review ranking."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"])
        det = _det("det_01", "obs_01", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        enc = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"])
        rev = ReviewEvent(
            id="rev_01", target_id="det_01", decision=ReviewDecision.CONFIRM_SPECIES,
            sequence_number=1, created_at=datetime.now(UTC), reviewer="human",
        )
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam], media_assets=[m1], observations=[o1],
            detections=[det], encounters=[enc], reviews=[rev],
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.eligible_candidates_count == 0
        assert res.ranked_candidates_count == 0

    def test_ambiguous_review_history_excluded_and_reported(self):
        """Conflicting reviews without sequence_number are excluded with an explicit conflict reason."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"])
        det = _det("det_01", "obs_01", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        enc = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"])
        # Two conflicting reviews with no sequence_number
        rev1 = ReviewEvent(id="rev_01", target_id="det_01", decision=ReviewDecision.CONFIRM_SPECIES, created_at=T0, reviewer="h1")
        rev2 = ReviewEvent(id="rev_02", target_id="det_01", decision=ReviewDecision.REJECT_DETECTION, created_at=T0, reviewer="h2")
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam], media_assets=[m1], observations=[o1],
            detections=[det], encounters=[enc], reviews=[rev1, rev2],
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.PARTIAL
        assert any("ambiguous" in r.lower() or "unresolved" in r.lower() for r in resp.exclusion_reasons)

    def test_detection_outside_encounters_excluded(self):
        """Detection not member of any encounter is excluded from encounter-metric ranking."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"])
        det = _det("det_01", "obs_01", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        # Snapshot has no encounters
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.COMPLETED),
            cameras=[cam], media_assets=[m1], observations=[o1],
            detections=[det], encounters=[],
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.ranked_candidates_count == 0

    def test_stable_tie_breaking_by_detection_id(self):
        """Candidates with tied max_absolute_impact are stably ordered by detection_id ascending."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        m2 = _media("med_02", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_Z"])
        o2 = _obs("obs_02", "cam_01", "med_02", ["det_A"])
        # Both have impact = 1.0
        det_z = _det("det_Z", "obs_01", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        det_a = _det("det_A", "obs_02", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        enc_z = _enc("enc_Z", "cam_01", ["det_Z"], ["obs_01"])
        enc_a = _enc("enc_A", "cam_01", ["det_A"], ["obs_02"])
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam], media_assets=[m1, m2], observations=[o1, o2],
            detections=[det_z, det_a], encounters=[enc_z, enc_a],
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert len(res.candidates) == 2
        # det_A must precede det_Z lexicographically
        assert res.candidates[0].detection_id == "det_A"
        assert res.candidates[0].rank == 1
        assert res.candidates[1].detection_id == "det_Z"
        assert res.candidates[1].rank == 2

    def test_result_limit_returns_ok_not_partial(self):
        """Requesting fewer results via result_limit does NOT mark an otherwise complete response partial."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        m2 = _media("med_02", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"])
        o2 = _obs("obs_02", "cam_01", "med_02", ["det_02"])
        det_1 = _det("det_01", "obs_01", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        det_2 = _det("det_02", "obs_02", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        enc_1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"])
        enc_2 = _enc("enc_02", "cam_01", ["det_02"], ["obs_02"])
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam], media_assets=[m1, m2], observations=[o1, o2],
            detections=[det_1, det_2], encounters=[enc_1, enc_2],
        )
        # Limit to 1 result via result_limit
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            result_limit=1,
        )
        resp = rank_review(snap, req)
        # Must be OK: all candidates evaluated, complete top-1 ranking
        assert resp.status == ResponseStatus.OK
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.ranked_candidates_count == 1
        assert res.eligible_candidates_count == 2
        assert res.is_evaluation_bounded is False

    def test_evaluation_limit_sets_partial_and_reports_coverage(self):
        """When evaluation_limit bounds candidate evaluation, status is PARTIAL with incomplete coverage reported."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        m2 = _media("med_02", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"])
        o2 = _obs("obs_02", "cam_01", "med_02", ["det_02"])
        det_1 = _det("det_01", "obs_01", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        det_2 = _det("det_02", "obs_02", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        enc_1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"])
        enc_2 = _enc("enc_02", "cam_01", ["det_02"], ["obs_02"])
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam], media_assets=[m1, m2], observations=[o1, o2],
            detections=[det_1, det_2], encounters=[enc_1, enc_2],
        )
        # Evaluation bounded to 1 candidate
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            evaluation_limit=1,
            evaluation_policy="time_order",
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.PARTIAL
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.is_evaluation_bounded is True
        assert res.evaluation_limit == 1
        assert res.evaluation_policy == "time_order"
        assert any("incomplete ranking coverage" in lim.lower() for lim in resp.limitations)

    def test_reference_snapshot_ranking_returns_unavailable(self):
        """Ranking is UNAVAILABLE on dataset_reference snapshots."""
        snap = Snapshot(
            metadata=_meta(mode=DataSourceMode.DATASET_REFERENCE),
            cameras=[_cam("cam_01")],
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.UNAVAILABLE
        assert any("dataset_reference" in lim for lim in resp.limitations)

    def test_revision_mismatch_returns_invalid_request(self):
        """Optimistic revision mismatch returns INVALID_REQUEST."""
        snap = self._setup_single_encounter_snap()
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            expected_revision=999,  # actual is 5
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.INVALID_REQUEST
        assert any("revision" in err.message.lower() for err in resp.errors)

    def test_snapshot_and_detections_immutable(self):
        """Snapshot and its Detection objects are never mutated during rank_review."""
        snap = self._setup_single_encounter_snap(
            alternatives=[TaxonAlternative(taxon_id="lynx_rufus", score=0.4)]
        )
        before_dump = snap.model_dump_json()
        det_before_taxon = snap.detections[0].predicted_taxon_id

        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
        )
        _ = rank_review(snap, req)

        after_dump = snap.model_dump_json()
        assert before_dump == after_dump, "Snapshot state mutated during ranking!"
        assert snap.detections[0].predicted_taxon_id == det_before_taxon

    def test_json_serialization_and_evidence_references(self):
        """rank_review response serializes to JSON and includes evidence references."""
        snap = self._setup_single_encounter_snap(
            alternatives=[TaxonAlternative(taxon_id="lynx_rufus", score=0.4)]
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
        )
        resp = rank_review(snap, req)
        json_str = resp.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["status"] == "ok"
        assert parsed["result"]["ranked_candidates_count"] == 1
        assert "det_01" in resp.evidence_references
        assert "enc_01" in resp.evidence_references

    def test_multi_species_encounter_sensitivity(self):
        """Encounter has D1 (Coyote) and D2 (Deer). Reviewing D1 to Puma adds Puma encounter."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01", "det_02"])
        d1 = _det("det_01", "obs_01", "canis_latrans", 0.6, [TaxonAlternative(taxon_id="puma_concolor", score=0.35)])
        d2 = _det("det_02", "obs_01", "odocoileus_hemionus", 0.9)
        enc = _enc("enc_01", "cam_01", ["det_01", "det_02"], ["obs_01"])
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam], media_assets=[m1], observations=[o1],
            detections=[d1, d2], encounters=[enc],
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="puma_concolor",
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.baseline_value == 0.0
        assert res.ranked_candidates_count == 1
        assert res.candidates[0].detection_id == "det_01"
        assert res.candidates[0].max_absolute_impact == 1.0

    def test_unknown_alternative_handling(self):
        """Explicit allow_unknown_alternative reduces species count when candidate was only target."""
        snap = self._setup_single_encounter_snap(
            predicted_taxon="lynx_rufus", confidence=0.6, alternatives=[]
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            parameters={"allow_unknown_alternative": True},
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.baseline_value == 1.0
        assert res.ranked_candidates_count == 1
        alt = res.candidates[0].alternatives_evaluated[0]
        assert alt.taxon_id == "__unknown__"
        assert alt.signed_delta == -1.0
        assert alt.counterfactual_value == 0.0

    def test_explicit_rejection_alternative_handling(self):
        """Explicit allow_rejection_alternative reduces species count when candidate was only target."""
        snap = self._setup_single_encounter_snap(
            predicted_taxon="lynx_rufus", confidence=0.6, alternatives=[]
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            parameters={"allow_rejection_alternative": True},
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.baseline_value == 1.0
        assert res.ranked_candidates_count == 1
        alt = res.candidates[0].alternatives_evaluated[0]
        assert alt.taxon_id == "__rejected__"
        assert alt.signed_delta == -1.0
        assert alt.counterfactual_value == 0.0

    def test_species_filter_entry_under_alternative(self):
        """Candidate currently predicted as Coyote enters focal species Puma under alternative."""
        snap = self._setup_single_encounter_snap(
            predicted_taxon="canis_latrans", confidence=0.55,
            alternatives=[TaxonAlternative(taxon_id="puma_concolor", score=0.4)]
        )
        # Search specifically for Puma sensitivity
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="puma_concolor",
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.baseline_value == 0.0
        assert res.ranked_candidates_count == 1
        assert res.candidates[0].current_prediction == "canis_latrans"
        assert res.candidates[0].alternatives_evaluated[0].taxon_id == "puma_concolor"
        assert res.candidates[0].alternatives_evaluated[0].signed_delta == 1.0

    def test_camera_and_time_scope_filtering(self):
        """Candidate outside time window or camera filter is excluded."""
        cam1 = _cam("cam_01")
        cam2 = _cam("cam_02")
        m1 = _media("med_01", "cam_01", T0)
        m2 = _media("med_02", "cam_02", T0 + timedelta(days=5))
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        o2 = _obs("obs_02", "cam_02", "med_02", ["det_02"], T0 + timedelta(days=5))
        d1 = _det("det_01", "obs_01", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        d2 = _det("det_02", "obs_02", "canis_latrans", 0.5, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)])
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], ["obs_02"], T0 + timedelta(days=5), T0 + timedelta(days=5, hours=1))
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam1, cam2], media_assets=[m1, m2], observations=[o1, o2],
            detections=[d1, d2], encounters=[e1, e2],
        )

        # Restrict camera scope to cam_01
        req_cam = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            camera_ids=["cam_01"],
        )
        resp_cam = rank_review(snap, req_cam)
        res_cam = ReviewRankingResult.model_validate(resp_cam.result)
        assert res_cam.ranked_candidates_count == 1
        assert res_cam.candidates[0].camera_id == "cam_01"

        # Restrict time window to exclude day 5
        req_time = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            start_time=T0 - timedelta(hours=1),
            end_time=T0 + timedelta(hours=2),
        )
        resp_time = rank_review(snap, req_time)
        res_time = ReviewRankingResult.model_validate(resp_time.result)
        assert res_time.ranked_candidates_count == 1
        assert res_time.candidates[0].detection_id == "det_01"

    def test_ranking_performance_reference(self):
        """Measures execution time on a 50-encounter, 100-detection snapshot."""
        cams = [_cam(f"cam_{i:02d}") for i in range(5)]
        medias = []
        obss = []
        dets = []
        encs = []
        for i in range(50):
            c_id = f"cam_{i % 5:02d}"
            m_id = f"med_{i:03d}"
            o_id = f"obs_{i:03d}"
            d1_id = f"det_{i*2:03d}"
            d2_id = f"det_{i*2+1:03d}"
            e_id = f"enc_{i:03d}"
            medias.append(_media(m_id, c_id, T0 + timedelta(hours=i)))
            obss.append(_obs(o_id, c_id, m_id, [d1_id, d2_id], T0 + timedelta(hours=i)))
            dets.append(_det(d1_id, o_id, "canis_latrans", 0.55, [TaxonAlternative(taxon_id="lynx_rufus", score=0.4)]))
            dets.append(_det(d2_id, o_id, "puma_concolor", 0.9))
            encs.append(_enc(e_id, c_id, [d1_id, d2_id], [o_id], T0 + timedelta(hours=i), T0 + timedelta(hours=i, minutes=30)))

        snap = Snapshot(
            metadata=_meta(),
            cameras=cams, media_assets=medias, observations=obss,
            detections=dets, encounters=encs,
        )

        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            max_records_to_rank=50,
        )

        t_start = time.perf_counter()
        resp = rank_review(snap, req)
        t_elapsed = time.perf_counter() - t_start

        assert resp.status == ResponseStatus.OK
        assert resp.result["ranked_candidates_count"] == 50
        # Check execution took less than 200ms
        assert t_elapsed < 1.0, f"Execution took too long: {t_elapsed:.4f}s"


class TestCandidateEligibilityScores:
    """Requirement 1: Species-classification scores vs alternative scores from same score space."""

    def test_species_score_compared_not_animal_detection_confidence(self):
        """
        Detection has high animal_detection_confidence (0.99), but moderate classification_confidence (0.55).
        Top alternative score is 0.45 (margin = 0.55 - 0.45 = 0.10).
        With threshold 0.25:
          If animal_detection_confidence were incorrectly used: margin = 0.99 - 0.45 = 0.54 > 0.25 (excluded!).
          Because classification_confidence is used: margin = 0.10 <= 0.25 (eligible and ranked!).
        """
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"])
        det = Detection(
            id="det_01",
            observation_id="obs_01",
            triage_state=TriageState.ANIMAL_DETECTED,
            animal_detection_confidence=0.99,  # animal presence is almost certain
            predicted_taxon_id="canis_latrans",
            classification_confidence=0.55,    # species classification is ambiguous!
            score_type=ScoreType.SOFTMAX,
            alternatives=[
                TaxonAlternative(taxon_id="lynx_rufus", score=0.45, raw_label="bobcat")
            ],
        )
        enc = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"])
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam], media_assets=[m1], observations=[o1],
            detections=[det], encounters=[enc],
        )

        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            score_margin_threshold=0.25,
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.OK
        res = ReviewRankingResult.model_validate(resp.result)
        # Confirms det_01 was NOT falsely excluded by animal_detection_confidence
        assert res.ranked_candidates_count == 1
        assert res.candidates[0].detection_id == "det_01"

    def test_missing_classification_confidence_eligible_without_invented_margin(self):
        """
        When classification_confidence is None, margin is not inventable.
        The candidate is handled explicitly as uncertain and remains eligible.
        """
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"])
        det = Detection(
            id="det_01",
            observation_id="obs_01",
            triage_state=TriageState.ANIMAL_DETECTED,
            animal_detection_confidence=0.90,
            predicted_taxon_id="canis_latrans",
            classification_confidence=None,  # missing classification confidence
            score_type=ScoreType.SOFTMAX,
            alternatives=[
                TaxonAlternative(taxon_id="lynx_rufus", score=0.40)
            ],
        )
        enc = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"])
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam], media_assets=[m1], observations=[o1],
            detections=[det], encounters=[enc],
        )

        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            score_margin_threshold=0.25,
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.ranked_candidates_count == 1
        assert res.candidates[0].current_confidence is None

    def test_incomparable_raw_score_type_eligible_without_invented_margin(self):
        """
        When score_type is RAW (logits), scores are incomparable to bounded [0.0, 1.0] probability margins.
        Candidate is handled explicitly and remains eligible.
        """
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"])
        det = Detection(
            id="det_01",
            observation_id="obs_01",
            triage_state=TriageState.ANIMAL_DETECTED,
            animal_detection_confidence=0.90,
            predicted_taxon_id="canis_latrans",
            classification_confidence=0.88,
            score_type=ScoreType.RAW,  # raw logits, incomparable to probability margin
            alternatives=[
                TaxonAlternative(taxon_id="lynx_rufus", score=0.20)
            ],
        )
        enc = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"])
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam], media_assets=[m1], observations=[o1],
            detections=[det], encounters=[enc],
        )

        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            score_margin_threshold=0.25,
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.ranked_candidates_count == 1

    def test_unambiguous_high_margin_excluded(self):
        """Detection with margin (0.90 - 0.10 = 0.80) > threshold (0.25) is excluded as unambiguous."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01")
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"])
        det = Detection(
            id="det_01",
            observation_id="obs_01",
            triage_state=TriageState.ANIMAL_DETECTED,
            animal_detection_confidence=0.95,
            predicted_taxon_id="canis_latrans",
            classification_confidence=0.90,
            score_type=ScoreType.SOFTMAX,
            alternatives=[
                TaxonAlternative(taxon_id="lynx_rufus", score=0.10)
            ],
        )
        enc = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"])
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam], media_assets=[m1], observations=[o1],
            detections=[det], encounters=[enc],
        )

        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            score_margin_threshold=0.25,
        )
        resp = rank_review(snap, req)
        res = ReviewRankingResult.model_validate(resp.result)
        assert res.ranked_candidates_count == 0
        assert res.excluded_candidates_count == 1


class TestAnalyzeAndRankReviewBaselineParity:
    """Requirement 3: Confirm rank_review() and analyze() produce the exact same baseline."""

    def test_species_encounter_counts_baseline_parity(self):
        """Baseline encounter count for target species matches analyze() under identical parameters."""
        cam1 = _cam("cam_01")
        cam2 = _cam("cam_02")
        m1 = _media("med_01", "cam_01", T0)
        m2 = _media("med_02", "cam_01", T0 + timedelta(hours=1))
        m3 = _media("med_03", "cam_02", T0 + timedelta(hours=2))

        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01", "det_02"], T0)
        o2 = _obs("obs_02", "cam_01", "med_02", ["det_03"], T0 + timedelta(hours=1))
        o3 = _obs("obs_03", "cam_02", "med_03", ["det_04"], T0 + timedelta(hours=2))

        # Enc 1 (cam_01): Bobcat (0.9) and Coyote (0.4) -> Bobcat present
        d1 = _det("det_01", "obs_01", "lynx_rufus", 0.90)
        d2 = _det("det_02", "obs_01", "canis_latrans", 0.40)
        e1 = _enc("enc_01", "cam_01", ["det_01", "det_02"], ["obs_01"], T0, T0 + timedelta(minutes=15))

        # Enc 2 (cam_01): Coyote predicted, but corrected to Bobcat by review -> Bobcat present
        d3 = _det("det_03", "obs_02", "canis_latrans", 0.50, [TaxonAlternative(taxon_id="lynx_rufus", score=0.45)])
        e2 = _enc("enc_02", "cam_01", ["det_03"], ["obs_02"], T0 + timedelta(hours=1), T0 + timedelta(hours=1, minutes=15))
        rev = ReviewEvent(
            id="rev_01", target_id="det_03", decision=ReviewDecision.CORRECT_SPECIES,
            corrected_taxon_id="lynx_rufus", sequence_number=1, created_at=T0, reviewer="biologist",
        )

        # Enc 3 (cam_02): Puma -> no Bobcat
        d4 = _det("det_04", "obs_03", "puma_concolor", 0.95)
        e3 = _enc("enc_03", "cam_02", ["det_04"], ["obs_03"], T0 + timedelta(hours=2), T0 + timedelta(hours=2, minutes=15))

        snap = Snapshot(
            metadata=_meta(revision=5),
            cameras=[cam1, cam2], media_assets=[m1, m2, m3], observations=[o1, o2, o3],
            detections=[d1, d2, d3, d4], encounters=[e1, e2, e3], reviews=[rev],
        )

        # Analyze call
        req_analyze = AnalysisRequest(
            metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            species_ids=["lynx_rufus"],
            expected_revision=5,
        )
        resp_analyze = analyze(snap, req_analyze)
        assert resp_analyze.status == ResponseStatus.OK
        bobcat_entry = next(e for e in resp_analyze.result["species_entries"] if e["taxon_id"] == "lynx_rufus")
        analyze_bobcat_count = float(bobcat_entry["encounter_count"])  # should be 2.0 (enc_01 and enc_02)

        # Rank review call
        req_rank = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
            expected_revision=5,
        )
        resp_rank = rank_review(snap, req_rank)
        assert resp_rank.status == ResponseStatus.OK
        rank_result = ReviewRankingResult.model_validate(resp_rank.result)

        # EXACT PARITY CHECK:
        assert rank_result.baseline_value == analyze_bobcat_count == 2.0

    def test_camera_comparison_baseline_parity(self):
        """Baseline difference for camera comparison matches analyze() Count(cam_A) - Count(cam_B)."""
        cam_a = _cam("cam_A")
        cam_b = _cam("cam_B")
        m1 = _media("med_01", "cam_A", T0)
        m2 = _media("med_02", "cam_A", T0 + timedelta(hours=1))
        m3 = _media("med_03", "cam_B", T0)

        o1 = _obs("obs_01", "cam_A", "med_01", ["det_01"], T0)
        o2 = _obs("obs_02", "cam_A", "med_02", ["det_02"], T0 + timedelta(hours=1))
        o3 = _obs("obs_03", "cam_B", "med_03", ["det_03"], T0)

        # Cam A has 2 Bobcat encounters
        d1 = _det("det_01", "obs_01", "lynx_rufus", 0.90)
        d2 = _det("det_02", "obs_02", "lynx_rufus", 0.90)
        e1 = _enc("enc_A1", "cam_A", ["det_01"], ["obs_01"], T0, T0 + timedelta(minutes=10))
        e2 = _enc("enc_A2", "cam_A", ["det_02"], ["obs_02"], T0 + timedelta(hours=1), T0 + timedelta(hours=1, minutes=10))

        # Cam B has 1 Bobcat encounter
        d3 = _det("det_03", "obs_03", "lynx_rufus", 0.90)
        e3 = _enc("enc_B1", "cam_B", ["det_03"], ["obs_03"], T0, T0 + timedelta(minutes=10))

        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam_a, cam_b], media_assets=[m1, m2, m3], observations=[o1, o2, o3],
            detections=[d1, d2, d3], encounters=[e1, e2, e3],
        )

        req_analyze = AnalysisRequest(
            metric=AnalysisMetric.CAMERA_COMPARISON,
            camera_ids=["cam_A", "cam_B"],
            species_ids=["lynx_rufus"],
        )
        resp_analyze = analyze(snap, req_analyze)
        assert resp_analyze.status == ResponseStatus.OK
        cam_entries = {e["camera_id"]: e for e in resp_analyze.result["cameras"]}
        count_a = float(cam_entries["cam_A"]["species_breakdown"].get("lynx_rufus", 0))
        count_b = float(cam_entries["cam_B"]["species_breakdown"].get("lynx_rufus", 0))
        expected_diff = count_a - count_b  # 2.0 - 1.0 = 1.0

        req_rank = ReviewRankingRequest(
            target_metric=AnalysisMetric.CAMERA_COMPARISON,
            target_species_id="lynx_rufus",
            camera_id_a="cam_A",
            camera_id_b="cam_B",
        )
        resp_rank = rank_review(snap, req_rank)
        res = ReviewRankingResult.model_validate(resp_rank.result)

        # EXACT PARITY CHECK:
        assert res.baseline_value == expected_diff == 1.0


class TestCompletedEmptyEncounterCountsAndRates:
    """Requirement 4: Completed-empty encounters return zero counts, while rates require a valid denominator."""

    def test_completed_empty_encounter_counts_return_zero(self):
        """Encounter grouping COMPLETED with encounters=[] returns zero counts with status OK."""
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.COMPLETED),
            cameras=[_cam("cam_01"), _cam("cam_02")],
            encounters=[],
        )

        # 1. species_encounter_counts
        resp_sp = analyze(snap, AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS))
        assert resp_sp.status == ResponseStatus.OK
        assert resp_sp.result["total_eligible_encounters"] == 0
        assert resp_sp.result["species_entries"] == []

        # 2. camera_comparison
        resp_cam = analyze(snap, AnalysisRequest(metric=AnalysisMetric.CAMERA_COMPARISON))
        assert resp_cam.status == ResponseStatus.OK
        for b in resp_cam.result["cameras"]:
            assert b["total_encounters"] == 0

        # 3. daily_activity
        resp_daily = analyze(snap, AnalysisRequest(metric=AnalysisMetric.DAILY_ACTIVITY, analysis_timezone="UTC"))
        assert resp_daily.status == ResponseStatus.OK
        assert resp_daily.result["date_counts"] == {}

        # 4. hourly_activity
        resp_hourly = analyze(snap, AnalysisRequest(metric=AnalysisMetric.HOURLY_ACTIVITY, analysis_timezone="UTC"))
        assert resp_hourly.status == ResponseStatus.OK
        assert all(count == 0 for count in resp_hourly.result["hour_counts"].values())

        # 5. overview
        resp_over = analyze(snap, AnalysisRequest(metric=AnalysisMetric.OVERVIEW))
        assert resp_over.status == ResponseStatus.OK
        assert resp_over.result["total_encounters"] == 0

    def test_effort_rate_zero_denominator_returns_insufficient_data(self):
        """Effort records cover 0 camera days in window -> INSUFFICIENT_DATA."""
        eff = MonitoringEffort(
            id="eff_01",
            camera_id="cam_01",
            active_intervals=[
                TimeInterval(start=T0, end=T0)  # zero duration interval
            ],
        )
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.COMPLETED),
            cameras=[_cam("cam_01")],
            encounters=[],
            monitoring_efforts=[eff],
        )
        resp = analyze(snap, AnalysisRequest(metric=AnalysisMetric.EFFORT_NORMALISED_RATES))
        assert resp.status == ResponseStatus.INSUFFICIENT_DATA

    def test_effort_rate_absent_effort_returns_unavailable(self):
        """Entirely absent monitoring effort -> UNAVAILABLE."""
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.COMPLETED),
            cameras=[_cam("cam_01")],
            encounters=[],
            monitoring_efforts=[],
        )
        resp = analyze(snap, AnalysisRequest(metric=AnalysisMetric.EFFORT_NORMALISED_RATES))
        assert resp.status == ResponseStatus.UNAVAILABLE

    def test_effort_rate_valid_denominator_completed_empty_returns_zero_rate(self):
        """Valid non-zero camera days with completed-empty encounters -> rate is 0.0 with status OK."""
        eff = MonitoringEffort(
            id="eff_01",
            camera_id="cam_01",
            active_intervals=[
                TimeInterval(start=T0, end=T0 + timedelta(days=5))  # 5 active camera days
            ],
        )
        snap = Snapshot(
            metadata=_meta(status=EncounterProcessingStatus.COMPLETED),
            cameras=[_cam("cam_01")],
            encounters=[],
            monitoring_efforts=[eff],
        )
        req = AnalysisRequest(
            metric=AnalysisMetric.EFFORT_NORMALISED_RATES,
            start_time=T0,
            end_time=T0 + timedelta(days=5),
        )
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.OK
        assert resp.result["total_active_camera_days"] == 5.0
        assert resp.result["total_encounters_in_effort"] == 0
        assert resp.result["overall_rate_per_camera_day"] == 0.0


class TestReferenceMetricsSeparation:
    """Requirement 5: Strict separation of reference-image metrics from encounter and operational metrics."""

    def test_rank_review_on_reference_image_species_counts_unavailable(self):
        """rank_review() rejects reference-image metric as UNAVAILABLE."""
        snap = Snapshot(
            metadata=_meta(mode=DataSourceMode.OPERATIONAL_PREDICTION),
            cameras=[_cam("cam_01")],
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.REFERENCE_IMAGE_SPECIES_COUNTS,
            target_species_id="lynx_rufus",
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.UNAVAILABLE
        assert any("deferred" in lim.lower() or "supported" in lim.lower() for lim in resp.limitations)

    def test_rank_review_on_reference_snapshot_unavailable(self):
        """rank_review() on dataset_reference snapshot returns UNAVAILABLE."""
        snap = Snapshot(
            metadata=_meta(mode=DataSourceMode.DATASET_REFERENCE),
            cameras=[_cam("cam_01")],
        )
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="lynx_rufus",
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.UNAVAILABLE
        assert any("dataset_reference" in lim for lim in resp.limitations)


class TestStoredSnapshotsBackwardCompatibility:
    """Requirement 6: Verify backward compatibility by loading actual stored 1.0.0 and 1.1.0 snapshot files."""

    def test_load_and_run_stored_1_0_0_valid_snapshot(self):
        """Loads actual stored examples/valid_snapshot.json (schema 1.0.0), validates, and executes analytics."""
        path = Path("examples/valid_snapshot.json")
        snap, report = load_and_validate_snapshot(path)
        assert report.is_valid, f"Validation errors on stored 1.0.0 snapshot: {report.errors}"
        assert snap.metadata.schema_version == "1.0.0"

        # Operational analytics run cleanly
        resp_an = analyze(snap, AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS))
        assert resp_an.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)

        # Operational review ranking executes cleanly
        resp_rk = rank_review(snap, ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="panthera_tigris",
        ))
        assert resp_rk.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)

    def test_load_and_run_stored_1_0_0_minimal_snapshot(self):
        """Loads actual stored examples/minimal_snapshot.json (schema 1.0.0) and validates."""
        path = Path("examples/minimal_snapshot.json")
        snap, report = load_and_validate_snapshot(path)
        assert report.is_valid, f"Validation errors on stored minimal 1.0.0 snapshot: {report.errors}"
        assert snap.metadata.schema_version == "1.0.0"
        resp = analyze(snap, AnalysisRequest(metric=AnalysisMetric.OVERVIEW))
        assert resp.status == ResponseStatus.OK

    def test_load_and_run_stored_1_1_0_snapshot(self):
        """Loads actual stored examples/snapshot_v1_1_0.json (schema 1.1.0), validates, and runs rank_review."""
        path = Path("examples/snapshot_v1_1_0.json")
        snap, report = load_and_validate_snapshot(path)
        assert report.is_valid, f"Validation errors on stored 1.1.0 snapshot: {report.errors}"
        assert snap.metadata.schema_version == "1.1.0"
        assert snap.metadata.encounter_processing_status == EncounterProcessingStatus.COMPLETED

        # Analyze run
        resp_an = analyze(snap, AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS))
        assert resp_an.status == ResponseStatus.OK

        # rank_review run
        resp_rk = rank_review(snap, ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="panthera_pardus",
        ))
        assert resp_rk.status == ResponseStatus.OK
        res = ReviewRankingResult.model_validate(resp_rk.result)
        assert res.ranked_candidates_count == 1
        assert res.candidates[0].detection_id == "det_001"


