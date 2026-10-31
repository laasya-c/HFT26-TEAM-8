"""Job Status and Progress API Endpoint.

Implements GET /api/v1/jobs/{id}:
- Retrieves persistent job state from SQLite.
- Reports progress percentage, item counts, and failures.
- Persists across application restarts.
"""
from typing import Any, Dict
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.backend.config import settings
from src.backend.core.auth_deps import require_role
from src.backend.core.exceptions import ForbiddenException
from src.backend.core.responses import success_response
from src.backend.db.session import get_db
from src.backend.models.auth import User
from src.backend.services.jobs import job_service

router = APIRouter()


@router.get("/jobs/{job_id}", status_code=status.HTTP_200_OK, summary="Get Persistent Job Status")
def get_job_status(
    job_id: str,
    current_user: User = Depends(require_role(["admin", "researcher"])),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve persistent processing job status, progress, and per-item errors.
    
    Enforces resource ownership: researchers can only inspect jobs they created.
    Sanctuary administrators possess oversight across all jobs.
    """
    job = job_service.get_job(db, job_id)

    # IDOR ownership invariant: non-admin users cannot access other users' processing jobs
    if job.created_by_user_id and job.created_by_user_id != current_user.id and current_user.role != "admin":
        raise ForbiddenException(
            "You do not have permission to access this job.",
            code="INSUFFICIENT_PERMISSIONS",
        )

    job_data = {
        "id": job.id,
        "upload_id": job.upload_id,
        "status": job.status,
        "progress": job.progress,
        "total_items": job.total_items,
        "processed_items": job.processed_items,
        "media_ids": job.media_ids,
        "run_id": job.run_id,
        "failures": job.failures,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
    return success_response(data=job_data, dataset_revision=settings.DEFAULT_DATASET_REVISION)
