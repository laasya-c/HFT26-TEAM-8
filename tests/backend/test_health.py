"""Tests for the System Health Endpoint (GET /api/v1/health)."""
import pytest
from starlette.testclient import TestClient


@pytest.mark.unit
def test_health_endpoint_structure(client: TestClient):
    """Verify health endpoint returns standard envelope and 200 status."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    payload = response.json()
    assert "data" in payload
    assert "meta" in payload
    assert "dataset_revision" in payload["meta"]

    data = payload["data"]
    assert "status" in data
    assert "version" in data
    assert "database" in data
    assert "worker" in data


@pytest.mark.unit
def test_health_worker_readiness_honesty(client: TestClient):
    """Verify that worker readiness is NEVER faked when no worker is active."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    worker = response.json()["data"]["worker"]
    # Scientific Rule: Never report worker ready when none exists
    assert worker["ready"] is False
    assert worker["status"] == "unavailable"
