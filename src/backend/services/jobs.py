"""Persistent Job Management Service.

Responsibilities:
1. Create and persist background processing jobs in SQLite.
2. Maintain job state transitions (queued -> running -> completed / partial / failed).
3. Ensure job status persists across application restarts.
4. Prevent duplicate processing runs on completed/failed jobs.
5. Record per-item processing failures and reasons.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from src.backend.core.exceptions import EntityNotFoundException, ValidationException
from src.backend.models.job import JobStatus, ProcessingJob


class JobService:
    """Manages persistent job records and state transitions in the database."""

    def create_job(
        self,
        db: Session,
        upload_id: str,
        media_ids: List[str],
        created_by_user_id: Optional[str] = None,
    ) -> ProcessingJob:
        """Creates a new persistent processing job in 'queued' state."""
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job = ProcessingJob(
            id=job_id,
            upload_id=upload_id,
            status=JobStatus.QUEUED.value,
            progress=0.0,
            total_items=len(media_ids),
            processed_items=0,
            media_ids=media_ids,
            created_by_user_id=created_by_user_id,
            failures=[],
            error_message=None,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    def get_job(self, db: Session, job_id: str) -> ProcessingJob:
        """Retrieves a persistent job by ID or raises EntityNotFoundException."""
        job = db.query(ProcessingJob).filter_by(id=job_id).first()
        if job is None:
            raise EntityNotFoundException("ProcessingJob", job_id)
        return job

    def start_job(self, db: Session, job_id: str, run_id: Optional[str] = None) -> ProcessingJob:
        """Transitions job from 'queued' to 'running'."""
        job = self.get_job(db, job_id)
        job.transition_to(JobStatus.RUNNING)
        if run_id:
            job.run_id = run_id
        db.commit()
        db.refresh(job)
        return job

    def update_progress(
        self,
        db: Session,
        job_id: str,
        processed_items: int,
        failures: Optional[List[Dict[str, Any]]] = None,
    ) -> ProcessingJob:
        """Updates job progress and logs any item failures."""
        job = self.get_job(db, job_id)
        if job.status not in (JobStatus.RUNNING.value, JobStatus.QUEUED.value):
            raise ValidationException(f"Cannot update progress for job in terminal state '{job.status}'.")

        job.processed_items = processed_items
        if job.total_items > 0:
            job.progress = round((processed_items / job.total_items) * 100.0, 1)
        if failures:
            current_failures = list(job.failures or [])
            current_failures.extend(failures)
            job.failures = current_failures
            flag_modified(job, "failures")
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return job

    def complete_job(
        self,
        db: Session,
        job_id: str,
        run_id: Optional[str] = None,
        failures: Optional[List[Dict[str, Any]]] = None,
    ) -> ProcessingJob:
        """Marks a job as completed or partially completed depending on failure list."""
        job = self.get_job(db, job_id)
        if failures:
            current_failures = list(job.failures or [])
            current_failures.extend(failures)
            job.failures = current_failures
            flag_modified(job, "failures")
        if run_id:
            job.run_id = run_id

        # If there are item-level failures, mark as 'partial'; otherwise 'completed'
        if len(job.failures) > 0 and len(job.failures) < job.total_items:
            job.transition_to(JobStatus.PARTIAL)
        elif len(job.failures) >= job.total_items and job.total_items > 0:
            job.transition_to(JobStatus.FAILED, error_message="All media items failed processing.")
        else:
            job.transition_to(JobStatus.COMPLETED)

        job.progress = 100.0
        job.processed_items = job.total_items
        db.commit()
        db.refresh(job)
        return job

    def fail_job(
        self,
        db: Session,
        job_id: str,
        error_message: str,
        failures: Optional[List[Dict[str, Any]]] = None,
    ) -> ProcessingJob:
        """Marks a job as failed with a meaningful scientific/operational error message."""
        job = self.get_job(db, job_id)
        if failures:
            current_failures = list(job.failures or [])
            current_failures.extend(failures)
            job.failures = current_failures
            flag_modified(job, "failures")
        job.transition_to(JobStatus.FAILED, error_message=error_message)
        db.commit()
        db.refresh(job)
        return job


# Global singleton instance
job_service = JobService()
