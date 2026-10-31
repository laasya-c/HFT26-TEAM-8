"""
WILDSCOPE — SpeciesNet concrete detector implementation
src/inference/speciesnet_detector.py

Implements BaseDetector using SpeciesNet 5.0.5 (MegaDetector V5 + classifier).

NMS note
--------
SpeciesNet's `SpeciesNetDetector.predict()` calls `yolov5_non_max_suppression`
internally (conf_thres=0.01, default IoU threshold=0.45).  This module does
NOT apply any additional NMS pass.  Callers who wish to suppress overlapping
detections post-hoc should use `ImageDetectionResult.filter_by_conf()` or a
custom IoU filter — they must be aware that NMS has already been applied once.

What this module does NOT do
-----------------------------
- Does not train or fine-tune model weights.
- Does not hard-code species predictions.
- Does not silently fall back to CPU without reporting the device used.
- Does not expose SpeciesNet-specific types through the BaseDetector interface.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import torch

from src.inference.base_detector import (
    BaseDetector,
    Detection,
    DetectionStatus,
    ImageDetectionResult,
    SpeciesClassification,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default model identifier
# ---------------------------------------------------------------------------
DEFAULT_MODEL_NAME = "kaggle:google/speciesnet/pyTorch/v4.0.3a/1"


class SpeciesNetAnimalDetector(BaseDetector):
    """
    Concrete BaseDetector implementation backed by SpeciesNet 5.0.5.

    Detection uses MegaDetector V5 (YOLOv5-based, AGPL-3.0 risk — see
    docs/inference/LICENSING.md).  Classification uses the SpeciesNet
    EfficientNet-based classifier (Apache-2.0).

    NMS is applied *inside* SpeciesNetDetector.predict() via yolov5's
    non_max_suppression call.  This class does not apply NMS again.

    Parameters
    ----------
    model_name : str
        SpeciesNet model identifier (kaggle: or hf: prefix).
    classify_device : str or None
        Device for the classifier.  None = auto (prefers CUDA > MPS > CPU).
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        classify_device: Optional[str] = None,
    ) -> None:
        # Lazy imports — SpeciesNet is heavy and should not load at import time
        from speciesnet.detector   import SpeciesNetDetector   as _Detector
        from speciesnet.classifier import SpeciesNetClassifier as _Classifier

        self._model_name = model_name

        t0 = time.perf_counter()
        logger.info("Loading SpeciesNetDetector (%s)...", model_name)
        self._detector   = _Detector(model_name)

        logger.info("Loading SpeciesNetClassifier (device=%s)...",
                    classify_device or "auto")
        self._classifier = _Classifier(model_name, device=classify_device)
        load_time = time.perf_counter() - t0

        logger.info(
            "Models loaded in %.1f s | detector=%s | classifier=%s",
            load_time, self._detector.device, self._classifier.device,
        )

    # ------------------------------------------------------------------
    # BaseDetector properties
    # ------------------------------------------------------------------

    @property
    def device(self) -> str:
        return str(self._detector.device)

    @property
    def model_name(self) -> str:
        return self._model_name

    # ------------------------------------------------------------------
    # Core implementation
    # ------------------------------------------------------------------

    def detect_batch(
        self,
        image_paths: list[str | Path],
        min_conf: float = 0.0,
    ) -> list[ImageDetectionResult]:
        """
        Run SpeciesNet detection + per-detection classification on a batch.

        NMS behaviour
        -------------
        SpeciesNet's detector already applies non_max_suppression internally
        (YOLOv5, conf_thres=0.01, iou_thres=0.45 default).  No additional
        NMS is applied here.  If min_conf > 0 the returned list is pre-filtered
        by confidence, but no duplicate suppression is performed.

        Classification
        --------------
        Each animal detection is classified independently.  A blank or unknown
        classification does NOT discard the detection — it sets
        detection.classification.is_blank / .is_unknown instead.
        """
        from speciesnet.utils import BBox, load_rgb_image

        results: list[ImageDetectionResult] = []

        for path in image_paths:
            path_str = str(path)
            result   = ImageDetectionResult(filepath=path_str)
            t_img    = time.perf_counter()

            try:
                # ── Load image ──────────────────────────────────────────
                t0 = time.perf_counter()
                pil_img = load_rgb_image(path_str)
                result.load_time_s = time.perf_counter() - t0

                if pil_img is None:
                    result.status        = DetectionStatus.LOAD_FAILURE
                    result.error_message = "load_rgb_image returned None"
                    results.append(result)
                    continue

                result.image_w, result.image_h = pil_img.size

                # ── Detection ───────────────────────────────────────────
                t1 = time.perf_counter()
                det_preprocessed = self._detector.preprocess(pil_img)
                det_output       = self._detector.predict(path_str,
                                                          det_preprocessed)
                result.detect_time_s   = time.perf_counter() - t1
                result.detect_device   = self._detector.device

                if "failures" in det_output:
                    result.status        = DetectionStatus.INFERENCE_ERROR
                    result.error_message = (
                        f"Detector failure: {det_output['failures']}"
                    )
                    results.append(result)
                    continue

                raw_dets = det_output.get("detections", [])

                # ── Classification ──────────────────────────────────────
                t2 = time.perf_counter()
                detections: list[Detection] = []

                for raw in raw_dets:
                    bbox_norm = raw["bbox"]   # [xmin, ymin, w, h] normalised
                    clf       = SpeciesClassification()

                    # Only classify animal detections
                    if raw["label"] == "animal":
                        try:
                            speciesnet_bbox = BBox(
                                xmin  = bbox_norm[0],
                                ymin  = bbox_norm[1],
                                width = bbox_norm[2],
                                height= bbox_norm[3],
                            )
                            cls_pre = self._classifier.preprocess(
                                pil_img, bboxes=[speciesnet_bbox]
                            )
                            cls_out = self._classifier.predict(path_str, cls_pre)

                            clf.attempted   = True
                            clf.device_used = self._classifier.device

                            if "classifications" in cls_out:
                                c = cls_out["classifications"]
                                clf.top_labels = c.get("classes", [])
                                clf.top_scores = c.get("scores",  [])

                            if not result.classify_device:
                                result.classify_device = self._classifier.device

                        except Exception as cls_exc:
                            # Classification failure does NOT discard the detection.
                            # Log and leave clf.attempted=True, lists empty.
                            clf.attempted = True
                            logger.warning(
                                "Classification failed for %s det bbox=%s: %s",
                                path_str, bbox_norm, cls_exc,
                            )

                    det = Detection(
                        bbox_norm        = bbox_norm,
                        image_w          = result.image_w,
                        image_h          = result.image_h,
                        detector_conf    = raw["conf"],
                        detector_label   = raw["label"],
                        detector_category= raw["category"],
                        classification   = clf,
                    )
                    # R1: bbox_valid is set automatically by Detection.__post_init__.
                    # If invalid, log a warning but keep the detection — its
                    # species classification is still valid, and the raw
                    # coordinates are preserved in det.bbox_norm for debugging.
                    # Downstream code must check det.bbox_valid before calling
                    # det.bbox_pixels.
                    if not det.bbox_valid:
                        logger.warning(
                            "Detector returned invalid bbox for %s "
                            "(bbox_norm=%s). Detection kept; bbox_valid=False "
                            "prevents use as pixel coordinates. "
                            "Raw coordinates available via det.bbox_norm.",
                            path_str, det.bbox_norm,
                        )
                    detections.append(det)

                result.classify_time_s = time.perf_counter() - t2
                result.status          = DetectionStatus.OK

                # Apply confidence floor if requested
                if min_conf > 0.0:
                    detections = [d for d in detections
                                  if d.detector_conf >= min_conf]

                result.detections = detections

            except Exception as exc:
                result.status        = DetectionStatus.INFERENCE_ERROR
                result.error_message = str(exc)
                logger.exception("Inference failed for %s", path_str)

            result.total_time_s = time.perf_counter() - t_img
            results.append(result)

        return results

