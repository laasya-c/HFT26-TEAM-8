"""
WILDSCOPE — SpeciesNet inference pipeline
src/inference/speciesnet_infer.py

Runs genuine pretrained SpeciesNet detection + per-detection classification
on a list of image paths. Designed to be the initial concrete implementation
behind a future swappable detector interface.

Architecture note
-----------------
This module intentionally keeps model-specific code isolated. The public
function `run_inference()` is the only entry point used by tests and scripts;
the SpeciesNet-specific classes (SpeciesNetDetector, SpeciesNetClassifier) are
imported only inside this module so they can be replaced later.

What this does NOT do
---------------------
- Does not train or fine-tune any model.
- Does not hard-code predictions.
- Does not silently fall back to CPU — device selection is reported explicitly.
- Does not commit or expose model weights.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model identifier
# ---------------------------------------------------------------------------
MODEL_NAME = "kaggle:google/speciesnet/pyTorch/v4.0.3a/1"

# ---------------------------------------------------------------------------
# Result dataclasses — plain Python, no SpeciesNet types exposed externally.
# ---------------------------------------------------------------------------

@dataclass
class DetectionResult:
    """One animal (or vehicle/person) detected by MegaDetector."""
    category: str               # "1"=animal, "3"=vehicle
    label: str                  # "animal" / "vehicle"
    conf: float                 # detection confidence (not a calibrated probability)
    bbox_norm: list[float]      # [x_min, y_min, width, height] normalised 0–1
    top5_classes: list[str] = field(default_factory=list)
    top5_scores: list[float] = field(default_factory=list)
    classification_attempted: bool = False


@dataclass
class ImageResult:
    """Complete inference result for one image."""
    filepath: str
    status: str = "pending"     # "ok" | "failure" | "error"
    image_w: Optional[int] = None
    image_h: Optional[int] = None
    detect_device: Optional[str] = None
    classify_device: Optional[str] = None
    load_time_s: float = 0.0
    detect_time_s: float = 0.0
    classify_time_s: float = 0.0
    total_time_s: float = 0.0
    detections: list[DetectionResult] = field(default_factory=list)
    raw_detect_output: Optional[dict] = None
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Main inference function
# ---------------------------------------------------------------------------

def run_inference(
    image_paths: list[str | Path],
    model_name: str = MODEL_NAME,
    classify_device: Optional[str] = None,  # None = auto (CUDA if available)
) -> list[ImageResult]:
    """
    Run SpeciesNet detection + per-detection classification on a list of images.

    Parameters
    ----------
    image_paths : list of str or Path
        Absolute paths to image files.
    model_name : str
        SpeciesNet model identifier (kaggle: or hf: prefix).
    classify_device : str or None
        Device for classifier. None = auto (prefers CUDA, then MPS, then CPU).

    Returns
    -------
    list of ImageResult
        One result per input image, in the same order.
    """
    # Lazy imports — torch and SpeciesNet are heavy.  Importing this module
    # does not load them; they are deferred until run_inference() is called.
    import torch
    from speciesnet.detector import SpeciesNetDetector
    from speciesnet.classifier import SpeciesNetClassifier
    from speciesnet.utils import BBox, load_rgb_image

    cuda_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if cuda_available else "N/A"
    logger.info("CUDA available: %s  |  GPU: %s", cuda_available, gpu_name)

    # ── Load models (downloads weights on first run) ────────────────────────
    t_load_start = time.perf_counter()
    logger.info("Loading detector (model_name=%s)...", model_name)
    detector = SpeciesNetDetector(model_name)

    logger.info("Loading classifier (device=%s)...", classify_device or "auto")
    classifier = SpeciesNetClassifier(model_name, device=classify_device)

    load_time = time.perf_counter() - t_load_start
    logger.info(
        "Models loaded in %.1f s  |  detector device=%s  |  classifier device=%s",
        load_time, detector.device, classifier.device,
    )

    results: list[ImageResult] = []

    for path in image_paths:
        path_str = str(path)
        result = ImageResult(filepath=path_str)
        t_img_start = time.perf_counter()

        try:
            # ── Load image ──────────────────────────────────────────────────
            t0 = time.perf_counter()
            pil_img = load_rgb_image(path_str)
            if pil_img is None:
                result.status = "failure"
                result.error_message = "load_rgb_image returned None"
                results.append(result)
                continue
            result.image_w, result.image_h = pil_img.size
            result.load_time_s = time.perf_counter() - t0

            # ── Detection ───────────────────────────────────────────────────
            t1 = time.perf_counter()
            det_preprocessed = detector.preprocess(pil_img)
            det_output = detector.predict(path_str, det_preprocessed)
            result.detect_time_s = time.perf_counter() - t1
            result.detect_device = detector.device
            result.raw_detect_output = det_output

            if "failures" in det_output:
                result.status = "failure"
                result.error_message = f"Detector failure: {det_output['failures']}"
                results.append(result)
                continue

            raw_detections = det_output.get("detections", [])

            # ── Classification — every detection independently ───────────────
            t2 = time.perf_counter()
            detection_results: list[DetectionResult] = []

            for raw_det in raw_detections:
                dr = DetectionResult(
                    category=raw_det["category"],
                    label=raw_det["label"],
                    conf=raw_det["conf"],
                    bbox_norm=raw_det["bbox"],
                )

                # Only classify animal detections (category "1").
                if raw_det["label"] == "animal":
                    bbox = raw_det["bbox"]  # [xmin, ymin, w, h] normalised
                    speciesnet_bbox = BBox(
                        xmin=bbox[0],
                        ymin=bbox[1],
                        width=bbox[2],
                        height=bbox[3],
                    )
                    cls_preprocessed = classifier.preprocess(
                        pil_img, bboxes=[speciesnet_bbox]
                    )
                    cls_output = classifier.predict(path_str, cls_preprocessed)

                    dr.classification_attempted = True
                    result.classify_device = classifier.device

                    if "classifications" in cls_output:
                        cls = cls_output["classifications"]
                        dr.top5_classes = cls.get("classes", [])
                        dr.top5_scores = cls.get("scores", [])

                detection_results.append(dr)

            result.classify_time_s = time.perf_counter() - t2
            result.detections = detection_results
            result.status = "ok"

        except Exception as exc:
            result.status = "error"
            result.error_message = str(exc)
            logger.exception("Inference failed for %s", path_str)

        result.total_time_s = time.perf_counter() - t_img_start
        results.append(result)

    return results
