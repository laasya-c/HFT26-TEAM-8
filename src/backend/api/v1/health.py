"""Health and Diagnostics Endpoint.

Reports:
- Application status and version.
- Real database connectivity.
- Honest worker readiness: NEVER fakes worker readiness when no inference worker is active.
"""
from typing import Any, Dict
from fastapi import APIRouter, Depends, status
from src.backend.adapters.inference import inference_adapter
from src.backend.config import settings
from src.backend.core.responses import success_response

try:
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from src.backend.db.session import get_db
    HAS_DB = True
except ImportError:
    HAS_DB = False

router = APIRouter()


def check_database(db: Any = None) -> Dict[str, Any]:
    """Test actual database responsiveness."""
    if not HAS_DB or db is None:
        return {
            "status": "unavailable",
            "details": "SQLAlchemy not installed or session unavailable."
        }
    try:
        db.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "dialect": db.bind.dialect.name if db.bind else "sqlite",
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "error": str(exc),
        }


def check_worker() -> Dict[str, Any]:
    """Honest worker readiness inspection.
    
    Scientific Rule: Never claim worker readiness without an active, verified worker.
    """
    is_ready = inference_adapter.is_available()
    worker_info = inference_adapter.get_worker_status()
    return {
        "ready": is_ready,
        "status": "ready" if is_ready else "unavailable",
        "details": worker_info["message"],
    }


if HAS_DB:
    @router.get("/health", status_code=status.HTTP_200_OK, summary="System Health & Readiness")
    def get_health(db: Session = Depends(get_db)) -> Dict[str, Any]:
        """Health check verifying database connection and honest worker readiness."""
        db_health = check_database(db)
        worker_health = check_worker()

        system_status = "healthy" if db_health.get("status") == "healthy" else "degraded"

        health_data = {
            "status": system_status,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "database": db_health,
            "worker": worker_health,
        }
        return success_response(data=health_data, dataset_revision=settings.DEFAULT_DATASET_REVISION)

else:
    @router.get("/health", status_code=status.HTTP_200_OK, summary="System Health & Readiness")
    def get_health() -> Dict[str, Any]:
        """Fallback health check when database dependencies are not yet installed."""
        db_health = check_database(None)
        worker_health = check_worker()

        health_data = {
            "status": "degraded",
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "database": db_health,
            "worker": worker_health,
        }
        return success_response(data=health_data, dataset_revision=settings.DEFAULT_DATASET_REVISION)
