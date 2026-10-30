"""
WILDSCOPE Decision Intelligence & Analytics Module
Contract Enums - Phase 1

Defines enumeration constants used across the shared data contracts,
validation engine, and future analytical execution points.
"""

from enum import Enum


class StrEnum(str, Enum):
    """String enum for reliable JSON serialization and comparison."""
    def __str__(self) -> str:
        return self.value


class MediaType(StrEnum):
    """Type of ingested camera-trap media."""
    IMAGE = "image"
    VIDEO = "video"


class TriageState(StrEnum):
    """
    Triage status from observation intelligence.
    Explicitly distinguishes empty frames, valid animal detections,
    processing failures, and unsupported taxa.
    """
    LIKELY_EMPTY = "likely_empty"
    ANIMAL_DETECTED = "animal_detected"
    PROCESSING_FAILURE = "processing_failure"
    UNSUPPORTED_TAXON = "unsupported_taxon"


class ScoreType(StrEnum):
    """
    Semantic nature of model prediction score.
    Crucial for preventing mistaking raw logits or uncalibrated softmax scores
    for true posterior probabilities.
    """
    RAW = "raw"
    SOFTMAX = "softmax"
    CALIBRATED = "calibrated"
    PROBABILITY = "probability"


class CalibrationStatus(StrEnum):
    """Status of model probability calibration."""
    UNCALIBRATED = "uncalibrated"
    CALIBRATED = "calibrated"
    NOT_APPLICABLE = "not_applicable"


class ReviewDecision(StrEnum):
    """
    Human review decision on a target detection or encounter.
    Reviews are append-only audit events and do not mutate original model outputs.
    """
    CONFIRM_SPECIES = "confirm_species"
    CORRECT_SPECIES = "correct_species"
    MARK_UNKNOWN = "mark_unknown"
    REJECT_DETECTION = "reject_detection"
    FLAG_FOR_EXPERT = "flag_for_expert"


class ResponseStatus(StrEnum):
    """
    Status of an analytical or review-ranking response envelope.
    Clear semantics distinguish missing data from missing capabilities.
    """
    OK = "ok"
    PARTIAL = "partial"
    INSUFFICIENT_DATA = "insufficient_data"
    UNAVAILABLE = "unavailable"
    INVALID_REQUEST = "invalid_request"


class AnalysisMetric(StrEnum):
    """
    Operations supported by the decision intelligence module.
    Rejects arbitrary or unsupported queries.

    Phase 2 additions:
    - OVERVIEW: snapshot-level summary (encounters, images, cameras, time coverage).
    - SPECIES_ENCOUNTER_COUNTS: deduplicated encounter/species contributions.
    - CAMERA_COMPARISON: per-camera/site encounter and species counts.
    - DAILY_ACTIVITY: encounter counts grouped by calendar date.
    - HOURLY_ACTIVITY: encounter counts grouped by hour-of-day (0-23).
    - SPECIES_CAMERA_MATRIX: species × camera count matrix.
    - EFFORT_NORMALISED_RATES: encounters per active camera-day.
    """
    OVERVIEW = "overview"
    SPECIES_ENCOUNTER_COUNTS = "species_encounter_counts"
    REFERENCE_IMAGE_SPECIES_COUNTS = "reference_image_species_counts"
    CAMERA_COMPARISON = "camera_comparison"
    DAILY_ACTIVITY = "daily_activity"
    HOURLY_ACTIVITY = "hourly_activity"
    SPECIES_CAMERA_MATRIX = "species_camera_matrix"
    EFFORT_NORMALISED_RATES = "effort_normalised_rates"
    # Phase 4 additions:
    CROSS_CAMERA_ASSOCIATIONS = "cross_camera_associations"
    # Phase 1 legacy names kept for backward compatibility
    ACTIVITY_TIME_DISTRIBUTION = "activity_time_distribution"
    CROSS_CAMERA_ASSOCIATION = "cross_camera_association"
    CAMERA_ACTIVITY_SUMMARY = "camera_activity_summary"
    MONITORING_COVERAGE_SUMMARY = "monitoring_coverage_summary"


class SpatialMode(StrEnum):
    """
    Spatial evaluation mode for cross-camera observation correlation (Phase 4, Feature F06).
    - TIME_SPECIES_ONLY: GPS coordinates optional; spatial checks not evaluated.
    - SPATIAL_WHEN_AVAILABLE: evaluates distance when coordinates exist; marks missing as unavailable.
    - SPATIAL_REQUIRED: evaluates only pairs with genuine coordinates; returns UNAVAILABLE if missing.
    """
    TIME_SPECIES_ONLY = "time_species_only"
    SPATIAL_WHEN_AVAILABLE = "spatial_when_available"
    SPATIAL_REQUIRED = "spatial_required"


class ClockComparabilityPolicy(StrEnum):
    """
    Policy declaring the operational basis for comparing timestamps across different cameras.
    - DOCUMENTED_SYNC: clocks verified synchronized across deployment (e.g. NTP, GPS, manual sync).
    - ANALYST_ASSUMPTION: explicit analyst policy assuming clocks are synchronized within stated bounds.
    - OFFSETS_KNOWN: clock offsets and uncertainty are known and propagated conservatively.
    - UNKNOWN: inter-camera clock alignment is unverified (returns INSUFFICIENT_DATA).
    """
    DOCUMENTED_SYNC = "documented_sync"
    ANALYST_ASSUMPTION = "analyst_assumption"
    OFFSETS_KNOWN = "offsets_known"
    UNKNOWN = "unknown"


class SpatialCheckStatus(StrEnum):
    """Outcome of spatial rule evaluation for a candidate cross-camera encounter pair."""
    NOT_EVALUATED = "not_evaluated"
    UNAVAILABLE = "unavailable"
    PASSED = "passed"
    FAILED = "failed"
    MEASURED = "measured"


class TemporalRelation(StrEnum):
    """Temporal interval relationship between two encounters."""
    OVERLAPPING = "overlapping"
    DISJOINT = "disjoint"


class InclusionPolicy(StrEnum):
    """Policy governing which detections are admitted into analytical aggregations."""
    REVIEWED_ONLY = "reviewed_only"
    PROVISIONAL_AND_REVIEWED = "provisional_and_reviewed"
    ALL_DETECTIONS = "all_detections"


class PredictionStatus(StrEnum):
    """Status of an inference execution run."""
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class EncounterProcessingStatus(StrEnum):
    """
    Status of encounter grouping processing in the vision/clustering pipeline (Harsh).
    Explicitly distinguishes whether encounter grouping is available, pending, completed, or failed.
    """
    UNAVAILABLE = "unavailable"    # Capability not configured/supported in this deployment
    PENDING = "pending"            # Pipeline execution has not yet run or is in-progress
    COMPLETED = "completed"        # Pipeline completed (even if 0 encounters resulted)
    FAILED = "failed"              # Pipeline failed during grouping execution


class DataSourceMode(StrEnum):
    """
    Discriminates operational inference data from official dataset reference annotations.

    Phase 2 extension. Never mix these modes in the same analytical computation.
    - OPERATIONAL_PREDICTION: real model inference outputs from Harsh/Santosh pipeline.
    - DATASET_REFERENCE: official human-annotated ground truth (e.g. Caltech Camera Traps).
    """
    OPERATIONAL_PREDICTION = "operational_prediction"
    DATASET_REFERENCE = "dataset_reference"


class ReviewOrderingMechanism(StrEnum):
    """
    Documents how multiple ReviewEvents for the same target are ordered
    when resolving the effective label.

    Phase 2 requirement: Shravan's resolver must not guess ordering.
    """
    BACKEND_REVISION = "backend_revision"   # Use dataset_revision increments (preferred)
    SEQUENCE_NUMBER = "sequence_number"     # Explicit per-event sequence numbers
    TIMESTAMP = "timestamp"                 # created_at (only if guaranteed unique+monotone)
    UNRESOLVABLE = "unresolvable"           # Multiple reviews with ambiguous ordering


class AnnotationSource(StrEnum):
    """
    Marks the source of an annotation entity in the dataset.
    Used by the dataset adapter to track provenance.
    """
    CALTECH_CCT = "caltech_cct"              # Caltech Camera Traps COCO format
    WILDSCOPE_INFERENCE = "wildscope_inference"  # WILDSCOPE operational pipeline
    SYNTHETIC_FIXTURE = "synthetic_fixture"  # Test/example fixtures


class ValidationErrorCode(StrEnum):
    """Stable error codes for contract and snapshot validation failures."""
    DUPLICATE_ID = "DUPLICATE_ID"
    BROKEN_REFERENCE = "BROKEN_REFERENCE"
    INVALID_CONFIDENCE = "INVALID_CONFIDENCE"
    INVALID_COORDINATES = "INVALID_COORDINATES"
    TEMPORAL_ORDER_VIOLATION = "TEMPORAL_ORDER_VIOLATION"
    MISSING_TIMEZONE = "MISSING_TIMEZONE"
    OVERLAPPING_EFFORT = "OVERLAPPING_EFFORT"
    INVALID_BBOX = "INVALID_BBOX"
    INVALID_REVIEW_PAYLOAD = "INVALID_REVIEW_PAYLOAD"
    ENCOUNTER_MEMBERSHIP_VIOLATION = "ENCOUNTER_MEMBERSHIP_VIOLATION"
    UNSUPPORTED_SCHEMA_VERSION = "UNSUPPORTED_SCHEMA_VERSION"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    # Phase 2 additions
    AMBIGUOUS_REVIEW_ORDER = "AMBIGUOUS_REVIEW_ORDER"
    CONFLICTING_REVIEW = "CONFLICTING_REVIEW"
    DATASET_SOURCE_MISMATCH = "DATASET_SOURCE_MISMATCH"
    MISSING_ENCOUNTER_SUPPORT = "MISSING_ENCOUNTER_SUPPORT"
    INVALID_RANKING_TARGET = "INVALID_RANKING_TARGET"
