"""
WILDSCOPE Decision Intelligence & Analytics Module
Core Entity Contracts - Phase 1

Defines strongly-typed Pydantic models for cameras, media assets, observations,
detections, encounters, reviews, monitoring effort, and spatial context.
"""

from __future__ import annotations
import math
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wildscope_analytics.contracts.enums import (
    CalibrationStatus,
    CandidatePlacementStatus,
    MediaType,
    PositionType,
    PredictionStatus,
    ProximityRelation,
    ReviewDecision,
    ScoreType,
    SpatialSourceType,
    TriageState,
)


class BaseContractModel(BaseModel):
    """Base model enforcing strict configuration and whitespace stripping."""
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class Camera(BaseContractModel):
    """
    Physical camera trap device record.
    Supports location-based grouping via site_id even when geographical
    coordinates are unknown or withheld.
    """
    id: str = Field(..., description="Stable unique identifier for the camera.")
    site_id: str | None = Field(
        default=None,
        description="Optional site or station identifier for hierarchical grouping."
    )
    latitude: float | None = Field(
        default=None,
        description="WGS84 latitude in decimal degrees [-90, 90]."
    )
    longitude: float | None = Field(
        default=None,
        description="WGS84 longitude in decimal degrees [-180, 180]."
    )
    timezone: str | None = Field(
        default=None,
        description="Declared IANA timezone identifier, e.g. 'Asia/Kolkata'."
    )
    provenance: dict[str, Any] | str | None = Field(
        default=None,
        description="Origin tracking for supplied camera metadata."
    )

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float | None) -> float | None:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ValueError("Latitude must be a finite number.")
            if not (-90.0 <= v <= 90.0):
                raise ValueError(f"Latitude {v} out of bounds [-90, 90].")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float | None) -> float | None:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ValueError("Longitude must be a finite number.")
            if not (-180.0 <= v <= 180.0):
                raise ValueError(f"Longitude {v} out of bounds [-180, 180].")
        return v

    @model_validator(mode="after")
    def validate_coordinate_pair(self) -> Camera:
        has_lat = self.latitude is not None
        has_lon = self.longitude is not None
        if has_lat != has_lon:
            raise ValueError(
                "Both latitude and longitude must be provided together, or both omitted."
            )
        return self


class NormalizedBBox(BaseContractModel):
    """
    Normalized bounding box.
    Convention: Coordinates in [0.0, 1.0] relative to frame dimensions.
    (0, 0) is top-left, (1, 1) is bottom-right.
    """
    x_min: float = Field(..., description="Left edge normalized coordinate [0, 1].")
    y_min: float = Field(..., description="Top edge normalized coordinate [0, 1].")
    x_max: float = Field(..., description="Right edge normalized coordinate [0, 1].")
    y_max: float = Field(..., description="Bottom edge normalized coordinate [0, 1].")

    @model_validator(mode="after")
    def validate_bounds(self) -> NormalizedBBox:
        coords = [self.x_min, self.y_min, self.x_max, self.y_max]
        for c in coords:
            if math.isnan(c) or math.isinf(c) or not (0.0 <= c <= 1.0):
                raise ValueError(f"Normalized bbox coordinate {c} must be finite in [0.0, 1.0].")
        if self.x_min > self.x_max:
            raise ValueError(f"x_min ({self.x_min}) cannot exceed x_max ({self.x_max}).")
        if self.y_min > self.y_max:
            raise ValueError(f"y_min ({self.y_min}) cannot exceed y_max ({self.y_max}).")
        return self


class TaxonAlternative(BaseContractModel):
    """Documented candidate species prediction with confidence score."""
    taxon_id: str = Field(..., description="Alternative taxon / species identifier.")
    score: float = Field(..., description="Model output score in [0.0, 1.0].")
    raw_label: str | None = Field(default=None, description="Raw model class string.")

    @field_validator("score")
    @classmethod
    def validate_score(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v) or not (0.0 <= v <= 1.0):
            raise ValueError(f"Alternative score {v} must be a finite number in [0.0, 1.0].")
        return v


class Detection(BaseContractModel):
    """
    Object-level animal detection and classification output.
    Distinguishes detection confidence from classification confidence,
    and explicitly tracks triage status and uncertainty.
    """
    id: str = Field(..., description="Stable unique detection ID.")
    observation_id: str = Field(..., description="Reference to parent Observation record.")
    run_id: str | None = Field(
        default=None,
        description="Reference to PredictionRun that generated this output."
    )
    triage_state: TriageState = Field(
        default=TriageState.ANIMAL_DETECTED,
        description="Triage outcome (likely_empty, animal_detected, processing_failure, unsupported_taxon)."
    )
    animal_detection_confidence: float = Field(
        ...,
        description="Confidence that an animal is present in the frame/crop [0.0, 1.0]."
    )
    predicted_taxon_id: str | None = Field(
        default=None,
        description="Canonical taxon identifier if species classification succeeded."
    )
    raw_label: str | None = Field(
        default=None,
        description="Original unmodified label emitted by the vision classifier."
    )
    classification_confidence: float | None = Field(
        default=None,
        description="Species classification score in [0.0, 1.0]."
    )
    score_type: ScoreType = Field(
        default=ScoreType.SOFTMAX,
        description="Output type of the classification score."
    )
    calibration_status: CalibrationStatus = Field(
        default=CalibrationStatus.UNCALIBRATED,
        description="Probability calibration status."
    )
    bbox: NormalizedBBox | None = Field(
        default=None,
        description="Normalized bounding box of detection in frame."
    )
    alternatives: list[TaxonAlternative] = Field(
        default_factory=list,
        description="Documented alternative species hypotheses."
    )

    @field_validator("animal_detection_confidence")
    @classmethod
    def validate_detection_confidence(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v) or not (0.0 <= v <= 1.0):
            raise ValueError(
                f"animal_detection_confidence {v} must be a finite number in [0.0, 1.0]."
            )
        return v

    @field_validator("classification_confidence")
    @classmethod
    def validate_classification_confidence(cls, v: float | None) -> float | None:
        if v is not None:
            if math.isnan(v) or math.isinf(v) or not (0.0 <= v <= 1.0):
                raise ValueError(
                    f"classification_confidence {v} must be a finite number in [0.0, 1.0]."
                )
        return v


class MediaAsset(BaseContractModel):
    """
    Source raw media file (image or video) stored in object/file storage.
    """
    id: str = Field(..., description="Stable unique identifier for media asset.")
    media_type: MediaType = Field(default=MediaType.IMAGE, description="image or video.")
    camera_id: str = Field(..., description="Reference to Camera where recorded.")
    storage_key: str = Field(..., description="Internal storage identifier or path key.")
    raw_timestamp: str | None = Field(
        default=None,
        description="Unparsed raw timestamp string from EXIF or filename."
    )
    captured_at: datetime | None = Field(
        default=None,
        description="Resolved timezone-aware capture timestamp."
    )
    timezone_source: str | None = Field(
        default=None,
        description="How timezone was resolved (e.g. 'camera_profile', 'exif_offset')."
    )
    provenance: dict[str, Any] | str | None = Field(
        default=None,
        description="Source provenance details."
    )

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at_tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("captured_at must be timezone-aware if provided.")
        return v


class Observation(BaseContractModel):
    """
    An individual frame or standalone image observation event.
    Links detections to source media and physical camera.
    """
    id: str = Field(..., description="Stable unique observation identifier.")
    camera_id: str = Field(..., description="Reference to physical Camera.")
    source_media_id: str = Field(..., description="Reference to MediaAsset.")
    frame_offset_ms: int | None = Field(
        default=None,
        ge=0,
        description="Video frame offset in milliseconds (null for still photos)."
    )
    captured_at: datetime | None = Field(
        default=None,
        description="Resolved timezone-aware capture timestamp."
    )
    raw_timestamp: str | None = Field(
        default=None,
        description="Raw EXIF timestamp string preserved for audit."
    )
    timezone_source: str | None = Field(
        default=None,
        description="Method used to establish timezone."
    )
    width_px: int | None = Field(default=None, gt=0, description="Source image width in pixels.")
    height_px: int | None = Field(default=None, gt=0, description="Source image height in pixels.")
    detection_ids: list[str] = Field(
        default_factory=list,
        description="Ordered list of Detection IDs belonging to this observation."
    )

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at_tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("Observation captured_at must be timezone-aware if provided.")
        return v


class PredictionRun(BaseContractModel):
    """
    Audit record of an inference model run.
    Ensures complete traceability of model hashes, device, and settings.
    """
    id: str = Field(..., description="Stable unique prediction run identifier.")
    model_version: str = Field(..., description="Version identifier of vision model artifact.")
    settings_hash: str | None = Field(default=None, description="Hash of inference hyper-parameters.")
    device: str | None = Field(default=None, description="Execution device (e.g. 'cuda:0', 'cpu').")
    started_at: datetime | None = Field(default=None, description="Job execution start time.")
    completed_at: datetime | None = Field(default=None, description="Job completion time.")
    status: PredictionStatus = Field(
        default=PredictionStatus.COMPLETED,
        description="Job completion status."
    )
    cache_hit: bool = Field(default=False, description="Whether output was served from cache.")
    failure_codes: list[str] = Field(default_factory=list, description="Non-fatal failure codes.")
    input_content_hash: str | None = Field(default=None, description="Hash of input media payload.")
    model_artifact_hash: str | None = Field(default=None, description="Hash of weights artifact.")
    preprocessing_hash: str | None = Field(default=None, description="Hash of transform pipeline.")

    @model_validator(mode="after")
    def validate_timing(self) -> PredictionRun:
        if self.started_at and self.completed_at:
            if self.started_at.tzinfo is None or self.started_at.tzinfo.utcoffset(self.started_at) is None:
                raise ValueError("PredictionRun started_at must be timezone-aware if provided.")
            if self.completed_at.tzinfo is None or self.completed_at.tzinfo.utcoffset(self.completed_at) is None:
                raise ValueError("PredictionRun completed_at must be timezone-aware if provided.")
            if self.started_at > self.completed_at:
                raise ValueError("PredictionRun started_at cannot be later than completed_at.")
        return self


class Encounter(BaseContractModel):
    """
    Operational grouping of observations within a camera trap temporal session.
    Represents an encounter event; does NOT establish individual animal identity
    or population size.
    """
    id: str = Field(..., description="Stable unique encounter identifier.")
    camera_id: str = Field(..., description="Reference to Camera where encounter occurred.")
    member_observation_ids: list[str] = Field(
        default_factory=list,
        description="Observation IDs included in this encounter."
    )
    member_detection_ids: list[str] = Field(
        default_factory=list,
        description="Detection IDs included in this encounter."
    )
    start_time: datetime | None = Field(
        default=None,
        description="Encounter start timestamp (timezone-aware)."
    )
    end_time: datetime | None = Field(
        default=None,
        description="Encounter end timestamp (timezone-aware)."
    )
    rule_version: str = Field(
        default="v1_time_gap",
        description="Grouping algorithm version (e.g. 30-minute burst gap)."
    )
    provenance: dict[str, Any] | str | None = Field(
        default=None,
        description="Evidence trace and grouping metadata."
    )

    @model_validator(mode="after")
    def validate_temporal_bounds(self) -> Encounter:
        if self.start_time is not None:
            if self.start_time.tzinfo is None or self.start_time.tzinfo.utcoffset(self.start_time) is None:
                raise ValueError("Encounter start_time must be timezone-aware if provided.")
        if self.end_time is not None:
            if self.end_time.tzinfo is None or self.end_time.tzinfo.utcoffset(self.end_time) is None:
                raise ValueError("Encounter end_time must be timezone-aware if provided.")
        if self.start_time is not None and self.end_time is not None:
            if self.start_time > self.end_time:
                raise ValueError(
                    f"Encounter start_time ({self.start_time}) cannot be after end_time ({self.end_time})."
                )
        if not self.member_observation_ids and not self.member_detection_ids:
            raise ValueError("Encounter must contain at least one member observation or detection ID.")
        return self


class ReviewEvent(BaseContractModel):
    """
    Human review decision.
    Original model outputs remain immutable; reviews are append-only audit events.
    The effective state is resolved transactionally by the backend.

    Phase 2 extension:
    - sequence_number: backend-assigned monotone integer ordering reviews on the same target.
      When supplied, the resolver uses this instead of created_at for deterministic ordering.
      Santosh must supply this when review_ordering_mechanism = "backend_revision".
    """
    id: str = Field(..., description="Stable unique review event ID.")
    target_id: str = Field(
        ...,
        description="Reference to target Detection ID (or Encounter ID)."
    )
    decision: ReviewDecision = Field(..., description="Review outcome decision.")
    corrected_taxon_id: str | None = Field(
        default=None,
        description="Required if decision is CORRECT_SPECIES, forbidden if REJECT_DETECTION."
    )
    reviewer: str = Field(..., min_length=1, description="Reviewer identifier or username.")
    reason: str | None = Field(default=None, description="Optional reasoning or notes.")
    created_at: datetime = Field(..., description="Timestamp when review was executed.")
    expected_revision: int | None = Field(
        default=None,
        description="Source dataset revision at time of review (for optimistic concurrency)."
    )
    sequence_number: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Phase 2: Backend-assigned monotone integer ordering ReviewEvents on the same target. "
            "When present, used as authoritative ordering; created_at is supplementary. "
            "expected_revision is a concurrency precondition, NOT an ordering mechanism."
        ),
    )

    @field_validator("created_at")
    @classmethod
    def validate_created_at_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("ReviewEvent created_at must be timezone-aware.")
        return v

    @model_validator(mode="after")
    def validate_decision_consistency(self) -> ReviewEvent:
        if self.decision == ReviewDecision.CORRECT_SPECIES:
            if not self.corrected_taxon_id or not self.corrected_taxon_id.strip():
                raise ValueError(
                    "corrected_taxon_id is required when decision is CORRECT_SPECIES."
                )
        elif self.decision == ReviewDecision.REJECT_DETECTION:
            if self.corrected_taxon_id:
                raise ValueError(
                    "corrected_taxon_id must not be specified when decision is REJECT_DETECTION."
                )
        return self


class TimeInterval(BaseContractModel):
    """A bounded time interval for monitoring effort."""
    start: datetime = Field(..., description="Interval start timestamp.")
    end: datetime = Field(..., description="Interval end timestamp.")

    @model_validator(mode="after")
    def validate_interval(self) -> TimeInterval:
        if self.start.tzinfo is None or self.start.tzinfo.utcoffset(self.start) is None:
            raise ValueError("Interval start must be timezone-aware.")
        if self.end.tzinfo is None or self.end.tzinfo.utcoffset(self.end) is None:
            raise ValueError("Interval end must be timezone-aware.")
        if self.start > self.end:
            raise ValueError(f"Interval start ({self.start}) cannot be after end ({self.end}).")
        return self


class MonitoringEffort(BaseContractModel):
    """
    Explicit documented operational effort intervals for a camera.
    Uptime is NOT inferred from image frequency or span.
    """
    id: str = Field(..., description="Stable unique monitoring effort record ID.")
    camera_id: str = Field(..., description="Reference to Camera.")
    active_intervals: list[TimeInterval] = Field(
        default_factory=list,
        description="Disjoint, non-overlapping active monitoring periods."
    )
    source: str | None = Field(
        default=None,
        description="Source of effort record (e.g. 'ranger_log', 'telemetry_heartbeat')."
    )
    completeness_notes: str | None = Field(
        default=None,
        description="Known limitations or gaps in effort tracking."
    )

    @model_validator(mode="after")
    def validate_non_overlapping_intervals(self) -> MonitoringEffort:
        # Sort intervals by start time and verify no overlap
        if len(self.active_intervals) > 1:
            sorted_intervals = sorted(self.active_intervals, key=lambda i: i.start)
            for idx in range(len(sorted_intervals) - 1):
                cur = sorted_intervals[idx]
                nxt = sorted_intervals[idx + 1]
                if cur.end > nxt.start:
                    raise ValueError(
                        f"Overlapping monitoring intervals detected for camera {self.camera_id}: "
                        f"[{cur.start.isoformat()} - {cur.end.isoformat()}] overlaps with "
                        f"[{nxt.start.isoformat()} - {nxt.end.isoformat()}]."
                    )
        return self


class DatasetReferenceAnnotation(BaseContractModel):
    """
    Official dataset annotation (e.g. from Caltech Camera Traps ground truth).

    Phase 2 discriminated type for dataset_reference mode.
    This entity MUST NOT be mixed with operational_prediction Detection records.
    It preserves:
    - Original source annotation ID and image ID.
    - Original category ID and category name exactly as published.
    - Namespace-prefixed internal identifiers to avoid collisions with operational IDs.
    - Bounding box in dataset-native COCO pixel format (xmin, ymin, width, height).

    Key distinctions from Detection:
    - No prediction run, model name, or confidence score (none are available).
    - No triage state (dataset annotations assert presence, not probability).
    - No invented review events.
    """
    id: str = Field(
        ...,
        description=(
            "Namespaced internal identifier, e.g. 'cct:ann:12345'. "
            "Original source annotation ID is preserved in source_annotation_id."
        ),
    )
    observation_id: str = Field(
        ..., description="Reference to the Observation record for the annotated image."
    )
    source_annotation_id: str = Field(
        ..., description="Original annotation ID as published by the dataset."
    )
    source_image_id: str = Field(
        ..., description="Original image ID from the dataset (before namespacing)."
    )
    dataset_name: str = Field(
        ..., description="Dataset name, e.g. 'caltech_camera_traps'."
    )
    dataset_version: str | None = Field(
        default=None,
        description="Dataset version or release identifier if available.",
    )
    category_id: int | str = Field(
        ...,
        description=(
            "Original category ID exactly as published. "
            "Integer for CCT (COCO Camera Traps format)."
        ),
    )
    category_name: str = Field(
        ...,
        description="Original category name exactly as published (e.g. 'coyote', 'empty', 'person').",
    )
    wildscope_taxon_id: str | None = Field(
        default=None,
        description=(
            "Mapped WILDSCOPE taxon identifier, if a canonical mapping exists. "
            "None if category is non-animal, empty, unknown, or unsupported. "
            "Mapping is documented in the dataset adapter."
        ),
    )
    is_animal: bool = Field(
        ...,
        description=(
            "True if category represents an animal species or group. "
            "False for 'empty', 'vehicle', 'person', and non-animal categories."
        ),
    )
    is_empty: bool = Field(
        default=False,
        description="True if category_name == 'empty' (no animal trigger).",
    )
    bbox_coco: list[float] | None = Field(
        default=None,
        description=(
            "Bounding box in COCO pixel format [xmin, ymin, width, height]. "
            "Preserved exactly from the source dataset. Not normalized."
        ),
    )
    sequence_id: str | None = Field(
        default=None,
        description="Dataset burst sequence ID (seq_id in CCT format).",
    )
    provenance: dict[str, Any] | str | None = Field(
        default=None,
        description="Source dataset provenance (URL, license, import timestamp).",
    )


class SpatialZone(BaseContractModel):
    """Supplied spatial zone boundary (e.g. park core, corridor, buffer zone)."""
    id: str = Field(..., description="Stable zone identifier.")
    name: str = Field(..., description="Human-readable zone label.")
    zone_type: str = Field(..., description="e.g. 'core_reserve', 'community_buffer', 'road_corridor'.")
    geometry: dict[str, Any] = Field(
        ...,
        description="GeoJSON-compatible geometry dictionary (Polygon, MultiPolygon, etc.)."
    )
    valid_from: datetime | None = Field(default=None, description="Start of temporal applicability.")
    valid_to: datetime | None = Field(default=None, description="End of temporal applicability.")

    @field_validator("geometry")
    @classmethod
    def validate_geometry_dict(cls, v: dict[str, Any]) -> dict[str, Any]:
        if "type" not in v or "coordinates" not in v:
            raise ValueError("Zone geometry must contain 'type' and 'coordinates' keys.")
        return v


class SpatialContext(BaseContractModel):
    """
    Optional spatial context provided with a snapshot.
    Camera coordinates are not exact animal coordinates.
    """
    crs: str = Field(default="EPSG:4326", description="Coordinate Reference System.")
    zones: list[SpatialZone] = Field(
        default_factory=list,
        description="Defined reserve boundaries or management zones."
    )
    candidate_sites: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Potential deployment sites for adaptive coverage optimization."
    )
    coverage_assumptions: dict[str, Any] = Field(
        default_factory=dict,
        description="Documented sensor range or viewshed assumptions."
    )
    provenance: str | None = Field(
        default=None,
        description="Source of GIS layers and spatial metadata."
    )


class CameraCoverage(BaseContractModel):
    """Declared or modeled spatial coverage for a camera trap."""
    camera_id: str = Field(..., description="Camera identifier.")
    geometry: dict[str, Any] | None = Field(
        default=None,
        description="GeoJSON-compatible Polygon/MultiPolygon geometry."
    )
    source_type: SpatialSourceType = Field(
        default=SpatialSourceType.ASSUMED,
        description="Source classification of coverage (measured, assumed, synthetic)."
    )
    detection_radius_meters: float | None = Field(
        default=None,
        gt=0.0,
        description="Effective detection range radius in meters if geometry is circular/buffer."
    )
    azimuth_degrees: float | None = Field(
        default=None,
        ge=0.0,
        le=360.0,
        description="Compass bearing angle of camera lens."
    )
    field_of_view_degrees: float | None = Field(
        default=None,
        gt=0.0,
        le=360.0,
        description="Horizontal sensor angle of view."
    )
    valid_from: datetime | None = Field(default=None, description="Start of coverage interval.")
    valid_to: datetime | None = Field(default=None, description="End of coverage interval.")
    provenance: str | None = Field(
        default=None,
        description="Documentation of coverage measurement or assumption."
    )


class CandidateSite(BaseContractModel):
    """Candidate camera placement site for monitoring optimization."""
    candidate_id: str = Field(..., description="Unique candidate site ID.")
    name: str | None = Field(default=None, description="Descriptive site label.")
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    geometry: dict[str, Any] | None = Field(
        default=None,
        description="GeoJSON Polygon/MultiPolygon representing modeled viewshed."
    )
    coverage_radius_meters: float = Field(
        default=50.0,
        gt=0.0,
        description="Radius in meters if geometry is modeled as circular buffer."
    )
    cost: float = Field(
        default=1.0,
        gt=0.0,
        description="Deployment or maintenance cost weight (must be finite positive number)."
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional site features (e.g. accessibility, tree cover)."
    )

    @field_validator("cost")
    @classmethod
    def validate_cost_finite(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0.0:
            raise ValueError(f"CandidateSite cost must be a finite positive number, got {v}")
        return v


class TargetLocation(BaseContractModel):
    """Spatial coordinate target evaluated against zones or infrastructure."""
    target_id: str = Field(..., description="Target point identifier (camera ID, encounter ID, etc.).")
    position_type: PositionType = Field(
        default=PositionType.CAMERA_SITE,
        description="Nature of location (camera_site, estimated_animal_position, observation_location)."
    )
    latitude: float = Field(..., ge=-90.0, le=90.0, description="WGS84 latitude.")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="WGS84 longitude.")
    uncertainty_radius_meters: float | None = Field(
        default=None,
        ge=0.0,
        description="Positional uncertainty radius in meters. None indicates uncertainty is unassessed."
    )
    associated_camera_id: str | None = Field(default=None, description="Optional associated camera.")
    associated_encounter_id: str | None = Field(default=None, description="Optional associated encounter.")
    species_id: str | None = Field(default=None, description="Optional associated focal taxon.")
    timestamp: datetime | None = Field(default=None, description="Time of observation/estimate.")

    @field_validator("uncertainty_radius_meters")
    @classmethod
    def validate_uncertainty_finite(cls, v: float | None) -> float | None:
        if v is not None and (not math.isfinite(v) or v < 0.0):
            raise ValueError(f"uncertainty_radius_meters must be a finite non-negative number, got {v}")
        return v
