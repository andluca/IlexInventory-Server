"""API tests for GET /api/v1/financials/margin (ILEX-008 step 4)."""

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


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _make_user(uid: int) -> types.SimpleNamespace:
    email = f"mlist_{uid}@test.invalid"
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


def _seed_product(owner_id: int, name: str = "Product") -> str:
    product_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO products (id, owner_id, sku, name, description, base_unit)
            VALUES (%s, %s, %s, %s, '', 'unit')
            """,
            (product_id, owner_id, f"M-{product_id[:8]}", name),
        )
    return product_id


def _seed_committed_so(
    owner_id: int,
    product_id: str,
    quantity: str,
    sell_price: str,
    unit_cost: str = "1.0000",
) -> str:
    """Seed a batch + committed SO for the given product. Returns so_id."""
    batch_id = str(uuid.uuid4())
    so_id = str(uuid.uuid4())
    sol_id = str(uuid.uuid4())
    qty = Decimal(quantity)
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (batch_id, owner_id, product_id, f"B-{batch_id[:8]}", Decimal(unit_cost)),
        )
        conn.execute(
            """
            INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity)
            VALUES (%s, %s, 'receipt', %s)
            """,
            (owner_id, batch_id, qty),
        )
        conn.execute(
            """
            INSERT INTO sales_orders
                   (id, owner_id, customer_name, status, committed_at)
            VALUES (%s, %s, 'ML Customer', 'committed', NOW())
            """,
            (so_id, owner_id),
        )
        conn.execute(
            """
            INSERT INTO sales_order_lines
                   (id, owner_id, sales_order_id, product_id, quantity, sell_price)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (sol_id, owner_id, so_id, product_id, qty, Decimal(sell_price)),
        )
        conn.execute(
            """
            INSERT INTO sale_allocations
                   (owner_id, sales_order_line_id, batch_id, allocated_quantity, unit_cost)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (owner_id, sol_id, batch_id, qty, Decimal(unit_cost)),
        )
    return so_id


# ---------------------------------------------------------------------------
# Brief anchor: single committed SO → correct shape
# ---------------------------------------------------------------------------

def test_margin_list_brief_example(db):
    """Brief anchor: single product → item has correct fields."""
    user = _make_user(8701)
    c = _client(user)

    product_id = _seed_product(user.id, name="Widget")
    _seed_committed_so(
        user.id, product_id,
        quantity="100.0000", sell_price="10.0000", unit_cost="1.0000",
    )

    response = c.get("/api/v1/financials/margin", {"from": _FROM, "to": _TO, "limit": "50"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["product_id"] == product_id
    assert item["product_name"] == "Widget"
    assert item["units_sold"] == "100.0000"
    assert item["revenue"] == "1000.0000"
    assert item["cogs"] == "100.0000"
    assert item["profit"] == "900.0000"
    assert item["margin_pct"] == "900.0000"
    assert data["next_cursor"] is None


# ---------------------------------------------------------------------------
# Cursor pagination: 3 products, page size 2
# ---------------------------------------------------------------------------

def test_margin_list_cursor_pagination(db):
    """Seed 3 products with distinct revenues; page limit=2 returns 2 + next_cursor."""
    user = _make_user(8702)
    c = _client(user)

    # Products with descending revenues: 3000, 2000, 1000
    for revenue_mult, name in [(300, "High"), (200, "Mid"), (100, "Low")]:
        pid = _seed_product(user.id, name=name)
        _seed_committed_so(
            user.id, pid,
            quantity="10.0000",
            sell_price=f"{revenue_mult}.0000",
            unit_cost="1.0000",
        )

    # Page 1: limit=2
    resp1 = c.get("/api/v1/financials/margin", {"from": _FROM, "to": _TO, "limit": "2"})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["items"]) == 2
    assert data1["next_cursor"] is not None

    # Items should be ordered by revenue DESC
    revenues = [Decimal(i["revenue"]) for i in data1["items"]]
    assert revenues[0] >= revenues[1]

    # Page 2: use next_cursor
    resp2 = c.get(
        "/api/v1/financials/margin",
        {"from": _FROM, "to": _TO, "limit": "2", "cursor": data1["next_cursor"]},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["items"]) == 1
    assert data2["next_cursor"] is None

    # All 3 unique products covered across both pages
    all_ids = {i["product_id"] for i in data1["items"]} | {i["product_id"] for i in data2["items"]}
    assert len(all_ids) == 3


# ---------------------------------------------------------------------------
# Validation: from > to → 400
# ---------------------------------------------------------------------------

def test_margin_list_from_gt_to_is_400(db):
    """from > to returns 400."""
    user = _make_user(8703)
    c = _client(user)

    response = c.get("/api/v1/financials/margin", {"from": "2026-05-10", "to": "2026-05-01"})
    assert response.status_code == 400
    assert response.json()["error"] == "ValidationError"


# ---------------------------------------------------------------------------
# Empty range → items=[], next_cursor=null
# ---------------------------------------------------------------------------

def test_margin_list_empty_range(db):
    """No sales in range → empty items list."""
    user = _make_user(8704)
    c = _client(user)

    response = c.get("/api/v1/financials/margin", {"from": "2020-01-01", "to": "2020-12-31"})
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["next_cursor"] is None
