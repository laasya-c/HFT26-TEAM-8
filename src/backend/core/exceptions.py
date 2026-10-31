"""Standard Error Handling & Custom Exceptions.

Per WILDSCOPE Solution Guide (p. 20):
Standard error response envelope:
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Description",
    "details": {}
  },
  "request_id": "request-id"
}
"""
import logging
import uuid
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.backend.config import settings

logger = logging.getLogger("wildscope.exceptions")

# RFC 9110 status code constant (avoids StarletteDeprecationWarning for HTTP_422_UNPROCESSABLE_ENTITY)
HTTP_422_UNPROCESSABLE = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


class WildscopeException(Exception):
    """Base exception for all WILDSCOPE domain errors."""
    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_SERVER_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class ConflictException(WildscopeException):
    """Raised on stale review collision (HTTP 409)."""
    def __init__(
        self,
        message: str = "Stale dataset revision conflict. Please refresh and retry.",
        expected_revision: Optional[int] = None,
        current_revision: Optional[int] = None,
    ):
        details = {}
        if expected_revision is not None:
            details["expected_revision"] = expected_revision
        if current_revision is not None:
            details["current_revision"] = current_revision
        super().__init__(
            message=message,
            code="STALE_REVISION_CONFLICT",
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class EntityNotFoundException(WildscopeException):
    """Raised when an image, encounter, or detection is not found (HTTP 404)."""
    def __init__(self, entity_name: str, entity_id: str):
        super().__init__(
            message=f"{entity_name} with ID '{entity_id}' not found.",
            code=f"{entity_name.upper()}_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"entity": entity_name, "id": entity_id},
        )


class ModuleUnavailableException(WildscopeException):
    """Raised when an external module (e.g. GPU inference or spatial engine) is unlinked (HTTP 503)."""
    def __init__(self, module_name: str, reason: str):
        super().__init__(
            message=f"Module '{module_name}' is currently unavailable: {reason}",
            code="MODULE_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"module": module_name, "reason": reason},
        )


class ValidationException(WildscopeException):
    """Raised on semantic domain validation failures (HTTP 422)."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="DOMAIN_VALIDATION_ERROR",
            status_code=HTTP_422_UNPROCESSABLE,
            details=details or {},
        )


class AuthenticationException(WildscopeException):
    """Raised on authentication failures, missing credentials, or expired tokens (HTTP 401)."""
    def __init__(
        self,
        message: str = "Authentication credentials were not provided or are invalid.",
        code: str = "AUTHENTICATION_FAILED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_401_UNAUTHORIZED,
            details=details or {},
        )


class ForbiddenException(WildscopeException):
    """Raised on authorization failures, role restrictions, or disabled accounts (HTTP 403)."""
    def __init__(
        self,
        message: str = "You do not have permission to perform this action.",
        code: str = "INSUFFICIENT_PERMISSIONS",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_403_FORBIDDEN,
            details=details or {},
        )


def make_json_safe(obj: Any) -> Any:
    """Recursively converts non-serializable objects (e.g. Exceptions in Pydantic ctx) into JSON-safe primitives."""
    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return [make_json_safe(item) for item in obj]
    elif isinstance(obj, Exception):
        return str(obj)
    elif isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    else:
        return str(obj)


def register_exception_handlers(app: FastAPI) -> None:
    """Register uniform error response handlers with FastAPI."""

    @app.exception_handler(WildscopeException)
    async def wildscope_exception_handler(request: Request, exc: WildscopeException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": make_json_safe(exc.details),
                },
                "request_id": request_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        safe_errors = make_json_safe(exc.errors())
        return JSONResponse(
            status_code=HTTP_422_UNPROCESSABLE,
            content={
                "error": {
                    "code": "REQUEST_VALIDATION_FAILED",
                    "message": "The incoming payload failed schema validation.",
                    "details": {"errors": safe_errors},
                },
                "request_id": request_id,
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.exception(f"Unhandled server error [request_id={request_id}]: {exc}")

        details: Dict[str, Any] = {"error_type": type(exc).__name__}
        if getattr(settings, "DEBUG", False):
            details["description"] = str(exc)

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected server error occurred.",
                    "details": details,
                },
                "request_id": request_id,
            },
        )
