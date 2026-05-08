"""API tests for GET /api/v1/batches/{id}/recall-report (ILEX-009 step 3)."""

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


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _make_user(uid: int) -> types.SimpleNamespace:
    email = f"rr_{uid}@test.invalid"
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
            (pid, owner_id, f"RR-{pid[:8]}", f"RR Prod {pid[:8]}"),
        )
    return pid


def _seed_batch(owner_id: int, product_id: str, quantity: str = "200.0000") -> str:
    bid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost) VALUES (%s,%s,%s,%s,%s)",
            (bid, owner_id, product_id, f"RR-{bid[:8]}", Decimal("1.0000")),
        )
        conn.execute(
            "INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity) VALUES (%s,%s,'receipt',%s)",
            (owner_id, bid, Decimal(quantity)),
        )
    return bid


def _seed_committed_so(
    owner_id: int,
    product_id: str,
    batch_id: str,
    quantity: str,
    customer_name: str = "Acme Corp",
    customer_contact: str = "ops@acme.com",
) -> str:
    so_id = str(uuid.uuid4())
    sol_id = str(uuid.uuid4())
    qty = Decimal(quantity)
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO sales_orders
                   (id, owner_id, customer_name, customer_contact, status, committed_at)
            VALUES (%s, %s, %s, %s, 'committed', NOW())
            """,
            (so_id, owner_id, customer_name, customer_contact),
        )
        conn.execute(
            """
            INSERT INTO sales_order_lines
                   (id, owner_id, sales_order_id, product_id, quantity, sell_price)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (sol_id, owner_id, so_id, product_id, qty, Decimal("10.0000")),
        )
        conn.execute(
            """
            INSERT INTO sale_allocations
                   (owner_id, sales_order_line_id, batch_id, allocated_quantity, unit_cost)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (owner_id, sol_id, batch_id, qty, Decimal("1.0000")),
        )
    return so_id


def _void_so(so_id: str) -> None:
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "UPDATE sales_orders SET voided_at = NOW() WHERE id = %s",
            (so_id,),
        )


def _client(user: types.SimpleNamespace) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _url(batch_id: str) -> str:
    return f"/api/v1/batches/{batch_id}/recall-report"


# ---------------------------------------------------------------------------
# Happy path: brief fixture
# ---------------------------------------------------------------------------

def test_recall_report_brief_fixture(db):
    """One committed SO of 100 units → items list has that SO with correct shape."""
    user = _make_user(9301)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid)
    so_id = _seed_committed_so(
        user.id, pid, bid,
        quantity="100.0000",
        customer_name="Acme Corp",
        customer_contact="ops@acme.com",
    )

    resp = _client(user).get(_url(bid), {"limit": 50, "offset": 0})
    assert resp.status_code == 200
    data = resp.json()

    assert data["total"] == 1
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert len(data["items"]) == 1

    item = data["items"][0]
    assert item["sale_order_id"] == so_id
    assert item["customer_name"] == "Acme Corp"
    assert item["customer_contact"] == "ops@acme.com"
    assert item["quantity_received"] == "100.0000"
    assert "sale_committed_at" in item


# ---------------------------------------------------------------------------
# Voided SO disappears
# ---------------------------------------------------------------------------

def test_recall_report_voided_so_excluded(db):
    """Committing then voiding an SO removes it from the recall report."""
    user = _make_user(9302)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid)
    so_id = _seed_committed_so(user.id, pid, bid, quantity="50.0000")
    _void_so(so_id)

    resp = _client(user).get(_url(bid))
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


# ---------------------------------------------------------------------------
# Cross-owner batch → 404
# ---------------------------------------------------------------------------

def test_recall_report_cross_owner_batch_returns_404(db):
    """Recall report for a batch owned by another user returns 404."""
    owner_a = _make_user(9303)
    owner_b = _make_user(9304)
    pid_a = _seed_product(owner_a.id)
    bid_a = _seed_batch(owner_a.id, pid_a)

    # owner_b tries to read owner_a's batch recall report
    resp = _client(owner_b).get(_url(bid_a))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Unauthenticated → 401
# ---------------------------------------------------------------------------

def test_recall_report_unauthenticated_returns_401(db):
    """Unauthenticated request returns 401."""
    fake_batch_id = str(uuid.uuid4())
    resp = APIClient().get(_url(fake_batch_id))
    assert resp.status_code == 401
