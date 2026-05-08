"""API tests — product CRUD endpoints.

Uses the idempotency test pattern: auth_user rows are pre-seeded via autocommit
psycopg so they're visible to the service's separate psycopg connection.
force_authenticate() injects the fake user into the DRF request.
"""

from __future__ import annotations

import itertools
import os
import types

import psycopg
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_BASE = "/api/v1"
_uid_counter = itertools.count(start=2000)


def _db_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


def _make_auth_user(uid: int) -> None:
    """Insert a minimal auth_user row via autocommit so it's visible cross-connection."""
    email = f"cat_{uid}@test.invalid"
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


def _fake_user(uid: int | None = None) -> types.SimpleNamespace:
    resolved = uid if uid is not None else next(_uid_counter)
    _make_auth_user(resolved)
    return types.SimpleNamespace(id=resolved, is_authenticated=True, is_active=True)


def _authed_client(user: types.SimpleNamespace | None = None) -> tuple[APIClient, types.SimpleNamespace]:
    if user is None:
        user = _fake_user()
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


def _create_product(client, sku: str = "SKU-1", name: str = "Product", base_unit: str = "ml") -> dict:
    resp = client.post(f"{_BASE}/products", {
        "sku": sku, "name": name, "description": "", "base_unit": base_unit
    }, format="json")
    assert resp.status_code == 200, resp.json()
    return resp.json()


# ---------------------------------------------------------------------------
# POST /products
# ---------------------------------------------------------------------------


def test_create_product_happy_path():
    client, _ = _authed_client()
    resp = client.post(f"{_BASE}/products", {
        "sku": "COLD-001", "name": "Cold Brew", "description": "Cold brew coffee", "base_unit": "ml"
    }, format="json")

    assert resp.status_code == 200
    data = resp.json()
    assert data["sku"] == "COLD-001"
    assert data["name"] == "Cold Brew"
    assert data["base_unit"] == "ml"
    assert data["archived_at"] is None
    assert "id" in data
    assert "created_at" in data


def test_create_product_duplicate_sku_returns_409():
    client, _ = _authed_client()
    client.post(f"{_BASE}/products", {"sku": "DUPE", "name": "First", "base_unit": "g"}, format="json")
    resp = client.post(f"{_BASE}/products", {"sku": "DUPE", "name": "Second", "base_unit": "g"}, format="json")

    assert resp.status_code == 409
    assert resp.json()["error"] == "DuplicateSKU"


def test_create_product_bad_base_unit_returns_400():
    client, _ = _authed_client()
    resp = client.post(f"{_BASE}/products", {
        "sku": "S1", "name": "N", "base_unit": "GALLON"
    }, format="json")

    assert resp.status_code == 400
    data = resp.json()
    assert "fields" in data
    assert "base_unit" in data["fields"]


# ---------------------------------------------------------------------------
# GET /products/{id}
# ---------------------------------------------------------------------------


def test_get_product_happy_path():
    client, _ = _authed_client()
    product = _create_product(client, sku="GET-001")
    product_id = product["id"]

    resp = client.get(f"{_BASE}/products/{product_id}")

    assert resp.status_code == 200
    assert resp.json()["sku"] == "GET-001"


def test_get_product_cross_owner_returns_404():
    """Cross-owner GET must return 404, not 403 (D4)."""
    client_a, _ = _authed_client()
    client_b, _ = _authed_client()

    product = _create_product(client_a, sku="CROSS-001")
    product_id = product["id"]

    resp = client_b.get(f"{_BASE}/products/{product_id}")

    assert resp.status_code == 404
    assert resp.json()["error"] == "ProductNotFound"


# ---------------------------------------------------------------------------
# PATCH /products/{id}
# ---------------------------------------------------------------------------


def test_patch_product_updates_name():
    client, _ = _authed_client()
    product = _create_product(client, sku="PATCH-001", name="Original")
    product_id = product["id"]

    resp = client.patch(f"{_BASE}/products/{product_id}", {"name": "Updated"}, format="json")

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated"
    assert data["description"] == ""  # unchanged


def test_patch_product_with_sku_key_returns_400():
    """PATCH with `sku` key is rejected by serializer (strict mode)."""
    client, _ = _authed_client()
    product = _create_product(client, sku="PATCH-002")
    product_id = product["id"]

    resp = client.patch(f"{_BASE}/products/{product_id}", {"sku": "NEW-SKU"}, format="json")

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /products/{id}/archive
# ---------------------------------------------------------------------------


def test_archive_product_without_batches_returns_409():
    """archive without batches raises ProductHasNoBatches."""
    client, _ = _authed_client()
    product = _create_product(client, sku="ARCH-001")
    product_id = product["id"]

    resp = client.post(f"{_BASE}/products/{product_id}/archive")

    assert resp.status_code == 409
    assert resp.json()["error"] == "ProductHasNoBatches"


# ---------------------------------------------------------------------------
# DELETE /products/{id}
# ---------------------------------------------------------------------------


def test_delete_product_removes_it():
    client, _ = _authed_client()
    product = _create_product(client, sku="DEL-API-001")
    product_id = product["id"]

    del_resp = client.delete(f"{_BASE}/products/{product_id}")
    assert del_resp.status_code == 204

    get_resp = client.get(f"{_BASE}/products/{product_id}")
    assert get_resp.status_code == 404
