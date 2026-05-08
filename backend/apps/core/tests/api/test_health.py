"""API tests for GET /api/v1/health.

Tests:
- Healthy: Postgres up → 200, {"status": "ok", "checks": {"postgres": "ok"}}
- Degraded: unreachable port → 503, {"status": "degraded", "checks": {"postgres": "down"}}
"""

from __future__ import annotations

import pytest
from django.test import override_settings
from rest_framework.test import APIClient


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def test_health_returns_200_when_postgres_up(client: APIClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["checks"]["postgres"] == "ok"


def test_health_response_is_json(client: APIClient) -> None:
    response = client.get("/api/v1/health")
    assert "application/json" in response["Content-Type"]


def test_health_returns_503_when_postgres_unreachable(client: APIClient) -> None:
    # Point DATABASE_URL at a closed port so psycopg raises OperationalError.
    # override_settings patches django.conf.settings, which HealthView reads.
    with override_settings(
        DATABASE_URL="postgresql://postgres:postgres@localhost:1/ilex_test"
    ):
        response = client.get("/api/v1/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["checks"]["postgres"] == "down"
