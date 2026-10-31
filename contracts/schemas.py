"""WILDSCOPE Shared Data Contracts (Draft).

Primary Source:
- WILDSCOPE Complete Solution Guide (v2 / 30 OCT 2026)
- WILDSCOPE Team Work Manual (v2 / 30 OCT 2026)

STATUS: DRAFT — Subject to formal review and signoff by Harsh, Shravan, and Laasya.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProvenanceEnum(str, Enum):
    """Origin tracking for evidence integrity."""
    OBSERVED = "observed"      # Sensor/camera recorded
    INFERRED = "inferred"      # Model/algorithm produced
    SIMULATED = "simulated"    # Test fixture / developer synthetic


class ReviewStatusEnum(str, Enum):
    """Human review decision states for F20."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class TelemetryStatusEnum(str, Enum):
    """Hardware reporting health states for F07."""
    REPORTING = "reporting"
    STALE = "stale"
    UNKNOWN = "unknown"        # When telemetry has not been received (not dead!)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Scientific Rule: Missing capture times must stay None.
    
    If provided, datetimes must be timezone-aware and normalized to UTC.
    Naive datetimes are rejected because guessing local time corrupts day/night analysis.
    """
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(
            "Datetime must be timezone-aware. Naive timestamps are rejected to prevent local timezone corruption."
        )
    return dt.astimezone(timezone.utc)


class ContractBaseModel(BaseModel):
    """Shared base model configuration."""
    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        extra="forbid",
        use_enum_values=True,
    )


class ImageFrameContract(ContractBaseModel):
    """Image or extracted video frame representation."""
    id: str = Field(..., description="Stable unique frame identifier")
    camera_id: str = Field(..., description="Associated camera trap ID")
    captured_at: Optional[datetime] = Field(
        None,
        description="Resolved UTC timestamp. NULL if raw capture time/timezone is unknown."
    )
    timezone_source: Optional[str] = Field(
        None,
        description="Source used to resolve timezone, e.g., 'camera_metadata', 'manual'"
    )
    content_url: str = Field(..., description="Safe relative API endpoint to retrieve media bytes")
    quality_flags: List[str] = Field(
        default_factory=list,
        description="Flags such as 'low_light', 'motion_blur', 'occluded'"
    )
    provenance: ProvenanceEnum = Field(..., description="Data provenance")
    # Proposed video extension fields
    source_media_id: Optional[str] = Field(None, description="Parent video ID if derived frame")
    frame_offset_ms: Optional[int] = Field(None, description="Offset in milliseconds within source video")

    @field_validator("captured_at", mode="after")
    @classmethod
    def validate_utc_timestamp(cls, v: Optional[datetime]) -> Optional[datetime]:
        return ensure_utc(v)


class DetectionContract(ContractBaseModel):
    """Single bounding-box detection and model prediction."""
    id: str = Field(..., description="Stable unique detection identifier")
    image_id: str = Field(..., description="Reference to ImageFrame ID")
    encounter_id: Optional[str] = Field(None, description="Assigned Encounter ID")
    bbox: Tuple[float, float, float, float] = Field(
        ...,
        description="Normalized coordinates: [x_min, y_min, width, height] bounded in [0.0, 1.0]"
    )
    taxon_id: Optional[str] = Field(
        None,
        description="Standardized species taxonomy ID (e.g. 'panthera_tigris')"
    )
    label: str = Field(..., description="Display label mapped to shared taxonomy")
    raw_label: str = Field(..., description="Original raw output string from vision model")
    score: float = Field(..., ge=0.0, le=1.0, description="Primary confidence score [0.0, 1.0]")
    detection_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Animal presence score")
    classification_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Taxon classification score")
    score_type: Optional[str] = Field(None, description="Semantic description of score (e.g. 'softmax_probability')")
    calibration_status: Optional[str] = Field(None, description="'uncalibrated', 'platt_scaled', 'isotonic'")
    alternatives: Dict[str, float] = Field(
        default_factory=dict,
        description="Alternative top-k species and scores"
    )
    model_version: str = Field(..., description="Vision model version / checkpoint tag")
    review_status: ReviewStatusEnum = Field(
        default=ReviewStatusEnum.PENDING,
        description="Current review state"
    )
    provenance: ProvenanceEnum = Field(..., description="Data provenance")

    @field_validator("bbox", mode="after")
    @classmethod
    def validate_bbox(cls, v: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
        x, y, w, h = v
        for val in (x, y, w, h):
            if val < 0.0 or val > 1.0:
                raise ValueError(f"Bounding box values must be normalized between 0.0 and 1.0. Got: {v}")
        if x + w > 1.001 or y + h > 1.001:
            raise ValueError(f"Bounding box extends outside unit frame: x+w={x+w}, y+h={y+h}")
        return v


class EncounterContract(ContractBaseModel):
    """Temporal or sequence grouping of detections at a camera station."""
    id: str = Field(..., description="Stable encounter ID")
    camera_id: str = Field(..., description="Camera ID where encounter occurred")
    image_ids: List[str] = Field(default_factory=list, description="Ordered member image/frame IDs")
    detection_ids: List[str] = Field(default_factory=list, description="Member detection IDs")
    start_at: Optional[datetime] = Field(None, description="Encounter start timestamp (UTC)")
    end_at: Optional[datetime] = Field(None, description="Encounter end timestamp (UTC)")
    grouping_rule_version: str = Field(..., description="Version of grouping algorithm used")
    review_status: str = Field(default="pending", description="Aggregate encounter review status")
    provenance: ProvenanceEnum = Field(..., description="Data provenance")

    @field_validator("start_at", "end_at", mode="after")
    @classmethod
    def validate_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        return ensure_utc(v)


class CameraContract(ContractBaseModel):
    """Camera trap hardware station record."""
    id: str = Field(..., description="Camera station ID (e.g. 'CAM-01')")
    label: str = Field(..., description="Human-readable camera label")
    timezone: str = Field(default="UTC", description="Deployment site IANA timezone")
    coordinates: Optional[Tuple[float, float]] = Field(
        None,
        description="Optional WGS84 coordinates: [longitude, latitude]. NULL if unlocated."
    )
    telemetry_status: TelemetryStatusEnum = Field(
        default=TelemetryStatusEnum.UNKNOWN,
        description="Hardware telemetry state. Image silence is NEVER treated as dead."
    )
    last_heartbeat_at: Optional[datetime] = Field(None, description="Most recent heartbeat log (UTC)")
    active_camera_days: Optional[float] = Field(None, ge=0.0, description="Documented deployment effort in days")
    provenance: ProvenanceEnum = Field(..., description="Data provenance")

    @field_validator("last_heartbeat_at", mode="after")
    @classmethod
    def validate_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        return ensure_utc(v)

    @field_validator("coordinates", mode="after")
    @classmethod
    def validate_coords(cls, v: Optional[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
        if v is not None:
            lon, lat = v
            if not (-180.0 <= lon <= 180.0):
                raise ValueError(f"Longitude must be between -180 and 180. Got: {lon}")
            if not (-90.0 <= lat <= 90.0):
                raise ValueError(f"Latitude must be between -90 and 90. Got: {lat}")
        return v


class CameraCreateRequest(ContractBaseModel):
    """Request payload for registering a camera station."""
    id: str = Field(..., min_length=1, max_length=36, description="Station identifier (e.g. 'CAM-01')")
    label: str = Field(..., min_length=1, max_length=200, description="Human-readable camera label")
    timezone: str = Field(default="UTC", description="Deployment site IANA timezone")
    coordinates: Optional[Tuple[float, float]] = Field(
        None,
        description="Optional WGS84 coordinates: [longitude, latitude]"
    )
    active_camera_days: Optional[float] = Field(None, ge=0.0, description="Deployment effort in days")
    provenance: ProvenanceEnum = Field(default=ProvenanceEnum.OBSERVED, description="Data provenance")

    @field_validator("id", "label", mode="after")
    @classmethod
    def validate_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or blank whitespace.")
        return v.strip()

    @field_validator("coordinates", mode="after")
    @classmethod
    def validate_coords(cls, v: Optional[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
        if v is not None:
            lon, lat = v
            if not (-180.0 <= lon <= 180.0):
                raise ValueError(f"Longitude must be between -180 and 180. Got: {lon}")
            if not (-90.0 <= lat <= 90.0):
                raise ValueError(f"Latitude must be between -90 and 90. Got: {lat}")
        return v


class CameraTelemetryContract(ContractBaseModel):
    """Hardware telemetry event record (F07)."""
    id: str = Field(..., description="Unique telemetry log ID")
    camera_id: str = Field(..., description="Associated camera trap ID")
    observed_at: datetime = Field(..., description="Timestamp of telemetry observation (UTC)")
    battery_level: Optional[float] = Field(None, description="Battery level (percentage 0-100 or voltage)")
    signal_strength: Optional[float] = Field(None, description="Cellular or radio signal strength")
    error_codes: List[str] = Field(default_factory=list, description="Logged hardware error codes")
    raw_payload: Optional[Dict[str, Any]] = Field(None, description="Original raw sensor payload")
    source: str = Field(default="satellite_relay", description="Telemetry reporting source")
    created_at: datetime = Field(..., description="Record creation timestamp (UTC)")
    provenance: ProvenanceEnum = Field(default=ProvenanceEnum.OBSERVED, description="Data provenance")

    @field_validator("observed_at", "created_at", mode="after")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        res = ensure_utc(v)
        assert res is not None
        return res


class TelemetryCreateRequest(ContractBaseModel):
    """Payload for submitting camera hardware telemetry (F07)."""
    observed_at: datetime = Field(..., description="Timestamp of observation in UTC")
    battery_level: Optional[float] = Field(None, ge=0.0, description="Battery level or percentage")
    signal_strength: Optional[float] = Field(None, description="Signal strength")
    error_codes: List[str] = Field(default_factory=list, description="Hardware error codes")
    raw_payload: Optional[Dict[str, Any]] = Field(None, description="Raw hardware telemetry payload")
    source: str = Field(default="satellite_relay", description="Transmission source")

    @field_validator("observed_at", mode="after")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        res = ensure_utc(v)
        assert res is not None
        return res


class MonitoringActionContract(ContractBaseModel):
    """Field intervention / maintenance action record (F11)."""
    id: str = Field(..., description="Unique action ID")
    camera_id: str = Field(..., description="Associated camera trap ID")
    action_type: str = Field(..., description="Action type: reposition, lens_clean, battery_replace, etc.")
    description: str = Field(..., description="Field intervention description")
    performed_at: datetime = Field(..., description="Timestamp action was completed (UTC)")
    baseline_start: Optional[datetime] = Field(None, description="Pre-intervention baseline window start")
    baseline_end: Optional[datetime] = Field(None, description="Pre-intervention baseline window end")
    post_start: Optional[datetime] = Field(None, description="Post-intervention observation window start")
    post_end: Optional[datetime] = Field(None, description="Post-intervention observation window end")
    source: str = Field(default="field_ranger", description="Intervention reporting source")
    created_at: datetime = Field(..., description="Record timestamp (UTC)")
    provenance: ProvenanceEnum = Field(default=ProvenanceEnum.OBSERVED, description="Data provenance")

    @field_validator("performed_at", "baseline_start", "baseline_end", "post_start", "post_end", "created_at", mode="after")
    @classmethod
    def validate_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        return ensure_utc(v)


class MonitoringActionCreateRequest(ContractBaseModel):
    """Request payload for logging a field intervention (F11)."""
    camera_id: str = Field(..., min_length=1, description="Associated camera trap station ID")
    action_type: str = Field(..., min_length=1, description="Action type (e.g. lens_clean, battery_replace, reposition)")
    description: str = Field(..., min_length=1, description="Detailed field notes")
    performed_at: datetime = Field(..., description="Timestamp intervention occurred (UTC)")
    baseline_start: Optional[datetime] = Field(None, description="Pre-intervention baseline start (UTC)")
    baseline_end: Optional[datetime] = Field(None, description="Pre-intervention baseline end (UTC)")
    post_start: Optional[datetime] = Field(None, description="Post-intervention observation start (UTC)")
    post_end: Optional[datetime] = Field(None, description="Post-intervention observation end (UTC)")
    source: str = Field(default="field_ranger", description="Reporting identity/source")

    @field_validator("camera_id", "action_type", "description", mode="after")
    @classmethod
    def validate_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or blank whitespace.")
        return v.strip()

    @field_validator("performed_at", "baseline_start", "baseline_end", "post_start", "post_end", mode="after")
    @classmethod
    def validate_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        return ensure_utc(v)

    @model_validator(mode="after")
    def validate_windows(self) -> "MonitoringActionCreateRequest":
        if self.baseline_start and self.baseline_end and self.baseline_start > self.baseline_end:
            raise ValueError("baseline_start cannot be after baseline_end.")
        if self.post_start and self.post_end and self.post_start > self.post_end:
            raise ValueError("post_start cannot be after post_end.")
        return self


class ReviewEventContract(ContractBaseModel):
    """Append-only human review event record (F20)."""
    id: str = Field(..., description="Unique review event ID")
    detection_id: str = Field(..., description="ID of detection being reviewed")
    decision: ReviewStatusEnum = Field(..., description="Reviewer decision")
    corrected_taxon_id: Optional[str] = Field(None, description="Corrected taxonomy ID if corrected")
    reason: str = Field(..., min_length=1, description="Explicit justification for decision")
    reviewer_id: str = Field(..., description="Authenticated or local demo reviewer identity")
    expected_revision: Optional[int] = Field(None, ge=1, description="Expected dataset revision prior to event")
    resulting_revision: int = Field(..., ge=1, description="Dataset revision produced by this event")
    provenance: ProvenanceEnum = Field(default=ProvenanceEnum.OBSERVED, description="Data provenance")
    created_at: datetime = Field(..., description="Timestamp of review event (UTC)")

    @field_validator("created_at", mode="after")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        res = ensure_utc(v)
        assert res is not None
        return res


class ReviewCreateRequest(ContractBaseModel):
    """Request payload for submitting a human review decision (F20)."""
    detection_id: str = Field(..., description="Stable unique detection identifier")
    decision: ReviewStatusEnum = Field(..., description="Review decision: confirmed, corrected, rejected, deferred")
    corrected_taxon_id: Optional[str] = Field(None, description="Corrected taxon ID (required if decision is corrected)")
    reason: str = Field(..., min_length=1, description="Explicit justification for decision")
    reviewer_id: str = Field(..., min_length=1, description="Reviewer identity")
    expected_revision: int = Field(..., ge=1, description="Expected dataset revision for optimistic concurrency")
    provenance: ProvenanceEnum = Field(default=ProvenanceEnum.OBSERVED, description="Data provenance")

    @field_validator("decision", mode="after")
    @classmethod
    def validate_decision(cls, v: ReviewStatusEnum) -> ReviewStatusEnum:
        if v == ReviewStatusEnum.PENDING or v == "pending":
            raise ValueError("Review decision cannot be 'pending'. Must be confirmed, corrected, rejected, or deferred.")
        return v

    @field_validator("reason", "reviewer_id", mode="after")
    @classmethod
    def validate_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or blank whitespace.")
        return v.strip()

    @model_validator(mode="after")
    def validate_correction_has_taxon(self) -> "ReviewCreateRequest":
        decision_val = self.decision.value if isinstance(self.decision, ReviewStatusEnum) else str(self.decision)
        if decision_val == "corrected":
            if not self.corrected_taxon_id or not self.corrected_taxon_id.strip():
                raise ValueError("corrected_taxon_id is required when decision is 'corrected'.")
        return self


class AnalysisResultContract(ContractBaseModel):
    """Deterministic analytical metric result (F10 / F18)."""
    id: str = Field(..., description="Analysis calculation ID")
    metric: str = Field(..., description="Metric key (e.g. 'species_encounter_count')")
    value: Any = Field(..., description="Calculated metric value (number, dict, array)")
    unit: str = Field(..., description="Unit of measurement (e.g. 'encounters', 'ratio')")
    inclusion: str = Field(default="reviewed_only", description="'reviewed_only', 'provisional', 'all'")
    evidence_refs: List[str] = Field(default_factory=list, description="Traceable IDs of supporting encounters/images")
    exclusions: List[str] = Field(default_factory=list, description="Reason for any omitted data")
    limitations: List[str] = Field(default_factory=list, description="Explicit scientific caveats")
    algorithm_version: str = Field(..., description="Version of analytical calculation")
    dataset_revision: int = Field(..., ge=1, description="Revision of dataset analyzed")
    provenance: ProvenanceEnum = Field(..., description="Data provenance")
