"""
WILDSCOPE Decision Intelligence & Analytics Module
Cross-Camera Observation Correlation - Phase 4 (Feature F06)

Finds pairs of encounters from different cameras that satisfy explicit species
and temporal rules, optionally applying spatial rules when genuine spatial
metadata is available.

CRITICAL SCIENTIFIC INTERPRETATION:
A match means: "Possible association between recorded sightings under the configured rules."
It does NOT establish:
  - The same individual animal.
  - A confirmed movement between cameras.
  - A migration route or wildlife corridor.
  - A known travel speed.
  - A probability of individual identity.

Same-species sightings close in time can be coincidental. Every result preserves this limitation.
GPS coordinates are optional; missing coordinates do not prevent valid time/species analysis.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from wildscope_analytics.contracts.entities import Encounter
from wildscope_analytics.contracts.enums import (
    AnalysisMetric,
    ClockComparabilityPolicy,
    DataSourceMode,
    EncounterProcessingStatus,
    InclusionPolicy,
    ResponseStatus,
    ReviewDecision,
    SpatialCheckStatus,
    SpatialMode,
    TemporalRelation,
    ValidationErrorCode,
)
from wildscope_analytics.contracts.requests import (
    AnalysisRequest,
    CrossCameraAssociationRequest,
)
from wildscope_analytics.contracts.responses import (
    AnalysisResponseEnvelope,
    CrossCameraAssociationPair,
    CrossCameraAssociationsResult,
    ValidationErrorDetail,
)
from wildscope_analytics.contracts.snapshot import CURRENT_SCHEMA_VERSION, Snapshot
from wildscope_analytics.validation import validate_snapshot_data


# ---------------------------------------------------------------------------
# GEODESIC DISTANCE (WGS84 HAVERSINE)
# ---------------------------------------------------------------------------

EARTH_RADIUS_METERS = 6371000.0


def haversine_distance_meters(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """
    Computes approximate spherical great-circle camera separation between two
    WGS84 coordinates on a spherical Earth model with mean radius 6,371,000 meters.
    Camera separation is not animal travel distance; actual animal travel paths,
    topography, vegetation, and physical barriers differ substantially from straight-line great-circle distance.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


# ---------------------------------------------------------------------------
# PLAIN-LANGUAGE EXPLANATION GENERATOR
# ---------------------------------------------------------------------------

def _generate_explanation(
    enc_a_id: str,
    cam_a_id: str,
    enc_b_id: str,
    cam_b_id: str,
    shared_taxa: list[str],
    nominal_gap: float,
    min_gap: float,
    max_gap: float,
    temporal_eligibility: str,
    order: str,
    dist: float | None,
) -> str:
    """Generates a deterministic plain-language explanation for an association."""
    taxa_str = ", ".join(f"'{t}'" for t in shared_taxa)
    if nominal_gap == 0.0 and min_gap == 0.0 and max_gap == 0.0:
        gap_str = "0.0s (overlapping intervals)"
    elif min_gap == max_gap:
        gap_str = f"nominal gap {nominal_gap:.1f}s ({temporal_eligibility})"
    else:
        gap_str = (
            f"nominal gap {nominal_gap:.1f}s (possible gap range: [{min_gap:.1f}s, {max_gap:.1f}s] "
            f"under clock uncertainty; {temporal_eligibility})"
        )

    if dist is not None:
        spatial_str = f"Approximate spherical great-circle camera separation is {dist:.1f} meters."
    else:
        spatial_str = "Camera distance is unknown or not evaluated; spatial feasibility was not evaluated."

    order_desc = {
        "overlapping": "recorded in overlapping time intervals",
        "A_before_B": f"encounter '{enc_a_id}' was recorded before encounter '{enc_b_id}'",
        "B_before_A": f"encounter '{enc_b_id}' was recorded before encounter '{enc_a_id}'",
    }.get(order, "recorded in disjoint intervals")

    return (
        f"Possible association between encounter '{enc_a_id}' (camera '{cam_a_id}') and "
        f"encounter '{enc_b_id}' (camera '{cam_b_id}') sharing species [{taxa_str}]. "
        f"Temporal separation: {gap_str} ({order_desc}). {spatial_str} "
        "Possible association only; individual animal identity and movement are not established."
    )


# ---------------------------------------------------------------------------
# CORE COMPUTATION ENGINE
# ---------------------------------------------------------------------------

def compute_cross_camera_associations(
    snapshot: Snapshot,
    request: CrossCameraAssociationRequest | AnalysisRequest,
) -> AnalysisResponseEnvelope:
    """
    Executes cross-camera observation correlation (Phase 4, Feature F06).
    Evaluates candidate encounters across different cameras against species,
    temporal, and optional spatial rules.
    """
    # 1. Normalize request to CrossCameraAssociationRequest
    if isinstance(request, dict):
        try:
            assoc_req = CrossCameraAssociationRequest(**request)
        except Exception:
            params = request.get("parameters") or request
            policy_raw = params.get("clock_comparability_policy", ClockComparabilityPolicy.ANALYST_ASSUMPTION)
            clock_policy = policy_raw if isinstance(policy_raw, ClockComparabilityPolicy) else ClockComparabilityPolicy(policy_raw)
            spatial_raw = params.get("spatial_mode", SpatialMode.TIME_SPECIES_ONLY)
            sp_mode = spatial_raw if isinstance(spatial_raw, SpatialMode) else SpatialMode(spatial_raw)
            assoc_req = CrossCameraAssociationRequest(
                metric=request.get("metric", AnalysisMetric.CROSS_CAMERA_ASSOCIATIONS),
                species_ids=request.get("species_ids"),
                camera_ids=request.get("camera_ids"),
                site_ids=request.get("site_ids"),
                start_time=request.get("start_time"),
                end_time=request.get("end_time"),
                analysis_timezone=request.get("analysis_timezone", "UTC"),
                max_temporal_separation_seconds=params.get("max_temporal_separation_seconds", 3600.0),
                clock_comparability_policy=clock_policy,
                clock_uncertainty_seconds=params.get("clock_uncertainty_seconds", 0.0),
                spatial_mode=sp_mode,
                max_spatial_distance_meters=params.get("max_spatial_distance_meters", None),
                inclusion_policy=request.get("inclusion_policy", InclusionPolicy.ALL_PROVISIONAL),
                min_confidence=request.get("min_confidence", 0.0),
                result_limit=params.get("result_limit", 50),
                evaluation_limit=params.get("evaluation_limit", None),
                evaluation_policy=params.get("evaluation_policy", "all_eligible"),
                expected_revision=request.get("expected_revision"),
                parameters=params,
            )
    elif isinstance(request, AnalysisRequest):
        params = request.parameters or {}
        policy_raw = params.get("clock_comparability_policy", ClockComparabilityPolicy.ANALYST_ASSUMPTION)
        clock_policy = policy_raw if isinstance(policy_raw, ClockComparabilityPolicy) else ClockComparabilityPolicy(policy_raw)

        spatial_raw = params.get("spatial_mode", SpatialMode.TIME_SPECIES_ONLY)
        sp_mode = spatial_raw if isinstance(spatial_raw, SpatialMode) else SpatialMode(spatial_raw)

        assoc_req = CrossCameraAssociationRequest(
            metric=request.metric,
            species_ids=request.species_ids,
            camera_ids=request.camera_ids,
            site_ids=request.site_ids,
            start_time=request.start_time,
            end_time=request.end_time,
            analysis_timezone=request.analysis_timezone,
            max_temporal_separation_seconds=params.get(
                "max_temporal_separation_seconds",
                3600.0
            ),
            clock_comparability_policy=clock_policy,
            clock_uncertainty_seconds=params.get("clock_uncertainty_seconds", 0.0),
            spatial_mode=sp_mode,
            max_spatial_distance_meters=params.get("max_spatial_distance_meters", None),
            inclusion_policy=request.inclusion_policy,
            min_confidence=request.min_confidence,
            result_limit=params.get("result_limit", 50),
            evaluation_limit=params.get("evaluation_limit", None),
            evaluation_policy=params.get("evaluation_policy", "all_eligible"),
            expected_revision=request.expected_revision,
            parameters=params,
        )
    else:
        assoc_req = request

    # 2. Contract and Snapshot Validation
    snap_report = validate_snapshot_data(snapshot)
    if not snap_report.is_valid:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=assoc_req.metric,
            applied_filters={"metric": assoc_req.metric.value},
            errors=snap_report.errors,
            warnings=snap_report.warnings,
            limitations=["Snapshot failed contract validation."],
        )

    # 3. Optimistic revision concurrency check
    if (
        assoc_req.expected_revision is not None
        and assoc_req.expected_revision != snapshot.metadata.dataset_revision
    ):
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=assoc_req.metric,
            applied_filters={"expected_revision": assoc_req.expected_revision},
            errors=[
                ValidationErrorDetail(
                    code=ValidationErrorCode.SCHEMA_VIOLATION,
                    message=(
                        f"Expected revision {assoc_req.expected_revision} does not match "
                        f"snapshot dataset revision {snapshot.metadata.dataset_revision}."
                    ),
                    field_path="expected_revision",
                )
            ],
            limitations=["Dataset revision conflict (optimistic lock mismatch)."],
        )

    # 4. Source mode guard: raw reference datasets contain images, not encounters
    source_mode = snapshot.metadata.data_source_mode
    if source_mode == DataSourceMode.DATASET_REFERENCE:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.UNAVAILABLE,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=assoc_req.metric,
            applied_filters={"data_source_mode": source_mode.value},
            limitations=[
                "Cross-camera encounter associations are UNAVAILABLE for raw image-only reference datasets. "
                "Reference datasets contain image annotations, not temporal encounter groupings."
            ],
            warnings=[
                "Encounter correlation requires operational encounter groupings produced by Harsh's pipeline."
            ],
        )

    # 5. Encounter processing status check
    status = snapshot.metadata.encounter_processing_status
    if not snapshot.encounters:
        if status == EncounterProcessingStatus.COMPLETED:
            # Grouping completed with 0 encounters -> valid empty result
            empty_result = CrossCameraAssociationsResult(
                data_source_mode=source_mode.value,
                clock_comparability_policy=assoc_req.clock_comparability_policy.value,
                clock_uncertainty_seconds=assoc_req.clock_uncertainty_seconds,
                spatial_mode=assoc_req.spatial_mode.value,
                temporal_threshold_seconds=assoc_req.max_temporal_separation_seconds,
                spatial_threshold_meters=assoc_req.max_spatial_distance_meters,
                total_eligible_encounters=0,
                total_candidate_pairs_evaluated=0,
                total_matching_pairs_found=0,
                returned_pairs_count=0,
                is_coverage_complete=True,
                evaluation_policy=assoc_req.evaluation_policy,
                associations=[],
            )
            return AnalysisResponseEnvelope(
                status=ResponseStatus.OK,
                schema_version=CURRENT_SCHEMA_VERSION,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=assoc_req.metric,
                applied_filters={"metric": assoc_req.metric.value},
                result=empty_result.model_dump(mode="json"),
                metric_units="associated encounter pairs",
                evidence_references=[],
                limitations=[
                    "Encounter grouping completed with zero encounters. No cross-camera associations exist."
                ],
            )
        # Pending, Failed, or Unavailable
        return AnalysisResponseEnvelope(
            status=ResponseStatus.UNAVAILABLE,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=assoc_req.metric,
            applied_filters={"metric": assoc_req.metric.value},
            limitations=[
                f"Encounter grouping is {status.value.upper() if status else 'UNAVAILABLE'} in Harsh's pipeline. "
                "Encounter-dependent correlation is UNAVAILABLE."
            ],
        )

    # 6. Clock comparability policy check
    limitations: list[str] = [
        "Possible association only; individual animal identity and movement are not established.",
        "Same-species sightings close in time can be coincidental.",
    ]
    warnings: list[str] = []
    exclusion_reasons: list[str] = []
    excluded_records_count = 0

    if assoc_req.clock_comparability_policy == ClockComparabilityPolicy.UNKNOWN:
        limitations.append(
            "Clock comparability policy is UNKNOWN; cannot reliably determine temporal separation "
            "across different physical camera clocks without an explicit synchronization record or analyst assumption."
        )
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INSUFFICIENT_DATA,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=assoc_req.metric,
            applied_filters={"clock_comparability_policy": assoc_req.clock_comparability_policy.value},
            result=None,
            metric_units="associated encounter pairs",
            limitations=limitations,
            warnings=["No clock comparability assumption provided; temporal separation cannot be computed."],
        )

    clock_offsets: dict[str, float] | None = None
    timestamps_pre_corrected = False
    correction_provenance: str | None = None

    if assoc_req.clock_comparability_policy == ClockComparabilityPolicy.OFFSETS_KNOWN:
        raw_offsets = assoc_req.parameters.get("clock_offsets")
        has_pre_corrected = assoc_req.parameters.get("timestamps_pre_corrected") is True
        prov = assoc_req.parameters.get("correction_provenance")

        # Ambiguous double correction: both clock_offsets and timestamps_pre_corrected=True supplied
        if raw_offsets is not None and has_pre_corrected:
            return AnalysisResponseEnvelope(
                status=ResponseStatus.INVALID_REQUEST,
                schema_version=CURRENT_SCHEMA_VERSION,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=assoc_req.metric,
                applied_filters={"clock_comparability_policy": assoc_req.clock_comparability_policy.value},
                result=None,
                metric_units="associated encounter pairs",
                limitations=[
                    "Ambiguous clock configuration: both 'clock_offsets' and 'timestamps_pre_corrected=True' were supplied. "
                    "Cannot determine whether timestamps have already been corrected or require offset addition."
                ],
                errors=[
                    ValidationErrorDetail(
                        code=ValidationErrorCode.SCHEMA_VIOLATION,
                        message="Ambiguous double correction: cannot supply both clock_offsets and timestamps_pre_corrected=True.",
                        field_path="parameters.clock_offsets",
                    )
                ],
            )

        if has_pre_corrected:
            if not prov:
                return AnalysisResponseEnvelope(
                    status=ResponseStatus.INSUFFICIENT_DATA,
                    schema_version=CURRENT_SCHEMA_VERSION,
                    dataset_revision=snapshot.metadata.dataset_revision,
                    metric=assoc_req.metric,
                    applied_filters={"clock_comparability_policy": assoc_req.clock_comparability_policy.value},
                    result=None,
                    metric_units="associated encounter pairs",
                    limitations=[
                        "Pre-corrected timestamps declared under OFFSETS_KNOWN without documented correction provenance "
                        "in parameters['correction_provenance']."
                    ],
                    warnings=["Pre-corrected timestamps require documented correction provenance."],
                )
            timestamps_pre_corrected = True
            correction_provenance = str(prov)
            limitations.append(f"Using pre-corrected timestamps with documented provenance: '{correction_provenance}'.")

        elif raw_offsets is not None:
            if not isinstance(raw_offsets, dict):
                return AnalysisResponseEnvelope(
                    status=ResponseStatus.INVALID_REQUEST,
                    schema_version=CURRENT_SCHEMA_VERSION,
                    dataset_revision=snapshot.metadata.dataset_revision,
                    metric=assoc_req.metric,
                    applied_filters={"clock_comparability_policy": assoc_req.clock_comparability_policy.value},
                    result=None,
                    metric_units="associated encounter pairs",
                    limitations=["'clock_offsets' in parameters must be a dictionary mapping camera_id to offset seconds."],
                    errors=[
                        ValidationErrorDetail(
                            code=ValidationErrorCode.SCHEMA_VIOLATION,
                            message="'clock_offsets' must be a dictionary of camera_id to float seconds.",
                            field_path="parameters.clock_offsets",
                        )
                    ],
                )
            # Validate all values are finite numbers
            validated_offsets: dict[str, float] = {}
            for cid, val in raw_offsets.items():
                if not isinstance(val, (int, float)) or not math.isfinite(val):
                    return AnalysisResponseEnvelope(
                        status=ResponseStatus.INVALID_REQUEST,
                        schema_version=CURRENT_SCHEMA_VERSION,
                        dataset_revision=snapshot.metadata.dataset_revision,
                        metric=assoc_req.metric,
                        applied_filters={"clock_comparability_policy": assoc_req.clock_comparability_policy.value},
                        result=None,
                        metric_units="associated encounter pairs",
                        limitations=[f"Non-finite or invalid clock offset for camera '{cid}': {val}."],
                        errors=[
                            ValidationErrorDetail(
                                code=ValidationErrorCode.SCHEMA_VIOLATION,
                                message=f"Clock offset for camera '{cid}' must be a finite number in seconds.",
                                field_path=f"parameters.clock_offsets.{cid}",
                            )
                        ],
                    )
                validated_offsets[str(cid)] = float(val)
            clock_offsets = validated_offsets
            correction_provenance = str(prov) if prov else "parameters.clock_offsets"
            limitations.append(
                f"Per-camera clock offsets applied (t_corrected = t_raw + offset_seconds). "
                f"Offsets defined for {len(clock_offsets)} camera(s)."
            )
        else:
            # Neither valid clock_offsets nor timestamps_pre_corrected=True
            # Uncertainty bounds alone do NOT satisfy OFFSETS_KNOWN!
            return AnalysisResponseEnvelope(
                status=ResponseStatus.INSUFFICIENT_DATA,
                schema_version=CURRENT_SCHEMA_VERSION,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=assoc_req.metric,
                applied_filters={"clock_comparability_policy": assoc_req.clock_comparability_policy.value},
                result=None,
                metric_units="associated encounter pairs",
                limitations=[
                    "Clock comparability policy OFFSETS_KNOWN requires either valid per-camera 'clock_offsets' "
                    "or 'timestamps_pre_corrected=True' with 'correction_provenance'. "
                    "Uncertainty bounds alone do not constitute offset corrections."
                ],
                warnings=[
                    "OFFSETS_KNOWN requires verified per-camera clock_offsets or pre-corrected timestamps with provenance."
                ],
            )

        if assoc_req.clock_uncertainty_seconds > 0.0:
            limitations.append(
                f"Combined pairwise clock uncertainty bound ±{assoc_req.clock_uncertainty_seconds:.1f}s propagated."
            )
    elif assoc_req.clock_comparability_policy == ClockComparabilityPolicy.ANALYST_ASSUMPTION:
        limitations.append(
            "Inter-camera clock alignment relies on analyst assumption; physical camera clock drift is unverified."
        )
    elif assoc_req.clock_comparability_policy == ClockComparabilityPolicy.DOCUMENTED_SYNC:
        limitations.append(
            "Deployment clocks verified synchronized (e.g. NTP, GPS, or calibration audit)."
        )

    # 7. Spatial prerequisites check
    cameras_map = {c.id: c for c in snapshot.cameras}
    cameras_with_gps = sum(1 for c in snapshot.cameras if c.latitude is not None and c.longitude is not None)

    if assoc_req.spatial_mode == SpatialMode.SPATIAL_REQUIRED:
        if cameras_with_gps == 0:
            return AnalysisResponseEnvelope(
                status=ResponseStatus.UNAVAILABLE,
                schema_version=CURRENT_SCHEMA_VERSION,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=assoc_req.metric,
                applied_filters={"spatial_mode": assoc_req.spatial_mode.value},
                result=None,
                metric_units="associated encounter pairs",
                limitations=[
                    "Spatial mode 'spatial_required' requested, but cameras lack genuine spatial coordinates."
                ],
                warnings=["Cannot perform spatial distance check without GPS coordinates on cameras."],
            )

    # 8. Camera and Site Scope Filtering
    scoped_camera_ids = set(cameras_map.keys())
    if assoc_req.camera_ids is not None:
        scoped_camera_ids &= set(assoc_req.camera_ids)
    if assoc_req.site_ids is not None:
        site_set = set(assoc_req.site_ids)
        scoped_camera_ids = {cid for cid in scoped_camera_ids if cameras_map[cid].site_id in site_set}

    # 9. Effective Label Resolution
    from wildscope_analytics.analytics import resolve_effective_labels
    labels = resolve_effective_labels(snapshot)
    detections_map = {d.id: d for d in snapshot.detections}

    # 10. Filter encounters and extract deduplicated species per encounter
    # encounter_info: dict[enc_id, dict]
    eligible_encounters: dict[str, dict[str, Any]] = {}
    focal_species_set = set(assoc_req.species_ids) if assoc_req.species_ids is not None else None

    for enc in snapshot.encounters:
        if enc.camera_id not in scoped_camera_ids:
            continue

        # Check timestamp presence and awareness
        if enc.start_time is None or enc.end_time is None:
            excluded_records_count += 1
            if "Encounter missing timestamp" not in exclusion_reasons:
                exclusion_reasons.append("Encounter missing timestamp")
            continue

        if enc.start_time.tzinfo is None or enc.end_time.tzinfo is None:
            excluded_records_count += 1
            if "Encounter timestamps lack timezone awareness" not in exclusion_reasons:
                exclusion_reasons.append("Encounter timestamps lack timezone awareness")
            continue

        # Check required camera offset under OFFSETS_KNOWN with clock_offsets
        if clock_offsets is not None and enc.camera_id not in clock_offsets:
            return AnalysisResponseEnvelope(
                status=ResponseStatus.INSUFFICIENT_DATA,
                schema_version=CURRENT_SCHEMA_VERSION,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=assoc_req.metric,
                applied_filters={"clock_comparability_policy": assoc_req.clock_comparability_policy.value},
                result=None,
                metric_units="associated encounter pairs",
                limitations=[
                    f"Camera '{enc.camera_id}' has encounters in scope but is missing from parameters['clock_offsets']. "
                    "Under OFFSETS_KNOWN, all cameras with scoped encounters must have an explicit offset."
                ],
                warnings=[f"Missing required clock offset for camera '{enc.camera_id}'."],
            )

        # Apply per-camera clock offset (sign convention: t_corrected = t_raw + offset_seconds)
        # Note: does NOT mutate the source snapshot.
        offset_seconds = clock_offsets[enc.camera_id] if clock_offsets is not None else 0.0
        offset_delta = timedelta(seconds=offset_seconds)
        corr_start = enc.start_time + offset_delta
        corr_end = enc.end_time + offset_delta

        # Check time window filter against corrected timestamps
        if assoc_req.start_time is not None and corr_end < assoc_req.start_time:
            continue
        if assoc_req.end_time is not None and corr_start > assoc_req.end_time:
            continue

        # Extract eligible species from member detections
        enc_species: set[str] = set()
        provenance_map: dict[str, str] = {}
        enc_det_ids: list[str] = []
        enc_obs_ids: list[str] = list(enc.member_observation_ids)

        for det_id in enc.member_detection_ids:
            det = detections_map.get(det_id)
            if det is None:
                continue

            eff = labels.get(det_id)
            if eff is None:
                continue

            # Review status filtering
            is_reviewed = eff.review_id is not None
            if assoc_req.inclusion_policy == InclusionPolicy.REVIEWED_ONLY and not is_reviewed:
                continue

            # Exclude rejected, empty frames, and unresolved conflicts
            if eff.is_rejected or eff.is_empty:
                continue

            # Ambiguous review conflicts
            if eff.is_unresolved:
                if "Ambiguous review conflict on detection excluded from species matching" not in warnings:
                    warnings.append("Ambiguous review conflict on detection excluded from species matching")
                continue

            # Unknown animal cannot match
            if eff.is_unknown:
                continue

            # Check confidence cutoff
            conf = det.classification_confidence or 0.0
            if conf < assoc_req.min_confidence:
                continue

            taxon = eff.taxon_id
            if not taxon or taxon == "unknown":
                continue

            if focal_species_set is not None and taxon not in focal_species_set:
                continue

            enc_species.add(taxon)
            enc_det_ids.append(det_id)
            provenance_desc = (
                f"reviewed_{eff.decision}:{taxon}"
                if is_reviewed and eff.decision
                else f"provisional_prediction:{taxon}:{conf:.2f}"
            )
            provenance_map[det_id] = provenance_desc

        if not enc_species:
            # Encounter has no eligible focal animal species
            continue

        eligible_encounters[enc.id] = {
            "encounter": enc,
            "camera_id": enc.camera_id,
            "species_set": enc_species,
            "detection_ids": sorted(enc_det_ids),
            "observation_ids": sorted(set(enc_obs_ids)),
            "provenance_map": provenance_map,
            "start_time": corr_start,
            "end_time": corr_end,
            "raw_start_time": enc.start_time,
            "raw_end_time": enc.end_time,
            "clock_offset_seconds": offset_seconds if clock_offsets is not None else None,
        }

    total_eligible_encounters = len(eligible_encounters)

    # 11. Optimized pair evaluation by indexing encounters per species
    # encounters_by_species: taxon -> list of enc_id
    encounters_by_species: dict[str, list[str]] = defaultdict(list)
    for enc_id, info in eligible_encounters.items():
        for sp in info["species_set"]:
            encounters_by_species[sp].append(enc_id)

    # Sort encounter IDs by start_time for each species to allow sliding-window evaluation
    for sp in encounters_by_species:
        encounters_by_species[sp].sort(
            key=lambda eid: (eligible_encounters[eid]["start_time"], eid)
        )

    # Track evaluated pairs and matches
    evaluated_pairs_set: set[tuple[str, str]] = set()
    matching_pairs: dict[str, CrossCameraAssociationPair] = {}
    is_coverage_complete = True
    evaluation_bound_hit = False

    max_gap = assoc_req.max_temporal_separation_seconds
    uncertainty = assoc_req.clock_uncertainty_seconds

    # Iterate over taxa
    for sp, enc_id_list in sorted(encounters_by_species.items()):
        if evaluation_bound_hit:
            break

        n_encs = len(enc_id_list)
        for i in range(n_encs):
            if evaluation_bound_hit:
                break

            id_a = enc_id_list[i]
            info_a = eligible_encounters[id_a]
            start_a = info_a["start_time"]
            end_a = info_a["end_time"]
            cam_a_id = info_a["camera_id"]

            for j in range(i + 1, n_encs):
                id_b = enc_id_list[j]
                info_b = eligible_encounters[id_b]
                cam_b_id = info_b["camera_id"]

                # Exclude same camera
                if cam_a_id == cam_b_id:
                    continue

                start_b = info_b["start_time"]
                end_b = info_b["end_time"]

                # Sliding window cutoff:
                # Since list is sorted by start_time, start_b >= start_a.
                # If start_b is strictly later than end_a, temporal gap is start_b - end_a.
                # If (start_b - end_a) - uncertainty > max_gap, all subsequent encounters
                # will also have start_k >= start_b > end_a with gap > max_gap!
                if start_b > end_a:
                    time_diff = (start_b - end_a).total_seconds()
                    if time_diff - uncertainty > max_gap:
                        break

                canonical_pair = (min(id_a, id_b), max(id_a, id_b))
                if canonical_pair in evaluated_pairs_set:
                    # Already evaluated this pair under another shared species
                    continue

                # Check evaluation limit
                if (
                    assoc_req.evaluation_limit is not None
                    and len(evaluated_pairs_set) >= assoc_req.evaluation_limit
                ):
                    evaluation_bound_hit = True
                    is_coverage_complete = False
                    break

                evaluated_pairs_set.add(canonical_pair)

                # Determine canonical A and B by encounter ID
                enc_1_id, enc_2_id = canonical_pair
                data_1 = eligible_encounters[enc_1_id]
                data_2 = eligible_encounters[enc_2_id]

                # Shared taxa
                shared_taxa = sorted(data_1["species_set"] & data_2["species_set"])
                if not shared_taxa:
                    continue

                # Temporal gap calculation
                t_start_1 = data_1["start_time"]
                t_end_1 = data_1["end_time"]
                t_start_2 = data_2["start_time"]
                t_end_2 = data_2["end_time"]

                diff_1_2 = (t_start_2 - t_end_1).total_seconds()
                diff_2_1 = (t_start_1 - t_end_2).total_seconds()
                nominal_gap = max(0.0, diff_1_2, diff_2_1)
                min_possible_gap = max(0.0, nominal_gap - uncertainty)
                # Exact attainable supremum over u in [-uncertainty, uncertainty]:
                # For disjoint intervals, this equals nominal_gap + uncertainty.
                # For overlapping intervals, max(0.0, diff_1_2 + U, diff_2_1 + U) computes the exact attainable
                # upper bound rather than an unattainable G + U enclosure.
                max_possible_gap = max(0.0, diff_1_2 + uncertainty, diff_2_1 + uncertainty)
                effective_gap = min_possible_gap

                # Temporal threshold evaluation (boundary included)
                # Eligibility means the candidate is possibly within the temporal separation window
                if min_possible_gap > max_gap:
                    continue

                temporal_eligibility = (
                    "definitely_within_threshold"
                    if max_possible_gap <= max_gap
                    else "possibly_within_threshold"
                )

                # Temporal relation and ordering
                if nominal_gap == 0.0:
                    temporal_relation = TemporalRelation.OVERLAPPING.value
                    observed_order = "overlapping"
                elif t_end_1 < t_start_2:
                    temporal_relation = TemporalRelation.DISJOINT.value
                    observed_order = "A_before_B"
                elif t_end_2 < t_start_1:
                    temporal_relation = TemporalRelation.DISJOINT.value
                    observed_order = "B_before_A"
                else:
                    temporal_relation = TemporalRelation.OVERLAPPING.value
                    observed_order = "overlapping"

                # Spatial check evaluation
                cam_1 = cameras_map[data_1["camera_id"]]
                cam_2 = cameras_map[data_2["camera_id"]]
                coords_ok = (
                    cam_1.latitude is not None
                    and cam_1.longitude is not None
                    and cam_2.latitude is not None
                    and cam_2.longitude is not None
                )

                dist_m: float | None = None
                spatial_units: str | None = None
                spatial_status: SpatialCheckStatus
                spatial_note: str
                passes_spatial = True

                if assoc_req.spatial_mode == SpatialMode.TIME_SPECIES_ONLY:
                    spatial_status = SpatialCheckStatus.NOT_EVALUATED
                    spatial_note = "Camera distance is unknown or not evaluated; spatial feasibility was not evaluated."
                elif assoc_req.spatial_mode == SpatialMode.SPATIAL_WHEN_AVAILABLE:
                    if coords_ok:
                        dist_m = haversine_distance_meters(
                            cam_1.latitude, cam_1.longitude,
                            cam_2.latitude, cam_2.longitude,
                        )
                        spatial_units = "meters"
                        spatial_note = (
                            f"Approximate spherical great-circle camera separation is {dist_m:.1f} meters. "
                            "Camera separation is not animal travel distance; biological movement feasibility is not validated."
                        )
                        if assoc_req.max_spatial_distance_meters is not None:
                            if dist_m <= assoc_req.max_spatial_distance_meters:
                                spatial_status = SpatialCheckStatus.PASSED
                            else:
                                spatial_status = SpatialCheckStatus.FAILED
                                passes_spatial = False
                        else:
                            spatial_status = SpatialCheckStatus.MEASURED
                    else:
                        spatial_status = SpatialCheckStatus.UNAVAILABLE
                        spatial_note = "Camera distance is unknown or not evaluated; spatial feasibility was not evaluated."
                else:  # SPATIAL_REQUIRED
                    if coords_ok:
                        dist_m = haversine_distance_meters(
                            cam_1.latitude, cam_1.longitude,
                            cam_2.latitude, cam_2.longitude,
                        )
                        spatial_units = "meters"
                        spatial_note = (
                            f"Approximate spherical great-circle camera separation is {dist_m:.1f} meters. "
                            "Camera separation is not animal travel distance; biological movement feasibility is not validated."
                        )
                        if assoc_req.max_spatial_distance_meters is not None:
                            if dist_m <= assoc_req.max_spatial_distance_meters:
                                spatial_status = SpatialCheckStatus.PASSED
                            else:
                                spatial_status = SpatialCheckStatus.FAILED
                                passes_spatial = False
                        else:
                            spatial_status = SpatialCheckStatus.MEASURED
                    else:
                        spatial_status = SpatialCheckStatus.UNAVAILABLE
                        spatial_note = "Camera distance is unknown or not evaluated; spatial feasibility was not evaluated."
                        passes_spatial = False

                if not passes_spatial:
                    continue

                # Merge provenance descriptions
                merged_provenance = {}
                merged_provenance.update(data_1["provenance_map"])
                merged_provenance.update(data_2["provenance_map"])

                assoc_id = f"assoc:{enc_1_id}::{enc_2_id}"
                explanation = _generate_explanation(
                    enc_1_id, data_1["camera_id"],
                    enc_2_id, data_2["camera_id"],
                    shared_taxa,
                    nominal_gap,
                    min_possible_gap,
                    max_possible_gap,
                    temporal_eligibility,
                    observed_order,
                    dist_m,
                )

                rule_outcomes = {
                    "species_match": True,
                    "temporal_threshold": True,
                    "spatial_threshold": passes_spatial,
                }

                matching_pairs[assoc_id] = CrossCameraAssociationPair(
                    association_id=assoc_id,
                    encounter_id_a=enc_1_id,
                    encounter_id_b=enc_2_id,
                    camera_id_a=data_1["camera_id"],
                    camera_id_b=data_2["camera_id"],
                    shared_taxa=shared_taxa,
                    observation_ids_a=data_1["observation_ids"],
                    observation_ids_b=data_2["observation_ids"],
                    detection_ids_a=data_1["detection_ids"],
                    detection_ids_b=data_2["detection_ids"],
                    effective_labels_provenance=merged_provenance,
                    start_time_a=t_start_1.isoformat(),
                    end_time_a=t_end_1.isoformat(),
                    start_time_b=t_start_2.isoformat(),
                    end_time_b=t_end_2.isoformat(),
                    nominal_gap_seconds=nominal_gap,
                    min_possible_gap_seconds=min_possible_gap,
                    max_possible_gap_seconds=max_possible_gap,
                    effective_gap_seconds=effective_gap,
                    temporal_eligibility=temporal_eligibility,
                    clock_offset_seconds_a=data_1["clock_offset_seconds"],
                    clock_offset_seconds_b=data_2["clock_offset_seconds"],
                    temporal_relation=temporal_relation,
                    observed_interval_order=observed_order,
                    spatial_check_status=spatial_status.value,
                    camera_distance_meters=round(dist_m, 2) if dist_m is not None else None,
                    spatial_units=spatial_units,
                    rule_outcomes=rule_outcomes,
                    spatial_note=spatial_note,
                    explanation=explanation,
                )

    # 12. Sort matching associations deterministically:
    # Primary: effective_gap_seconds ascending; Secondary: association_id ascending
    sorted_associations = sorted(
        matching_pairs.values(),
        key=lambda pair: (pair.effective_gap_seconds, pair.association_id),
    )

    total_matching = len(sorted_associations)

    # 13. Apply result_limit (top-k)
    limit = assoc_req.result_limit or 50
    returned_associations = sorted_associations[:limit]

    # Collect evidence references
    evidence_refs: list[str] = []
    for pair in returned_associations:
        evidence_refs.append(f"enc:{pair.encounter_id_a}")
        evidence_refs.append(f"enc:{pair.encounter_id_b}")
    evidence_refs = sorted(set(evidence_refs))[:20]

    if not is_coverage_complete:
        limitations.append(
            f"Coverage is incomplete: candidate pair evaluation was bounded by evaluation_limit={assoc_req.evaluation_limit}."
        )

    # Response status determination
    if not is_coverage_complete or excluded_records_count > 0:
        resp_status = ResponseStatus.PARTIAL
    else:
        resp_status = ResponseStatus.OK

    result = CrossCameraAssociationsResult(
        data_source_mode=source_mode.value,
        rule_version="cross_camera_association_v1",
        clock_comparability_policy=assoc_req.clock_comparability_policy.value,
        clock_uncertainty_seconds=assoc_req.clock_uncertainty_seconds,
        clock_offsets_applied=clock_offsets,
        timestamps_pre_corrected=timestamps_pre_corrected,
        correction_provenance=correction_provenance,
        spatial_mode=assoc_req.spatial_mode.value,
        temporal_threshold_seconds=assoc_req.max_temporal_separation_seconds,
        spatial_threshold_meters=assoc_req.max_spatial_distance_meters,
        total_eligible_encounters=total_eligible_encounters,
        total_candidate_pairs_evaluated=len(evaluated_pairs_set),
        total_matching_pairs_found=total_matching,
        returned_pairs_count=len(returned_associations),
        is_coverage_complete=is_coverage_complete,
        evaluation_policy=assoc_req.evaluation_policy,
        associations=returned_associations,
    )

    applied_filters = {
        "metric": assoc_req.metric.value,
        "species_ids": assoc_req.species_ids,
        "camera_ids": assoc_req.camera_ids,
        "site_ids": assoc_req.site_ids,
        "start_time": assoc_req.start_time.isoformat() if assoc_req.start_time else None,
        "end_time": assoc_req.end_time.isoformat() if assoc_req.end_time else None,
        "max_temporal_separation_seconds": assoc_req.max_temporal_separation_seconds,
        "clock_comparability_policy": assoc_req.clock_comparability_policy.value,
        "clock_uncertainty_seconds": assoc_req.clock_uncertainty_seconds,
        "spatial_mode": assoc_req.spatial_mode.value,
        "max_spatial_distance_meters": assoc_req.max_spatial_distance_meters,
        "inclusion_policy": assoc_req.inclusion_policy.value,
        "min_confidence": assoc_req.min_confidence,
        "result_limit": assoc_req.result_limit,
        "evaluation_limit": assoc_req.evaluation_limit,
    }

    return AnalysisResponseEnvelope(
        status=resp_status,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=assoc_req.metric,
        applied_filters=applied_filters,
        result=result.model_dump(mode="json"),
        metric_units="associated encounter pairs",
        evidence_references=evidence_refs,
        excluded_records_count=excluded_records_count,
        exclusion_reasons=exclusion_reasons,
        warnings=warnings,
        limitations=limitations,
    )


# ---------------------------------------------------------------------------
# EXHAUSTIVE REFERENCE IMPLEMENTATION (FOR PARITY TESTING)
# ---------------------------------------------------------------------------

def _exhaustive_pairwise_associations(
    snapshot: Snapshot,
    request: CrossCameraAssociationRequest,
) -> list[str]:
    """
    Exhaustive O(N^2) unoptimized candidate generator.
    Evaluates every pair of encounters from different cameras without sliding-window pruning.
    Used exclusively in regression tests to verify parity with the optimized generator.
    Returns sorted list of matching association_ids.
    """
    from wildscope_analytics.analytics import resolve_effective_labels
    labels = resolve_effective_labels(snapshot)
    detections_map = {d.id: d for d in snapshot.detections}
    cameras_map = {c.id: c for c in snapshot.cameras}

    # Extract species per encounter
    enc_data = {}
    focal_species = set(request.species_ids) if request.species_ids else None
    clock_offsets = request.parameters.get("clock_offsets") if request.parameters else None

    for enc in snapshot.encounters:
        if enc.start_time is None or enc.end_time is None:
            continue
        taxa = set()
        for did in enc.member_detection_ids:
            det = detections_map.get(did)
            if not det:
                continue
            eff = labels.get(did)
            if not eff or eff.is_rejected or eff.is_empty or eff.is_unresolved or eff.is_unknown:
                continue
            if eff.taxon_id and eff.taxon_id != "unknown":
                if focal_species is None or eff.taxon_id in focal_species:
                    taxa.add(eff.taxon_id)
        if taxa:
            offset_sec = float(clock_offsets[enc.camera_id]) if clock_offsets and enc.camera_id in clock_offsets else 0.0
            from datetime import timedelta
            corr_start = enc.start_time + timedelta(seconds=offset_sec)
            corr_end = enc.end_time + timedelta(seconds=offset_sec)
            enc_data[enc.id] = (enc, taxa, corr_start, corr_end)

    enc_ids = sorted(enc_data.keys())
    matching_ids = []

    for i in range(len(enc_ids)):
        id_1 = enc_ids[i]
        enc_1, taxa_1, start_1, end_1 = enc_data[id_1]
        for j in range(i + 1, len(enc_ids)):
            id_2 = enc_ids[j]
            enc_2, taxa_2, start_2, end_2 = enc_data[id_2]

            # Different camera
            if enc_1.camera_id == enc_2.camera_id:
                continue

            # Shared taxa
            shared = taxa_1 & taxa_2
            if not shared:
                continue

            # Temporal gap using offset-corrected timestamps
            diff_1_2 = (start_2 - end_1).total_seconds()
            diff_2_1 = (start_1 - end_2).total_seconds()
            nominal_gap = max(0.0, diff_1_2, diff_2_1)
            effective_gap = max(0.0, nominal_gap - request.clock_uncertainty_seconds)

            if effective_gap > request.max_temporal_separation_seconds:
                continue

            # Spatial check
            cam_1 = cameras_map[enc_1.camera_id]
            cam_2 = cameras_map[enc_2.camera_id]
            coords_ok = (
                cam_1.latitude is not None and cam_1.longitude is not None
                and cam_2.latitude is not None and cam_2.longitude is not None
            )

            if request.spatial_mode == SpatialMode.SPATIAL_REQUIRED and not coords_ok:
                continue

            if coords_ok and request.max_spatial_distance_meters is not None:
                dist = haversine_distance_meters(
                    cam_1.latitude, cam_1.longitude,
                    cam_2.latitude, cam_2.longitude,
                )
                if dist > request.max_spatial_distance_meters:
                    continue

            pair_id = f"assoc:{min(id_1, id_2)}::{max(id_1, id_2)}"
            matching_ids.append(pair_id)

    return sorted(matching_ids)
