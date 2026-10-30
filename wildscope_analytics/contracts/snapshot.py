"""
WILDSCOPE Decision Intelligence & Analytics Module
Snapshot Contracts - Phase 1 / Phase 2

Defines the complete snapshot model representing a point-in-time state
of cameras, media, observations, detections, encounters, reviews, effort,
and spatial context.

Phase 2 additions:
- data_source_mode: discriminates operational_prediction from dataset_reference.
- review_ordering_mechanism: documents how multi-review ordering is resolved.
- Schema version bumped to 1.1.0 (backward-compatible additive change).
  Existing 1.0.0 snapshots remain accepted; 1.1.0 adds optional fields.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from wildscope_analytics.contracts.entities import (
    BaseContractModel,
    Camera,
    DatasetReferenceAnnotation,
    Detection,
    Encounter,
    MediaAsset,
    MonitoringEffort,
    Observation,
    PredictionRun,
    ReviewEvent,
    SpatialContext,
)
from wildscope_analytics.contracts.enums import (
    DataSourceMode,
    EncounterProcessingStatus,
    ReviewOrderingMechanism,
)

CURRENT_SCHEMA_VERSION = "1.3.0"
SUPPORTED_SCHEMA_VERSIONS = {"1.0.0", "1.1.0", "1.2.0", "1.3.0"}


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
    data_source_mode: DataSourceMode = Field(
        default=DataSourceMode.OPERATIONAL_PREDICTION,
        description=(
            "Phase 2: discriminates operational model inference data from official dataset "
            "reference annotations. Analytics outputs are labelled accordingly."
        ),
    )
    review_ordering_mechanism: ReviewOrderingMechanism = Field(
        default=ReviewOrderingMechanism.BACKEND_REVISION,
        description=(
            "Phase 2: documents how multiple ReviewEvents for the same detection target "
            "are ordered when resolving effective labels. "
            "backend_revision requires Santosh to supply a per-event sequence_number field."
        ),
    )
    encounter_processing_status: EncounterProcessingStatus | None = Field(
        default=None,
        description=(
            "Phase 3: status of encounter grouping processing (Harsh's group_encounters). "
            "When None (legacy 1.0.0/1.1.0 snapshot), conservative compatibility treats an empty "
            "encounters list as UNAVAILABLE."
        ),
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
    reference_annotations: list[DatasetReferenceAnnotation] = Field(
        default_factory=list,
        description=(
            "Phase 2: Official dataset reference annotations (e.g. Caltech Camera Traps). "
            "Populated only when data_source_mode == 'dataset_reference'. "
            "MUST NOT be mixed with operational_prediction Detection records in analytics."
        ),
    )
