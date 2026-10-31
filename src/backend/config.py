"""WILDSCOPE Application Configuration.

Manages runtime settings, database paths, storage roots, and environment flags.
Loads from environment variables or .env file with sensible defaults for local development.
"""
import os
from pathlib import Path
from typing import List

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    HAS_SETTINGS = True
except ImportError:
    from pydantic import BaseModel
    HAS_SETTINGS = False


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


if HAS_SETTINGS:
    class Settings(BaseSettings):
        """Standard application settings with pydantic-settings."""
        model_config = SettingsConfigDict(
            env_file=str(REPO_ROOT / ".env"),
            env_file_encoding="utf-8",
            extra="ignore",
        )

        APP_NAME: str = "WILDSCOPE AI"
        APP_VERSION: str = "0.1.0"
        API_V1_STR: str = "/api/v1"
        DEBUG: bool = True
        ENVIRONMENT: str = "development"

        # Database Configuration
        # Defaults to local SQLite in repository root
        DATABASE_URL: str = f"sqlite:///{REPO_ROOT / 'wildscope.db'}"

        # Media Storage Root (files stored on disk, never in database rows)
        STORAGE_ROOT: str = str(REPO_ROOT / "storage")

        # Initial Dataset Revision
        DEFAULT_DATASET_REVISION: int = 1

        # Camera Telemetry Freshness Window (F07)
        CAMERA_TELEMETRY_FRESHNESS_HOURS: float = 24.0

        # CORS Allowed Origins
        CORS_ORIGINS: List[str] = [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]

        # Security & JWT Authentication Configuration
        JWT_SECRET_KEY: str = "wildscope-development-secret-key-replace-in-production-min32chars"
        JWT_ALGORITHM: str = "HS256"
        ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
        REFRESH_TOKEN_EXPIRE_DAYS: int = 7
        COOKIE_SECURE: bool = False
        COOKIE_SAMESITE: str = "lax"
        REFRESH_COOKIE_NAME: str = "wildscope_refresh_token"
        CSRF_HEADER_NAME: str = "x-requested-with"

else:
    class Settings(BaseModel):  # type: ignore[no-redef]
        """Fallback configuration class when pydantic-settings is not installed."""
        APP_NAME: str = os.getenv("APP_NAME", "WILDSCOPE AI")
        APP_VERSION: str = os.getenv("APP_VERSION", "0.1.0")
        API_V1_STR: str = os.getenv("API_V1_STR", "/api/v1")
        DEBUG: bool = os.getenv("DEBUG", "true").lower() in ("true", "1")
        ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

        DATABASE_URL: str = os.getenv(
            "DATABASE_URL",
            f"sqlite:///{REPO_ROOT / 'wildscope.db'}"
        )
        STORAGE_ROOT: str = os.getenv("STORAGE_ROOT", str(REPO_ROOT / "storage"))
        DEFAULT_DATASET_REVISION: int = int(os.getenv("DEFAULT_DATASET_REVISION", "1"))
        CAMERA_TELEMETRY_FRESHNESS_HOURS: float = float(os.getenv("CAMERA_TELEMETRY_FRESHNESS_HOURS", "24.0"))
        CORS_ORIGINS: List[str] = [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]

        # Security & JWT Authentication Configuration
        JWT_SECRET_KEY: str = os.getenv(
            "JWT_SECRET_KEY",
            "wildscope-development-secret-key-replace-in-production-min32chars"
        )
        JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
        ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
        REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
        COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1")
        COOKIE_SAMESITE: str = os.getenv("COOKIE_SAMESITE", "lax")
        REFRESH_COOKIE_NAME: str = os.getenv("REFRESH_COOKIE_NAME", "wildscope_refresh_token")
        CSRF_HEADER_NAME: str = os.getenv("CSRF_HEADER_NAME", "x-requested-with")


# Singleton instance
settings = Settings()
