"""API tests for GET /batches/{id}/recall-report?format=csv (ILEX-009 step 5)."""

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
# Seed helpers (same as test_recall_report.py)
# ---------------------------------------------------------------------------

def _make_user(uid: int) -> types.SimpleNamespace:
    email = f"rrcsv_{uid}@test.invalid"
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
            (pid, owner_id, f"RRCSV-{pid[:8]}", f"RRCSVProd {pid[:8]}"),
        )
    return pid


def _seed_batch(owner_id: int, product_id: str) -> str:
    bid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost) VALUES (%s,%s,%s,%s,%s)",
            (bid, owner_id, product_id, f"RRCSV-{bid[:8]}", Decimal("1.0000")),
        )
        conn.execute(
            "INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity) VALUES (%s,%s,'receipt',%s)",
            (owner_id, bid, Decimal("200.0000")),
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


def _client(user: types.SimpleNamespace) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _url(batch_id: str) -> str:
    return f"/api/v1/batches/{batch_id}/recall-report"


def _collect_csv(response) -> str:
    return b"".join(response.streaming_content).decode("utf-8")


# ---------------------------------------------------------------------------
# Happy path: 1 row → 2 lines (header + data)
# ---------------------------------------------------------------------------

def test_recall_report_csv_brief_fixture(db):
    """1 committed SO → CSV has 2 lines (header + 1 row) with correct values."""
    user = _make_user(9501)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid)
    _seed_committed_so(
        user.id, pid, bid,
        quantity="100.0000",
        customer_name="Acme Corp",
        customer_contact="ops@acme.com",
    )

    resp = _client(user).get(_url(bid), {"format": "csv"})
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv; charset=utf-8"
    assert f"recall-report-{bid}" in resp["Content-Disposition"]

    body = _collect_csv(resp)
    lines = body.splitlines()
    assert lines[0] == "sale_order_id,customer_name,customer_contact,quantity_received,sale_committed_at"
    assert len(lines) == 2

    # quantity_received must preserve 4 decimal places
    fields = lines[1].split(",")
    qty_idx = 3
    assert fields[qty_idx] == "100.0000"

    # sale_committed_at must be ISO-8601
    committed_at_idx = 4
    assert "T" in fields[committed_at_idx]


# ---------------------------------------------------------------------------
# Empty result → header row only
# ---------------------------------------------------------------------------

def test_recall_report_csv_empty_result_header_only(db):
    """Batch with no committed SOs → CSV has only the header line."""
    user = _make_user(9502)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid)

    resp = _client(user).get(_url(bid), {"format": "csv"})
    assert resp.status_code == 200
    body = _collect_csv(resp)
    lines = body.splitlines()
    assert len(lines) == 1
    assert lines[0] == "sale_order_id,customer_name,customer_contact,quantity_received,sale_committed_at"


# ---------------------------------------------------------------------------
# Cross-owner batch → 404
# ---------------------------------------------------------------------------

def test_recall_report_csv_cross_owner_returns_404(db):
    """CSV path: cross-owner batch → 404 (same precheck as JSON path)."""
    owner_a = _make_user(9503)
    owner_b = _make_user(9504)
    pid_a = _seed_product(owner_a.id)
    bid_a = _seed_batch(owner_a.id, pid_a)

    resp = _client(owner_b).get(_url(bid_a), {"format": "csv"})
    assert resp.status_code == 404
