"""API tests — product list endpoint."""

from __future__ import annotations

import itertools
import os
import types

import psycopg
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_BASE = "/api/v1"
_uid_counter = itertools.count(start=3000)


def _db_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


def _make_auth_user(uid: int) -> None:
    email = f"lst_{uid}@test.invalid"
    with psycopg.connect(_db_url(), autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO auth_user
                (id, username, email, password,
                 is_superuser, is_staff, is_active,
                 first_name, last_name, date_joined)
            VALUES (%s, %s, %s, 'unusable!', false, false, true, '', '', NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            (uid, email, email),
        )


def _fake_user() -> types.SimpleNamespace:
    uid = next(_uid_counter)
    _make_auth_user(uid)
    return types.SimpleNamespace(id=uid, is_authenticated=True, is_active=True)


def _authed_client() -> tuple[APIClient, types.SimpleNamespace]:
    user = _fake_user()
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


def _create_product(client, sku: str, name: str = "Product") -> dict:
    resp = client.post(f"{_BASE}/products", {
        "sku": sku, "name": name, "description": "", "base_unit": "ml"
    }, format="json")
    assert resp.status_code == 200, resp.json()
    return resp.json()


def test_list_empty_returns_zero():
    client, _ = _authed_client()
    resp = client.get(f"{_BASE}/products")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert "limit" in data
    assert "offset" in data


def test_list_archived_filter():
    """active/archived filter: archived=false returns only active products."""
    client, _ = _authed_client()
    _create_product(client, sku="LIST-001", name="Active 1")
    _create_product(client, sku="LIST-002", name="Active 2")
    _create_product(client, sku="LIST-003", name="Active 3")

    # archived=false should return all 3 (none are archived)
    resp_active = client.get(f"{_BASE}/products?archived=false")
    assert resp_active.status_code == 200
    data = resp_active.json()
    assert data["total"] == 3

    # archived=true should return 0 (none archived)
    resp_archived = client.get(f"{_BASE}/products?archived=true")
    assert resp_archived.status_code == 200
    assert resp_archived.json()["total"] == 0


def test_list_search_filters_by_name():
    client, _ = _authed_client()
    _create_product(client, sku="SRCH-001", name="Cold Brew")
    _create_product(client, sku="SRCH-002", name="Hot Latte")

    resp = client.get(f"{_BASE}/products?search=cold")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Cold Brew"


def test_list_pagination():
    client, _ = _authed_client()
    _create_product(client, sku="PAGE-001", name="Product 1")
    _create_product(client, sku="PAGE-002", name="Product 2")
    _create_product(client, sku="PAGE-003", name="Product 3")

    resp = client.get(f"{_BASE}/products?limit=1&offset=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 1
    assert data["limit"] == 1
    assert data["offset"] == 1
