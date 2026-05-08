"""API tests — anonymous requests to catalog endpoints return 401."""

from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_BASE = "/api/v1"


def test_anonymous_list_returns_401():
    resp = APIClient().get(f"{_BASE}/products")
    assert resp.status_code == 401


def test_anonymous_create_returns_401():
    resp = APIClient().post(f"{_BASE}/products", {}, format="json")
    assert resp.status_code == 401


def test_anonymous_detail_returns_401():
    resp = APIClient().get(f"{_BASE}/products/{uuid.uuid4()}")
    assert resp.status_code == 401


def test_anonymous_patch_returns_401():
    resp = APIClient().patch(f"{_BASE}/products/{uuid.uuid4()}", {}, format="json")
    assert resp.status_code == 401


def test_anonymous_delete_returns_401():
    resp = APIClient().delete(f"{_BASE}/products/{uuid.uuid4()}")
    assert resp.status_code == 401


def test_anonymous_archive_returns_401():
    resp = APIClient().post(f"{_BASE}/products/{uuid.uuid4()}/archive")
    assert resp.status_code == 401


def test_anonymous_import_returns_401():
    resp = APIClient().post(f"{_BASE}/products/import")
    assert resp.status_code == 401
