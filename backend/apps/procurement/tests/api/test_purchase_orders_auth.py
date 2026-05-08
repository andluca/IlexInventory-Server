"""API auth tests for procurement endpoints.

Any procurement endpoint without session → 401.
"""

from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_ENDPOINTS = [
    ("GET", "/api/v1/purchase-orders"),
    ("POST", "/api/v1/purchase-orders"),
    ("GET", f"/api/v1/purchase-orders/{uuid.uuid4()}"),
    ("PATCH", f"/api/v1/purchase-orders/{uuid.uuid4()}"),
    ("DELETE", f"/api/v1/purchase-orders/{uuid.uuid4()}"),
    ("POST", f"/api/v1/purchase-orders/{uuid.uuid4()}/receive"),
]


@pytest.mark.parametrize("method,url", _ENDPOINTS)
def test_unauthenticated_returns_401(method: str, url: str):
    """Any procurement endpoint without session returns 401."""
    client = APIClient()
    fn = getattr(client, method.lower())
    resp = fn(url, format="json")
    assert resp.status_code == 401
