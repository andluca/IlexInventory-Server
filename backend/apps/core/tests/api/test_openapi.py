"""API tests for GET /api/v1/openapi.json (drf-spectacular schema endpoint).

Tests:
- Returns 200 with correct Content-Type
- Body is valid JSON with openapi 3.x, info.title, info.version
- /api/v1/health path is present in the schema
"""

from __future__ import annotations

import json

import pytest
from rest_framework.test import APIClient


@pytest.fixture
def client() -> APIClient:
    return APIClient()


_ACCEPT = "application/vnd.oai.openapi+json"


def _schema(client: APIClient) -> dict:
    """Fetch the schema with the correct Accept header; parse body with json.loads."""
    response = client.get("/api/v1/openapi.json", HTTP_ACCEPT=_ACCEPT)
    return json.loads(response.content)


def test_openapi_returns_200(client: APIClient) -> None:
    response = client.get("/api/v1/openapi.json", HTTP_ACCEPT=_ACCEPT)
    assert response.status_code == 200


def test_openapi_content_type(client: APIClient) -> None:
    response = client.get("/api/v1/openapi.json", HTTP_ACCEPT=_ACCEPT)
    assert "application/vnd.oai.openapi" in response["Content-Type"]


def test_openapi_body_has_openapi_31(client: APIClient) -> None:
    data = _schema(client)
    assert data.get("openapi") == "3.1.0"


def test_openapi_body_has_info_fields(client: APIClient) -> None:
    data = _schema(client)
    assert data.get("info", {}).get("title")
    assert data.get("info", {}).get("version")


def test_openapi_includes_health_path(client: APIClient) -> None:
    data = _schema(client)
    paths = data.get("paths", {})
    assert "/api/v1/health" in paths, f"Expected /api/v1/health in paths; got: {list(paths)}"
