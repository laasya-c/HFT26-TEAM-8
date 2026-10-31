"""
WILDSCOPE — Detector abstraction layer
src/inference/base_detector.py

Defines the public interface for all animal detectors used in WILDSCOPE.
SpeciesNet (MegaDetector V5) is the initial concrete implementation, but
any detector can be substituted by implementing BaseDetector.

Design goals
------------
* Detector scores and species-classifier scores are always kept separate.
* Bounding-box coordinates and image dimensions are always preserved.
* Multiple detections per image are supported.
* "Blank" or unknown species is a valid classification outcome, not an error.
* No detections (empty list) is distinct from an inference failure.
* No SpeciesNet-specific types, constants, or identifiers appear in this module.

Nothing in this file imports from SpeciesNet or any model library.
"""

from __future__ import annotations

import copy
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Detection status
# ---------------------------------------------------------------------------

class DetectionStatus(Enum):
    """High-level outcome of running a detector on one image."""
    OK             = auto()   # Detection ran; result list may be empty
    LOAD_FAILURE   = auto()   # Image could not be loaded or decoded
    INFERENCE_ERROR = auto()  # Model raised an exception during inference
    NOT_RUN        = auto()   # Detector was never invoked (default state)


# ---------------------------------------------------------------------------
# Species classification output
# ---------------------------------------------------------------------------

@dataclass
class SpeciesClassification:
    """
    Result of running a species classifier on a single detection crop.

    Scores are softmax values over the full taxonomy label set (all species,
    family, order, blank, etc.).  They sum to 1.0 across *all* labels, not
    just the top-5 shown here.  Labels at different taxonomy levels (species,
    genus, family) are *separate* classes in the distribution and must never
    be summed to produce a combined probability.

    A top-1 label of "" or "blank" is valid and means the classifier found
    insufficient visual information in the crop.
    """
    top_labels: list[str]   = field(default_factory=list)
    top_scores: list[float] = field(default_factory=list)
    device_used: str        = "unknown"
    attempted:  bool        = False   # False iff classification was skipped

    # ------------------------------------------------------------------
    @property
    def top_label(self) -> Optional[str]:
        """Convenience: highest-scoring label, or None if list is empty."""
        return self.top_labels[0] if self.top_labels else None

    @property
    def top_score(self) -> Optional[float]:
        """Convenience: highest softmax score, or None if list is empty."""
        return self.top_scores[0] if self.top_scores else None

    @property
    def is_blank(self) -> bool:
        """True when the top label is the explicit 'blank' output.

        SpeciesNet blank labels end with a semicolon segment whose value
        is exactly "blank" (case-insensitive).  Substring matching is
        intentionally avoided to prevent false positives on labels like
        "blanket" or "black-blank".
        """
        lbl = self.top_label or ""
        # Exact match of the final semicolon segment, case-insensitive.
        return lbl.split(";")[-1].strip().lower() == "blank"

    @property
    def is_unknown(self) -> bool:
        """True when classification was not attempted or returned nothing."""
        return not self.attempted or not self.top_labels

    def __repr__(self) -> str:  # noqa: D401
        if not self.attempted:
            return "SpeciesClassification(not attempted)"
        if not self.top_labels:
            return "SpeciesClassification(empty)"
        return (
            f"SpeciesClassification(top={self.top_label!r}, "
            f"score={self.top_score:.4f}, attempted={self.attempted})"
        )


# ---------------------------------------------------------------------------
# Single detection result
# ---------------------------------------------------------------------------

@dataclass
class Detection:
    """
    One animal (or vehicle/person) detected in an image.

    Coordinates
    -----------
    bbox_norm: [x_min, y_min, width, height], all normalised to [0, 1].
    image_w, image_h: original pixel dimensions used for display/conversion.

    Confidence
    ----------
    detector_conf is the raw score from MegaDetector (or equivalent).
    It is NOT a calibrated probability and must not be treated as one.

    Classification
    --------------
    classification holds the species result.  It may be absent (not
    attempted), blank (classifier returned insufficient-info output), or
    unknown (classification failed after a successful detection).
    Classification failure does NOT invalidate the detection.
    """
    # Detection geometry
    bbox_norm:     list[float]           # [xmin, ymin, w, h] normalised 0-1
    image_w:       int
    image_h:       int

    # Detector output
    detector_conf: float                 # raw MegaDetector score
    detector_label: str                  # e.g. "animal", "vehicle", "person"
    detector_category: str               # raw category string from model

    # Species classification (may be empty/not attempted)
    classification: SpeciesClassification = field(
        default_factory=SpeciesClassification
    )

    def __post_init__(self) -> None:
        # C3 fix: store a defensive copy of the caller's list so that
        # mutating the original input or this stored list are independent.
        self.bbox_norm = list(self.bbox_norm)
        # Note: bbox_valid is a @property — no stored field to set here.
        # It calls validate_bbox() on every access so it always reflects
        # the current state of bbox_norm, even after post-construction mutation.

    # ------------------------------------------------------------------
    @property
    def bbox_valid(self) -> bool:
        """True iff the current bbox_norm represents valid geometry.

        Computed live on every access by calling validate_bbox(), so it
        always reflects the current state of bbox_norm — including any
        in-place mutations made after construction.

        True  → bbox_pixels is safe to call.
        False → bbox_norm holds invalid coordinates (preserved for debugging);
                bbox_pixels will raise ValueError.
        """
        return self.validate_bbox()

    @property
    def bbox_pixels(self) -> tuple[int, int, int, int]:
        """
        Return bbox as integer pixel coordinates (x_min, y_min, w, h).
        Derived from bbox_norm and image dimensions.

        Raises
        ------
        ValueError
            If bbox_valid is False.  The raw (possibly invalid) coordinates
            are still accessible via bbox_norm for debugging purposes.
        """
        if not self.bbox_valid:
            raise ValueError(
                f"bbox_pixels is not available: bounding-box geometry is "
                f"invalid (bbox_norm={self.bbox_norm!r}). "
                "Access Detection.bbox_norm directly for raw debugging coordinates."
            )
        xn, yn, wn, hn = self.bbox_norm
        return (
            int(xn * self.image_w),
            int(yn * self.image_h),
            int(wn * self.image_w),
            int(hn * self.image_h),
        )

    @property
    def is_animal(self) -> bool:
        """True when the detector labelled this detection as an animal."""
        return self.detector_label.lower() == "animal"

    def validate_bbox(self) -> bool:
        """
        Return True iff the normalised bbox values represent valid geometry.
        Never raises — all malformed inputs (wrong type, wrong length, NaN,
        infinity, out-of-range) are treated as invalid and return False.

        Checks (in order):
        1. Exactly 4 coordinates present.
        2. All coordinates are finite real numbers (rejects NaN and ±infinity,
           and any non-numeric type such as str or None).
        3. x_min and y_min are non-negative.
        4. width and height are strictly positive (> 0).
        5. All coordinates are within [0, 1].
        6. The box does not extend beyond the image boundary, with a small
           tolerance (1e-6) to absorb floating-point rounding from the model.
        """
        try:
            if len(self.bbox_norm) != 4:
                return False
            xn, yn, wn, hn = self.bbox_norm
            # Reject NaN and infinity before any comparison — comparisons with NaN
            # always return False, which could silently let malformed values through.
            # math.isfinite also raises TypeError for non-numeric types, which is
            # caught by the outer try/except.
            if not all(math.isfinite(v) for v in (xn, yn, wn, hn)):
                return False
            return (
                0.0 <= xn <= 1.0
                and 0.0 <= yn <= 1.0
                and 0.0 <  wn <= 1.0
                and 0.0 <  hn <= 1.0
                and xn + wn <= 1.0 + 1e-6   # allow tiny float rounding
                and yn + hn <= 1.0 + 1e-6
            )
        except (TypeError, ValueError):
            # Non-numeric element types or other unexpected values → invalid.
            return False


# ---------------------------------------------------------------------------
# Per-image detection result
# ---------------------------------------------------------------------------

@dataclass
class ImageDetectionResult:
    """
    Complete detection (and optional classification) result for one image.

    status == OK does not guarantee detections is non-empty.
    An empty detections list with status==OK means the model ran successfully
    but found nothing above the requested threshold.
    """
    filepath:     str
    status:       DetectionStatus = DetectionStatus.NOT_RUN
    image_w:      Optional[int]   = None
    image_h:      Optional[int]   = None
    detections:   list[Detection] = field(default_factory=list)

    # Timing (seconds)
    load_time_s:     float = 0.0
    detect_time_s:   float = 0.0
    classify_time_s: float = 0.0
    total_time_s:    float = 0.0

    # Device strings (e.g. "cuda", "cpu")
    detect_device:   Optional[str] = None
    classify_device: Optional[str] = None

    error_message:   Optional[str] = None

    # ------------------------------------------------------------------
    @property
    def succeeded(self) -> bool:
        return self.status == DetectionStatus.OK

    @property
    def animal_count(self) -> int:
        return sum(1 for d in self.detections if d.is_animal)

    def animals(self) -> list[Detection]:
        """Return only animal detections, in order."""
        return [d for d in self.detections if d.is_animal]

    def filter_by_conf(self, min_conf: float) -> "ImageDetectionResult":
        """
        Return a *new* ImageDetectionResult with only detections whose
        detector_conf >= min_conf.  The original result is not modified,
        preserving raw model outputs.

        Each Detection in the returned result is an independent deep copy:
        mutating its fields or nested SpeciesClassification lists will NOT
        affect the original result.  Status, image metadata, device
        information and timing fields are copied from the original.
        """
        filtered = [
            copy.deepcopy(d)
            for d in self.detections
            if d.detector_conf >= min_conf
        ]
        import dataclasses
        return dataclasses.replace(self, detections=filtered)


# ---------------------------------------------------------------------------
# Abstract detector interface
# ---------------------------------------------------------------------------

class BaseDetector(ABC):
    """
    Abstract base class for all WILDSCOPE animal detectors.

    Implementors must override `detect_batch`.  `detect` is a convenience
    wrapper around `detect_batch` for single-image use.

    The interface deliberately hides all model-specific details.  Callers
    receive only `ImageDetectionResult` objects containing `Detection` items.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        image_path: str | Path,
        min_conf: float = 0.0,
    ) -> ImageDetectionResult:
        """
        Run detection on a single image.

        Parameters
        ----------
        image_path:
            Absolute path to the image file.
        min_conf:
            Minimum detector confidence.  0.0 = return everything the model
            produced (raw outputs preserved).  Apply filtering at call time
            rather than baking in a threshold.

        Returns
        -------
        ImageDetectionResult
            Status is OK even if the detection list is empty.
        """
        results = self.detect_batch([image_path], min_conf=min_conf)
        return results[0]

    @abstractmethod
    def detect_batch(
        self,
        image_paths: list[str | Path],
        min_conf: float = 0.0,
    ) -> list[ImageDetectionResult]:
        """
        Run detection on a list of images.

        Implementations must:
        - Return one ImageDetectionResult per input path, in the same order.
        - Set status=OK even when zero detections are found.
        - Set status=LOAD_FAILURE when the image file cannot be opened.
        - Set status=INFERENCE_ERROR when the model raises an exception.
        - Never apply NMS unless documented (to avoid double-suppression).
        - Never modify the caller's list.

        Parameters
        ----------
        image_paths:
            Absolute paths to image files.
        min_conf:
            If > 0, implementations may pre-filter to this threshold.
            Callers can also filter after the fact via
            ImageDetectionResult.filter_by_conf().

        Returns
        -------
        list of ImageDetectionResult
            Same length as image_paths.
        """
        ...

    # ------------------------------------------------------------------
    # Optional hook — subclasses may override
    # ------------------------------------------------------------------

    @property
    def device(self) -> str:
        """Hardware device the detector runs on (e.g. 'cuda', 'cpu')."""
        return "unknown"

    @property
    def model_name(self) -> str:
        """Human-readable model identifier."""
        return type(self).__name__

    def __repr__(self) -> str:
        return f"{type(self).__name__}(device={self.device!r})"

