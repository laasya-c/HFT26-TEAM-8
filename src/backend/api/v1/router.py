"""API v1 Central Router.

Santosh owns and exposes the only /api/v1 backend for the entire platform.
In Phase 1, the health endpoint is fully implemented. Future endpoints are registered
as development placeholders that report explicit 501/503 states until their respective phases.
"""
from fastapi import APIRouter
from src.backend.api.v1 import auth, cameras, health, jobs, media, monitoring, observations, reviews, uploads

api_router = APIRouter()

# Core Endpoints
api_router.include_router(auth.router, tags=["Authentication & Access Control"])
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(uploads.router, tags=["Uploads & Ingestion"])
api_router.include_router(jobs.router, tags=["Persistent Jobs"])
api_router.include_router(media.router, tags=["Media Serving"])
api_router.include_router(observations.router, tags=["Observations & Encounters"])
api_router.include_router(reviews.router, tags=["Human Review (F20)"])
api_router.include_router(cameras.router, tags=["Camera Health & Telemetry (F07)"])
api_router.include_router(monitoring.router, tags=["Monitoring Improvement Feedback (F11)"])
