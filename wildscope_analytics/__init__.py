"""
WILDSCOPE Decision Intelligence & Analytics Module
Package Root - Phase 1 / Phase 2

Phase 1: Shared contracts, data validation, request/response models.
Phase 2: Effective-label resolver, cross-camera analytics, Caltech dataset adapter.

Public interface:
  analyze(snapshot, request)  → AnalysisResponseEnvelope  [Phase 2: implemented]
  rank_review(snapshot, request) → AnalysisResponseEnvelope [Phase 3: unavailable]
"""

from wildscope_analytics.contracts import (
    AnalysisMetric,
    AnalysisRequest,
    AnalysisResponseEnvelope,
    AnnotationSource,
    BaseContractModel,
    CalibrationStatus,
    Camera,
    CURRENT_SCHEMA_VERSION,
    DatasetReferenceAnnotation,
    DataSourceMode,
    Detection,
    Encounter,
    InclusionPolicy,
    MediaAsset,
    MediaType,
    MonitoringEffort,
    NormalizedBBox,
    Observation,
    PredictionRun,
    PredictionStatus,
    ResponseStatus,
    ReviewDecision,
    ReviewEvent,
    ReviewOrderingMechanism,
    ReviewRankingRequest,
    ScoreType,
    Snapshot,
    SnapshotMetadata,
    SpatialContext,
    SpatialZone,
    SUPPORTED_SCHEMA_VERSIONS,
    TaxonAlternative,
    TimeInterval,
    TriageState,
    ValidationErrorDetail,
    ValidationErrorCode,
)
from wildscope_analytics.validation import (
    ValidationReport,
    load_and_validate_snapshot,
    validate_analysis_request,
    validate_review_ranking_request,
    validate_snapshot_data,
)
from wildscope_analytics.analytics import analyze
from wildscope_analytics.analytics import rank_review


from wildscope_analytics.analytics import analyze
from wildscope_analytics.analytics import rank_review


__all__ = [
    "AnalysisMetric",
    "AnalysisRequest",
    "AnalysisResponseEnvelope",
    "AnnotationSource",
    "BaseContractModel",
    "CalibrationStatus",
    "Camera",
    "CURRENT_SCHEMA_VERSION",
    "DatasetReferenceAnnotation",
    "DataSourceMode",
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
    "ReviewOrderingMechanism",
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
    "ValidationReport",
    "analyze",
    "load_and_validate_snapshot",
    "rank_review",
    "validate_analysis_request",
    "validate_review_ranking_request",
    "validate_snapshot_data",
]
