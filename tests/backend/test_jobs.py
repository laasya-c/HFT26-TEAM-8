"""Tests for Persistent Job Management and State Transitions."""
import pytest
from src.backend.models.job import JobStatus, ProcessingJob
from src.backend.services.jobs import job_service


@pytest.mark.integration
def test_job_lifecycle_queued_to_completed(db_session):
    """Verify standard job creation, progress updates, and completion."""
    job = job_service.create_job(
        db=db_session,
        upload_id="up_test_01",
        media_ids=["med_1", "med_2"],
    )
    assert job.status == JobStatus.QUEUED.value
    assert job.progress == 0.0
    assert job.total_items == 2

    # Insert a valid PredictionRun to satisfy foreign key constraint on processing_jobs.run_id
    from src.backend.models.prediction import PredictionRun
    prediction_run = PredictionRun(
        id="run_test_01",
        model_name="MegaDetector",
        model_version="v5a",
        device="cpu",
        status="running",
    )
    db_session.add(prediction_run)
    db_session.commit()

    # Start job
    job = job_service.start_job(db=db_session, job_id=job.id, run_id=prediction_run.id)
    assert job.status == JobStatus.RUNNING.value
    assert job.run_id == "run_test_01"

    # Update progress
    job = job_service.update_progress(db=db_session, job_id=job.id, processed_items=1)
    assert job.progress == 50.0

    # Complete job
    job = job_service.complete_job(db=db_session, job_id=job.id)
    assert job.status == JobStatus.COMPLETED.value
    assert job.progress == 100.0
    assert job.completed_at is not None


@pytest.mark.integration
def test_job_failure_state(db_session):
    """Verify marking job as failed records explicit reason."""
    job = job_service.create_job(
        db=db_session,
        upload_id="up_test_02",
        media_ids=["med_3"],
    )

    job = job_service.fail_job(
        db=db_session,
        job_id=job.id,
        error_message="Worker unavailable: GPU memory exhausted",
        failures=[{"item": "med_3", "error": "CUDA out of memory"}],
    )
    assert job.status == JobStatus.FAILED.value
    assert "Worker unavailable" in job.error_message
    assert len(job.failures) == 1


@pytest.mark.unit
def test_invalid_job_state_transition():
    """Verify that terminal states (completed/failed) cannot transition back to running."""
    job = ProcessingJob(
        id="job_dummy",
        upload_id="up_dummy",
        status=JobStatus.COMPLETED.value,
    )

    with pytest.raises(ValueError) as exc_info:
        job.transition_to(JobStatus.RUNNING)
    assert "Illegal job state transition" in str(exc_info.value)
