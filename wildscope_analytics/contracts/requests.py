"""
WILDSCOPE Decision Intelligence & Analytics Module
Request Contracts - Phase 1

Defines typed request contracts for analyze() and rank_review() entry points.
Enforces explicit supported values and validates temporal filters and revisions.
"""

from __future__ import annotations
from datetime import datetime
import math
from typing import Any

from pydantic import Field, field_validator, model_validator

from wildscope_analytics.contracts.entities import (
    BaseContractModel,
    CameraCoverage,
    CandidateSite,
    SpatialZone,
    TargetLocation,
)
from wildscope_analytics.contracts.enums import (
    AnalysisMetric,
    ClockComparabilityPolicy,
    InclusionPolicy,
    PositionType,
    SpatialMode,
    SpatialSourceType,
)


class AnalysisRequest(BaseContractModel):
    """
    Request payload for analytical computation entry points.
    Encapsulates metric selection, filtering parameters, timezone,
    and optimistic concurrency revision checks.
    """
    metric: AnalysisMetric = Field(
        ...,
        description="Selected operational metric to compute."
    )
    species_ids: list[str] | None = Field(
        default=None,
        description="Filter for specific taxon identifiers. None means all species."
    )
    camera_ids: list[str] | None = Field(
        default=None,
        description="Filter for specific camera traps. None means all cameras."
    )
    site_ids: list[str] | None = Field(
        default=None,
        description="Filter for specific sites or clusters. None means all sites."
    )
    start_time: datetime | None = Field(
        default=None,
        description="Start of analysis time window (must be timezone-aware if given)."
    )
    end_time: datetime | None = Field(
        default=None,
        description="End of analysis time window (must be timezone-aware if given)."
    )
    analysis_timezone: str | None = Field(
        default=None,
        description="IANA timezone identifier for diurnal/time-of-day bucketing."
    )
    inclusion_policy: InclusionPolicy = Field(
        default=InclusionPolicy.PROVISIONAL_AND_REVIEWED,
        description="Whether to include unreviewed model predictions or only reviewed records."
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum detection/classification confidence cutoff."
    )
    expected_revision: int | None = Field(
        default=None,
        ge=0,
        description="Expected dataset revision to prevent calculating against stale data."
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Metric-specific documented configuration parameters."
    )

    @field_validator("start_time")
    @classmethod
    def validate_start_tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("start_time must be timezone-aware if provided.")
        return v

    @field_validator("end_time")
    @classmethod
    def validate_end_tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("end_time must be timezone-aware if provided.")
        return v

    @model_validator(mode="after")
    def validate_window(self) -> AnalysisRequest:
        if self.start_time is not None and self.end_time is not None:
            if self.start_time > self.end_time:
                raise ValueError(
                    f"start_time ({self.start_time}) cannot be later than end_time ({self.end_time})."
                )
        return self


class ReviewRankingRequest(BaseContractModel):
    """
    Request payload for conclusion-sensitive review prioritization.
    Ranks unreviewed detections by their potential marginal impact on a selected metric.
    """
    target_metric: AnalysisMetric = Field(
        ...,
        description="Operational metric whose sensitivity guides review priority."
    )
    species_ids: list[str] | None = Field(
        default=None,
        description="Scope review ranking to particular species hypotheses."
    )
    camera_ids: list[str] | None = Field(
        default=None,
        description="Scope review ranking to particular camera traps."
    )
    inclusion_policy: InclusionPolicy = Field(
        default=InclusionPolicy.PROVISIONAL_AND_REVIEWED,
        description="Inclusion baseline for computing marginal delta."
    )
    top_k_candidates: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of alternative label candidates evaluated per detection."
    )
    score_margin_threshold: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description=(
            "Ambiguity margin threshold between top species prediction and highest alternative species score "
            "(default: 0.25). Detections with margin > threshold in probability score space are considered unambiguous "
            "and excluded from the candidate queue unless explicitly flagged for expert review."
        )
    )
    result_limit: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description=(
            "Maximum number of top-ranked results to return after evaluating all eligible candidates (default: 50). "
            "Fewer requested results does NOT mark an otherwise complete response as partial."
        )
    )
    max_records_to_rank: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Backward-compatible alias for result_limit."
    )
    evaluation_limit: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Evaluate only a bounded subset of candidate detections during simulation. "
            "Applying this limit produces incomplete ranking coverage and sets status to PARTIAL."
        )
    )
    evaluation_policy: str = Field(
        default="all_eligible",
        description="Selection policy when evaluation_limit is set (e.g. 'all_eligible', 'time_order')."
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum detection/classification confidence cutoff for baseline metric parity."
    )
    expected_revision: int | None = Field(
        default=None,
        ge=0,
        description="Expected dataset revision for consistency."
    )
    target_species_id: str | None = Field(
        default=None,
        description="Focal species for sensitivity ranking (e.g. for SPECIES_ENCOUNTER_COUNTS or CAMERA_COMPARISON)."
    )
    camera_id_a: str | None = Field(
        default=None,
        description="First camera identifier for CAMERA_COMPARISON difference metric (camera_a - camera_b)."
    )
    camera_id_b: str | None = Field(
        default=None,
        description="Second camera identifier for CAMERA_COMPARISON difference metric (camera_a - camera_b)."
    )
    start_time: datetime | None = Field(
        default=None,
        description="Start of analysis time window (must be timezone-aware if given)."
    )
    end_time: datetime | None = Field(
        default=None,
        description="End of analysis time window (must be timezone-aware if given)."
    )
    analysis_timezone: str | None = Field(
        default=None,
        description="IANA timezone identifier."
    )
    include_zero_impact: bool = Field(
        default=False,
        description="Whether to include candidates whose maximum absolute marginal impact is 0."
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Metric-specific documented configuration parameters."
    )

    @field_validator("start_time")
    @classmethod
    def validate_ranking_start_tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("start_time must be timezone-aware if provided.")
        return v

    @field_validator("end_time")
    @classmethod
    def validate_ranking_end_tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("end_time must be timezone-aware if provided.")
        return v

    @model_validator(mode="after")
    def validate_ranking_window(self) -> ReviewRankingRequest:
        if self.start_time is not None and self.end_time is not None:
            if self.start_time > self.end_time:
                raise ValueError(
                    f"start_time ({self.start_time}) cannot be later than end_time ({self.end_time})."
                )
        if self.result_limit is None and self.max_records_to_rank is None:
            self.result_limit = 50
            self.max_records_to_rank = 50
        elif self.result_limit is None and self.max_records_to_rank is not None:
            self.result_limit = self.max_records_to_rank
        elif self.result_limit is not None and self.max_records_to_rank is None:
            self.max_records_to_rank = self.result_limit
        return self


class CrossCameraAssociationRequest(BaseContractModel):
    """
    Phase 4 Request payload for cross-camera observation correlation (Feature F06).
    Finds pairs of encounters from different cameras that satisfy explicit species,
    temporal, and optional spatial rules.

    CRITICAL INTERPRETATION:
    A match means: 'Possible association between recorded sightings under the configured rules.'
    It does NOT establish the same individual animal, confirmed movement, migration corridor,
    travel speed, or probability of identity.
    """
    metric: AnalysisMetric = Field(
        default=AnalysisMetric.CROSS_CAMERA_ASSOCIATIONS,
        description="Selected operational metric: CROSS_CAMERA_ASSOCIATIONS."
    )
    species_ids: list[str] | None = Field(
        default=None,
        description="Optional focal species/taxa IDs to match. None evaluates all eligible species."
    )
    camera_ids: list[str] | None = Field(
        default=None,
        description="Optional set of camera IDs to include in the evaluation."
    )
    site_ids: list[str] | None = Field(
        default=None,
        description="Optional set of site IDs to include."
    )
    start_time: datetime | None = Field(
        default=None,
        description="Start of analysis time window (must be timezone-aware)."
    )
    end_time: datetime | None = Field(
        default=None,
        description="End of analysis time window (must be timezone-aware)."
    )
    analysis_timezone: str | None = Field(
        default=None,
        description="IANA timezone identifier for reporting and interval localization."
    )
    max_temporal_separation_seconds: float = Field(
        default=3600.0,
        ge=0.0,
        description=(
            "Maximum allowable temporal separation in seconds between encounter intervals (default: 3600.0s = 1.0h). "
            "Encounters with gap <= max_temporal_separation_seconds satisfy the temporal rule. "
            "Notice: this is an unvalidated configurable heuristic, not a proven biological or travel threshold."
        )
    )
    clock_comparability_policy: ClockComparabilityPolicy = Field(
        default=ClockComparabilityPolicy.ANALYST_ASSUMPTION,
        description=(
            "Policy declaring the basis for comparing timestamps across different physical cameras. "
            "Options: documented_sync, analyst_assumption, offsets_known, unknown. "
            "When 'unknown', time-based association returns INSUFFICIENT_DATA because inter-camera clock alignment is unverified. "
            "When 'offsets_known', requires either valid per-camera clock_offsets dict (seconds, t_corrected = t_raw + offset) "
            "or timestamps_pre_corrected=True with correction_provenance. Uncertainty bounds alone do not satisfy offsets_known."
        )
    )
    clock_uncertainty_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Combined pairwise clock-offset uncertainty bound U_pair >= 0 in seconds between cameras (default: 0.0s). "
            "If individual cameras have per-camera clock uncertainties u_A and u_B, then U_pair = u_A + u_B. "
            "For nominal gap G, true separation lies within the possible gap range [max(0, G - U_pair), G + U_pair]. "
            "Threshold eligibility means 'possibly within window' (min_possible_gap <= max_temporal_separation_seconds)."
        )
    )
    spatial_mode: SpatialMode = Field(
        default=SpatialMode.TIME_SPECIES_ONLY,
        description=(
            "Spatial rule evaluation mode: "
            "1) time_species_only: do not require coordinates, spatial_check_status='not_evaluated'. "
            "2) spatial_when_available: apply distance checks when coordinates exist; mark others 'unavailable'. "
            "3) spatial_required: evaluate only pairs with valid coordinates; if none exist, returns UNAVAILABLE."
        )
    )
    max_spatial_distance_meters: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional maximum distance threshold in meters between camera traps. "
            "When configured, pairs with geodesic distance > threshold are excluded."
        )
    )
    inclusion_policy: InclusionPolicy = Field(
        default=InclusionPolicy.PROVISIONAL_AND_REVIEWED,
        description="Policy governing which detections within encounters are admitted."
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum detection/classification confidence cutoff."
    )
    result_limit: int | None = Field(
        default=50,
        ge=1,
        le=1000,
        description="Maximum number of top-ranked associations to return (default: 50). Does NOT mark response partial."
    )
    evaluation_limit: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Optional upper bound on candidate pairs evaluated during simulation. "
            "When applied, bounds evaluation work, marks coverage incomplete, and sets status to PARTIAL."
        )
    )
    evaluation_policy: str = Field(
        default="all_eligible",
        description="Policy governing pair candidate selection when evaluation_limit is set."
    )
    expected_revision: int | None = Field(
        default=None,
        ge=0,
        description="Expected dataset revision for optimistic concurrency."
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional additional parameters."
    )

    @field_validator("start_time")
    @classmethod
    def validate_assoc_start_tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("start_time must be timezone-aware if provided.")
        return v

    @field_validator("end_time")
    @classmethod
    def validate_assoc_end_tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("end_time must be timezone-aware if provided.")
        return v

    @model_validator(mode="after")
    def validate_assoc_parameters(self) -> CrossCameraAssociationRequest:
        if self.start_time is not None and self.end_time is not None:
            if self.start_time > self.end_time:
                raise ValueError(
                    f"start_time ({self.start_time}) cannot be later than end_time ({self.end_time})."
                )
        if not math.isfinite(self.max_temporal_separation_seconds):
            raise ValueError("max_temporal_separation_seconds must be a finite non-negative number.")
        if not math.isfinite(self.clock_uncertainty_seconds):
            raise ValueError("clock_uncertainty_seconds must be a finite non-negative number.")
        if self.max_spatial_distance_meters is not None:
            if not math.isfinite(self.max_spatial_distance_meters):
                raise ValueError("max_spatial_distance_meters must be a finite non-negative number.")
        return self


class ActivityAnomalyRequest(BaseContractModel):
    """
    Phase 5 Request payload for activity anomaly indicators (Feature F12).
    Compares recorded encounter activity for a focal species at a camera trap
    against that camera's historical baseline.

    CRITICAL INTERPRETATION:
    Outputs are reviewable statistical indicators—not proof of population change,
    migration, poaching, camera failure, or ecological causes.
    """
    metric: AnalysisMetric = Field(
        default=AnalysisMetric.ACTIVITY_ANOMALY,
        description="Selected operational metric: ACTIVITY_ANOMALY."
    )
    baseline_start_time: datetime = Field(
        ...,
        description="Start of baseline historical time window (start-inclusive, timezone-aware)."
    )
    baseline_end_time: datetime = Field(
        ...,
        description="End of baseline historical time window (end-exclusive, timezone-aware)."
    )
    evaluation_start_time: datetime = Field(
        ...,
        description="Start of evaluation time window (start-inclusive, timezone-aware)."
    )
    evaluation_end_time: datetime = Field(
        ...,
        description="End of evaluation time window (end-exclusive, timezone-aware)."
    )
    analysis_timezone: str = Field(
        default="UTC",
        description="IANA timezone identifier for day-bin boundaries and interval localization."
    )
    species_ids: list[str] | None = Field(
        default=None,
        description="Optional list of focal species to evaluate. None evaluates all eligible species in scope."
    )
    camera_ids: list[str] | None = Field(
        default=None,
        description="Optional list of camera IDs to evaluate. Each camera is evaluated as an independent series."
    )
    site_ids: list[str] | None = Field(
        default=None,
        description="Optional list of site IDs to scope cameras."
    )
    min_baseline_days: int = Field(
        default=7,
        ge=1,
        description="Minimum number of valid active baseline calendar days required for evaluation (default: 7)."
    )
    min_baseline_active_effort_days: float = Field(
        default=5.0,
        ge=0.0,
        description="Minimum total active baseline effort in camera-days required (default: 5.0)."
    )
    min_evaluation_active_effort_days: float = Field(
        default=1.0,
        ge=0.0,
        description="Minimum active evaluation effort in camera-days required (default: 1.0)."
    )
    min_day_coverage_ratio: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum fraction of the actual local calendar-day duration covered by active monitoring "
            "to qualify as a valid baseline day (default: 0.5 = 50% of local day, e.g. 12h on standard 24h days, "
            "11.5h on 23h DST spring-forward days, 12.5h on 25h DST fall-back days)."
        )
    )
    anomaly_threshold_sigmas: float = Field(
        default=3.0,
        ge=0.0,
        description="Number of normal-consistent MAD dispersions from baseline median required for anomaly alert (default: 3.0)."
    )
    min_absolute_rate_change: float = Field(
        default=0.2,
        ge=0.0,
        description="Minimum absolute rate change (encounters/active camera-day) required to prevent spurious micro-alerts (default: 0.2)."
    )
    allow_zero_dispersion_absolute_fallback: bool = Field(
        default=True,
        description="Whether to allow absolute threshold alerts when baseline dispersion MAD is zero."
    )
    allow_suspect_comparability: bool = Field(
        default=False,
        description=(
            "Whether to evaluate anomaly indicators when stationarity is SUSPECT_OR_CHANGED. "
            "When False (default policy), series with suspected camera repositioning, model version changes, "
            "or deployment shifts are classified as NOT_EVALUABLE. When True, indicators are computed "
            "with explicit qualification warnings."
        )
    )
    inclusion_policy: InclusionPolicy = Field(
        default=InclusionPolicy.PROVISIONAL_AND_REVIEWED,
        description="Policy governing which detections within encounters are admitted."
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum classification confidence cutoff."
    )
    expected_revision: int | None = Field(
        default=None,
        ge=0,
        description="Expected dataset revision for optimistic concurrency."
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional additional parameters."
    )

    @field_validator("baseline_start_time", "baseline_end_time", "evaluation_start_time", "evaluation_end_time")
    @classmethod
    def validate_anomaly_times_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("All window boundary timestamps must be timezone-aware.")
        return v

    @model_validator(mode="after")
    def validate_anomaly_windows(self) -> ActivityAnomalyRequest:
        if self.baseline_start_time >= self.baseline_end_time:
            raise ValueError(
                f"baseline_start_time ({self.baseline_start_time}) must precede baseline_end_time ({self.baseline_end_time})."
            )
        if self.baseline_end_time > self.evaluation_start_time:
            raise ValueError(
                f"Baseline window must precede and not overlap evaluation window: "
                f"baseline_end ({self.baseline_end_time}) > eval_start ({self.evaluation_start_time})."
            )
        if self.evaluation_start_time >= self.evaluation_end_time:
            raise ValueError(
                f"evaluation_start_time ({self.evaluation_start_time}) must precede evaluation_end_time ({self.evaluation_end_time})."
            )
        if not math.isfinite(self.min_baseline_active_effort_days):
            raise ValueError("min_baseline_active_effort_days must be finite.")
        if not math.isfinite(self.min_evaluation_active_effort_days):
            raise ValueError("min_evaluation_active_effort_days must be finite.")
        if not math.isfinite(self.anomaly_threshold_sigmas):
            raise ValueError("anomaly_threshold_sigmas must be finite.")
        if not math.isfinite(self.min_absolute_rate_change):
            raise ValueError("min_absolute_rate_change must be finite.")
        return self


class BlindSpotAnalysisRequest(BaseContractModel):
    """Request payload for monitoring blind spot analysis (Feature F08)."""
    study_area_polygon: dict[str, Any] | None = Field(
        default=None,
        description="GeoJSON Polygon/MultiPolygon defining study area boundary."
    )
    camera_coverages: list[CameraCoverage] = Field(
        default_factory=list,
        description="Explicit camera coverage polygons/assumptions. If omitted, uses cameras in snapshot."
    )
    coverage_inventory_complete: bool = Field(
        default=False,
        description="Whether coverage inventory is explicitly confirmed complete. When True and active cameras are 0, returns a valid complete-zero 100% gap."
    )
    crs: str | None = Field(default="EPSG:4326", description="Expected Coordinate Reference System.")
    default_coverage_radius_meters: float = Field(
        default=50.0,
        gt=0.0,
        description="Default circular coverage radius in meters for cameras without explicit polygon."
    )
    camera_ids: list[str] | None = Field(
        default=None,
        description="Optional subset of cameras to evaluate."
    )
    start_time: datetime | None = Field(
        default=None,
        description="Optional start of temporal evaluation window."
    )
    end_time: datetime | None = Field(
        default=None,
        description="Optional end of temporal evaluation window."
    )
    expected_revision: int | None = Field(
        default=None,
        ge=0,
        description="Expected snapshot dataset revision."
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional additional parameters."
    )

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("Timestamp must be timezone-aware if provided.")
        return v

    @field_validator("default_coverage_radius_meters")
    @classmethod
    def validate_radius_finite(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0.0:
            raise ValueError(f"default_coverage_radius_meters must be a finite positive number, got {v}")
        return v


class CandidatePlacementRequest(BaseContractModel):
    """Request payload for candidate camera placement ranking (Feature F09)."""
    study_area_polygon: dict[str, Any] | None = Field(
        default=None,
        description="GeoJSON Polygon/MultiPolygon defining study area boundary."
    )
    candidate_sites: list[CandidateSite] = Field(
        default_factory=list,
        description="Candidate placement sites to evaluate."
    )
    exclusion_zones: list[SpatialZone] = Field(
        default_factory=list,
        description="Exclusion zones where placement or coverage is forbidden."
    )
    existing_camera_coverages: list[CameraCoverage] = Field(
        default_factory=list,
        description="Baseline camera coverages already deployed. If empty, uses snapshot."
    )
    crs: str | None = Field(default="EPSG:4326", description="Expected Coordinate Reference System.")
    default_coverage_radius_meters: float = Field(
        default=50.0,
        gt=0.0,
        description="Default circular coverage radius in meters."
    )
    cost_weight: float = Field(
        default=1.0,
        ge=0.0,
        description="Weight of cost in score calculation (score = marginal_gain / (cost^cost_weight))."
    )
    expected_revision: int | None = Field(
        default=None,
        ge=0,
        description="Expected snapshot dataset revision."
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional additional parameters."
    )

    @field_validator("cost_weight")
    @classmethod
    def validate_cost_weight_finite(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0.0:
            raise ValueError(f"cost_weight must be a finite non-negative number, got {v}")
        return v


class ProximityAnalysisRequest(BaseContractModel):
    """Request payload for geofencing and proximity indicators (Feature F14)."""
    target_locations: list[TargetLocation] = Field(
        default_factory=list,
        description="Target locations to evaluate. If omitted, uses cameras with coordinates in snapshot."
    )
    zones: list[SpatialZone] = Field(
        default_factory=list,
        description="Spatial zones or infrastructure to test against. If omitted, uses snapshot.spatial_context.zones."
    )
    crs: str | None = Field(default="EPSG:4326", description="Expected Coordinate Reference System.")
    proximity_threshold_meters: float = Field(
        default=100.0,
        ge=0.0,
        description="Proximity distance threshold in meters for boundary proximity alerts."
    )
    expected_revision: int | None = Field(
        default=None,
        ge=0,
        description="Expected snapshot dataset revision."
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional additional parameters."
    )

    @field_validator("proximity_threshold_meters")
    @classmethod
    def validate_proximity_threshold_finite(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0.0:
            raise ValueError(f"proximity_threshold_meters must be a finite non-negative number, got {v}")
        return v


class InfrastructureScenarioRequest(BaseContractModel):
    """Request payload for wildlife-infrastructure scenario analysis (Feature F16)."""
    scenario_id: str = Field(..., description="Unique scenario identifier.")
    scenario_name: str = Field(..., description="Descriptive scenario name.")
    study_area_polygon: dict[str, Any] | None = Field(
        default=None,
        description="Baseline study area polygon."
    )
    baseline_camera_coverages: list[CameraCoverage] = Field(
        default_factory=list,
        description="Baseline camera coverages."
    )
    crs: str | None = Field(default="EPSG:4326", description="Expected Coordinate Reference System.")
    default_coverage_radius_meters: float = Field(
        default=50.0,
        gt=0.0,
        description="Default camera coverage radius in meters."
    )
    hypothetical_features: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Hypothetical features (roads with buffers, proposed cameras, exclusion zones)."
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Explicit documented scenario assumptions."
    )
    expected_revision: int | None = Field(
        default=None,
        ge=0,
        description="Expected snapshot dataset revision."
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional additional parameters."
    )
