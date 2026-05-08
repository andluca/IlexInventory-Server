"""API tests for commit and preview endpoints."""

from __future__ import annotations

import os
import types
import uuid
from decimal import Decimal

import psycopg
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")
_BASE = "/api/v1/sales-orders"


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _make_user(uid: int) -> types.SimpleNamespace:
    email = f"cpa_{uid}@test.invalid"
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
            (pid, owner_id, f"CPA-{pid[:8]}", f"Prod {pid[:8]}"),
        )
    return pid


def _seed_batch(owner_id: int, product_id: str, qty: str = "100.0000",
                unit_cost: str = "1.0000") -> str:
    batch_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost) VALUES (%s,%s,%s,%s,%s)",
            (batch_id, owner_id, product_id, f"B-{batch_id[:8]}", Decimal(unit_cost)),
        )
        conn.execute(
            "INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity) VALUES (%s,%s,'receipt',%s)",
            (owner_id, batch_id, Decimal(qty)),
        )
    return batch_id


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _create_so(client, product_id: str, qty: str = "100.0000", price: str = "10.0000") -> dict:
    resp = client.post(
        _BASE,
        {"customer_name": "Test Corp", "lines": [{"product_id": product_id, "quantity": qty, "sell_price": price}]},
        format="json",
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# POST /sales-orders/{id}/commit — happy path (brief anchor test)
# ---------------------------------------------------------------------------

def test_commit_happy_path_brief_example():
    """End-to-end: receive 100 @ $1, commit 100 @ $10; verify COGS + on_hand."""
    user = _make_user(9401)
    pid = _seed_product(user.id)
    batch_id = _seed_batch(user.id, pid, qty="100.0000", unit_cost="1.0000")
    so = _create_so(_client(user), pid, qty="100.0000", price="10.0000")
    so_id = so["id"]

    resp = _client(user).post(
        f"{_BASE}/{so_id}/commit",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="commit-9401",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "committed"
    assert data["committed_at"] is not None
    assert len(data["allocations"]) == 1

    alloc = data["allocations"][0]
    assert Decimal(alloc["unit_cost"]) == Decimal("1.0000")
    assert Decimal(alloc["allocated_quantity"]) == Decimal("100.0000")

    # Revenue: sell_price * qty = 10 * 100 = 1000
    line = data["lines"][0]
    revenue = Decimal(line["sell_price"]) * Decimal(line["quantity"])
    assert revenue == Decimal("1000.0000")

    # COGS: unit_cost * allocated_qty = 1 * 100 = 100
    cogs = Decimal(alloc["unit_cost"]) * Decimal(alloc["allocated_quantity"])
    assert cogs == Decimal("100.0000")

    # Profit: 900
    assert revenue - cogs == Decimal("900.0000")

    # v_stock_by_batch on-hand = 0
    with psycopg.connect(_DB_URL) as conn:
        row = conn.execute(
            "SELECT on_hand FROM v_stock_by_batch WHERE batch_id = %s",
            (batch_id,),
        ).fetchone()
    assert Decimal(str(row[0])) == Decimal("0.0000")


def test_commit_missing_idempotency_key_returns_400():
    """POST /commit without Idempotency-Key returns 400."""
    user = _make_user(9402)
    pid = _seed_product(user.id)
    _seed_batch(user.id, pid)
    so = _create_so(_client(user), pid)

    resp = _client(user).post(f"{_BASE}/{so['id']}/commit", {}, format="json")
    assert resp.status_code == 400


def test_commit_duplicate_idempotency_key_returns_cached_response():
    """Duplicate Idempotency-Key returns cached commit response."""
    user = _make_user(9403)
    pid = _seed_product(user.id)
    _seed_batch(user.id, pid, qty="100.0000")
    so = _create_so(_client(user), pid, qty="100.0000")

    resp1 = _client(user).post(
        f"{_BASE}/{so['id']}/commit", {}, format="json",
        HTTP_IDEMPOTENCY_KEY="idem-commit-9403",
    )
    assert resp1.status_code == 200

    resp2 = _client(user).post(
        f"{_BASE}/{so['id']}/commit", {}, format="json",
        HTTP_IDEMPOTENCY_KEY="idem-commit-9403",
    )
    assert resp2.status_code == 200
    assert resp1.json()["id"] == resp2.json()["id"]


def test_commit_insufficient_stock_returns_422():
    """commit with insufficient stock returns 422 InsufficientStock."""
    user = _make_user(9404)
    pid = _seed_product(user.id)
    _seed_batch(user.id, pid, qty="5.0000")
    so = _create_so(_client(user), pid, qty="10.0000")

    resp = _client(user).post(
        f"{_BASE}/{so['id']}/commit", {}, format="json",
        HTTP_IDEMPOTENCY_KEY="insufficient-9404",
    )
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"] == "InsufficientStock"


# ---------------------------------------------------------------------------
# POST /sales-orders/{id}/preview
# ---------------------------------------------------------------------------

def test_preview_returns_proposed_allocations():
    """Preview returns proposed allocations without writing anything."""
    user = _make_user(9405)
    pid = _seed_product(user.id)
    batch_id = _seed_batch(user.id, pid, qty="100.0000", unit_cost="1.0000")
    so = _create_so(_client(user), pid, qty="60.0000")

    resp = _client(user).post(f"{_BASE}/{so['id']}/preview", {}, format="json")
    assert resp.status_code == 200
    data = resp.json()
    assert "allocations" in data
    allocs = data["allocations"]
    assert len(allocs) == 1
    assert str(allocs[0]["batch_id"]) == batch_id
    assert Decimal(allocs[0]["quantity"]) == Decimal("60.0000")

    # Verify on-hand unchanged
    with psycopg.connect(_DB_URL) as conn:
        row = conn.execute(
            "SELECT on_hand FROM v_stock_by_batch WHERE batch_id = %s",
            (batch_id,),
        ).fetchone()
    assert Decimal(str(row[0])) == Decimal("100.0000")


def test_preview_insufficient_stock_returns_422():
    """Preview with insufficient stock returns 422."""
    user = _make_user(9406)
    pid = _seed_product(user.id)
    _seed_batch(user.id, pid, qty="5.0000")
    so = _create_so(_client(user), pid, qty="10.0000")

    resp = _client(user).post(f"{_BASE}/{so['id']}/preview", {}, format="json")
    assert resp.status_code == 422
