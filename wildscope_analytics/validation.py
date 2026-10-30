"""
WILDSCOPE Decision Intelligence & Analytics Module
Validation Engine - Phase 1

Implements comprehensive schema and relational validation for snapshots and requests.
Provides structured error reporting with stable error codes and exact field paths.
"""

from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Any

from pydantic import ValidationError

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
)
from wildscope_analytics.contracts.enums import (
    ReviewDecision,
    ValidationErrorCode,
)
from wildscope_analytics.contracts.requests import AnalysisRequest, ReviewRankingRequest
from wildscope_analytics.contracts.responses import ValidationErrorDetail
from wildscope_analytics.contracts.snapshot import (
    CURRENT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    Snapshot,
)


class ValidationReport(BaseContractModel):
    """Structured report returned after validating a snapshot or request payload."""
    is_valid: bool
    schema_version: str | None = None
    dataset_revision: int | None = None
    errors: list[ValidationErrorDetail] = []
    warnings: list[str] = []
    counts: dict[str, int] = {}

    def add_error(
        self,
        code: ValidationErrorCode | str,
        message: str,
        field_path: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> None:
        self.errors.append(
            ValidationErrorDetail(
                code=code,
                message=message,
                field_path=field_path,
                entity_type=entity_type,
                entity_id=entity_id,
            )
        )
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


def _pydantic_error_to_validation_detail(err: dict[str, Any]) -> ValidationErrorDetail:
    """Translates a raw Pydantic v2 error dict into a structured ValidationErrorDetail."""
    loc = err.get("loc", ())
    field_path = ".".join(str(item) for item in loc) or "$"
    msg = err.get("msg", "Validation error")
    err_type = err.get("type", "")

    # Map Pydantic error type to stable code
    if "timezone" in msg.lower():
        code = ValidationErrorCode.MISSING_TIMEZONE
    elif "latitude" in field_path.lower() or "longitude" in field_path.lower() or "coordinate" in msg.lower():
        code = ValidationErrorCode.INVALID_COORDINATES
    elif "confidence" in field_path.lower() or "score" in field_path.lower():
        code = ValidationErrorCode.INVALID_CONFIDENCE
    elif "bbox" in field_path.lower() or "bounds" in msg.lower():
        code = ValidationErrorCode.INVALID_BBOX
    elif "decision" in field_path.lower() or "corrected_taxon_id" in field_path.lower():
        code = ValidationErrorCode.INVALID_REVIEW_PAYLOAD
    elif "schema_version" in field_path.lower():
        code = ValidationErrorCode.UNSUPPORTED_SCHEMA_VERSION
    elif "interval" in msg.lower() or "earlier" in msg.lower() or "later" in msg.lower() or "start_time" in field_path:
        code = ValidationErrorCode.TEMPORAL_ORDER_VIOLATION
    elif "overlapping" in msg.lower():
        code = ValidationErrorCode.OVERLAPPING_EFFORT
    else:
        code = ValidationErrorCode.SCHEMA_VIOLATION

    return ValidationErrorDetail(
        code=code,
        message=msg,
        field_path=field_path,
    )


def validate_snapshot_data(snapshot: Snapshot) -> ValidationReport:
    """
    Performs deep cross-entity referential integrity, uniqueness,
    and business rule validation on an instantiated Snapshot model.
    """
    report = ValidationReport(
        is_valid=True,
        schema_version=snapshot.metadata.schema_version,
        dataset_revision=snapshot.metadata.dataset_revision,
        counts={
            "cameras": len(snapshot.cameras),
            "media_assets": len(snapshot.media_assets),
            "observations": len(snapshot.observations),
            "prediction_runs": len(snapshot.prediction_runs),
            "detections": len(snapshot.detections),
            "encounters": len(snapshot.encounters),
            "reviews": len(snapshot.reviews),
            "monitoring_efforts": len(snapshot.monitoring_efforts),
        },
    )

    # 1. Supported Schema Version Check
    if snapshot.metadata.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        report.add_error(
            code=ValidationErrorCode.UNSUPPORTED_SCHEMA_VERSION,
            message=(
                f"Schema version '{snapshot.metadata.schema_version}' is unsupported. "
                f"Supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            ),
            field_path="metadata.schema_version",
            entity_type="SnapshotMetadata",
        )

    # 2. Entity Uniqueness Checks
    camera_map: dict[str, Camera] = {}
    for idx, cam in enumerate(snapshot.cameras):
        if cam.id in camera_map:
            report.add_error(
                code=ValidationErrorCode.DUPLICATE_ID,
                message=f"Duplicate camera ID: '{cam.id}'",
                field_path=f"cameras[{idx}].id",
                entity_type="Camera",
                entity_id=cam.id,
            )
        else:
            camera_map[cam.id] = cam

    media_map: dict[str, MediaAsset] = {}
    for idx, med in enumerate(snapshot.media_assets):
        if med.id in media_map:
            report.add_error(
                code=ValidationErrorCode.DUPLICATE_ID,
                message=f"Duplicate media asset ID: '{med.id}'",
                field_path=f"media_assets[{idx}].id",
                entity_type="MediaAsset",
                entity_id=med.id,
            )
        else:
            media_map[med.id] = med

    run_map: dict[str, PredictionRun] = {}
    for idx, run in enumerate(snapshot.prediction_runs):
        if run.id in run_map:
            report.add_error(
                code=ValidationErrorCode.DUPLICATE_ID,
                message=f"Duplicate prediction run ID: '{run.id}'",
                field_path=f"prediction_runs[{idx}].id",
                entity_type="PredictionRun",
                entity_id=run.id,
            )
        else:
            run_map[run.id] = run

    obs_map: dict[str, Observation] = {}
    for idx, obs in enumerate(snapshot.observations):
        if obs.id in obs_map:
            report.add_error(
                code=ValidationErrorCode.DUPLICATE_ID,
                message=f"Duplicate observation ID: '{obs.id}'",
                field_path=f"observations[{idx}].id",
                entity_type="Observation",
                entity_id=obs.id,
            )
        else:
            obs_map[obs.id] = obs

    det_map: dict[str, Detection] = {}
    for idx, det in enumerate(snapshot.detections):
        if det.id in det_map:
            report.add_error(
                code=ValidationErrorCode.DUPLICATE_ID,
                message=f"Duplicate detection ID: '{det.id}'",
                field_path=f"detections[{idx}].id",
                entity_type="Detection",
                entity_id=det.id,
            )
        else:
            det_map[det.id] = det

    enc_map: dict[str, Encounter] = {}
    for idx, enc in enumerate(snapshot.encounters):
        if enc.id in enc_map:
            report.add_error(
                code=ValidationErrorCode.DUPLICATE_ID,
                message=f"Duplicate encounter ID: '{enc.id}'",
                field_path=f"encounters[{idx}].id",
                entity_type="Encounter",
                entity_id=enc.id,
            )
        else:
            enc_map[enc.id] = enc

    rev_map: dict[str, ReviewEvent] = {}
    for idx, rev in enumerate(snapshot.reviews):
        if rev.id in rev_map:
            report.add_error(
                code=ValidationErrorCode.DUPLICATE_ID,
                message=f"Duplicate review ID: '{rev.id}'",
                field_path=f"reviews[{idx}].id",
                entity_type="ReviewEvent",
                entity_id=rev.id,
            )
        else:
            rev_map[rev.id] = rev

    effort_map: dict[str, MonitoringEffort] = {}
    for idx, eff in enumerate(snapshot.monitoring_efforts):
        if eff.id in effort_map:
            report.add_error(
                code=ValidationErrorCode.DUPLICATE_ID,
                message=f"Duplicate monitoring effort ID: '{eff.id}'",
                field_path=f"monitoring_efforts[{idx}].id",
                entity_type="MonitoringEffort",
                entity_id=eff.id,
            )
        else:
            effort_map[eff.id] = eff

    # Spatial zones uniqueness
    if snapshot.spatial_context and snapshot.spatial_context.zones:
        zone_ids: set[str] = set()
        for idx, zone in enumerate(snapshot.spatial_context.zones):
            if zone.id in zone_ids:
                report.add_error(
                    code=ValidationErrorCode.DUPLICATE_ID,
                    message=f"Duplicate spatial zone ID: '{zone.id}'",
                    field_path=f"spatial_context.zones[{idx}].id",
                    entity_type="SpatialZone",
                    entity_id=zone.id,
                )
            else:
                zone_ids.add(zone.id)

    # 3. Referential Integrity Checks

    # MediaAsset -> Camera
    for idx, med in enumerate(snapshot.media_assets):
        if med.camera_id not in camera_map:
            report.add_error(
                code=ValidationErrorCode.BROKEN_REFERENCE,
                message=f"MediaAsset '{med.id}' references unknown camera '{med.camera_id}'.",
                field_path=f"media_assets[{idx}].camera_id",
                entity_type="MediaAsset",
                entity_id=med.id,
            )

    # Observation -> Camera and MediaAsset
    for idx, obs in enumerate(snapshot.observations):
        if obs.camera_id not in camera_map:
            report.add_error(
                code=ValidationErrorCode.BROKEN_REFERENCE,
                message=f"Observation '{obs.id}' references unknown camera '{obs.camera_id}'.",
                field_path=f"observations[{idx}].camera_id",
                entity_type="Observation",
                entity_id=obs.id,
            )
        if snapshot.media_assets and obs.source_media_id not in media_map:
            report.add_error(
                code=ValidationErrorCode.BROKEN_REFERENCE,
                message=f"Observation '{obs.id}' references unknown source media '{obs.source_media_id}'.",
                field_path=f"observations[{idx}].source_media_id",
                entity_type="Observation",
                entity_id=obs.id,
            )
        # Check observation.detection_ids
        for det_idx, det_id in enumerate(obs.detection_ids):
            if det_id not in det_map:
                report.add_error(
                    code=ValidationErrorCode.BROKEN_REFERENCE,
                    message=f"Observation '{obs.id}' links unknown detection '{det_id}'.",
                    field_path=f"observations[{idx}].detection_ids[{det_idx}]",
                    entity_type="Observation",
                    entity_id=obs.id,
                )

    # Detection -> Observation and PredictionRun
    for idx, det in enumerate(snapshot.detections):
        if det.observation_id not in obs_map:
            report.add_error(
                code=ValidationErrorCode.BROKEN_REFERENCE,
                message=f"Detection '{det.id}' references unknown observation '{det.observation_id}'.",
                field_path=f"detections[{idx}].observation_id",
                entity_type="Detection",
                entity_id=det.id,
            )
        if det.run_id and snapshot.prediction_runs and det.run_id not in run_map:
            report.add_error(
                code=ValidationErrorCode.BROKEN_REFERENCE,
                message=f"Detection '{det.id}' references unknown prediction run '{det.run_id}'.",
                field_path=f"detections[{idx}].run_id",
                entity_type="Detection",
                entity_id=det.id,
            )

    # Encounter -> Camera and Members
    for idx, enc in enumerate(snapshot.encounters):
        if enc.camera_id not in camera_map:
            report.add_error(
                code=ValidationErrorCode.BROKEN_REFERENCE,
                message=f"Encounter '{enc.id}' references unknown camera '{enc.camera_id}'.",
                field_path=f"encounters[{idx}].camera_id",
                entity_type="Encounter",
                entity_id=enc.id,
            )
        # Member observation checks
        for m_idx, obs_id in enumerate(enc.member_observation_ids):
            if obs_id not in obs_map:
                report.add_error(
                    code=ValidationErrorCode.BROKEN_REFERENCE,
                    message=f"Encounter '{enc.id}' contains unknown member observation '{obs_id}'.",
                    field_path=f"encounters[{idx}].member_observation_ids[{m_idx}]",
                    entity_type="Encounter",
                    entity_id=enc.id,
                )
            else:
                member_obs = obs_map[obs_id]
                if member_obs.camera_id != enc.camera_id:
                    report.add_error(
                        code=ValidationErrorCode.ENCOUNTER_MEMBERSHIP_VIOLATION,
                        message=(
                            f"Encounter '{enc.id}' on camera '{enc.camera_id}' contains member "
                            f"observation '{obs_id}' belonging to camera '{member_obs.camera_id}'."
                        ),
                        field_path=f"encounters[{idx}].member_observation_ids[{m_idx}]",
                        entity_type="Encounter",
                        entity_id=enc.id,
                    )
        # Member detection checks
        for d_idx, det_id in enumerate(enc.member_detection_ids):
            if det_id not in det_map:
                report.add_error(
                    code=ValidationErrorCode.BROKEN_REFERENCE,
                    message=f"Encounter '{enc.id}' contains unknown member detection '{det_id}'.",
                    field_path=f"encounters[{idx}].member_detection_ids[{d_idx}]",
                    entity_type="Encounter",
                    entity_id=enc.id,
                )
            else:
                member_det = det_map[det_id]
                parent_obs = obs_map.get(member_det.observation_id)
                if parent_obs and parent_obs.camera_id != enc.camera_id:
                    report.add_error(
                        code=ValidationErrorCode.ENCOUNTER_MEMBERSHIP_VIOLATION,
                        message=(
                            f"Encounter '{enc.id}' on camera '{enc.camera_id}' contains member "
                            f"detection '{det_id}' from observation on camera '{parent_obs.camera_id}'."
                        ),
                        field_path=f"encounters[{idx}].member_detection_ids[{d_idx}]",
                        entity_type="Encounter",
                        entity_id=enc.id,
                    )

    # ReviewEvent -> Target Detection
    for idx, rev in enumerate(snapshot.reviews):
        # Target must be a known detection (or encounter)
        if rev.target_id not in det_map and rev.target_id not in enc_map:
            report.add_error(
                code=ValidationErrorCode.BROKEN_REFERENCE,
                message=f"Review '{rev.id}' references unknown target detection/encounter '{rev.target_id}'.",
                field_path=f"reviews[{idx}].target_id",
                entity_type="ReviewEvent",
                entity_id=rev.id,
            )

    # MonitoringEffort -> Camera and Cross-record Interval Overlap
    efforts_by_camera: dict[str, list[MonitoringEffort]] = {}
    for idx, eff in enumerate(snapshot.monitoring_efforts):
        if eff.camera_id not in camera_map:
            report.add_error(
                code=ValidationErrorCode.BROKEN_REFERENCE,
                message=f"MonitoringEffort '{eff.id}' references unknown camera '{eff.camera_id}'.",
                field_path=f"monitoring_efforts[{idx}].camera_id",
                entity_type="MonitoringEffort",
                entity_id=eff.id,
            )
        efforts_by_camera.setdefault(eff.camera_id, []).append(eff)

    for cam_id, eff_list in efforts_by_camera.items():
        if len(eff_list) > 1:
            all_intervals = []
            for eff in eff_list:
                for interval in eff.active_intervals:
                    all_intervals.append((interval.start, interval.end, eff.id))
            all_intervals.sort(key=lambda x: x[0])
            for i in range(len(all_intervals) - 1):
                cur = all_intervals[i]
                nxt = all_intervals[i + 1]
                if cur[1] > nxt[0]:
                    report.add_error(
                        code=ValidationErrorCode.OVERLAPPING_EFFORT,
                        message=(
                            f"Overlapping effort intervals for camera '{cam_id}' between "
                            f"efforts '{cur[2]}' and '{nxt[2]}': [{cur[0].isoformat()} - {cur[1].isoformat()}] "
                            f"overlaps with [{nxt[0].isoformat()} - {nxt[1].isoformat()}]."
                        ),
                        field_path=f"monitoring_efforts[camera_id={cam_id}]",
                        entity_type="MonitoringEffort",
                        entity_id=cur[2],
                    )

    # 4. Optional Data Advisory Warnings (Distinguish corrupt from missing optional)
    for cam in snapshot.cameras:
        if cam.latitude is None or cam.longitude is None:
            report.add_warning(
                f"Camera '{cam.id}' lacks GPS coordinates; geographical spatial mapping will be unavailable."
            )
        if cam.timezone is None:
            report.add_warning(
                f"Camera '{cam.id}' has no declared timezone; diurnal analysis will require request timezone."
            )

    for obs in snapshot.observations:
        if obs.captured_at is None:
            report.add_warning(
                f"Observation '{obs.id}' has no timezone-aware captured_at timestamp; "
                "time-series analysis will exclude this record."
            )

    if not snapshot.monitoring_efforts:
        report.add_warning(
            "No monitoring effort records provided; effort-normalized rate comparisons will be unavailable."
        )

    if not snapshot.spatial_context:
        report.add_warning(
            "No spatial context provided; virtual geofencing and corridor overlay checks will be unavailable."
        )

    return report


def load_and_validate_snapshot(
    data: str | bytes | dict[str, Any] | Path | Snapshot,
) -> tuple[Snapshot | None, ValidationReport]:
    """
    Public entry point: loads and validates a snapshot payload.
    Accepts raw JSON string/bytes, dictionary, Path, or instantiated Snapshot.
    Returns (snapshot, report). If validation fails, snapshot is None if parsing failed,
    or the parsed snapshot alongside the populated error report.
    """
    if isinstance(data, Path):
        with open(data, "r", encoding="utf-8") as f:
            raw_dict = json.load(f)
    elif isinstance(data, (str, bytes)):
        try:
            raw_dict = json.loads(data)
        except Exception as e:
            rep = ValidationReport(is_valid=False)
            rep.add_error(
                code=ValidationErrorCode.SCHEMA_VIOLATION,
                message=f"Invalid JSON syntax: {str(e)}",
                field_path="$",
            )
            return None, rep
    elif isinstance(data, dict):
        raw_dict = data
    elif isinstance(data, Snapshot):
        rep = validate_snapshot_data(data)
        return (data if rep.is_valid else data), rep
    else:
        rep = ValidationReport(is_valid=False)
        rep.add_error(
            code=ValidationErrorCode.SCHEMA_VIOLATION,
            message=f"Unsupported input type: {type(data)}",
            field_path="$",
        )
        return None, rep

    # Attempt Pydantic v2 model instantiation
    try:
        snapshot = Snapshot.model_validate(raw_dict)
    except ValidationError as pe:
        rep = ValidationReport(is_valid=False)
        for err in pe.errors():
            rep.errors.append(_pydantic_error_to_validation_detail(err))
        return None, rep

    # Run deep cross-entity validation
    report = validate_snapshot_data(snapshot)
    return snapshot, report


def validate_analysis_request(
    data: str | bytes | dict[str, Any] | AnalysisRequest,
) -> tuple[AnalysisRequest | None, ValidationReport]:
    """
    Validates an AnalysisRequest payload.
    Enforces valid operations, supported metrics, and temporal consistency.
    """
    if isinstance(data, (str, bytes)):
        try:
            raw_dict = json.loads(data)
        except Exception as e:
            rep = ValidationReport(is_valid=False)
            rep.add_error(
                code=ValidationErrorCode.SCHEMA_VIOLATION,
                message=f"Invalid JSON syntax: {str(e)}",
                field_path="$",
            )
            return None, rep
    elif isinstance(data, dict):
        raw_dict = data
    elif isinstance(data, AnalysisRequest):
        rep = ValidationReport(is_valid=True)
        return data, rep
    else:
        rep = ValidationReport(is_valid=False)
        rep.add_error(
            code=ValidationErrorCode.SCHEMA_VIOLATION,
            message=f"Unsupported input type: {type(data)}",
            field_path="$",
        )
        return None, rep

    try:
        req = AnalysisRequest.model_validate(raw_dict)
        return req, ValidationReport(is_valid=True)
    except ValidationError as pe:
        rep = ValidationReport(is_valid=False)
        for err in pe.errors():
            rep.errors.append(_pydantic_error_to_validation_detail(err))
        return None, rep


def validate_review_ranking_request(
    data: str | bytes | dict[str, Any] | ReviewRankingRequest,
) -> tuple[ReviewRankingRequest | None, ValidationReport]:
    """
    Validates a ReviewRankingRequest payload.
    """
    if isinstance(data, (str, bytes)):
        try:
            raw_dict = json.loads(data)
        except Exception as e:
            rep = ValidationReport(is_valid=False)
            rep.add_error(
                code=ValidationErrorCode.SCHEMA_VIOLATION,
                message=f"Invalid JSON syntax: {str(e)}",
                field_path="$",
            )
            return None, rep
    elif isinstance(data, dict):
        raw_dict = data
    elif isinstance(data, ReviewRankingRequest):
        rep = ValidationReport(is_valid=True)
        return data, rep
    else:
        rep = ValidationReport(is_valid=False)
        rep.add_error(
            code=ValidationErrorCode.SCHEMA_VIOLATION,
            message=f"Unsupported input type: {type(data)}",
            field_path="$",
        )
        return None, rep

    try:
        req = ReviewRankingRequest.model_validate(raw_dict)
        return req, ValidationReport(is_valid=True)
    except ValidationError as pe:
        rep = ValidationReport(is_valid=False)
        for err in pe.errors():
            rep.errors.append(_pydantic_error_to_validation_detail(err))
        return None, rep
