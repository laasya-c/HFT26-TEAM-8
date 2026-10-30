"""
WILDSCOPE Decision Intelligence & Analytics Module
Request Contracts - Phase 1

Defines typed request contracts for analyze() and rank_review() entry points.
Enforces explicit supported values and validates temporal filters and revisions.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from wildscope_analytics.contracts.entities import BaseContractModel
from wildscope_analytics.contracts.enums import AnalysisMetric, InclusionPolicy


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
        description="Ambiguity margin threshold between top predictions triggering review."
    )
    max_records_to_rank: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum prioritized records returned in response."
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
        return self
