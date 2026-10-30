"""
WILDSCOPE Decision Intelligence & Analytics Module
Snapshot Contracts - Phase 1

Defines the complete snapshot model representing a point-in-time state
of cameras, media, observations, detections, encounters, reviews, effort,
and spatial context.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from wildscope_analytics.contracts.entities import (
    BaseContractModel,
    Camera,
    Detection,
    Encounter,
    MediaAsset,
    MonitoringEffort,
    Observation,
    PredictionRun,
    ReviewEvent,
    SpatialContext,
)

CURRENT_SCHEMA_VERSION = "1.0.0"
SUPPORTED_SCHEMA_VERSIONS = {"1.0.0"}


class SnapshotMetadata(BaseContractModel):
    """
    Metadata describing snapshot provenance, structural schema version,
    and underlying transactional data revision.
    """
    schema_version: str = Field(
        default=CURRENT_SCHEMA_VERSION,
        description="Semantic version of the data contract schema."
    )
    dataset_revision: int = Field(
        ...,
        ge=0,
        description="Transactional data revision counter identifying this data state."
    )
    created_at: datetime = Field(
        ...,
        description="Timezone-aware timestamp when snapshot was assembled."
    )
    source_system: str = Field(
        default="WILDSCOPE_BACKEND",
        description="System or worker generating this snapshot."
    )
    provenance: dict[str, Any] | str | None = Field(
        default=None,
        description="Traceability metadata for snapshot assembly."
    )
    has_spatial_context: bool = Field(
        default=False,
        description="Flag indicating whether spatial zones and layers are included."
    )
    has_monitoring_effort: bool = Field(
        default=False,
        description="Flag indicating whether verified camera active intervals are supplied."
    )

    @field_validator("created_at")
    @classmethod
    def validate_created_at_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("Snapshot created_at must be timezone-aware.")
        return v

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, v: str) -> str:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported schema version '{v}'. Supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        return v


class Snapshot(BaseContractModel):
    """
    Top-level snapshot envelope exchanged between backend persistence
    and analytical/decision intelligence modules.
    Entities are normalized and linked via stable references.
    """
    metadata: SnapshotMetadata = Field(..., description="Snapshot header and provenance.")
    cameras: list[Camera] = Field(
        default_factory=list,
        description="Camera traps present in snapshot."
    )
    media_assets: list[MediaAsset] = Field(
        default_factory=list,
        description="Original media records."
    )
    observations: list[Observation] = Field(
        default_factory=list,
        description="Observation records (individual images or sampled frames)."
    )
    prediction_runs: list[PredictionRun] = Field(
        default_factory=list,
        description="Audit records of vision model inference executions."
    )
    detections: list[Detection] = Field(
        default_factory=list,
        description="Object-level detections with scores and triage state."
    )
    encounters: list[Encounter] = Field(
        default_factory=list,
        description="Operational groupings of observations."
    )
    reviews: list[ReviewEvent] = Field(
        default_factory=list,
        description="Append-only human review audit history."
    )
    monitoring_efforts: list[MonitoringEffort] = Field(
        default_factory=list,
        description="Camera operational uptime intervals (optional)."
    )
    spatial_context: SpatialContext | None = Field(
        default=None,
        description="Reserve boundaries and spatial context (optional)."
    )
