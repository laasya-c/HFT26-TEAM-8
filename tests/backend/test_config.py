"""Tests for Application Configuration."""
import pytest
from src.backend.config import settings


@pytest.mark.unit
def test_default_configuration():
    """Verify default application settings are properly loaded."""
    assert settings.APP_NAME == "WILDSCOPE AI"
    assert settings.API_V1_STR == "/api/v1"
    assert settings.DEFAULT_DATASET_REVISION == 1
    assert "sqlite" in settings.DATABASE_URL
    assert len(settings.CORS_ORIGINS) > 0
