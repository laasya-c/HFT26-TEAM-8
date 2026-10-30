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
