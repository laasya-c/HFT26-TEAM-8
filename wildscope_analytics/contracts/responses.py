"""
WILDSCOPE Decision Intelligence & Analytics Module
Response Envelope Contracts - Phase 1

Defines standard response envelopes and structured error models returned
by analysis and review-ranking pipelines to the frontend (Laasya) and API (Santosh).
"""

from __future__ import annotations
from typing import Any, Generic, TypeVar

from pydantic import Field

from wildscope_analytics.contracts.entities import BaseContractModel
from wildscope_analytics.contracts.enums import (
    AnalysisMetric,
    ResponseStatus,
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
