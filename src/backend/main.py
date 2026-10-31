"""WILDSCOPE AI — Backend FastAPI Application Entrypoint.

Primary entrypoint for the WILDSCOPE REST API.
Owned exclusively by Santosh Yuvaraj.
"""
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from src.backend.api.v1.router import api_router
from src.backend.config import settings
from src.backend.core.exceptions import register_exception_handlers


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Injects a unique request ID into request.state and response headers."""
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.
    
    Alembic is the single source of truth for database schema creation and migrations.
    Application startup only verifies database connectivity and ensures storage root directories exist.
    """
    # 1. Ensure storage directories exist
    try:
        from pathlib import Path
        storage_path = Path(settings.STORAGE_ROOT)
        (storage_path / "uploads").mkdir(parents=True, exist_ok=True)
        (storage_path / "media").mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"[WILDSCOPE Startup Warning] Storage root initialization: {exc}")

    # 2. Verify database connectivity without modifying tables
    try:
        from sqlalchemy import text
        from src.backend.db.session import engine
        if engine is not None:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
    except Exception as exc:
        print(f"[WILDSCOPE Startup Warning] Database connectivity check: {exc}")
    yield


def create_application() -> FastAPI:
    """FastAPI Application Factory."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="WILDSCOPE AI — Wildlife Conservation Intelligence Platform Backend",
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
        lifespan=lifespan,
    )

    # 1. Request ID Tracking
    app.add_middleware(RequestIDMiddleware)

    # 2. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Custom Error & Exception Handlers
    register_exception_handlers(app)

    # 4. Mount API v1 Router
    app.include_router(api_router, prefix=settings.API_V1_STR)

    return app


app = create_application()
