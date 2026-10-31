"""
WILDSCOPE Decision Intelligence & Analytics Module
Response Envelope Contracts - Phase 1

Defines standard response envelopes and structured error models returned
by analysis and review-ranking pipelines to the frontend (Laasya) and API (Santosh).
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import Field

from wildscope_analytics.contracts.entities import BaseContractModel
from wildscope_analytics.contracts.enums import (
    AnalysisMetric,
    AnomalyOutcome,
    CandidatePlacementStatus,
    ComparabilityAssessment,
    PositionType,
    ProximityRelation,
    ResponseStatus,
    SpatialSourceType,
    ValidationErrorCode,
)
from wildscope_analytics.contracts.snapshot import CURRENT_SCHEMA_VERSION

T = TypeVar("T")


class ValidationErrorDetail(BaseContractModel):
    """Structured detail for a contract or data validation error."""
    code: ValidationErrorCode | str = Field(
        ...,
        description="Stable machine-readable error code."
    )
    message: str = Field(..., description="Human-readable explanation of error.")
    field_path: str = Field(
        ...,
        description="Path to violating field in dot/bracket notation, e.g. 'detections[2].classification_confidence'."
    )
    entity_type: str | None = Field(default=None, description="Entity type involved, e.g. 'Detection'.")
    entity_id: str | None = Field(default=None, description="Identifier of entity if known.")


class AnalysisResponseEnvelope(BaseContractModel, Generic[T]):
    """
    Standard envelope enclosing all analytical and review ranking outcomes.

    Status semantics:
    - OK: Computation completed cleanly against sufficient validated data.
    - PARTIAL: Usable result produced, but some records were excluded due to quality/missing fields.
    - INSUFFICIENT_DATA: Relevant inputs exist, but their quantity/quality is inadequate (e.g. no effort records).
    - UNAVAILABLE: Required capability or prerequisite is absent (e.g. unconfigured model, missing telemetry).
    - INVALID_REQUEST: Request parameters failed validation or revision mismatch occurred.
    """
    status: ResponseStatus = Field(
        ...,
        description="Operational status of the response."
    )
    schema_version: str = Field(
        default=CURRENT_SCHEMA_VERSION,
        description="Schema contract version."
    )
    dataset_revision: int = Field(
        ...,
        ge=0,
        description="Data revision of the source snapshot used for computation."
    )
    metric: AnalysisMetric | None = Field(
        default=None,
        description="Metric evaluated in this response."
    )
    applied_filters: dict[str, Any] = Field(
        default_factory=dict,
        description="Echo of filters applied during computation."
    )
    result: T | None = Field(
        default=None,
        description="Typed analytical payload, or None when unavailable/insufficient."
    )
    metric_units: str | dict[str, str] | None = Field(
        default=None,
        description="Units of measurement (e.g. 'encounters/camera-day', 'count')."
    )
    evidence_references: list[str] = Field(
        default_factory=list,
        description="Audit references to source entity IDs (camera, media, observation, encounter, review)."
    )
    excluded_records_count: int = Field(
        default=0,
        ge=0,
        description="Count of records excluded during calculation."
    )
    exclusion_reasons: list[str] = Field(
        default_factory=list,
        description="Documented reasons for record exclusions."
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Advisory warnings encountered during processing."
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Explicit methodological or data limitations."
    )
    errors: list[ValidationErrorDetail] = Field(
        default_factory=list,
        description="Structured error details if status is INVALID_REQUEST or validation failed."
    )


class EvaluatedAlternative(BaseContractModel):
    """Evaluation of one candidate alternative outcome on the target metric."""
    taxon_id: str = Field(..., description="Hypothetical alternative taxon/label.")
    alternative_score: float | None = Field(default=None, description="Model score/confidence for this alternative if provided.")
    counterfactual_value: float = Field(..., description="Target metric value if this alternative were confirmed.")
    signed_delta: float = Field(..., description="Signed change from baseline (counterfactual - baseline).")
    absolute_delta: float = Field(..., description="Absolute magnitude of change (|counterfactual - baseline|).")
    impact_summary: str = Field(..., description="Concise human-readable impact description.")


class RankedCandidateResult(BaseContractModel):
    """Ranked review candidate with counterfactual evaluations."""
    rank: int = Field(..., ge=1, description="Priority rank (1 = highest impact).")
    detection_id: str = Field(..., description="ID of the candidate Detection.")
    encounter_id: str = Field(..., description="ID of the Encounter containing this detection.")
    observation_id: str = Field(..., description="ID of parent Observation.")
    camera_id: str = Field(..., description="ID of the physical Camera trap.")
    current_effective_label: str | None = Field(default=None, description="Current effective taxon label before review.")
    current_prediction: str | None = Field(default=None, description="Original predicted taxon ID.")
    current_confidence: float | None = Field(default=None, description="Model confidence for current prediction.")
    score_type: str | None = Field(default=None, description="Score type of model prediction.")
    alternatives_evaluated: list[EvaluatedAlternative] = Field(
        default_factory=list,
        description="Evaluated alternative outcomes."
    )
    max_absolute_impact: float = Field(..., description="Maximum absolute change in target metric across alternatives.")
    explanation: str = Field(..., description="Deterministic explanation of why this candidate is prioritized.")


class ReviewRankingResult(BaseContractModel):
    """Complete typed payload for conclusion-sensitive review ranking."""
    target_metric: str = Field(..., description="Metric whose sensitivity guided review priority.")
    target_species_id: str | None = Field(default=None, description="Focal species for scalar metric.")
    metric_units: str = Field(..., description="Units of the evaluated metric.")
    baseline_value: float = Field(..., description="Baseline value of target metric prior to review.")
    camera_id_a: str | None = Field(default=None, description="Camera A for comparison metric.")
    camera_id_b: str | None = Field(default=None, description="Camera B for comparison metric.")
    total_detections_in_scope: int = Field(..., description="Total detections in scope.")
    eligible_candidates_count: int = Field(..., description="Detections meeting review eligibility.")
    ranked_candidates_count: int = Field(..., description="Count of returned ranked candidates.")
    excluded_candidates_count: int = Field(..., description="Detections evaluated but excluded (e.g. resolved, zero-impact).")
    result_limit: int = Field(default=50, description="Requested result limit for top-k candidates.")
    evaluation_limit: int | None = Field(default=None, description="Candidate evaluation cap if applied.")
    evaluation_policy: str = Field(default="all_eligible", description="Candidate evaluation selection policy.")
    is_evaluation_bounded: bool = Field(default=False, description="Whether candidate evaluation was capped before evaluating all candidates.")
    candidates: list[RankedCandidateResult] = Field(default_factory=list, description="Ranked review candidates.")
    marginal_analysis_disclaimer: str = Field(
        default=(
            "One-candidate-at-a-time marginal sensitivity analysis. Does NOT represent a joint uncertainty interval. "
            "Changes from multiple candidates are not additive due to encounter deduplication."
        ),
        description="Methodological limitations of marginal sensitivity ranking."
    )
    note: str = Field(
        default=(
            "Ranking priority is deterministically computed based on potential impact on the selected metric. "
            "This does not invent probabilities, write review events, or assert alternative labels are true."
        ),
        description="Operational context for reviewers."
    )


class CrossCameraAssociationPair(BaseContractModel):
    """
    Typed record for a single correlated encounter pair across different cameras (Feature F06).
    """
    association_id: str = Field(..., description="Deterministic stable pair identifier, e.g. 'assoc:enc_1::enc_2'.")
    encounter_id_a: str = Field(..., description="Identifier of the first encounter in the pair.")
    encounter_id_b: str = Field(..., description="Identifier of the second encounter in the pair.")
    camera_id_a: str = Field(..., description="Physical camera ID for encounter A.")
    camera_id_b: str = Field(..., description="Physical camera ID for encounter B.")
    shared_taxa: list[str] = Field(..., description="Eligible species present in both encounters.")
    observation_ids_a: list[str] = Field(default_factory=list, description="Source observation IDs for encounter A.")
    observation_ids_b: list[str] = Field(default_factory=list, description="Source observation IDs for encounter B.")
    detection_ids_a: list[str] = Field(default_factory=list, description="Source detection IDs for encounter A.")
    detection_ids_b: list[str] = Field(default_factory=list, description="Source detection IDs for encounter B.")
    effective_labels_provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Effective label resolution and provenance per detection ID."
    )
    start_time_a: str = Field(..., description="ISO 8601 start timestamp for encounter A.")
    end_time_a: str = Field(..., description="ISO 8601 end timestamp for encounter A.")
    start_time_b: str = Field(..., description="ISO 8601 start timestamp for encounter B.")
    end_time_b: str = Field(..., description="ISO 8601 end timestamp for encounter B.")
    nominal_gap_seconds: float = Field(..., description="Nominal temporal gap in seconds between encounter intervals: max(0, start_B - end_A, start_A - end_B).")
    min_possible_gap_seconds: float = Field(..., description="Exact attainable lower bound on temporal separation in seconds accounting for combined pairwise clock uncertainty: max(0, nominal_gap - uncertainty).")
    max_possible_gap_seconds: float = Field(..., description="Exact attainable upper bound on temporal separation in seconds accounting for combined pairwise clock uncertainty: max(0, (start_B - end_A) + U, (start_A - end_B) + U). Note: for overlapping intervals, G + U is an enclosure, while this field calculates the exact attainable supremum.")
    effective_gap_seconds: float = Field(..., description="Backward-compatible alias for min_possible_gap_seconds. Lower bound of possible gap range, NOT a definitive corrected gap.")
    temporal_eligibility: str = Field(..., description="Eligibility classification: 'definitely_within_threshold' if max_possible_gap <= threshold else 'possibly_within_threshold'.")
    clock_offset_seconds_a: float | None = Field(default=None, description="Applied clock offset in seconds for camera A (t_corrected = t_raw + offset).")
    clock_offset_seconds_b: float | None = Field(default=None, description="Applied clock offset in seconds for camera B (t_corrected = t_raw + offset).")
    temporal_relation: str = Field(..., description="'overlapping' or 'disjoint'.")
    observed_interval_order: str = Field(..., description="'overlapping', 'A_before_B', or 'B_before_A'.")
    spatial_check_status: str = Field(
        ...,
        description="'not_evaluated', 'unavailable', 'passed', 'failed', or 'measured'."
    )
    camera_distance_meters: float | None = Field(
        default=None,
        description="Approximate spherical great-circle camera separation in meters if coordinates exist and are evaluated. Camera separation is not animal travel distance."
    )
    spatial_units: str | None = Field(
        default=None,
        description="'meters' if camera distance was calculated, otherwise None."
    )
    rule_outcomes: dict[str, bool] = Field(
        ...,
        description="Evaluated boolean outcomes for individual association rules."
    )
    disclaimer: str = Field(
        default="Possible association only; individual animal identity and movement are not established.",
        description="Mandatory scientific disclaimer."
    )
    spatial_note: str = Field(
        ...,
        description="Explicit note detailing spatial evaluation status and limitations."
    )
    explanation: str = Field(
        ...,
        description="Deterministic plain-language explanation of the association."
    )


class CrossCameraAssociationsResult(BaseContractModel):
    """Complete typed payload for cross-camera observation correlation (Feature F06)."""
    data_source_mode: str = Field(..., description="Snapshot data source mode.")
    rule_version: str = Field(default="cross_camera_association_v1", description="Association rule engine version.")
    clock_comparability_policy: str = Field(..., description="Policy used for inter-camera clock comparisons.")
    clock_uncertainty_seconds: float = Field(default=0.0, description="Clock uncertainty propagated in seconds.")
    clock_offsets_applied: dict[str, float] | None = Field(default=None, description="Per-camera clock offsets applied in seconds (t_corrected = t_raw + offset).")
    timestamps_pre_corrected: bool = Field(default=False, description="Whether timestamps were pre-corrected prior to analysis.")
    correction_provenance: str | None = Field(default=None, description="Documented provenance for pre-corrected timestamps or offset source.")
    spatial_mode: str = Field(..., description="Spatial mode used during evaluation.")
    temporal_threshold_seconds: float = Field(..., description="Maximum allowable temporal gap in seconds.")
    spatial_threshold_meters: float | None = Field(default=None, description="Maximum allowable camera distance in meters if set.")
    total_eligible_encounters: int = Field(..., description="Total encounters meeting scope and species criteria.")
    total_candidate_pairs_evaluated: int = Field(..., description="Total candidate pairs evaluated.")
    total_matching_pairs_found: int = Field(..., description="Total matching pairs satisfying all rules.")
    returned_pairs_count: int = Field(..., description="Count of association pairs returned.")
    is_coverage_complete: bool = Field(default=True, description="Whether pair evaluation was exhaustive or bounded.")
    evaluation_policy: str = Field(default="all_eligible", description="Candidate pair evaluation policy.")
    associations: list[CrossCameraAssociationPair] = Field(default_factory=list, description="Correlated encounter pairs.")
    disclaimer: str = Field(
        default=(
            "Possible association only; individual animal identity and movement are not established. "
            "Same-species sightings close in time can be coincidental."
        ),
        description="Mandatory scientific limitation."
    )
    spatial_disclaimer: str = Field(
        default="Camera separation is not animal travel distance; biological movement feasibility is not validated.",
        description="Spatial measurement limitation."
    )


class BaselineDailyBin(BaseContractModel):
    """Daily effort and encounter bin for historical baseline calculations (Feature F12)."""
    date: str = Field(..., description="Calendar date in ISO format YYYY-MM-DD under analysis timezone.")
    active_seconds: float = Field(..., ge=0.0, description="Total active monitoring effort in seconds during this day.")
    active_camera_days: float = Field(..., ge=0.0, description="Active effort in camera-days (active_seconds / 86400.0).")
    coverage_ratio: float = Field(..., ge=0.0, le=1.0, description="Fraction of day covered by active monitoring effort.")
    is_valid_baseline_day: bool = Field(..., description="True if coverage_ratio meets min_day_coverage_ratio.")
    encounter_count: int = Field(..., ge=0, description="Encounter count of focal species during active intervals of this day.")
    daily_encounter_rate: float | None = Field(
        default=None,
        ge=0.0,
        description="Encounters per active camera-day (encounter_count / active_camera_days). None if day is excluded."
    )


class ActivityAnomalySeriesResult(BaseContractModel):
    """Statistical anomaly indicator evaluation for an independent camera/species series (Feature F12)."""
    camera_id: str = Field(..., description="Camera trap evaluated.")
    species_id: str = Field(..., description="Focal species evaluated.")
    site_id: str | None = Field(default=None, description="Site identifier if known.")
    outcome: AnomalyOutcome = Field(..., description="Anomaly classification outcome.")
    baseline_start_time: datetime = Field(..., description="Start of baseline window.")
    baseline_end_time: datetime = Field(..., description="End of baseline window.")
    baseline_calendar_days_total: int = Field(..., ge=0, description="Total calendar days spanned by baseline window.")
    baseline_valid_active_days: int = Field(..., ge=0, description="Number of baseline days meeting minimum active coverage.")
    baseline_total_active_effort_days: float = Field(..., ge=0.0, description="Sum of active camera-days across valid baseline days.")
    baseline_median_daily_rate: float | None = Field(
        default=None,
        ge=0.0,
        description="Robust baseline centre: median daily encounter rate across valid days."
    )
    baseline_mad_daily_rate: float | None = Field(
        default=None,
        ge=0.0,
        description="Robust baseline dispersion: median absolute deviation (MAD) of daily rates."
    )
    baseline_dispersion_sigma: float | None = Field(
        default=None,
        ge=0.0,
        description="Normal-consistent scale estimate: 1.4826 * MAD."
    )
    evaluation_start_time: datetime = Field(..., description="Start of evaluation window.")
    evaluation_end_time: datetime = Field(..., description="End of evaluation window.")
    evaluation_active_effort_days: float = Field(..., ge=0.0, description="Active camera-days in evaluation window.")
    evaluation_encounter_count: int = Field(..., ge=0, description="Focal species encounters in evaluation active intervals.")
    evaluation_encounter_rate: float | None = Field(
        default=None,
        ge=0.0,
        description="Encounters per active camera-day in evaluation window."
    )
    absolute_rate_change: float | None = Field(
        default=None,
        description="Evaluation rate minus baseline median rate (R_eval - R_tilde)."
    )
    relative_rate_change: float | None = Field(
        default=None,
        description="Relative rate change ((R_eval - R_tilde) / R_tilde). None if R_tilde == 0."
    )
    anomaly_score_sigmas: float | None = Field(
        default=None,
        description="Number of robust dispersion sigmas from baseline median ((R_eval - R_tilde) / sigma). None if sigma == 0."
    )
    comparability_assessment: ComparabilityAssessment = Field(
        default=ComparabilityAssessment.UNASSESSED,
        description="Operational stationarity assessment across baseline and evaluation."
    )
    comparability_notes: list[str] = Field(
        default_factory=list,
        description="Explicit observations regarding deployment, hardware, or model stability."
    )
    evaluation_notes: list[str] = Field(
        default_factory=list,
        description="Detailed contextual evaluation notes and qualification warnings."
    )
    out_of_effort_encounters_count: int = Field(
        default=0,
        ge=0,
        description="Encounters recorded outside active effort intervals (flagged and excluded from rate calculations)."
    )
    baseline_daily_bins: list[BaselineDailyBin] = Field(
        default_factory=list,
        description="Full daily breakdown for auditing and transparent visualization."
    )
    disclaimer: str = Field(
        default=(
            "Reviewable statistical indicator only. Comparing an aggregate evaluation rate with daily baseline MAD "
            "is a standardized descriptive deviation ratio (an exploratory heuristic), not a calibrated significance level, "
            "hypothesis test p-value, or probability of true biological change. Does not prove population change, "
            "migration, poaching, camera malfunction, or ecological causation."
        ),
        description="Mandatory scientific disclaimer."
    )


class ActivityAnomaliesResult(BaseContractModel):
    """Complete typed payload for activity anomaly indicators (Feature F12)."""
    data_source_mode: str = Field(..., description="Snapshot data source mode.")
    metric: str = Field(default="activity_anomaly", description="Operational metric identifier.")
    analysis_timezone: str = Field(..., description="Timezone used for calendar day binning.")
    baseline_start_time: datetime = Field(..., description="Baseline start time.")
    baseline_end_time: datetime = Field(..., description="Baseline end time.")
    evaluation_start_time: datetime = Field(..., description="Evaluation start time.")
    evaluation_end_time: datetime = Field(..., description="Evaluation end time.")
    total_series_evaluated: int = Field(..., ge=0, description="Total independent camera/species series evaluated.")
    increased_count: int = Field(0, ge=0, description="Count of series with INCREASED activity indicator.")
    decreased_count: int = Field(0, ge=0, description="Count of series with DECREASED activity indicator.")
    no_indicator_count: int = Field(0, ge=0, description="Count of series with NO_INDICATOR.")
    not_evaluable_count: int = Field(0, ge=0, description="Count of series that were NOT_EVALUABLE.")
    series: list[ActivityAnomalySeriesResult] = Field(
        default_factory=list,
        description="Independent results for each camera/species series."
    )
    disclaimer: str = Field(
        default=(
            "Statistical anomaly indicators are reviewable operational signals. Comparing aggregate evaluation rates "
            "with daily baseline MAD is an exploratory heuristic, not a calibrated significance level or p-value. "
            "They do not constitute proof of biological or ecological change, nor camera failure. Unmonitored intervals, "
            "seasonality, and detection probability variation must be evaluated before drawing conclusions."
        ),
        description="Mandatory global scientific disclaimer."
    )


class BlindSpotResult(BaseContractModel):
    """Complete typed payload for monitoring blind spot analysis (Feature F08)."""
    data_source_mode: str = Field(..., description="Snapshot data source mode.")
    metric: str = Field(default="monitoring_blind_spots", description="Operational metric identifier.")
    projection_method: str = Field(..., description="Geodesic or projection method used for planar area.")
    study_area_sq_meters: float = Field(..., ge=0.0, description="Total study area in square meters.")
    study_area_sq_km: float = Field(..., ge=0.0, description="Total study area in square kilometers.")
    covered_area_sq_meters: float = Field(..., ge=0.0, description="Total covered area in square meters.")
    covered_area_sq_km: float = Field(..., ge=0.0, description="Total covered area in square kilometers.")
    uncovered_area_sq_meters: float = Field(..., ge=0.0, description="Total uncovered (gap) area in square meters.")
    uncovered_area_sq_km: float = Field(..., ge=0.0, description="Total uncovered (gap) area in square kilometers.")
    coverage_fraction: float = Field(..., ge=0.0, le=1.0, description="Fraction of study area covered [0.0, 1.0].")
    gap_polygons_count: int = Field(..., ge=0, description="Number of disjoint gap polygons.")
    gap_polygons: list[dict[str, Any]] = Field(
        default_factory=list,
        description="GeoJSON Polygon geometries for uncovered gap areas in [lon, lat] coordinates."
    )
    active_cameras_evaluated_count: int = Field(..., ge=0, description="Number of cameras contributing coverage.")
    is_coverage_complete: bool = Field(default=True, description="Whether coverage inventory was complete.")
    coverage_inventory_status: str = Field(
        default="complete_active",
        description="Inventory status: 'complete_active', 'complete_zero', 'partial', or 'unassessed'."
    )
    source_classification: SpatialSourceType = Field(
        default=SpatialSourceType.ASSUMED,
        description="Source classification of coverage (measured, assumed, synthetic)."
    )
    disclaimer: str = Field(
        default=(
            "Calculated from declared/assumed camera coverage geometry. Represents area outside declared coverage, "
            "NOT field-validated wildlife absence or proven lack of animal occurrence."
        ),
        description="Mandatory scientific disclaimer."
    )


class CandidatePlacementItem(BaseContractModel):
    """Single ranked candidate placement site evaluation (Feature F09)."""
    candidate_id: str = Field(..., description="Unique candidate site ID.")
    rank: int | None = Field(default=None, ge=1, description="Priority rank (1 = highest marginal benefit), None if excluded.")
    status: CandidatePlacementStatus = Field(..., description="Feasibility status (feasible, excluded, redundant).")
    marginal_coverage_gain_sq_meters: float = Field(..., ge=0.0, description="Marginal unmonitored area gained in m^2.")
    marginal_coverage_gain_sq_km: float = Field(..., ge=0.0, description="Marginal unmonitored area gained in km^2.")
    score: float = Field(..., ge=0.0, description="Efficiency score (marginal gain / cost).")
    cost: float = Field(..., gt=0.0, description="Deployment cost weight.")
    overlap_with_baseline_sq_meters: float = Field(..., ge=0.0, description="Overlap area with existing baseline coverage in m^2.")
    is_in_exclusion_zone: bool = Field(default=False, description="Whether candidate site falls in an exclusion zone.")
    exclusion_reasons: list[str] = Field(default_factory=list, description="Reasons for exclusion if applicable.")
    notes: str | None = Field(default=None, description="Contextual evaluation notes.")


class CandidatePlacementResult(BaseContractModel):
    """Complete typed payload for candidate camera placement ranking (Feature F09)."""
    data_source_mode: str = Field(..., description="Snapshot data source mode.")
    metric: str = Field(default="candidate_placement", description="Operational metric identifier.")
    projection_method: str = Field(..., description="Geodesic or projection method used for planar area.")
    study_area_sq_meters: float = Field(..., ge=0.0, description="Total study area in square meters.")
    baseline_covered_area_sq_meters: float = Field(..., ge=0.0, description="Existing baseline coverage in m^2.")
    baseline_coverage_fraction: float = Field(..., ge=0.0, le=1.0, description="Baseline coverage fraction [0.0, 1.0].")
    ranked_candidates: list[CandidatePlacementItem] = Field(
        default_factory=list,
        description="Ranked eligible candidate camera placement sites."
    )
    excluded_candidates: list[CandidatePlacementItem] = Field(
        default_factory=list,
        description="Excluded candidate camera placement sites (e.g. falling inside exclusion zones)."
    )
    total_candidates: int = Field(..., ge=0, description="Total candidate sites evaluated.")
    feasible_candidates_count: int = Field(..., ge=0, description="Count of feasible candidates.")
    excluded_candidates_count: int = Field(..., ge=0, description="Count of excluded candidates.")
    marginal_analysis_disclaimer: str = Field(
        default=(
            "Candidate ranks reflect single-site marginal coverage gain over the baseline. Marginal gains are NOT "
            "additive; placing multiple candidates simultaneously requires joint combinatorial evaluation as candidate "
            "viewsheds may overlap."
        ),
        description="Mandatory non-additivity disclaimer."
    )
    disclaimer: str = Field(
        default=(
            "Candidate camera placement ranking is a decision-support tool based on declared spatial assumptions. "
            "It does not guarantee optimal field detection probability, animal visibility, terrain accessibility, or equipment security."
        ),
        description="Mandatory scientific disclaimer."
    )


class TargetProximityItem(BaseContractModel):
    """Proximity evaluation between a target location and a spatial zone/infrastructure (Feature F14)."""
    target_id: str = Field(..., description="Target point identifier.")
    position_type: PositionType = Field(..., description="Nature of location (camera_site, estimated_animal_position, etc.).")
    zone_id: str = Field(..., description="Spatial zone or infrastructure identifier.")
    zone_name: str = Field(..., description="Human-readable zone label.")
    zone_type: str = Field(..., description="Zone category (e.g. core_reserve, road_corridor).")
    relation: ProximityRelation = Field(..., description="Topological relationship (inside, outside, boundary, indeterminate).")
    region_distance_meters: float = Field(..., ge=0.0, description="Shortest distance to zone interior (0.0 if inside).")
    boundary_distance_meters: float = Field(..., ge=0.0, description="Shortest distance to zone boundary in meters.")
    within_threshold: bool = Field(..., description="Whether location is nominally within declared proximity threshold.")
    threshold_status: str = Field(
        default="definitely_outside",
        description="'definitely_within', 'definitely_outside', or 'uncertain' due to positional uncertainty."
    )
    proximity_threshold_meters: float = Field(..., ge=0.0, description="Evaluation threshold in meters.")
    uncertainty_radius_meters: float = Field(0.0, ge=0.0, description="Positional uncertainty radius in meters.")
    uncertainty_status: str = Field(default="unassessed", description="'assessed' or 'unassessed'.")
    position_description: str = Field(..., description="Clear contextual description distinguishing camera site from animal position.")
    warning: str | None = Field(default=None, description="Caveats or notes on boundary uncertainty.")


class ProximityResult(BaseContractModel):
    """Complete typed payload for geofencing and proximity indicators (Feature F14)."""
    data_source_mode: str = Field(..., description="Snapshot data source mode.")
    metric: str = Field(default="proximity_indicators", description="Operational metric identifier.")
    projection_method: str = Field(..., description="Projection or distance measurement method.")
    targets_evaluated_count: int = Field(..., ge=0, description="Total targets evaluated.")
    zones_evaluated_count: int = Field(..., ge=0, description="Total zones/infrastructure features evaluated.")
    evaluations: list[TargetProximityItem] = Field(
        default_factory=list,
        description="Pairwise target-zone proximity evaluations."
    )
    disclaimer: str = Field(
        default=(
            "Proximity indicators reflect geometric distance between supplied coordinates and zone boundaries under "
            "the declared projection. For camera sites, this indicates physical device placement proximity, NOT animal "
            "geofence crossing. Positional uncertainty can cause indeterminate boundary relations. Descriptive indicator "
            "only; no threat or danger score is assigned."
        ),
        description="Mandatory scientific disclaimer."
    )


class InfrastructureScenarioResult(BaseContractModel):
    """Complete typed payload for wildlife-infrastructure scenario analysis (Feature F16)."""
    scenario_id: str = Field(..., description="Unique scenario identifier.")
    scenario_name: str = Field(..., description="Descriptive scenario name.")
    projection_method: str = Field(..., description="Projection or distance measurement method.")
    source_classification: SpatialSourceType = Field(
        default=SpatialSourceType.HYPOTHETICAL,
        description="Classification of scenario features."
    )
    study_area_sq_meters: float = Field(..., ge=0.0, description="Study area in square meters.")
    baseline_covered_sq_meters: float = Field(..., ge=0.0, description="Baseline covered area in square meters.")
    baseline_coverage_fraction: float = Field(..., ge=0.0, le=1.0, description="Baseline coverage fraction [0.0, 1.0].")
    scenario_covered_sq_meters: float = Field(..., ge=0.0, description="Scenario covered area in square meters.")
    scenario_coverage_fraction: float = Field(..., ge=0.0, le=1.0, description="Scenario coverage fraction [0.0, 1.0].")
    absolute_change_sq_meters: float = Field(..., description="Absolute change in covered area (scenario - baseline) in m^2.")
    relative_change_fraction: float | None = Field(default=None, description="Relative change in coverage fraction ((scen - base) / base).")
    hypothetical_features_applied: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Summary of hypothetical features applied in scenario."
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Explicit scenario assumptions."
    )
    disclaimer: str = Field(
        default=(
            "Hypothetical scenario analysis only. Evaluates geometric coverage and proximity changes under explicit "
            "assumptions. Does not predict ecological impacts, animal movement route displacement, or population viability changes."
        ),
        description="Mandatory scientific disclaimer."
    )

