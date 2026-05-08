"""API tests for GET /api/v1/financials/dashboard?format=csv (ILEX-009 step 7)."""

from __future__ import annotations

import os
import types
import uuid
from datetime import date, timedelta
from decimal import Decimal

import psycopg
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

# Wide range covering today, within 365-day limit
_FROM = (date.today() - timedelta(days=180)).isoformat()
_TO = date.today().isoformat()

_URL = "/api/v1/financials/dashboard"


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _make_user(uid: int) -> types.SimpleNamespace:
    email = f"dashcsv_{uid}@test.invalid"
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


def _client(user: types.SimpleNamespace) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _seed_product(owner_id: int, name: str = "Widget") -> str:
    product_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO products (id, owner_id, sku, name, description, base_unit) VALUES (%s,%s,%s,%s,'','unit')",
            (product_id, owner_id, f"DASHCSV-{product_id[:8]}", name),
        )
    return product_id


def _seed_batch(owner_id: int, product_id: str, quantity: str, unit_cost: str = "1.0000") -> str:
    batch_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost) VALUES (%s,%s,%s,%s,%s)",
            (batch_id, owner_id, product_id, f"DB-{batch_id[:8]}", Decimal(unit_cost)),
        )
        conn.execute(
            "INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity) VALUES (%s,%s,'receipt',%s)",
            (owner_id, batch_id, Decimal(quantity)),
        )
    return batch_id


def _seed_committed_so(
    owner_id: int, product_id: str, batch_id: str,
    quantity: str, sell_price: str, unit_cost: str,
) -> str:
    so_id = str(uuid.uuid4())
    sol_id = str(uuid.uuid4())
    qty = Decimal(quantity)
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO sales_orders (id, owner_id, customer_name, status, committed_at) VALUES (%s,%s,'Customer','committed',NOW())",
            (so_id, owner_id),
        )
        conn.execute(
            "INSERT INTO sales_order_lines (id, owner_id, sales_order_id, product_id, quantity, sell_price) VALUES (%s,%s,%s,%s,%s,%s)",
            (sol_id, owner_id, so_id, product_id, qty, Decimal(sell_price)),
        )
        conn.execute(
            "INSERT INTO sale_allocations (owner_id, sales_order_line_id, batch_id, allocated_quantity, unit_cost) VALUES (%s,%s,%s,%s,%s)",
            (owner_id, sol_id, batch_id, qty, Decimal(unit_cost)),
        )
    return so_id


def _collect_csv(response) -> str:
    return b"".join(response.streaming_content).decode("utf-8")


# ---------------------------------------------------------------------------
# Happy path: brief fixture — CSV rows match JSON top_products
# ---------------------------------------------------------------------------

def test_dashboard_csv_brief_fixture(db):
    """CSV body has header + N rows matching JSON top_products field-by-field."""
    user = _make_user(9701)
    pid = _seed_product(user.id, name="Widget")
    bid = _seed_batch(user.id, pid, quantity="100.0000", unit_cost="1.0000")
    _seed_committed_so(user.id, pid, bid, quantity="100.0000", sell_price="10.0000", unit_cost="1.0000")

    # Get JSON variant for field-by-field comparison
    resp_json = _client(user).get(_URL, {"from": _FROM, "to": _TO, "top": "5"})
    assert resp_json.status_code == 200
    top_products = resp_json.json()["top_products"]

    resp_csv = _client(user).get(_URL, {"from": _FROM, "to": _TO, "top": "5", "format": "csv"})
    assert resp_csv.status_code == 200
    assert resp_csv["Content-Type"] == "text/csv; charset=utf-8"
    assert "dashboard-" in resp_csv["Content-Disposition"]

    body = _collect_csv(resp_csv)
    lines = body.splitlines()
    assert lines[0] == "product_id,product_name,units_sold,revenue,cogs,profit,margin_pct"
    assert len(lines) == len(top_products) + 1  # header + N rows

    # First data row matches JSON top_products[0]
    if top_products:
        fields = lines[1].split(",")
        assert str(top_products[0]["product_id"]) == fields[0]
        assert top_products[0]["product_name"] == fields[1]
        assert Decimal(top_products[0]["units_sold"]) == Decimal(fields[2])
        assert Decimal(top_products[0]["revenue"]) == Decimal(fields[3])
        assert Decimal(top_products[0]["cogs"]) == Decimal(fields[4])
        assert Decimal(top_products[0]["profit"]) == Decimal(fields[5])
        if top_products[0]["margin_pct"] is not None:
            assert Decimal(top_products[0]["margin_pct"]) == Decimal(fields[6])
        else:
            assert fields[6] == ""


# ---------------------------------------------------------------------------
# Empty range → header row only
# ---------------------------------------------------------------------------

def test_dashboard_csv_empty_range_header_only(db):
    """No sales in range → CSV has header row only."""
    user = _make_user(9702)

    resp = _client(user).get(_URL, {"from": "2020-01-01", "to": "2020-12-31", "format": "csv"})
    assert resp.status_code == 200
    body = _collect_csv(resp)
    lines = body.splitlines()
    assert len(lines) == 1
    assert lines[0] == "product_id,product_name,units_sold,revenue,cogs,profit,margin_pct"
