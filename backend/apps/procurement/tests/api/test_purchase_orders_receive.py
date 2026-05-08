"""API tests for POST /purchase-orders/{id}/receive.

ILEX-005 scope: procurement-side effects only.
Batch + movement assertions deferred to ILEX-006.

TODO(ILEX-006): Amend to verify batches and movements in DB after the
inventory service stub is replaced with the real implementation.
"""

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
_uid_counter = itertools.count(start=9100)


def _make_auth_user(uid: int) -> None:
    email = f"po_rcv_{uid}@test.invalid"
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


def _create_po(client: APIClient, product_id: str) -> dict:
    resp = client.post(
        _PO_LIST_URL,
        {
            "supplier_name": "Supplier",
            "lines": [{"product_id": product_id, "quantity": "1.0000", "unit_cost": "1.0000"}],
        },
        format="json",
    )
    assert resp.status_code == 200, resp.json()
    return resp.json()


# ---------------------------------------------------------------------------
# Missing Idempotency-Key → 400
# ---------------------------------------------------------------------------

def test_receive_missing_idempotency_key_returns_400():
    """POST /receive without Idempotency-Key → 400 ValidationError."""
    user = _fake_user()
    client = _authenticated_client(user)
    product_id = _seed_product(user.id)
    po = _create_po(client, product_id)
    line_id = po["lines"][0]["id"]

    resp = client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        {"lines": [{"line_id": line_id, "batch_code": "B-001", "expiration_date": None}]},
        format="json",
        # No HTTP_IDEMPOTENCY_KEY
    )

    assert resp.status_code == 400
    data = resp.json()
    assert data["error"] == "ValidationError"
    assert "Idempotency-Key" in data["detail"]


# ---------------------------------------------------------------------------
# Happy path receive
# ---------------------------------------------------------------------------

def test_receive_draft_po_happy_path():
    """POST /receive on draft PO → 200, status='received', received_at non-null."""
    user = _fake_user()
    client = _authenticated_client(user)
    product_id = _seed_product(user.id)
    po = _create_po(client, product_id)
    po_id = po["id"]
    line_id = po["lines"][0]["id"]
    idem_key = f"idem-happy-{uuid.uuid4().hex}"

    resp = client.post(
        f"/api/v1/purchase-orders/{po_id}/receive",
        {"lines": [{"line_id": line_id, "batch_code": "B-001", "expiration_date": "2027-12-31"}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=idem_key,
    )

    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["status"] == "received"
    assert data["received_at"] is not None


# ---------------------------------------------------------------------------
# Idempotency: same key → cached response, received_at unchanged
# ---------------------------------------------------------------------------

def test_receive_idempotency_same_key_returns_cached():
    """Same Idempotency-Key on retry returns cached body; received_at unchanged.

    Asserts idempotency via observable state: received_at is the same across
    retries (no double-execution). No spy/counter needed — DB state is the
    observable fact.
    """
    user = _fake_user()
    client = _authenticated_client(user)
    product_id = _seed_product(user.id)
    po = _create_po(client, product_id)
    po_id = po["id"]
    line_id = po["lines"][0]["id"]
    idem_key = f"idem-same-{uuid.uuid4().hex}"

    # First call
    resp1 = client.post(
        f"/api/v1/purchase-orders/{po_id}/receive",
        {"lines": [{"line_id": line_id, "batch_code": "B-001", "expiration_date": None}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=idem_key,
    )
    assert resp1.status_code == 200
    received_at_first = resp1.json()["received_at"]

    # Second call with same key → cached
    resp2 = client.post(
        f"/api/v1/purchase-orders/{po_id}/receive",
        {"lines": [{"line_id": line_id, "batch_code": "B-001", "expiration_date": None}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=idem_key,
    )
    assert resp2.status_code == 200
    received_at_second = resp2.json()["received_at"]

    # received_at unchanged — cached body returned
    assert received_at_first == received_at_second


# ---------------------------------------------------------------------------
# Different key on already-received PO → 409
# ---------------------------------------------------------------------------

def test_receive_different_key_on_received_po_returns_409():
    """New Idempotency-Key on already-received PO → 409 PurchaseOrderAlreadyReceived."""
    user = _fake_user()
    client = _authenticated_client(user)
    product_id = _seed_product(user.id)
    po = _create_po(client, product_id)
    po_id = po["id"]
    line_id = po["lines"][0]["id"]

    # First receive
    client.post(
        f"/api/v1/purchase-orders/{po_id}/receive",
        {"lines": [{"line_id": line_id, "batch_code": "B-001", "expiration_date": None}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"idem-first-{uuid.uuid4().hex}",
    )

    # Second receive with NEW key → 409
    resp = client.post(
        f"/api/v1/purchase-orders/{po_id}/receive",
        {"lines": [{"line_id": line_id, "batch_code": "B-002", "expiration_date": None}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"idem-second-{uuid.uuid4().hex}",
    )

    assert resp.status_code == 409
    assert resp.json()["error"] == "PurchaseOrderAlreadyReceived"


# ---------------------------------------------------------------------------
# Cross-owner receive → 404
# ---------------------------------------------------------------------------

def test_receive_cross_owner_returns_404():
    """POST /receive by another user → 404 PurchaseOrderNotFound (D4)."""
    user_a = _fake_user()
    user_b = _fake_user()
    client_a = _authenticated_client(user_a)
    client_b = _authenticated_client(user_b)
    product_a = _seed_product(user_a.id)

    po = _create_po(client_a, product_a)
    po_id = po["id"]
    line_id = po["lines"][0]["id"]

    resp = client_b.post(
        f"/api/v1/purchase-orders/{po_id}/receive",
        {"lines": [{"line_id": line_id, "batch_code": "B-001", "expiration_date": None}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"idem-cross-{uuid.uuid4().hex}",
    )

    assert resp.status_code == 404
    assert resp.json()["error"] == "PurchaseOrderNotFound"
