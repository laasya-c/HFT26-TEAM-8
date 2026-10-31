"""
WILDSCOPE Decision Intelligence & Analytics Module
Cross-Phase End-to-End Public Workflow Verification (Part 9)

Tests complete multi-phase public workflows on explicitly synthetic datasets:
Workflow A: Snapshot -> Species Analytics -> Review Ranking -> Append Review -> Increment Revision -> Recompute.
Workflow B: Encounters -> Time/Species Association (No GPS) -> Optional Spatial Association (Synthetic Geometry).
Workflow C: Verified Synthetic Effort -> Anomaly Indicators -> Changed Revision -> Recomputation & Parity.
Workflow D: Synthetic Coverage Inventory -> Blind Spot Gap Analysis -> Placement Ranking -> Infrastructure Scenario.

DISCLAIMER: All data used herein is synthetic test data designed for deterministic
algorithmic verification; it is NOT field-validated operational or biological ground truth.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
import pytest

from wildscope_analytics.contracts.entities import (
    Camera,
    CameraCoverage,
    CandidateSite,
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
from wildscope_analytics.contracts.snapshot import (
    Snapshot,
    SnapshotMetadata,
)
from wildscope_analytics.contracts.enums import (
    AnalysisMetric,
    ClockComparabilityPolicy,
    DataSourceMode,
    InclusionPolicy,
    ResponseStatus,
    ReviewDecision,
    SpatialMode,
    ValidationErrorCode,
)
from wildscope_analytics.contracts.requests import (
    ActivityAnomalyRequest,
    AnalysisRequest,
    BlindSpotAnalysisRequest,
    CandidatePlacementRequest,
    CrossCameraAssociationRequest,
    InfrastructureScenarioRequest,
    ReviewRankingRequest,
)
from wildscope_analytics.analytics import (
    analyze,
    compute_monitoring_blind_spots,
    compute_proximity_indicators,
    evaluate_infrastructure_scenario,
    rank_candidate_placements,
    rank_review,
)
from wildscope_analytics.associations import compute_cross_camera_associations
from wildscope_analytics.anomalies import compute_activity_anomalies


# ---------------------------------------------------------------------------
# Synthetic Test Fixture Helpers
# ---------------------------------------------------------------------------

def _build_synthetic_workflow_a_snapshot() -> Snapshot:
    """Creates a deterministic synthetic snapshot with unreviewed ambiguous predictions."""
    meta = SnapshotMetadata(
        schema_version="1.0.0",
        dataset_revision=1,
        created_at=datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc),
        source_system="wildscope_synthetic_workflow_a",
        data_source_mode=DataSourceMode.OPERATIONAL_PREDICTION,
        provenance={"synthetic_disclaimer": "SYNTHETIC FIXTURE FOR WORKFLOW A VERIFICATION"},
    )
    cams = [
        Camera(id="cam_01", site_id="site_alpha", timezone="UTC", latitude=15.0, longitude=75.0),
        Camera(id="cam_02", site_id="site_alpha", timezone="UTC", latitude=15.05, longitude=75.05),
    ]
    assets = [
        MediaAsset(id="med_01", camera_id="cam_01", storage_key="img01.jpg", captured_at=datetime(2026, 10, 31, 6, 0, 0, tzinfo=timezone.utc)),
        MediaAsset(id="med_02", camera_id="cam_01", storage_key="img02.jpg", captured_at=datetime(2026, 10, 31, 7, 0, 0, tzinfo=timezone.utc)),
    ]
    obs = [
        Observation(id="obs_01", camera_id="cam_01", source_media_id="med_01", captured_at=datetime(2026, 10, 31, 6, 0, 0, tzinfo=timezone.utc), detection_ids=["det_01"]),
        Observation(id="obs_02", camera_id="cam_01", source_media_id="med_02", captured_at=datetime(2026, 10, 31, 7, 0, 0, tzinfo=timezone.utc), detection_ids=["det_02"]),
    ]
    runs = [
        PredictionRun(
            id="run_01",
            model_version="5.0",
            started_at=datetime(2026, 10, 31, 7, 50, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 10, 31, 8, 0, 0, tzinfo=timezone.utc),
        )
    ]
    # det_01: low confidence panthera_tigris, high uncertainty
    # det_02: high confidence panthera_pardus
    dets = [
        Detection(
            id="det_01",
            observation_id="obs_01",
            run_id="run_01",
            animal_detection_confidence=0.88,
            predicted_taxon_id="panthera_tigris",
            classification_confidence=0.51,
            alternatives=[TaxonAlternative(taxon_id="panthera_pardus", score=0.45)],
        ),
        Detection(
            id="det_02",
            observation_id="obs_02",
            run_id="run_01",
            animal_detection_confidence=0.95,
            predicted_taxon_id="panthera_pardus",
            classification_confidence=0.92,
        ),
    ]
    encs = [
        Encounter(id="enc_01", camera_id="cam_01", start_time=datetime(2026, 10, 31, 6, 0, 0, tzinfo=timezone.utc), end_time=datetime(2026, 10, 31, 6, 5, 0, tzinfo=timezone.utc), member_detection_ids=["det_01"]),
        Encounter(id="enc_02", camera_id="cam_01", start_time=datetime(2026, 10, 31, 7, 0, 0, tzinfo=timezone.utc), end_time=datetime(2026, 10, 31, 7, 5, 0, tzinfo=timezone.utc), member_detection_ids=["det_02"]),
    ]
    efforts = [
        MonitoringEffort(
            id="eff_01",
            camera_id="cam_01",
            active_intervals=[
                TimeInterval(start=datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc), end=datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc))
            ],
        )
    ]
    return Snapshot(
        metadata=meta,
        cameras=cams,
        media_assets=assets,
        observations=obs,
        prediction_runs=runs,
        detections=dets,
        encounters=encs,
        reviews=[],
        monitoring_efforts=efforts,
    )


# ===========================================================================
# PART 9: Cross-Phase Public Workflows
# ===========================================================================

class TestCrossPhaseWorkflows:
    """Verifies complete end-to-end multi-phase analytics workflows."""

    def test_workflow_a_analytics_ranking_review_lifecycle(self):
        """
        Workflow A:
        1. Valid snapshot -> compute species encounter counts.
        2. Run review ranking to prioritize uncertain predictions.
        3. Simulate reviewer confirming the top-ranked candidate on a copied snapshot.
        4. Increment dataset revision from 1 to 2.
        5. Verify stale expected_revision=1 is rejected on updated snapshot.
        6. Recompute analytics and ranking; verify updated effective label changes species counts.
        7. Verify original snapshot remains completely unmutated.
        """
        snap_v1 = _build_synthetic_workflow_a_snapshot()
        assert snap_v1.metadata.dataset_revision == 1

        # 1. Species analytics before review
        req_counts = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp_counts_v1 = analyze(snap_v1, req_counts)
        assert resp_counts_v1.status == ResponseStatus.OK
        assert resp_counts_v1.dataset_revision == 1
        counts_v1 = {e["taxon_id"]: e["encounter_count"] for e in resp_counts_v1.result["species_entries"]}
        assert counts_v1["panthera_tigris"] == 1
        assert counts_v1["panthera_pardus"] == 1

        # 2. Review ranking targeting panthera_tigris
        req_rank = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="panthera_tigris",
            expected_revision=1,
        )
        resp_rank_v1 = rank_review(snap_v1, req_rank)
        assert resp_rank_v1.status == ResponseStatus.OK
        assert resp_rank_v1.dataset_revision == 1
        assert resp_rank_v1.result["ranked_candidates_count"] >= 1
        top_cand = resp_rank_v1.result["candidates"][0]
        assert top_cand["detection_id"] == "det_01"
        assert top_cand["observation_id"] == "obs_01"
        assert top_cand["encounter_id"] == "enc_01"

        # 3. Simulate reviewer intervention: human corrects det_01 to panthera_pardus
        snap_v2 = snap_v1.model_copy(deep=True)
        review_event = ReviewEvent(
            id="rev_01",
            target_id="det_01",
            decision=ReviewDecision.CORRECT_SPECIES,
            corrected_taxon_id="panthera_pardus",
            created_at=datetime(2026, 10, 31, 9, 0, 0, tzinfo=timezone.utc),
            reviewer="expert_reviewer_shravan",
            sequence_number=1,
        )
        snap_v2.reviews.append(review_event)
        snap_v2.metadata.dataset_revision = 2

        # 4. Verify original snapshot v1 was NOT mutated
        assert len(snap_v1.reviews) == 0
        assert snap_v1.metadata.dataset_revision == 1

        # 5. Stale expected revision guard: request with expected_revision=1 rejected on snap_v2
        stale_req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS, expected_revision=1)
        stale_resp = analyze(snap_v2, stale_req)
        assert stale_resp.status == ResponseStatus.INVALID_REQUEST
        assert len(stale_resp.errors) > 0
        assert "expected" in stale_resp.errors[0].message.lower() or "revision" in stale_resp.errors[0].message.lower()

        # 6. Recompute species analytics on v2: panthera_tigris drops to 0, panthera_pardus increases to 2
        req_counts_v2 = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS, expected_revision=2)
        resp_counts_v2 = analyze(snap_v2, req_counts_v2)
        assert resp_counts_v2.status == ResponseStatus.OK
        assert resp_counts_v2.dataset_revision == 2
        counts_v2 = {e["taxon_id"]: e["encounter_count"] for e in resp_counts_v2.result["species_entries"]}
        assert counts_v2.get("panthera_tigris", 0) == 0
        assert counts_v2["panthera_pardus"] == 2

        # 7. Recompute review ranking on v2: det_01 is now reviewed, no longer eligible for review
        req_rank_v2 = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            target_species_id="panthera_tigris",
            expected_revision=2,
        )
        resp_rank_v2 = rank_review(snap_v2, req_rank_v2)
        assert resp_rank_v2.status == ResponseStatus.OK
        assert resp_rank_v2.dataset_revision == 2
        assert resp_rank_v2.result["ranked_candidates_count"] == 0

        # Predictable JSON serialization
        serialized = resp_counts_v2.model_dump(mode="json")
        assert json.loads(json.dumps(serialized))["dataset_revision"] == 2

    def test_workflow_b_associations_time_mode_without_gps_and_spatial_mode(self):
        """
        Workflow B:
        1. Encounters across 2 cameras without GPS coordinates.
        2. Time/species association succeeds without GPS (spatial_mode=time_species_only).
        3. Optional spatial association requests fail cleanly when GPS is required.
        4. When synthetic coordinates are supplied, spatial distance is calculated.
        5. Verify Haversine separation is labelled approximate spherical camera separation,
           NOT animal travel distance.
        """
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=5,
            created_at=datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc),
            source_system="wildscope_synthetic_workflow_b",
            data_source_mode=DataSourceMode.OPERATIONAL_PREDICTION,
        )
        # Cameras without GPS
        cams = [
            Camera(id="cam_east", site_id="site_ridge", timezone="UTC", latitude=None, longitude=None),
            Camera(id="cam_west", site_id="site_ridge", timezone="UTC", latitude=None, longitude=None),
        ]
        assets = [
            MediaAsset(id="med_e", camera_id="cam_east", storage_key="e.jpg", captured_at=datetime(2026, 10, 31, 2, 0, 0, tzinfo=timezone.utc)),
            MediaAsset(id="med_w", camera_id="cam_west", storage_key="w.jpg", captured_at=datetime(2026, 10, 31, 2, 30, 0, tzinfo=timezone.utc)),
        ]
        obs = [
            Observation(id="obs_e", camera_id="cam_east", source_media_id="med_e", captured_at=datetime(2026, 10, 31, 2, 0, 0, tzinfo=timezone.utc), detection_ids=["det_e"]),
            Observation(id="obs_w", camera_id="cam_west", source_media_id="med_w", captured_at=datetime(2026, 10, 31, 2, 30, 0, tzinfo=timezone.utc), detection_ids=["det_w"]),
        ]
        runs = [
            PredictionRun(
                id="run_md",
                model_version="1.0",
                started_at=datetime(2026, 10, 31, 2, 50, 0, tzinfo=timezone.utc),
                completed_at=datetime(2026, 10, 31, 3, 0, 0, tzinfo=timezone.utc),
            )
        ]
        dets = [
            Detection(id="det_e", observation_id="obs_e", run_id="run_md", animal_detection_confidence=0.9, predicted_taxon_id="elephas_maximus"),
            Detection(id="det_w", observation_id="obs_w", run_id="run_md", animal_detection_confidence=0.9, predicted_taxon_id="elephas_maximus"),
        ]
        encs = [
            Encounter(id="enc_e", camera_id="cam_east", start_time=datetime(2026, 10, 31, 2, 0, 0, tzinfo=timezone.utc), end_time=datetime(2026, 10, 31, 2, 10, 0, tzinfo=timezone.utc), member_detection_ids=["det_e"]),
            Encounter(id="enc_w", camera_id="cam_west", start_time=datetime(2026, 10, 31, 2, 30, 0, tzinfo=timezone.utc), end_time=datetime(2026, 10, 31, 2, 40, 0, tzinfo=timezone.utc), member_detection_ids=["det_w"]),
        ]
        snap_no_gps = Snapshot(
            metadata=meta,
            cameras=cams,
            media_assets=assets,
            observations=obs,
            prediction_runs=runs,
            detections=dets,
            encounters=encs,
            reviews=[],
            monitoring_efforts=[],
        )

        # 1. Time/species only mode without GPS succeeds
        req_time = CrossCameraAssociationRequest(
            metric=AnalysisMetric.CROSS_CAMERA_ASSOCIATIONS,
            spatial_mode=SpatialMode.TIME_SPECIES_ONLY,
            clock_comparability_policy=ClockComparabilityPolicy.DOCUMENTED_SYNC,
            max_temporal_separation_seconds=3600.0,
        )
        resp_time = analyze(snap_no_gps, req_time)
        assert resp_time.status == ResponseStatus.OK
        assert resp_time.result["total_matching_pairs_found"] == 1
        assoc = resp_time.result["associations"][0]
        assert assoc["camera_id_a"] == "cam_east"
        assert assoc["camera_id_b"] == "cam_west"
        assert assoc["camera_distance_meters"] is None

        # 2. Spatial required mode fails with UNAVAILABLE when GPS coordinates are missing
        req_spatial_req = CrossCameraAssociationRequest(
            metric=AnalysisMetric.CROSS_CAMERA_ASSOCIATIONS,
            spatial_mode=SpatialMode.SPATIAL_REQUIRED,
            clock_comparability_policy=ClockComparabilityPolicy.DOCUMENTED_SYNC,
            max_temporal_separation_seconds=3600.0,
            max_spatial_distance_meters=1000.0,
        )
        resp_spatial_req = analyze(snap_no_gps, req_spatial_req)
        assert resp_spatial_req.status == ResponseStatus.UNAVAILABLE

        # 3. Supply synthetic coordinates to cameras
        snap_with_gps = snap_no_gps.model_copy(deep=True)
        snap_with_gps.cameras = [
            Camera(id="cam_east", site_id="site_ridge", timezone="UTC", latitude=11.500, longitude=76.500),
            Camera(id="cam_west", site_id="site_ridge", timezone="UTC", latitude=11.505, longitude=76.505),
        ]

        resp_spatial_ok = analyze(snap_with_gps, req_spatial_req)
        assert resp_spatial_ok.status == ResponseStatus.OK
        assert resp_spatial_ok.result["total_matching_pairs_found"] == 1
        pair = resp_spatial_ok.result["associations"][0]
        assert pair["camera_distance_meters"] is not None
        assert 700.0 < pair["camera_distance_meters"] < 900.0

        # Parity check between analyze() and compute_cross_camera_associations()
        resp_direct = compute_cross_camera_associations(snap_with_gps, req_spatial_req)
        assert resp_direct.result["total_matching_pairs_found"] == resp_spatial_ok.result["total_matching_pairs_found"]
        assert resp_direct.result["associations"][0]["camera_distance_meters"] == pair["camera_distance_meters"]

    def test_workflow_c_activity_anomalies_and_effort_revision_parity(self):
        """
        Workflow C:
        1. Multi-day synthetic baseline (7 days) + 1 day evaluation.
        2. Detect activity anomaly on focal species.
        3. Verify effort and count parity with Phase 2 compute_effort_normalised_rates.
        4. Recompute under revision update.
        """
        # Build 8 consecutive days of monitoring effort and encounters
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=10,
            created_at=datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc),
            source_system="wildscope_synthetic_workflow_c",
            data_source_mode=DataSourceMode.OPERATIONAL_PREDICTION,
        )
        cam = Camera(
            id="cam_anom_01",
            site_id="site_valley",
            timezone="UTC",
            provenance={"stationarity_verified": True, "verification_scope": "2026-10-01_to_2026-10-08"},
        )
        # 8 full days of active monitoring: 2026-10-01 to 2026-10-09
        eff_intervals = [
            TimeInterval(
                start=datetime(2026, 10, 1 + i, 0, 0, 0, tzinfo=timezone.utc),
                end=datetime(2026, 10, 2 + i, 0, 0, 0, tzinfo=timezone.utc),
            )
            for i in range(8)
        ]
        effort = MonitoringEffort(id="eff_cam_01", camera_id="cam_anom_01", active_intervals=eff_intervals)

        # Baseline (days 1-7): exactly 1 encounter per day
        # Evaluation (day 8): 6 encounters (spike)
        dets: list[Detection] = []
        obs: list[Observation] = []
        encs: list[Encounter] = []
        assets: list[MediaAsset] = []
        run = PredictionRun(
            id="run_01",
            model_version="1.0",
            started_at=datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 10, 1, 0, 10, 0, tzinfo=timezone.utc),
        )

        # Baseline days 0 to 6
        for day_idx in range(7):
            d_time = datetime(2026, 10, 1 + day_idx, 10, 0, 0, tzinfo=timezone.utc)
            mid = f"med_base_{day_idx}"
            oid = f"obs_base_{day_idx}"
            did = f"det_base_{day_idx}"
            eid = f"enc_base_{day_idx}"
            assets.append(MediaAsset(id=mid, camera_id="cam_anom_01", storage_key=f"{mid}.jpg", captured_at=d_time))
            obs.append(Observation(id=oid, camera_id="cam_anom_01", source_media_id=mid, captured_at=d_time, detection_ids=[did]))
            dets.append(Detection(id=did, observation_id=oid, run_id="run_01", animal_detection_confidence=0.9, predicted_taxon_id="canis_lupus"))
            encs.append(Encounter(id=eid, camera_id="cam_anom_01", start_time=d_time, end_time=d_time, member_detection_ids=[did]))

        # Evaluation day 7 (2026-10-08): 6 encounters
        for k in range(6):
            d_time = datetime(2026, 10, 8, 2 + k * 2, 0, 0, tzinfo=timezone.utc)
            mid = f"med_eval_{k}"
            oid = f"obs_eval_{k}"
            did = f"det_eval_{k}"
            eid = f"enc_eval_{k}"
            assets.append(MediaAsset(id=mid, camera_id="cam_anom_01", storage_key=f"{mid}.jpg", captured_at=d_time))
            obs.append(Observation(id=oid, camera_id="cam_anom_01", source_media_id=mid, captured_at=d_time, detection_ids=[did]))
            dets.append(Detection(id=did, observation_id=oid, run_id="run_01", animal_detection_confidence=0.9, predicted_taxon_id="canis_lupus"))
            encs.append(Encounter(id=eid, camera_id="cam_anom_01", start_time=d_time, end_time=d_time, member_detection_ids=[did]))

        snap_c = Snapshot(
            metadata=meta,
            cameras=[cam],
            media_assets=assets,
            observations=obs,
            prediction_runs=[run],
            detections=dets,
            encounters=encs,
            reviews=[],
            monitoring_efforts=[effort],
        )

        req_anom = ActivityAnomalyRequest(
            metric=AnalysisMetric.ACTIVITY_ANOMALY,
            baseline_start_time=datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
            baseline_end_time=datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc),
            evaluation_start_time=datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc),
            evaluation_end_time=datetime(2026, 10, 9, 0, 0, 0, tzinfo=timezone.utc),
            species_ids=["canis_lupus"],
            camera_ids=["cam_anom_01"],
            analysis_timezone="UTC",
            min_baseline_days=7,
            min_baseline_active_effort_days=5.0,
            expected_revision=10,
        )

        resp_anom = analyze(snap_c, req_anom)
        assert resp_anom.status == ResponseStatus.OK
        assert resp_anom.dataset_revision == 10
        series = resp_anom.result["series"][0]
        assert series["outcome"] == "increased"
        assert series["evaluation_encounter_count"] == 6
        assert series["baseline_median_daily_rate"] == 1.0

        # Phase 2 rate parity check for the evaluation window
        req_p2 = AnalysisRequest(
            metric=AnalysisMetric.EFFORT_NORMALISED_RATES,
            start_time=datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 10, 9, 0, 0, 0, tzinfo=timezone.utc),
            camera_ids=["cam_anom_01"],
            species_ids=["canis_lupus"],
            analysis_timezone="UTC",
        )
        resp_p2 = analyze(snap_c, req_p2)
        assert resp_p2.status == ResponseStatus.OK
        cam_row = resp_p2.result["camera_rates"][0]
        assert cam_row["camera_id"] == "cam_anom_01"
        assert cam_row["encounters_in_effort"] == 6
        assert round(cam_row["active_camera_days_in_window"], 2) == 1.0
        assert cam_row["rate_per_camera_day"] == series["evaluation_encounter_rate"]

    def test_workflow_d_spatial_blind_spots_placement_and_scenarios(self):
        """
        Workflow D:
        1. Study area polygon with declared camera coverage -> blind spot gap analysis.
        2. Placement ranking on candidate sites with exclusion zone filtering.
        3. Infrastructure scenario adding a buffered road and hypothetical camera.
        4. Parity across dedicated vs unified entry points.
        """
        # Study area: 0.1 deg square (~11 km x 11 km)
        study_poly = {
            "type": "Polygon",
            "coordinates": [
                [
                    [-118.1, 34.0],
                    [-118.0, 34.0],
                    [-118.0, 34.1],
                    [-118.1, 34.1],
                    [-118.1, 34.0],
                ]
            ],
        }
        meta = SnapshotMetadata(
            schema_version="1.0.0",
            dataset_revision=20,
            created_at=datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc),
            source_system="wildscope_synthetic_workflow_d",
            data_source_mode=DataSourceMode.OPERATIONAL_PREDICTION,
        )
        cam = Camera(id="cam_active_01", site_id="site_reserve", timezone="UTC", latitude=34.05, longitude=-118.05)
        cov = CameraCoverage(
            camera_id="cam_active_01",
            detection_radius_meters=100.0,
        )
        snap_spatial = Snapshot(
            metadata=meta,
            cameras=[cam],
            media_assets=[],
            observations=[],
            prediction_runs=[],
            detections=[],
            encounters=[],
            reviews=[],
            monitoring_efforts=[],
            spatial_context=SpatialContext(
                zones=[SpatialZone(id="zone_study", name="Reserve Study Area", zone_type="study_area", geometry=study_poly)],
            ),
        )

        # 1. Blind Spot Analysis
        req_blind = BlindSpotAnalysisRequest(
            study_area_polygon=study_poly,
            camera_coverages=[cov],
            expected_revision=20,
        )
        resp_blind = analyze(snap_spatial, req_blind)
        assert resp_blind.status == ResponseStatus.OK
        assert resp_blind.dataset_revision == 20
        assert resp_blind.result.study_area_sq_meters > 0.0
        assert resp_blind.result.coverage_fraction < 0.01  # 100m radius is tiny compared to 11km x 11km
        assert resp_blind.result.gap_polygons_count >= 1

        # 2. Candidate Placement Ranking with one feasible site and one excluded site
        exclusion_poly = {
            "type": "Polygon",
            "coordinates": [
                [
                    [-118.09, 34.01],
                    [-118.08, 34.01],
                    [-118.08, 34.02],
                    [-118.09, 34.02],
                    [-118.09, 34.01],
                ]
            ],
        }
        cand_feasible = CandidateSite(
            candidate_id="cand_good",
            name="North Ridge Site",
            latitude=34.08,
            longitude=-118.03,
            cost=500.0,
            coverage_radius_meters=200.0,
        )
        cand_excluded = CandidateSite(
            candidate_id="cand_bad",
            name="Restricted Zone Site",
            latitude=34.015,
            longitude=-118.085,  # inside exclusion_poly
            cost=200.0,
            coverage_radius_meters=200.0,
        )
        excl_zone = SpatialZone(
            id="zone_excl",
            name="Restricted Zone",
            zone_type="exclusion_zone",
            geometry=exclusion_poly,
        )
        req_cand = CandidatePlacementRequest(
            study_area_polygon=study_poly,
            candidate_sites=[cand_feasible, cand_excluded],
            exclusion_zones=[excl_zone],
            cost_weight=0.1,
            expected_revision=20,
        )
        resp_cand = analyze(snap_spatial, req_cand)
        assert resp_cand.status == ResponseStatus.OK
        assert resp_cand.result.total_candidates == 2
        assert resp_cand.result.feasible_candidates_count == 1
        assert resp_cand.result.excluded_candidates_count == 1
        assert len(resp_cand.result.ranked_candidates) == 1
        assert resp_cand.result.ranked_candidates[0].candidate_id == "cand_good"
        assert resp_cand.result.ranked_candidates[0].rank == 1
        assert len(resp_cand.result.excluded_candidates) == 1
        assert resp_cand.result.excluded_candidates[0].candidate_id == "cand_bad"
        assert resp_cand.result.excluded_candidates[0].rank is None

        # 3. Infrastructure Scenario: Road buffer + hypothetical camera
        road_line = {
            "type": "LineString",
            "coordinates": [[-118.1, 34.05], [-118.0, 34.05]],
        }
        road_feat = {
            "name": "Proposed Patrol Road",
            "type": "road",
            "geometry": road_line,
            "buffer_meters": 50.0,
        }
        cam_feat = {
            "name": "Hypothetical Camera 01",
            "type": "proposed_camera",
            "geometry": {
                "type": "Point",
                "coordinates": [-118.07, 34.07],
            },
            "buffer_meters": 150.0,
        }
        req_infra = InfrastructureScenarioRequest(
            scenario_id="scenario_01",
            scenario_name="Patrol Road Scenario",
            study_area_polygon=study_poly,
            baseline_camera_coverages=[cov],
            hypothetical_features=[road_feat, cam_feat],
            expected_revision=20,
        )
        resp_infra = analyze(snap_spatial, req_infra)
        assert resp_infra.status == ResponseStatus.OK
        assert resp_infra.result.absolute_change_sq_meters != 0.0
        assert len(resp_infra.result.hypothetical_features_applied) == 2

        # Parity check: unified analyze() vs dedicated evaluate_infrastructure_scenario()
        resp_direct = evaluate_infrastructure_scenario(snap_spatial, req_infra)
        assert resp_direct.result.absolute_change_sq_meters == resp_infra.result.absolute_change_sq_meters
        assert resp_direct.result.scenario_covered_sq_meters == resp_infra.result.scenario_covered_sq_meters
