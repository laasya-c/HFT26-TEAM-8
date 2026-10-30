"""
WILDSCOPE Decision Intelligence & Analytics Module
Package Root - Phase 1

This package defines shared contracts, data validation rules, request models,
and response envelopes for WILDSCOPE.

Phase 1 establishes the trustworthy inputs and outputs.
Analytical calculation engines and ranking algorithms are intentionally deferred to Phase 2.
"""

from wildscope_analytics.contracts import (
    AnalysisMetric,
    AnalysisRequest,
    AnalysisResponseEnvelope,
    BaseContractModel,
    CalibrationStatus,
    Camera,
    CURRENT_SCHEMA_VERSION,
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


def analyze(
    snapshot: Snapshot,
    request: AnalysisRequest,
) -> AnalysisResponseEnvelope[None]:
    """
    Entry point for analytical computations.

    In Phase 1, this function strictly validates the contracts.
    Computational engines (encounter aggregation, diurnal activity, effort normalization)
    are deferred to Phase 2.

    Returns an envelope with status=UNAVAILABLE and explicit limitations rather than
    fabricating metrics or returning fake status=OK.
    """
    # Validate snapshot data
    snap_report = validate_snapshot_data(snapshot)
    if not snap_report.is_valid:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=request.metric,
            applied_filters={"metric": request.metric.value},
            errors=snap_report.errors,
            warnings=snap_report.warnings,
            limitations=["Snapshot failed contract validation."],
        )

    # Validate request revision if expected_revision provided
    if (
        request.expected_revision is not None
        and request.expected_revision != snapshot.metadata.dataset_revision
    ):
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=request.metric,
            applied_filters={"expected_revision": request.expected_revision},
            errors=[
                ValidationErrorDetail(
                    code=ValidationErrorCode.SCHEMA_VIOLATION,
                    message=(
                        f"Expected revision {request.expected_revision} does not match "
                        f"snapshot dataset revision {snapshot.metadata.dataset_revision}."
                    ),
                    field_path="expected_revision",
                )
            ],
            limitations=["Dataset revision conflict (optimistic lock mismatch)."],
        )

    # Phase 1: Explicitly indicate calculation engine is deferred
    return AnalysisResponseEnvelope(
        status=ResponseStatus.UNAVAILABLE,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=request.metric,
        applied_filters={
            "metric": request.metric.value,
            "inclusion_policy": request.inclusion_policy.value,
            "min_confidence": request.min_confidence,
        },
        warnings=snap_report.warnings,
        limitations=[
            "Analytical algorithm implementations are deferred to Phase 2.",
            "Phase 1 establishes shared data contracts, referential integrity, and validation only.",
            "No fabricated or predetermined statistical values are returned.",
        ],
    )


def rank_review(
    snapshot: Snapshot,
    request: ReviewRankingRequest,
) -> AnalysisResponseEnvelope[None]:
    """
    Entry point for conclusion-sensitive review prioritization.

    In Phase 1, this function strictly validates the contracts.
    Sensitivity ranking algorithms are deferred to Phase 2.

    Returns an envelope with status=UNAVAILABLE and explicit limitations.
    """
    snap_report = validate_snapshot_data(snapshot)
    if not snap_report.is_valid:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=request.target_metric,
            applied_filters={"target_metric": request.target_metric.value},
            errors=snap_report.errors,
            warnings=snap_report.warnings,
            limitations=["Snapshot failed contract validation."],
        )

    if (
        request.expected_revision is not None
        and request.expected_revision != snapshot.metadata.dataset_revision
    ):
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=request.target_metric,
            applied_filters={"expected_revision": request.expected_revision},
            errors=[
                ValidationErrorDetail(
                    code=ValidationErrorCode.SCHEMA_VIOLATION,
                    message=(
                        f"Expected revision {request.expected_revision} does not match "
                        f"snapshot dataset revision {snapshot.metadata.dataset_revision}."
                    ),
                    field_path="expected_revision",
                )
            ],
            limitations=["Dataset revision conflict (optimistic lock mismatch)."],
        )

    return AnalysisResponseEnvelope(
        status=ResponseStatus.UNAVAILABLE,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=request.target_metric,
        applied_filters={
            "target_metric": request.target_metric.value,
            "top_k_candidates": request.top_k_candidates,
            "score_margin_threshold": request.score_margin_threshold,
        },
        warnings=snap_report.warnings,
        limitations=[
            "Conclusion-sensitive review ranking engine is deferred to Phase 2.",
            "Phase 1 establishes shared data contracts and validation only.",
            "No fabricated priority rankings are returned.",
        ],
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
    "ValidationReport",
    "analyze",
    "load_and_validate_snapshot",
    "rank_review",
    "validate_analysis_request",
    "validate_review_ranking_request",
    "validate_snapshot_data",
]
