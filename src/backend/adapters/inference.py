"""Inference Module Integration Adapter.

Boundary between Backend (Santosh) and Vision Worker (Harsh Rao).

Expected Interface from Harsh:
- run_batch(manifest: List[Dict], settings: Dict) -> BatchResult
- group_encounters(observations: List[Dict], settings: Dict) -> List[Dict]

Scientific & Engineering Rules:
1. Santosh NEVER loads vision models (YOLO/MegaDetector) inside the backend.
2. Santosh NEVER downloads model weights or fakes predictions.
3. If Harsh's module is unlinked or offline:
   - Returns explicit unavailable state.
   - Marks the processing job as 'failed' with a genuine error message.
   - Preserves uploaded media and job record for future execution.
"""
import importlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from contracts.schemas import DetectionContract, ProvenanceEnum
from src.backend.core.exceptions import ModuleUnavailableException
from src.backend.models.encounter import Encounter, EncounterMember
from src.backend.models.media import ImageFrame, MediaAsset
from src.backend.models.prediction import Detection, PredictionRun
from src.backend.services.jobs import job_service

logger = logging.getLogger("wildscope.adapters.inference")


class InferenceAdapter:
    """Safely interfaces with Harsh's external vision pipeline."""

    def __init__(self):
        self._inference_module = None
        self._checked = False

    def is_available(self) -> bool:
        """Determines if Harsh's vision module is installed and reachable."""
        try:
            mod = importlib.import_module("src.inference")
            if hasattr(mod, "run_batch"):
                self._inference_module = mod
                return True
        except ImportError:
            pass
        return False

    def get_worker_status(self) -> Dict[str, Any]:
        """Provides diagnostic information about worker readiness."""
        available = self.is_available()
        return {
            "available": available,
            "module": "src.inference",
            "owner": "Harsh Rao",
            "device_policy": "RTX 4050 CUDA (Python 3.11 target)",
            "message": (
                "Vision worker connected and ready."
                if available
                else "Vision worker unavailable. src.inference is not yet linked or online."
            ),
        }

    def dispatch_batch_job(
        self,
        db: Session,
        job_id: str,
        media_assets: List[MediaAsset],
        settings_payload: Optional[Dict[str, Any]] = None,
    ) -> PredictionRun:
        """Dispatches an inference run for uploaded media assets.
        
        If Harsh's module is unavailable, marks the job as failed honestly.
        Never fabricates predictions.
        """
        # 1. Check availability
        if not self.is_available():
            error_msg = (
                "Inference worker (Harsh Rao) is not available. "
                "Module 'src.inference' with function 'run_batch()' is not installed. "
                "Job marked as failed honestly; no synthetic predictions were fabricated."
            )
            job_service.fail_job(db, job_id, error_message=error_msg)
            raise ModuleUnavailableException("src.inference", error_msg)

        # 2. Build trusted manifest from persisted database records
        # Client paths are NEVER passed directly to the worker
        manifest = []
        for media in media_assets:
            for frame in media.frames:
                manifest.append({
                    "image_id": frame.id,
                    "storage_key": media.storage_key,
                    "content_hash": media.content_hash,
                })

        # 3. Initialize and persist PredictionRun before linking to job to satisfy FK
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        prediction_run = PredictionRun(
            id=run_id,
            model_name="MegaDetector+Classifier",
            model_version="v5a",
            device="unknown",
            started_at=started_at,
            status="running",
            failures=[],
        )
        db.add(prediction_run)
        db.flush()

        # 4. Mark job as running with valid foreign key link
        job_service.start_job(db, job_id, run_id=run_id)

        # 5. Invoke Harsh's run_batch()
        try:
            batch_result = self._inference_module.run_batch(manifest, settings_payload or {})
        except Exception as exc:
            logger.error("Vision worker crashed during batch execution: %s", exc)
            prediction_run.status = "failed"
            prediction_run.completed_at = datetime.now(timezone.utc)
            db.commit()
            job_service.fail_job(db, job_id, error_message=f"Vision worker execution failure: {str(exc)}")
            raise RuntimeError(f"Vision worker crashed during inference: {exc}")

        # 6. Extract actual worker-reported model metadata and update PredictionRun
        worker_model_name = getattr(batch_result, "model_name", "MegaDetector+Classifier")
        worker_model_version = getattr(batch_result, "model_version", "v5a")
        worker_device = getattr(batch_result, "device", "cpu")
        raw_detections = getattr(batch_result, "detections", [])
        raw_failures = getattr(batch_result, "failures", [])

        if isinstance(batch_result, dict):
            worker_model_name = batch_result.get("model_name", worker_model_name)
            worker_model_version = batch_result.get("model_version", worker_model_version)
            worker_device = batch_result.get("device", worker_device)
            raw_detections = batch_result.get("detections", raw_detections)
            raw_failures = batch_result.get("failures", raw_failures)

        prediction_run.model_name = worker_model_name
        prediction_run.model_version = worker_model_version
        prediction_run.device = worker_device
        prediction_run.completed_at = datetime.now(timezone.utc)
        prediction_run.status = "completed" if not raw_failures else "partial"
        prediction_run.failures = raw_failures
        db.flush()

        # 7. Persist Validated Detections (Immutable)
        persisted_detections = []
        for det_data in raw_detections:
            det_model_version = det_data.get("model_version") or prediction_run.model_version
            # Validate against shared contract before writing
            validated_contract = DetectionContract(
                id=det_data.get("id", str(uuid.uuid4())),
                image_id=det_data["image_id"],
                encounter_id=det_data.get("encounter_id"),
                bbox=tuple(det_data["bbox"]),
                taxon_id=det_data.get("taxon_id"),
                label=det_data["label"],
                raw_label=det_data["raw_label"],
                score=det_data["score"],
                detection_score=det_data.get("detection_score"),
                classification_score=det_data.get("classification_score"),
                score_type=det_data.get("score_type"),
                calibration_status=det_data.get("calibration_status"),
                alternatives=det_data.get("alternatives", {}),
                model_version=det_model_version,
                review_status="pending",
                provenance=ProvenanceEnum.INFERRED,
            )

            db_det = Detection(
                id=validated_contract.id,
                image_id=validated_contract.image_id,
                run_id=prediction_run.id,
                encounter_id=validated_contract.encounter_id,
                bbox_x=validated_contract.bbox[0],
                bbox_y=validated_contract.bbox[1],
                bbox_w=validated_contract.bbox[2],
                bbox_h=validated_contract.bbox[3],
                raw_label=validated_contract.raw_label,
                taxon_id=validated_contract.taxon_id,
                label=validated_contract.label,
                score=validated_contract.score,
                detection_score=validated_contract.detection_score,
                classification_score=validated_contract.classification_score,
                score_type=validated_contract.score_type,
                calibration_status=validated_contract.calibration_status,
                alternatives=validated_contract.alternatives,
                model_version=validated_contract.model_version,
                review_status=validated_contract.review_status,
                provenance=validated_contract.provenance,
            )
            db.add(db_det)
            persisted_detections.append(db_det)

        db.flush()

        # 8. Complete the job record
        job_service.complete_job(db, job_id, run_id=run_id, failures=raw_failures)
        db.commit()
        db.refresh(prediction_run)
        return prediction_run


# Global singleton adapter
inference_adapter = InferenceAdapter()
