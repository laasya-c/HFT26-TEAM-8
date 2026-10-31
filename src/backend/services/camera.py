"""Camera Trap & Telemetry Service (F07).

Scientific & Architecture Responsibilities:
1. Hardware telemetry state tracking (reporting, stale, unknown).
2. Freshness calculation using configurable threshold (default 24 hours).
3. Decoupling hardware health from observation image silence.
   (Image silence alone NEVER marks a camera trap as dead/failed).
4. Persist and expose camera station metadata, GPS coordinates, and deployment effort.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from contracts.schemas import ProvenanceEnum, TelemetryStatusEnum
from src.backend.config import settings
from src.backend.core.exceptions import EntityNotFoundException, ValidationException
from src.backend.models.camera import Camera, CameraTelemetry
from src.backend.models.media import ImageFrame, MediaAsset


class CameraService:
    """Manages camera stations, hardware telemetry ingestion, and freshness calculation."""

    def compute_telemetry_status(
        self,
        last_heartbeat_at: Optional[datetime],
        now_utc: Optional[datetime] = None,
        freshness_hours: Optional[float] = None,
    ) -> str:
        """Determines telemetry status based on heartbeat timestamp.
        
        Rules:
        - If no telemetry heartbeat was ever received -> 'unknown'
        - If now - last_heartbeat <= freshness_hours -> 'reporting'
        - If now - last_heartbeat > freshness_hours -> 'stale'
        - Image silence is NEVER treated as camera failure.
        """
        if last_heartbeat_at is None:
            return TelemetryStatusEnum.UNKNOWN.value

        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        if last_heartbeat_at.tzinfo is None:
            last_heartbeat_at = last_heartbeat_at.replace(tzinfo=timezone.utc)

        threshold = freshness_hours if freshness_hours is not None else settings.CAMERA_TELEMETRY_FRESHNESS_HOURS
        delta_seconds = (now_utc - last_heartbeat_at).total_seconds()

        if delta_seconds <= threshold * 3600.0:
            return TelemetryStatusEnum.REPORTING.value
        return TelemetryStatusEnum.STALE.value

    def get_camera(self, db: Session, camera_id: str) -> Camera:
        """Retrieves a camera record or raises EntityNotFoundException."""
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if not camera:
            raise EntityNotFoundException("Camera", camera_id)
        return camera

    def list_cameras(
        self,
        db: Session,
        telemetry_status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Lists cameras with database-level pagination and read-only telemetry freshness calculation."""
        now_utc = datetime.now(timezone.utc)
        freshness_threshold = settings.CAMERA_TELEMETRY_FRESHNESS_HOURS
        cutoff = now_utc - timedelta(hours=freshness_threshold)

        query = db.query(Camera)

        if telemetry_status:
            status_lower = telemetry_status.lower()
            if status_lower == TelemetryStatusEnum.UNKNOWN.value:
                query = query.filter(Camera.last_heartbeat_at.is_(None))
            elif status_lower == TelemetryStatusEnum.REPORTING.value:
                query = query.filter(
                    Camera.last_heartbeat_at.isnot(None),
                    Camera.last_heartbeat_at >= cutoff,
                )
            elif status_lower == TelemetryStatusEnum.STALE.value:
                query = query.filter(
                    Camera.last_heartbeat_at.isnot(None),
                    Camera.last_heartbeat_at < cutoff,
                )
            else:
                query = query.filter(Camera.id == "__no_matching_status__")

        total = query.count()
        cameras = query.order_by(Camera.created_at.desc()).offset(offset).limit(limit).all()

        items = []
        for cam in cameras:
            evaluated_status = self.compute_telemetry_status(cam.last_heartbeat_at, now_utc)
            coords = [cam.longitude, cam.latitude] if cam.latitude is not None and cam.longitude is not None else None
            items.append({
                "id": cam.id,
                "label": cam.label,
                "timezone": cam.timezone,
                "coordinates": coords,
                "telemetry_status": evaluated_status,
                "last_heartbeat_at": cam.last_heartbeat_at.isoformat() if cam.last_heartbeat_at else None,
                "active_camera_days": cam.active_camera_days,
                "provenance": cam.provenance,
                "created_at": cam.created_at.isoformat() if cam.created_at else None,
            })

        return items, total

    def create_camera(self, db: Session, camera_data: Dict[str, Any]) -> Camera:
        """Registers a new camera trap station."""
        cam_id = camera_data.get("id")
        existing = db.query(Camera).filter(Camera.id == cam_id).first()
        if existing:
            raise ValidationException(f"Camera with ID '{cam_id}' already exists.")

        coords = camera_data.get("coordinates")
        lon, lat = (coords[0], coords[1]) if coords else (None, None)

        camera = Camera(
            id=cam_id,
            label=camera_data.get("label"),
            timezone=camera_data.get("timezone", "UTC"),
            latitude=lat,
            longitude=lon,
            telemetry_status=TelemetryStatusEnum.UNKNOWN.value,
            last_heartbeat_at=None,
            active_camera_days=camera_data.get("active_camera_days"),
            provenance=camera_data.get("provenance", ProvenanceEnum.OBSERVED.value),
            created_at=datetime.now(timezone.utc),
        )
        db.add(camera)
        db.commit()
        db.refresh(camera)
        return camera

    def submit_telemetry(
        self,
        db: Session,
        camera_id: str,
        payload: Dict[str, Any],
    ) -> CameraTelemetry:
        """Appends a hardware telemetry log and updates camera heartbeat state."""
        camera = self.get_camera(db, camera_id)

        observed_at = payload.get("observed_at")
        if isinstance(observed_at, str):
            observed_at = datetime.fromisoformat(observed_at)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

        log = CameraTelemetry(
            id=str(uuid.uuid4()),
            camera_id=camera.id,
            observed_at=observed_at,
            battery_level=payload.get("battery_level"),
            signal_strength=payload.get("signal_strength"),
            error_codes=payload.get("error_codes") or [],
            raw_payload=payload.get("raw_payload"),
            source=payload.get("source", "satellite_relay"),
            created_at=datetime.now(timezone.utc),
        )
        db.add(log)

        # Update camera heartbeat if this telemetry is the latest observation
        if camera.last_heartbeat_at is None or observed_at >= camera.last_heartbeat_at:
            camera.last_heartbeat_at = observed_at
            camera.telemetry_status = self.compute_telemetry_status(camera.last_heartbeat_at)
            db.add(camera)

        db.commit()
        db.refresh(log)
        return log

    def get_database_dialect(self, db: Session) -> str:
        """Determines the active SQL dialect name of the database connection."""
        try:
            bind = db.get_bind()
            return bind.dialect.name if bind and hasattr(bind, "dialect") else ""
        except Exception:
            return ""

    def get_camera_details(self, db: Session, camera_id: str) -> Dict[str, Any]:
        """Retrieves comprehensive camera diagnostics including telemetry and visual quality."""
        camera = self.get_camera(db, camera_id)
        now_utc = datetime.now(timezone.utc)
        evaluated_status = self.compute_telemetry_status(camera.last_heartbeat_at, now_utc)

        # 1. Latest Telemetry Log
        latest_telemetry = (
            db.query(CameraTelemetry)
            .filter(CameraTelemetry.camera_id == camera.id)
            .order_by(CameraTelemetry.observed_at.desc())
            .first()
        )

        # 2. Observation Quality History (Decoupled from hardware telemetry)
        image_count_query = (
            db.query(func.count(ImageFrame.id))
            .join(MediaAsset, ImageFrame.source_media_id == MediaAsset.id)
            .filter(MediaAsset.camera_id == camera.id)
        )
        total_images = image_count_query.scalar() or 0
        quality_flags_count: Dict[str, int] = {}

        if total_images > 0:
            dialect_name = self.get_database_dialect(db)

            aggregated = False
            if dialect_name == "sqlite":
                try:
                    stmt = text("""
                        SELECT j.value AS flag, COUNT(*) AS cnt
                        FROM image_frames f
                        JOIN media_assets m ON f.source_media_id = m.id
                        CROSS JOIN json_each(
                            CASE 
                                WHEN f.quality_flags IS NOT NULL AND json_valid(f.quality_flags) = 1 
                                THEN f.quality_flags 
                                ELSE '[]' 
                            END
                        ) j
                        WHERE m.camera_id = :camera_id
                        GROUP BY j.value
                    """)
                    rows = db.execute(stmt, {"camera_id": camera.id}).fetchall()
                    for flag_val, count_val in rows:
                        if flag_val:
                            quality_flags_count[str(flag_val)] = int(count_val)
                    aggregated = True
                except Exception:
                    aggregated = False

            elif dialect_name in ("postgresql", "postgres"):
                try:
                    stmt = text("""
                        SELECT j AS flag, COUNT(*) AS cnt
                        FROM image_frames f
                        JOIN media_assets m ON f.source_media_id = m.id
                        CROSS JOIN jsonb_array_elements_text(
                            CASE 
                                WHEN jsonb_typeof(to_jsonb(f.quality_flags)) = 'array' 
                                THEN to_jsonb(f.quality_flags) 
                                ELSE '[]'::jsonb 
                            END
                        ) j
                        WHERE m.camera_id = :camera_id
                        GROUP BY j
                    """)
                    rows = db.execute(stmt, {"camera_id": camera.id}).fetchall()
                    for flag_val, count_val in rows:
                        if flag_val:
                            quality_flags_count[str(flag_val)] = int(count_val)
                    aggregated = True
                except Exception:
                    aggregated = False

            if not aggregated:
                # Column-only projection: avoids instantiating full ORM models into memory
                flag_rows = (
                    db.query(ImageFrame.quality_flags)
                    .join(MediaAsset, ImageFrame.source_media_id == MediaAsset.id)
                    .filter(MediaAsset.camera_id == camera.id)
                    .all()
                )
                for (flags,) in flag_rows:
                    if flags and isinstance(flags, (list, tuple)):
                        for flag in flags:
                            quality_flags_count[str(flag)] = quality_flags_count.get(str(flag), 0) + 1

        coords = [camera.longitude, camera.latitude] if camera.latitude is not None and camera.longitude is not None else None

        return {
            "id": camera.id,
            "label": camera.label,
            "timezone": camera.timezone,
            "coordinates": coords,
            "telemetry_status": evaluated_status,
            "last_heartbeat_at": camera.last_heartbeat_at.isoformat() if camera.last_heartbeat_at else None,
            "active_camera_days": camera.active_camera_days,
            "provenance": camera.provenance,
            "telemetry_health": {
                "status": evaluated_status,
                "freshness_threshold_hours": settings.CAMERA_TELEMETRY_FRESHNESS_HOURS,
                "latest_telemetry": {
                    "id": latest_telemetry.id,
                    "observed_at": latest_telemetry.observed_at.isoformat(),
                    "battery_level": latest_telemetry.battery_level,
                    "signal_strength": latest_telemetry.signal_strength,
                    "error_codes": latest_telemetry.error_codes,
                    "source": latest_telemetry.source,
                } if latest_telemetry else None,
            },
            "observation_quality": {
                "total_images": total_images,
                "quality_flags_summary": quality_flags_count,
                "scientific_rule": "Visual quality flags and image silence are decoupled from hardware telemetry state.",
            },
        }

    def list_telemetry_history(
        self,
        db: Session,
        camera_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Lists historical telemetry log records for a camera station."""
        self.get_camera(db, camera_id)  # verify existence
        query = db.query(CameraTelemetry).filter(CameraTelemetry.camera_id == camera_id)
        total = query.count()
        records = query.order_by(CameraTelemetry.observed_at.desc()).offset(offset).limit(limit).all()

        items = [
            {
                "id": r.id,
                "camera_id": r.camera_id,
                "observed_at": r.observed_at.isoformat(),
                "battery_level": r.battery_level,
                "signal_strength": r.signal_strength,
                "error_codes": r.error_codes,
                "raw_payload": r.raw_payload,
                "source": r.source,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]
        return items, total


camera_service = CameraService()
