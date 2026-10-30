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
