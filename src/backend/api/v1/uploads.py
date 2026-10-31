"""Media Upload API Endpoint.

Implements POST /api/v1/uploads:
- Multipart media upload.
- Magic bytes verification (JPEG, PNG, MP4).
- Deterministic SHA-256 calculation.
- Content-addressed disk storage outside the database.
- Deduplication without confusing filenames.
- Creation of persistent processing job.
- Returns HTTP 202 Accepted with upload_id and job_id.
"""
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from contracts.schemas import ensure_utc
from src.backend.adapters.inference import inference_adapter
from src.backend.config import settings
from src.backend.core.auth_deps import require_role
from src.backend.core.exceptions import EntityNotFoundException, ModuleUnavailableException, ValidationException
from src.backend.core.responses import success_response
from src.backend.db.session import get_db
from src.backend.models.auth import User
from src.backend.models.camera import Camera
from src.backend.models.job import JobStatus, ProcessingJob
from src.backend.models.media import MediaAsset
from src.backend.services.jobs import job_service
from src.backend.services.storage import storage_service

logger = logging.getLogger("wildscope.uploads")
router = APIRouter()


def execute_background_job(job_id: str, media_ids: List[str], db_session: Optional[Session] = None) -> None:
    """Dispatches the worker execution in a separate background thread/task.
    
    Creates its own clean database session (or reuses provided session) and guarantees failure recording on errors.
    """
    from src.backend.db.session import SessionLocal
    db = db_session if db_session is not None else SessionLocal()
    should_close = db_session is None
    try:
        media_assets = db.query(MediaAsset).filter(MediaAsset.id.in_(media_ids)).all()
        if not media_assets and media_ids:
            error_msg = f"Cannot process job {job_id}: None of the requested media assets exist in the database."
            logger.error(error_msg)
            job_service.fail_job(db=db, job_id=job_id, error_message=error_msg)
            return

        inference_adapter.dispatch_batch_job(db, job_id, media_assets)
    except ModuleUnavailableException as exc:
        # Expected unavailable worker state: inference_adapter already recorded fail_job with honest reason
        logger.info(f"Background job {job_id} inference module offline: {exc}")
    except Exception as exc:
        logger.exception(f"Unexpected failure executing background job {job_id}: {exc}")
        try:
            job = db.query(ProcessingJob).filter_by(id=job_id).first()
            if job and job.status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
                job_service.fail_job(
                    db=db,
                    job_id=job_id,
                    error_message=f"Background processing failure: {type(exc).__name__}: {str(exc)}",
                )
        except Exception as inner_exc:
            logger.error(f"Failed to record failure for job {job_id}: {inner_exc}")
    finally:
        if should_close:
            db.close()


@router.post("/uploads", status_code=status.HTTP_202_ACCEPTED, summary="Upload Media for Inference")
async def upload_media(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(..., description="One or more camera-trap images or videos"),
    camera_id: Optional[str] = Form(None, description="Optional camera station ID"),
    captured_at: Optional[str] = Form(None, description="Optional ISO-8601 capture timestamp"),
    current_user: User = Depends(require_role(["admin", "researcher"])),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Upload multipart media files, validate signatures, store bytes safely, and queue persistent job."""
    if not files or len(files) == 0:
        raise ValidationException("At least one media file must be provided.")

    # 1. Parse and validate optional camera station
    if camera_id:
        camera_record = db.query(Camera).filter_by(id=camera_id).first()
        if camera_record is None:
            raise EntityNotFoundException("Camera", camera_id)

    # 2. Parse and validate optional capture timestamp
    resolved_capture_time: Optional[datetime] = None
    timezone_source: Optional[str] = None
    if captured_at:
        try:
            parsed_dt = datetime.fromisoformat(captured_at)
            resolved_capture_time = ensure_utc(parsed_dt)
            timezone_source = "upload_request"
        except Exception as exc:
            raise ValidationException(f"Invalid capture timestamp '{captured_at}': {exc}")

    upload_id = f"up_{uuid.uuid4().hex[:12]}"
    stored_media_items = []
    media_asset_ids = []
    newly_created_file_paths: List[Path] = []

    try:
        # 3. Process and store each uploaded file via streaming (bounded memory)
        for uploaded_file in files:
            filename = uploaded_file.filename or "unknown.dat"

            media_asset, primary_frame, is_duplicate = await storage_service.store_media_stream(
                upload_file=uploaded_file,
                original_filename=filename,
                db_session=db,
                camera_id=camera_id,
                captured_at=resolved_capture_time,
                timezone_source=timezone_source,
                uploader_id=current_user.id,
            )

            # Track files newly written to disk in this uncommitted batch
            if not is_duplicate:
                disk_path = storage_service.resolve_safe_path(media_asset.storage_key)
                newly_created_file_paths.append(disk_path)

            media_asset_ids.append(media_asset.id)
            stored_media_items.append({
                "media_id": media_asset.id,
                "frame_id": primary_frame.id if primary_frame else None,
                "filename": filename,
                "content_hash": media_asset.content_hash,
                "is_duplicate": is_duplicate,
                "content_url": primary_frame.content_url if primary_frame else None,
            })

        db.commit()
    except Exception as exc:
        db.rollback()
        # Clean up any newly written files if batch validation/persistence fails
        # NEVER delete files that were already committed or shared via deduplication
        for file_path in newly_created_file_paths:
            try:
                relative_key = str(file_path.relative_to(storage_service.root_dir)).replace("\\", "/")
                committed_asset = db.query(MediaAsset).filter(MediaAsset.storage_key == relative_key).first()
                if not committed_asset and file_path.exists() and file_path.is_file():
                    file_path.unlink(missing_ok=True)
            except Exception as clean_err:
                logger.warning(f"Failed to clean up uncommitted upload file {file_path}: {clean_err}")
        raise

    # 4. Create persistent background job in 'queued' state
    job = job_service.create_job(
        db=db,
        upload_id=upload_id,
        media_ids=media_asset_ids,
        created_by_user_id=current_user.id,
    )

    # 5. Schedule asynchronous worker task
    background_tasks.add_task(execute_background_job, job.id, media_asset_ids)

    # 6. Return HTTP 202 Accepted response
    response_data = {
        "upload_id": upload_id,
        "job_id": job.id,
        "files_received": len(stored_media_items),
        "status": job.status,
        "media_items": stored_media_items,
    }
    return success_response(data=response_data, dataset_revision=settings.DEFAULT_DATASET_REVISION)
