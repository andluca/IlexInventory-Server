"""API tests for sales order CRUD (list, create, detail, PATCH, DELETE)."""

from __future__ import annotations

import os
import types
import uuid

import psycopg
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")
_URL = "/api/v1/sales-orders"


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _make_user(uid: int) -> types.SimpleNamespace:
    email = f"soa_{uid}@test.invalid"
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
    return types.SimpleNamespace(id=uid, is_authenticated=True, is_active=True)


def _seed_product(owner_id: int) -> str:
    pid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO products (id, owner_id, sku, name, description, base_unit) VALUES (%s,%s,%s,%s,'','unit')",
            (pid, owner_id, f"SLA-{pid[:8]}", f"Prod {pid[:8]}"),
        )
    return pid


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _create_payload(product_id: str, qty: str = "10.0000", price: str = "5.0000") -> dict:
    return {
        "customer_name": "Acme Corp",
        "customer_contact": "ops@acme.test",
        "lines": [{"product_id": product_id, "quantity": qty, "sell_price": price}],
    }


# ---------------------------------------------------------------------------
# POST /sales-orders — create draft
# ---------------------------------------------------------------------------

def test_post_creates_draft_so():
    """POST /sales-orders creates a draft SO; returns 201 with correct structure."""
    user = _make_user(9101)
    pid = _seed_product(user.id)

    resp = _client(user).post(_URL, _create_payload(pid), format="json")
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "draft"
    assert data["customer_name"] == "Acme Corp"
    assert len(data["lines"]) == 1
    assert data["allocations"] == []


def test_post_empty_lines_returns_400():
    """POST with empty lines returns 400."""
    user = _make_user(9102)

    resp = _client(user).post(
        _URL,
        {"customer_name": "Test", "lines": []},
        format="json",
    )
    assert resp.status_code == 400


def test_post_zero_quantity_returns_400():
    """POST with quantity <= 0 returns 400 (serializer-level check)."""
    user = _make_user(9103)
    pid = _seed_product(user.id)

    resp = _client(user).post(
        _URL,
        {"customer_name": "Test", "lines": [{"product_id": pid, "quantity": "0", "sell_price": "5"}]},
        format="json",
    )
    assert resp.status_code == 400


def test_post_negative_price_returns_400():
    """POST with sell_price < 0 returns 400 (serializer-level check)."""
    user = _make_user(9104)
    pid = _seed_product(user.id)

    resp = _client(user).post(
        _URL,
        {"customer_name": "Test", "lines": [{"product_id": pid, "quantity": "1", "sell_price": "-1"}]},
        format="json",
    )
    assert resp.status_code == 400


def test_post_cross_owner_product_returns_404():
    """POST referencing another owner's product returns 404 (D4)."""
    user_a = _make_user(9105)
    user_b = _make_user(9106)
    pid_a = _seed_product(user_a.id)

    resp = _client(user_b).post(
        _URL,
        _create_payload(pid_a),
        format="json",
    )
    assert resp.status_code == 404


def test_post_unauthenticated_returns_403():
    """POST without authentication returns 403."""
    resp = APIClient().post(_URL, {"customer_name": "x", "lines": []}, format="json")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /sales-orders — list
# ---------------------------------------------------------------------------

def test_get_list_returns_own_sos():
    """GET /sales-orders returns only the authenticated owner's SOs."""
    user_a = _make_user(9107)
    user_b = _make_user(9108)
    pid_a = _seed_product(user_a.id)

    _client(user_a).post(_URL, _create_payload(pid_a), format="json")

    resp = _client(user_b).get(_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    # user_b sees 0 items (their own, which is 0)
    for item in data["items"]:
        assert item["owner_id"] == user_b.id


# ---------------------------------------------------------------------------
# GET /sales-orders/{id} — detail
# ---------------------------------------------------------------------------

def test_get_detail_returns_so():
    """GET /sales-orders/{id} returns the SO with lines and empty allocations."""
    user = _make_user(9109)
    pid = _seed_product(user.id)
    create_resp = _client(user).post(_URL, _create_payload(pid), format="json")
    so_id = create_resp.json()["id"]

    resp = _client(user).get(f"{_URL}/{so_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == so_id
    assert len(data["lines"]) == 1
    assert data["allocations"] == []


def test_get_detail_cross_owner_returns_404():
    """GET /sales-orders/{id} cross-owner returns 404 (D4)."""
    user_a = _make_user(9110)
    user_b = _make_user(9111)
    pid_a = _seed_product(user_a.id)
    create_resp = _client(user_a).post(_URL, _create_payload(pid_a), format="json")
    so_id = create_resp.json()["id"]

    resp = _client(user_b).get(f"{_URL}/{so_id}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /sales-orders/{id} — update draft
# ---------------------------------------------------------------------------

def test_patch_updates_customer_name():
    """PATCH updates customer_name on a draft SO."""
    user = _make_user(9112)
    pid = _seed_product(user.id)
    create_resp = _client(user).post(_URL, _create_payload(pid), format="json")
    so_id = create_resp.json()["id"]

    resp = _client(user).patch(f"{_URL}/{so_id}", {"customer_name": "New Name"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["customer_name"] == "New Name"


def test_patch_committed_so_returns_409():
    """PATCH a committed SO returns 409."""
    user = _make_user(9113)
    pid = _seed_product(user.id)
    so_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO sales_orders (id, owner_id, customer_name, status, committed_at) VALUES (%s,%s,'Test','committed',NOW())",
            (so_id, user.id),
        )
        conn.execute(
            "INSERT INTO sales_order_lines (owner_id, sales_order_id, product_id, quantity, sell_price) VALUES (%s,%s,%s,1,1)",
            (user.id, so_id, pid),
        )

    resp = _client(user).patch(f"{_URL}/{so_id}", {"customer_name": "Updated"}, format="json")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /sales-orders/{id} — delete draft
# ---------------------------------------------------------------------------

def test_delete_draft_returns_204():
    """DELETE /sales-orders/{id} deletes draft; returns 204."""
    user = _make_user(9114)
    pid = _seed_product(user.id)
    create_resp = _client(user).post(_URL, _create_payload(pid), format="json")
    so_id = create_resp.json()["id"]

    resp = _client(user).delete(f"{_URL}/{so_id}")
    assert resp.status_code == 204

    get_resp = _client(user).get(f"{_URL}/{so_id}")
    assert get_resp.status_code == 404


def test_delete_committed_so_returns_409():
    """DELETE a committed SO returns 409."""
    user = _make_user(9115)
    pid = _seed_product(user.id)
    so_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO sales_orders (id, owner_id, customer_name, status, committed_at) VALUES (%s,%s,'Test','committed',NOW())",
            (so_id, user.id),
        )
        conn.execute(
            "INSERT INTO sales_order_lines (owner_id, sales_order_id, product_id, quantity, sell_price) VALUES (%s,%s,%s,1,1)",
            (user.id, so_id, pid),
        )

    resp = _client(user).delete(f"{_URL}/{so_id}")
    assert resp.status_code == 409
