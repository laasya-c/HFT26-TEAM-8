"""
WILDSCOPE Shared Data Contracts - Phase 1

Exports enumerations, entity schemas, snapshot models, requests, and response envelopes.
"""

from wildscope_analytics.contracts.entities import (
    BaseContractModel,
    Camera,
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
    CalibrationStatus,
    InclusionPolicy,
    MediaType,
    PredictionStatus,
    ResponseStatus,
    ReviewDecision,
    ScoreType,
    TriageState,
    ValidationErrorCode,
)
from wildscope_analytics.contracts.requests import AnalysisRequest, ReviewRankingRequest
from wildscope_analytics.contracts.responses import (
    AnalysisResponseEnvelope,
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
    "BaseContractModel",
    "CalibrationStatus",
    "Camera",
    "CURRENT_SCHEMA_VERSION",
    "Detection",
    "Encounter",
    "InclusionPolicy",
    "MediaAsset",
    "MediaType",
    "MonitoringEffort",
    "NormalizedBBox",
    "Observation",
    "PredictionRun",
    "PredictionStatus",
    "ResponseStatus",
    "ReviewDecision",
    "ReviewEvent",
    "ReviewRankingRequest",
    "ScoreType",
    "Snapshot",
    "SnapshotMetadata",
    "SpatialContext",
    "SpatialZone",
    "SUPPORTED_SCHEMA_VERSIONS",
    "TaxonAlternative",
    "TimeInterval",
    "TriageState",
    "ValidationErrorDetail",
    "ValidationErrorCode",
]
