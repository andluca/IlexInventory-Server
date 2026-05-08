"""API tests for GET /purchase-orders list endpoint."""

from __future__ import annotations

import itertools
import os
import types
import uuid

import psycopg
import pytest
from rest_framework.test import APIClient, force_authenticate

pytestmark = pytest.mark.django_db

_PO_LIST_URL = "/api/v1/purchase-orders"
_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")
_uid_counter = itertools.count(start=8000)


def _make_auth_user(uid: int) -> None:
    email = f"po_list_{uid}@test.invalid"
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO auth_user (id, username, email, password,
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


def _seed_product(owner_id: int) -> str:
    product_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO products (id, owner_id, sku, name, description, base_unit)
            VALUES (%s, %s, %s, %s, '', 'unit')
            """,
            (product_id, owner_id, f"SKU-{product_id[:8]}", f"Prod {product_id[:8]}"),
        )
    return product_id


def _authenticated_client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _create_po(client: APIClient, product_id: str, supplier_name: str = "Supplier") -> dict:
    resp = client.post(
        _PO_LIST_URL,
        {
            "supplier_name": supplier_name,
            "lines": [{"product_id": product_id, "quantity": "1.0000", "unit_cost": "1.0000"}],
        },
        format="json",
    )
    assert resp.status_code == 200, resp.json()
    return resp.json()


# ---------------------------------------------------------------------------
# Empty list
# ---------------------------------------------------------------------------

def test_list_empty_returns_empty():
    """GET /purchase-orders for fresh user → empty list."""
    user = _fake_user()
    client = _authenticated_client(user)

    resp = client.get(_PO_LIST_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


# ---------------------------------------------------------------------------
# Status filter
# ---------------------------------------------------------------------------

def test_list_status_filter():
    """?status=draft returns only drafts."""
    user = _fake_user()
    client = _authenticated_client(user)
    p1 = _seed_product(user.id)
    p2 = _seed_product(user.id)
    idem_key = f"idem-list-filter-{uuid.uuid4().hex}"

    po1 = _create_po(client, p1, "Draft Supplier 1")
    po2 = _create_po(client, p2, "Draft Supplier 2")

    # Receive one of them
    line_id = po1["lines"][0]["id"]
    client.post(
        f"/api/v1/purchase-orders/{po1['id']}/receive",
        {"lines": [{"line_id": line_id, "batch_code": "B-001", "expiration_date": None}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=idem_key,
    )

    resp_draft = client.get(f"{_PO_LIST_URL}?status=draft")
    assert resp_draft.status_code == 200
    data = resp_draft.json()
    assert all(item["status"] == "draft" for item in data["items"])

    resp_rcvd = client.get(f"{_PO_LIST_URL}?status=received")
    assert resp_rcvd.status_code == 200
    assert all(item["status"] == "received" for item in resp_rcvd.json()["items"])


# ---------------------------------------------------------------------------
# Supplier search
# ---------------------------------------------------------------------------

def test_list_search_supplier():
    """?search=acme matches supplier_name ILIKE."""
    user = _fake_user()
    client = _authenticated_client(user)
    p1 = _seed_product(user.id)
    p2 = _seed_product(user.id)

    _create_po(client, p1, "Acme Corp")
    _create_po(client, p2, "Beta Suppliers")

    resp = client.get(f"{_PO_LIST_URL}?search=acme")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert "Acme" in data["items"][0]["supplier_name"]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def test_list_pagination():
    """?limit=1&offset=1 returns the second item."""
    user = _fake_user()
    client = _authenticated_client(user)
    p1 = _seed_product(user.id)
    p2 = _seed_product(user.id)

    _create_po(client, p1, "Supplier One")
    _create_po(client, p2, "Supplier Two")

    resp = client.get(f"{_PO_LIST_URL}?limit=1&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 2

    resp2 = client.get(f"{_PO_LIST_URL}?limit=1&offset=1")
    data2 = resp2.json()
    assert len(data2["items"]) == 1
    assert data["items"][0]["id"] != data2["items"][0]["id"]
