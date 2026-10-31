"""WILDSCOPE Shared Data Contracts.

NOTICE: This package contains draft Pydantic contract definitions and shared schemas
for cross-module communication between Backend (Santosh), Inference (Harsh),
Intelligence (Shravan), and Frontend (Laasya).

These schemas are INITIAL PROPOSALS pending review and team signoff.
"""
from .schemas import (
    AnalysisResultContract,
    CameraContract,
    DetectionContract,
    EncounterContract,
    ImageFrameContract,
    ProvenanceEnum,
    ReviewEventContract,
    ReviewStatusEnum,
    TelemetryStatusEnum,
)

__all__ = [
    "ProvenanceEnum",
    "ReviewStatusEnum",
    "TelemetryStatusEnum",
    "ImageFrameContract",
    "DetectionContract",
    "EncounterContract",
    "CameraContract",
    "ReviewEventContract",
    "AnalysisResultContract",
]
