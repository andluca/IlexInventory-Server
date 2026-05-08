"""API tests for purchase order CRUD operations.

Uses force_authenticate with pre-seeded auth_user rows (autocommit) so
the user is visible to the service's separate psycopg connections.
Mirrors the catalog API test pattern.
"""

from __future__ import annotations

import itertools
import os
import types
import uuid

import psycopg
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_PO_LIST_URL = "/api/v1/purchase-orders"
_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")
_uid_counter = itertools.count(start=7000)


def _make_auth_user(uid: int) -> None:
    """Insert a minimal auth_user row via autocommit (visible cross-connection)."""
    email = f"po_crud_{uid}@test.invalid"
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
    """Return a DRF client that's force-authenticated as user."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# POST /purchase-orders — create
# ---------------------------------------------------------------------------

def test_create_po_happy_path():
    """POST /purchase-orders with 2 lines → 200, status='draft', lines echoed."""
    user = _fake_user()
    client = _authenticated_client(user)
    p1 = _seed_product(user.id)
    p2 = _seed_product(user.id)

    resp = client.post(
        _PO_LIST_URL,
        {
            "supplier_name": "Acme Corp",
            "supplier_contact": "acme@example.com",
            "lines": [
                {"product_id": p1, "quantity": "10.0000", "unit_cost": "2.5000"},
                {"product_id": p2, "quantity": "5.0000", "unit_cost": "0.0000"},
            ],
        },
        format="json",
    )

    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["status"] == "draft"
    assert data["received_at"] is None
    assert data["supplier_name"] == "Acme Corp"
    assert len(data["lines"]) == 2
    # Money fields serialized as strings (SPEC §2.5)
    for line in data["lines"]:
        assert isinstance(line["quantity"], str)
        assert isinstance(line["unit_cost"], str)


def test_create_po_empty_lines_returns_400():
    """POST with empty lines → 400 ValidationError."""
    user = _fake_user()
    client = _authenticated_client(user)

    resp = client.post(
        _PO_LIST_URL,
        {"supplier_name": "Acme", "lines": []},
        format="json",
    )

    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data or "fields" in data


def test_create_po_unknown_product_returns_404():
    """POST with random product_id → 404 ProductNotFound."""
    user = _fake_user()
    client = _authenticated_client(user)
    random_product_id = str(uuid.uuid4())

    resp = client.post(
        _PO_LIST_URL,
        {
            "supplier_name": "Acme",
            "lines": [
                {"product_id": random_product_id, "quantity": "1.0000", "unit_cost": "1.0000"}
            ],
        },
        format="json",
    )

    assert resp.status_code == 404
    assert resp.json()["error"] == "ProductNotFound"


# ---------------------------------------------------------------------------
# GET /purchase-orders/{id} — detail
# ---------------------------------------------------------------------------

def test_get_po_by_id_happy_path():
    """GET /purchase-orders/{id} returns the PO."""
    user = _fake_user()
    client = _authenticated_client(user)
    product_id = _seed_product(user.id)

    create_resp = client.post(
        _PO_LIST_URL,
        {
            "supplier_name": "Supplier",
            "lines": [
                {"product_id": product_id, "quantity": "1.0000", "unit_cost": "1.0000"}
            ],
        },
        format="json",
    )
    po_id = create_resp.json()["id"]

    resp = client.get(f"/api/v1/purchase-orders/{po_id}")

    assert resp.status_code == 200
    assert resp.json()["id"] == po_id


def test_get_po_cross_owner_returns_404():
    """GET /purchase-orders/{id} by another user → 404 (D4). Mandatory owner-scope test."""
    user_a = _fake_user()
    user_b = _fake_user()
    client_a = _authenticated_client(user_a)
    client_b = _authenticated_client(user_b)
    product_a = _seed_product(user_a.id)

    create_resp = client_a.post(
        _PO_LIST_URL,
        {
            "supplier_name": "Supplier A",
            "lines": [
                {"product_id": product_a, "quantity": "1.0000", "unit_cost": "1.0000"}
            ],
        },
        format="json",
    )
    po_id = create_resp.json()["id"]

    resp = client_b.get(f"/api/v1/purchase-orders/{po_id}")

    assert resp.status_code == 404
    assert resp.json()["error"] == "PurchaseOrderNotFound"


# ---------------------------------------------------------------------------
# PATCH /purchase-orders/{id}
# ---------------------------------------------------------------------------

def test_patch_po_received_returns_409():
    """PATCH on received PO → 409 PurchaseOrderNotDraft."""
    user = _fake_user()
    client = _authenticated_client(user)
    product_id = _seed_product(user.id)
    idem_key = f"idem-patch-rcvd-{uuid.uuid4().hex}"

    create_resp = client.post(
        _PO_LIST_URL,
        {
            "supplier_name": "Supplier",
            "lines": [
                {"product_id": product_id, "quantity": "1.0000", "unit_cost": "1.0000"}
            ],
        },
        format="json",
    )
    data = create_resp.json()
    po_id = data["id"]
    line_id = data["lines"][0]["id"]

    # Receive the PO
    client.post(
        f"/api/v1/purchase-orders/{po_id}/receive",
        {"lines": [{"line_id": line_id, "batch_code": "B-001", "expiration_date": None}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=idem_key,
    )

    resp = client.patch(
        f"/api/v1/purchase-orders/{po_id}",
        {"supplier_name": "Should Fail"},
        format="json",
    )

    assert resp.status_code == 409
    assert resp.json()["error"] == "PurchaseOrderNotDraft"


def test_patch_po_unknown_field_returns_400():
    """PATCH with 'status' field → 400 ValidationError."""
    user = _fake_user()
    client = _authenticated_client(user)
    product_id = _seed_product(user.id)

    create_resp = client.post(
        _PO_LIST_URL,
        {
            "supplier_name": "Supplier",
            "lines": [
                {"product_id": product_id, "quantity": "1.0000", "unit_cost": "1.0000"}
            ],
        },
        format="json",
    )
    po_id = create_resp.json()["id"]

    resp = client.patch(
        f"/api/v1/purchase-orders/{po_id}",
        {"status": "received"},
        format="json",
    )

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /purchase-orders/{id}
# ---------------------------------------------------------------------------

def test_delete_received_po_returns_409():
    """DELETE on received PO → 409 PurchaseOrderNotDraft."""
    user = _fake_user()
    client = _authenticated_client(user)
    product_id = _seed_product(user.id)
    idem_key = f"idem-delete-rcvd-{uuid.uuid4().hex}"

    create_resp = client.post(
        _PO_LIST_URL,
        {
            "supplier_name": "Supplier",
            "lines": [
                {"product_id": product_id, "quantity": "1.0000", "unit_cost": "1.0000"}
            ],
        },
        format="json",
    )
    data = create_resp.json()
    po_id = data["id"]
    line_id = data["lines"][0]["id"]

    # Receive first
    client.post(
        f"/api/v1/purchase-orders/{po_id}/receive",
        {"lines": [{"line_id": line_id, "batch_code": "B-001", "expiration_date": None}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=idem_key,
    )

    resp = client.delete(f"/api/v1/purchase-orders/{po_id}")
    assert resp.status_code == 409
    assert resp.json()["error"] == "PurchaseOrderNotDraft"


def test_delete_draft_returns_204_then_get_returns_404():
    """DELETE a draft PO → 204; subsequent GET → 404."""
    user = _fake_user()
    client = _authenticated_client(user)
    product_id = _seed_product(user.id)

    create_resp = client.post(
        _PO_LIST_URL,
        {
            "supplier_name": "Supplier",
            "lines": [
                {"product_id": product_id, "quantity": "1.0000", "unit_cost": "1.0000"}
            ],
        },
        format="json",
    )
    po_id = create_resp.json()["id"]

    del_resp = client.delete(f"/api/v1/purchase-orders/{po_id}")
    assert del_resp.status_code == 204

    get_resp = client.get(f"/api/v1/purchase-orders/{po_id}")
    assert get_resp.status_code == 404
