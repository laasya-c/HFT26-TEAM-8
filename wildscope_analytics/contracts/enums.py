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
    """
    SPECIES_ENCOUNTER_COUNTS = "species_encounter_counts"
    ACTIVITY_TIME_DISTRIBUTION = "activity_time_distribution"
    CROSS_CAMERA_ASSOCIATION = "cross_camera_association"
    CAMERA_ACTIVITY_SUMMARY = "camera_activity_summary"
    MONITORING_COVERAGE_SUMMARY = "monitoring_coverage_summary"


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
