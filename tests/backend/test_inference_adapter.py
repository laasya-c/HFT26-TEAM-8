"""Tests for Inference Module Adapter (Boundary with Harsh Rao)."""
from unittest.mock import MagicMock
import pytest

from src.backend.adapters.inference import InferenceAdapter
from src.backend.core.exceptions import ModuleUnavailableException
from src.backend.models.job import JobStatus
from src.backend.models.media import ImageFrame, MediaAsset
from src.backend.models.prediction import Detection, PredictionRun
from src.backend.services.jobs import job_service


@pytest.mark.unit
def test_adapter_reports_worker_unavailable_when_unlinked():
    """Verify that when src.inference is not installed, adapter honestly reports unavailable."""
    adapter = InferenceAdapter()
    assert adapter.is_available() is False

    status = adapter.get_worker_status()
    assert status["available"] is False
    assert "unavailable" in status["message"].lower()


@pytest.mark.integration
def test_dispatch_fails_honestly_when_worker_unavailable(db_session):
    """Verify dispatching a job marks the job as failed honestly rather than fabricating results."""
    adapter = InferenceAdapter()
    job = job_service.create_job(db=db_session, upload_id="up_test", media_ids=["med_1"])

    with pytest.raises(ModuleUnavailableException) as exc_info:
        adapter.dispatch_batch_job(
            db=db_session,
            job_id=job.id,
            media_assets=[],
        )

    # Job must be marked failed in database
    db_session.refresh(job)
    assert job.status == JobStatus.FAILED.value
    assert "Inference worker (Harsh Rao) is not available" in job.error_message


@pytest.mark.integration
def test_adapter_persists_genuine_detections_from_worker(db_session):
    """Verify that when the worker returns valid predictions, they are contract-validated and persisted."""
    adapter = InferenceAdapter()

    # Create test media in DB
    media = MediaAsset(
        id="med_mock_01",
        type="image",
        storage_key="media/test.jpg",
        content_hash="mockhash123",
        provenance="observed",
    )
    frame = ImageFrame(
        id="frm_mock_01",
        source_media_id="med_mock_01",
        content_url="/api/v1/images/frm_mock_01/content",
        provenance="observed",
    )
    db_session.add(media)
    db_session.add(frame)
    db_session.flush()

    job = job_service.create_job(db=db_session, upload_id="up_mock", media_ids=["med_mock_01"])

    # Mock Harsh's run_batch response
    mock_batch_result = MagicMock()
    mock_batch_result.model_name = "MegaDetector+SpeciesNet"
    mock_batch_result.model_version = "v5a"
    mock_batch_result.device = "cuda:0"
    mock_batch_result.failures = []
    mock_batch_result.detections = [
        {
            "id": "det_mock_01",
            "image_id": "frm_mock_01",
            "bbox": [0.2, 0.3, 0.4, 0.4],
            "taxon_id": "panthera_tigris",
            "label": "Tiger",
            "raw_label": "tiger 0.94",
            "score": 0.94,
            "detection_score": 0.99,
            "classification_score": 0.94,
            "alternatives": {"panthera_pardus": 0.04},
        }
    ]

    mock_module = MagicMock()
    mock_module.run_batch.return_value = mock_batch_result
    adapter._inference_module = mock_module
    adapter.is_available = lambda: True

    # Dispatch job
    run = adapter.dispatch_batch_job(
        db=db_session,
        job_id=job.id,
        media_assets=[media],
    )

    assert run is not None
    assert run.model_name == "MegaDetector+SpeciesNet"
    assert run.model_version == "v5a"
    assert run.device == "cuda:0"

    # Verify detection persisted
    det = db_session.query(Detection).filter_by(id="det_mock_01").first()
    assert det is not None
    assert det.raw_label == "tiger 0.94"
    assert det.score == 0.94
    assert det.bbox_x == 0.2
    assert det.model_version == "v5a"
    assert det.model_version == run.model_version

    # Verify job marked completed
    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED.value
    assert job.progress == 100.0


@pytest.mark.integration
def test_adapter_preserves_custom_worker_model_metadata(db_session):
    """Verify that custom worker model metadata is accurately propagated down to persisted detections."""
    adapter = InferenceAdapter()

    media = MediaAsset(
        id="med_custom_01",
        type="image",
        storage_key="media/custom.jpg",
        content_hash="hash_custom_456",
        provenance="observed",
    )
    frame = ImageFrame(
        id="frm_custom_01",
        source_media_id="med_custom_01",
        content_url="/api/v1/images/frm_custom_01/content",
        provenance="observed",
    )
    db_session.add(media)
    db_session.add(frame)
    db_session.flush()

    job = job_service.create_job(db=db_session, upload_id="up_custom", media_ids=["med_custom_01"])

    mock_batch_result = MagicMock()
    mock_batch_result.model_name = "YOLOv8x-Conservation"
    mock_batch_result.model_version = "v8.2.1-custom"
    mock_batch_result.device = "cuda:1"
    mock_batch_result.failures = []
    mock_batch_result.detections = [
        {
            "id": "det_custom_01",
            "image_id": "frm_custom_01",
            "bbox": [0.1, 0.1, 0.5, 0.5],
            "taxon_id": "elephas_maximus",
            "label": "Asian Elephant",
            "raw_label": "elephant 0.98",
            "score": 0.98,
        }
    ]

    mock_module = MagicMock()
    mock_module.run_batch.return_value = mock_batch_result
    adapter._inference_module = mock_module
    adapter.is_available = lambda: True

    run = adapter.dispatch_batch_job(
        db=db_session,
        job_id=job.id,
        media_assets=[media],
    )

    assert run.model_name == "YOLOv8x-Conservation"
    assert run.model_version == "v8.2.1-custom"
    assert run.device == "cuda:1"

    det = db_session.query(Detection).filter_by(id="det_custom_01").first()
    assert det is not None
    assert det.model_version == "v8.2.1-custom"
    assert det.model_version == run.model_version
