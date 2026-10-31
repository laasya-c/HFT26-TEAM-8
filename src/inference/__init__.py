"""
WILDSCOPE — src/inference package
Exports the public inference API.

Import cost
-----------
Importing this package loads only the pure-Python abstraction layer
(base_detector.py) — no torch, no SpeciesNet, no GPU initialisation.
SpeciesNetAnimalDetector is exported but loaded lazily: torch and
SpeciesNet are imported only when the class is first accessed.
"""

from src.inference.base_detector import (
    BaseDetector,
    Detection,
    DetectionStatus,
    ImageDetectionResult,
    SpeciesClassification,
)

__all__ = [
    "BaseDetector",
    "Detection",
    "DetectionStatus",
    "ImageDetectionResult",
    "SpeciesClassification",
    "SpeciesNetAnimalDetector",   # available via lazy import — see __getattr__
]


def __getattr__(name: str):
    """Lazy import for heavyweight detector implementations (PEP 562).

    Importing src.inference does NOT load torch or SpeciesNet until a
    concrete detector class is first accessed.  This keeps the base
    abstraction types (Detection, ImageDetectionResult, …) fast to import
    for tests and utility code that never instantiates a real model.

    Usage (unchanged from eager import):
        from src.inference import SpeciesNetAnimalDetector
        detector = SpeciesNetAnimalDetector()
    """
    if name == "SpeciesNetAnimalDetector":
        from src.inference.speciesnet_detector import SpeciesNetAnimalDetector
        return SpeciesNetAnimalDetector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
