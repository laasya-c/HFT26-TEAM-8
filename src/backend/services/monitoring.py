"""Monitoring Improvement Feedback Service (F11).

Scientific & Architecture Responsibilities:
1. Log and persist field interventions (lens clean, battery replace, reposition, firmware).
2. Compare documented before/after uptime and visual observation quality.
3. Accounting for monitoring effort and missing data:
   - Return 'insufficient_data' whenever baseline or post-intervention observation windows are missing or lack evidence.
4. Scientific Integrity Rule:
   - NEVER claim causal improvement from before/after comparisons.
   - Observational comparisons are non-randomized and subject to ecological/weather confounders.
5. Network monitoring health summary (F07/F11).
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy.orm import Session

from contracts.schemas import ProvenanceEnum, TelemetryStatusEnum
from src.backend.config import settings
from src.backend.core.exceptions import EntityNotFoundException, ValidationException
from src.backend.models.camera import Camera, CameraTelemetry, MonitoringAction
from src.backend.models.media import ImageFrame, MediaAsset
from src.backend.services.camera import camera_service


CAUSAL_DISCLAIMER = (
    "Observational before/after comparison only. Does not establish causal intervention impact. "
    "Environmental variability, seasonal animal movements, and local weather may confound metric differences."
)


class MonitoringService:
    """Manages field monitoring actions and before/after feedback evaluation."""

    def create_action(
        self,
        db: Session,
        data: Dict[str, Any],
        created_by_user_id: Optional[str] = None,
    ) -> MonitoringAction:
        """Persists a new field monitoring / maintenance action."""
        camera_id = data.get("camera_id")
        camera_service.get_camera(db, camera_id)  # Validate camera exists

        def _to_utc(dt: Any) -> Optional[datetime]:
            if dt is None:
                return None
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt

        performed_at = _to_utc(data.get("performed_at"))
        baseline_start = _to_utc(data.get("baseline_start"))
        baseline_end = _to_utc(data.get("baseline_end"))
        post_start = _to_utc(data.get("post_start"))
        post_end = _to_utc(data.get("post_end"))

        # Semantic validation
        if baseline_start and baseline_end and baseline_start > baseline_end:
            raise ValidationException("baseline_start must be before or equal to baseline_end.")
        if post_start and post_end and post_start > post_end:
            raise ValidationException("post_start must be before or equal to post_end.")

        action = MonitoringAction(
            id=str(uuid.uuid4()),
            camera_id=camera_id,
            action_type=data.get("action_type", "").strip(),
            description=data.get("description", "").strip(),
            performed_at=performed_at,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            post_start=post_start,
            post_end=post_end,
            source=data.get("source", "field_ranger"),
            created_by_user_id=data.get("created_by_user_id") or created_by_user_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(action)
        db.commit()
        db.refresh(action)
        return action

    def get_action(self, db: Session, action_id: str) -> MonitoringAction:
        """Retrieves a monitoring action by ID or raises EntityNotFoundException."""
        action = db.query(MonitoringAction).filter(MonitoringAction.id == action_id).first()
        if not action:
            raise EntityNotFoundException("MonitoringAction", action_id)
        return action

    def list_actions(
        self,
        db: Session,
        camera_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[MonitoringAction], int]:
        """Lists historical monitoring actions, optionally filtered by camera_id."""
        query = db.query(MonitoringAction)
        if camera_id:
            query = query.filter(MonitoringAction.camera_id == camera_id)

        total = query.count()
        actions = query.order_by(MonitoringAction.performed_at.desc()).offset(offset).limit(limit).all()
        return actions, total

    def evaluate_feedback(self, db: Session, action: MonitoringAction) -> Dict[str, Any]:
        """Calculates effort-qualified before/after comparison metrics.
        
        Rules:
        - If baseline or post window is undefined -> returns status='insufficient_data'
        - If baseline or post window lacks any telemetry or imagery -> returns status='insufficient_data'
        - Always includes explicit non-causal disclaimer and declared scientific limitations.
        """
        # 1. Check for missing windows
        if not (action.baseline_start and action.baseline_end and action.post_start and action.post_end):
            return {
                "action_id": action.id,
                "camera_id": action.camera_id,
                "action_type": action.action_type,
                "status": "insufficient_data",
                "reason": "Pre-intervention baseline or post-intervention observation window is undefined.",
                "is_causal": False,
                "causal_claim_disclaimer": CAUSAL_DISCLAIMER,
                "limitations": [
                    "Cannot evaluate intervention impact without both baseline and post-intervention time bounds."
                ],
            }

        # 2. Window Durations
        baseline_duration_days = max((action.baseline_end - action.baseline_start).total_seconds() / 86400.0, 0.001)
        post_duration_days = max((action.post_end - action.post_start).total_seconds() / 86400.0, 0.001)

        # 3. Query Telemetry in both windows
        baseline_telemetry = (
            db.query(CameraTelemetry)
            .filter(
                CameraTelemetry.camera_id == action.camera_id,
                CameraTelemetry.observed_at >= action.baseline_start,
                CameraTelemetry.observed_at <= action.baseline_end,
            )
            .all()
        )
        post_telemetry = (
            db.query(CameraTelemetry)
            .filter(
                CameraTelemetry.camera_id == action.camera_id,
                CameraTelemetry.observed_at >= action.post_start,
                CameraTelemetry.observed_at <= action.post_end,
            )
            .all()
        )

        # 4. Query Media / ImageFrames in both windows
        baseline_frames = (
            db.query(ImageFrame)
            .join(MediaAsset, ImageFrame.source_media_id == MediaAsset.id)
            .filter(
                MediaAsset.camera_id == action.camera_id,
                ImageFrame.created_at >= action.baseline_start,
                ImageFrame.created_at <= action.baseline_end,
            )
            .all()
        )
        post_frames = (
            db.query(ImageFrame)
            .join(MediaAsset, ImageFrame.source_media_id == MediaAsset.id)
            .filter(
                MediaAsset.camera_id == action.camera_id,
                ImageFrame.created_at >= action.post_start,
                ImageFrame.created_at <= action.post_end,
            )
            .all()
        )

        # Check evidence sufficiency
        baseline_has_evidence = len(baseline_telemetry) > 0 or len(baseline_frames) > 0
        post_has_evidence = len(post_telemetry) > 0 or len(post_frames) > 0

        if not (baseline_has_evidence and post_has_evidence):
            return {
                "action_id": action.id,
                "camera_id": action.camera_id,
                "action_type": action.action_type,
                "status": "insufficient_data",
                "reason": "Insufficient telemetry or media evidence recorded in baseline or post-intervention window.",
                "is_causal": False,
                "causal_claim_disclaimer": CAUSAL_DISCLAIMER,
                "limitations": [
                    "Zero telemetry and zero observation media recorded during the evaluation window.",
                    "Active camera effort could not be verified."
                ],
            }

        # 5. Calculate Metrics
        def _compute_metrics(telemetry_list: List[CameraTelemetry], frame_list: List[ImageFrame], duration_days: float) -> Dict[str, Any]:
            heartbeat_count = len(telemetry_list)
            heartbeat_rate_per_day = round(heartbeat_count / duration_days, 2)
            batteries = [t.battery_level for t in telemetry_list if t.battery_level is not None]
            avg_battery = round(sum(batteries) / len(batteries), 2) if batteries else None
            
            image_count = len(frame_list)
            image_rate_per_day = round(image_count / duration_days, 2)
            flagged_images = sum(1 for f in frame_list if f.quality_flags and len(f.quality_flags) > 0)
            degradation_ratio = round(flagged_images / image_count, 3) if image_count > 0 else 0.0

            return {
                "window_days": round(duration_days, 2),
                "heartbeat_count": heartbeat_count,
                "heartbeat_rate_per_day": heartbeat_rate_per_day,
                "avg_battery_level": avg_battery,
                "image_count": image_count,
                "image_rate_per_day": image_rate_per_day,
                "flagged_degraded_images": flagged_images,
                "degradation_ratio": degradation_ratio,
            }

        baseline_metrics = _compute_metrics(baseline_telemetry, baseline_frames, baseline_duration_days)
        post_metrics = _compute_metrics(post_telemetry, post_frames, post_duration_days)

        # 6. Compute Observed Deltas
        delta_battery = (
            round(post_metrics["avg_battery_level"] - baseline_metrics["avg_battery_level"], 2)
            if post_metrics["avg_battery_level"] is not None and baseline_metrics["avg_battery_level"] is not None
            else None
        )
        delta_heartbeat_rate = round(post_metrics["heartbeat_rate_per_day"] - baseline_metrics["heartbeat_rate_per_day"], 2)
        delta_image_rate = round(post_metrics["image_rate_per_day"] - baseline_metrics["image_rate_per_day"], 2)
        delta_degradation_ratio = round(post_metrics["degradation_ratio"] - baseline_metrics["degradation_ratio"], 3)

        return {
            "action_id": action.id,
            "camera_id": action.camera_id,
            "action_type": action.action_type,
            "status": "evaluated",
            "is_causal": False,
            "causal_claim_disclaimer": CAUSAL_DISCLAIMER,
            "baseline_metrics": baseline_metrics,
            "post_metrics": post_metrics,
            "observed_changes": {
                "delta_avg_battery": delta_battery,
                "delta_heartbeat_rate_per_day": delta_heartbeat_rate,
                "delta_image_rate_per_day": delta_image_rate,
                "delta_degradation_ratio": delta_degradation_ratio,
            },
            "limitations": [
                "Observational study only; does not isolate natural environmental variations from intervention.",
                "Non-randomized intervention timing.",
                "Wildlife encounter rates depend on seasonal animal presence, not merely camera functioning."
            ],
        }

    def get_network_monitoring_summary(self, db: Session) -> Dict[str, Any]:
        """Provides holistic network monitoring statistics across all camera stations."""
        now_utc = datetime.now(timezone.utc)
        cameras = db.query(Camera).all()

        status_counts = {
            TelemetryStatusEnum.REPORTING.value: 0,
            TelemetryStatusEnum.STALE.value: 0,
            TelemetryStatusEnum.UNKNOWN.value: 0,
        }

        for cam in cameras:
            eval_status = camera_service.compute_telemetry_status(cam.last_heartbeat_at, now_utc)
            status_counts[eval_status] = status_counts.get(eval_status, 0) + 1

        total_telemetry = db.query(CameraTelemetry).count()
        total_actions = db.query(MonitoringAction).count()

        recent_actions = (
            db.query(MonitoringAction)
            .order_by(MonitoringAction.performed_at.desc())
            .limit(5)
            .all()
        )

        return {
            "total_cameras": len(cameras),
            "telemetry_health_breakdown": status_counts,
            "total_telemetry_logs": total_telemetry,
            "total_monitoring_actions": total_actions,
            "freshness_threshold_hours": settings.CAMERA_TELEMETRY_FRESHNESS_HOURS,
            "recent_actions": [
                {
                    "id": a.id,
                    "camera_id": a.camera_id,
                    "action_type": a.action_type,
                    "description": a.description,
                    "performed_at": a.performed_at.isoformat(),
                    "source": a.source,
                }
                for a in recent_actions
            ],
        }


monitoring_service = MonitoringService()
