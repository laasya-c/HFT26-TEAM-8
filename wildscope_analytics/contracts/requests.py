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

from wildscope_analytics.contracts.entities import BaseContractModel
from wildscope_analytics.contracts.enums import (
    AnalysisMetric,
    ClockComparabilityPolicy,
    InclusionPolicy,
    SpatialMode,
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
