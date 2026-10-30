"""
WILDSCOPE Shared Data Contracts - Phase 1 / Phase 2

Exports enumerations, entity schemas, snapshot models, requests, and response envelopes.

Phase 2 additions:
- DataSourceMode: discriminates operational vs dataset_reference analytics.
- ReviewOrderingMechanism: documents how multi-review ordering is resolved.
- AnnotationSource: marks provenance of annotation entities.
- DatasetReferenceAnnotation: official dataset annotations (no invented confidence/runs).
- Snapshot.reference_annotations, SnapshotMetadata.data_source_mode.
- ReviewEvent.sequence_number: backend ordering field.
"""

from wildscope_analytics.contracts.entities import (
    BaseContractModel,
    Camera,
    DatasetReferenceAnnotation,
    Detection,
    Encounter,
    MediaAsset,
    MonitoringEffort,
    NormalizedBBox,
    Observation,
    PredictionRun,
    ReviewEvent,
    SpatialContext,
    SpatialZone,
    TaxonAlternative,
    TimeInterval,
)
from wildscope_analytics.contracts.enums import (
    AnalysisMetric,
    AnnotationSource,
    CalibrationStatus,
    ClockComparabilityPolicy,
    DataSourceMode,
    EncounterProcessingStatus,
    InclusionPolicy,
    MediaType,
    PredictionStatus,
    ResponseStatus,
    ReviewDecision,
    ReviewOrderingMechanism,
    ScoreType,
    SpatialCheckStatus,
    SpatialMode,
    TemporalRelation,
    TriageState,
    ValidationErrorCode,
)
from wildscope_analytics.contracts.requests import (
    AnalysisRequest,
    CrossCameraAssociationRequest,
    ReviewRankingRequest,
)
from wildscope_analytics.contracts.responses import (
    AnalysisResponseEnvelope,
    CrossCameraAssociationPair,
    CrossCameraAssociationsResult,
    EvaluatedAlternative,
    RankedCandidateResult,
    ReviewRankingResult,
    ValidationErrorDetail,
)
from wildscope_analytics.contracts.snapshot import (
    CURRENT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    Snapshot,
    SnapshotMetadata,
)

__all__ = [
    "AnalysisMetric",
    "AnalysisRequest",
    "AnalysisResponseEnvelope",
    "AnnotationSource",
    "BaseContractModel",
    "CalibrationStatus",
    "Camera",
    "ClockComparabilityPolicy",
    "CrossCameraAssociationPair",
    "CrossCameraAssociationRequest",
    "CrossCameraAssociationsResult",
    "CURRENT_SCHEMA_VERSION",
    "DatasetReferenceAnnotation",
    "DataSourceMode",
    "Detection",
    "Encounter",
    "EncounterProcessingStatus",
    "EvaluatedAlternative",
    "InclusionPolicy",
    "MediaAsset",
    "MediaType",
    "MonitoringEffort",
    "NormalizedBBox",
    "Observation",
    "PredictionRun",
    "PredictionStatus",
    "RankedCandidateResult",
    "ResponseStatus",
    "ReviewDecision",
    "ReviewEvent",
    "ReviewOrderingMechanism",
    "ReviewRankingRequest",
    "ReviewRankingResult",
    "ScoreType",
    "Snapshot",
    "SnapshotMetadata",
    "SpatialCheckStatus",
    "SpatialContext",
    "SpatialMode",
    "SpatialZone",
    "SUPPORTED_SCHEMA_VERSIONS",
    "TaxonAlternative",
    "TemporalRelation",
    "TimeInterval",
    "TriageState",
    "ValidationErrorDetail",
    "ValidationErrorCode",
]
