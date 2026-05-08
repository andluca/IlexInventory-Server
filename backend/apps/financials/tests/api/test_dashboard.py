"""API tests for GET /api/v1/financials/dashboard (ILEX-008 step 3)."""

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
# Auth/session helpers
# ---------------------------------------------------------------------------

def _make_user(uid: int) -> types.SimpleNamespace:
    email = f"dash_{uid}@test.invalid"
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
            """
            INSERT INTO products (id, owner_id, sku, name, description, base_unit)
            VALUES (%s, %s, %s, %s, '', 'unit')
            """,
            (product_id, owner_id, f"D-{product_id[:8]}", name),
        )
    return product_id


def _seed_batch(owner_id: int, product_id: str, quantity: str, unit_cost: str = "1.0000") -> str:
    batch_id = str(uuid.uuid4())
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
            (owner_id, batch_id, Decimal(quantity)),
        )
    return batch_id


def _seed_committed_so(
    owner_id: int,
    product_id: str,
    batch_id: str,
    quantity: str,
    sell_price: str,
    unit_cost: str,
) -> str:
    so_id = str(uuid.uuid4())
    sol_id = str(uuid.uuid4())
    qty = Decimal(quantity)
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO sales_orders
                   (id, owner_id, customer_name, status, committed_at)
            VALUES (%s, %s, 'Test Customer', 'committed', NOW())
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


def _void_so(so_id: str) -> None:
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "UPDATE sales_orders SET voided_at = NOW() WHERE id = %s",
            (so_id,),
        )


# ---------------------------------------------------------------------------
# Happy path: brief example
# ---------------------------------------------------------------------------

def test_dashboard_brief_example(db):
    """Brief anchor: 100 units @ $1 received, 100 sold @ $10 → 1000/100/900/900%."""
    user = _make_user(8801)
    c = _client(user)

    product_id = _seed_product(user.id, name="Widget")
    batch_id = _seed_batch(user.id, product_id, quantity="100.0000", unit_cost="1.0000")
    _seed_committed_so(
        user.id, product_id, batch_id,
        quantity="100.0000", sell_price="10.0000", unit_cost="1.0000",
    )

    response = c.get("/api/v1/financials/dashboard", {"from": _FROM, "to": _TO})
    assert response.status_code == 200
    data = response.json()

    totals = data["totals"]
    assert totals["revenue"] == "1000.0000"
    assert totals["cogs"] == "100.0000"
    assert totals["profit"] == "900.0000"
    assert totals["margin_pct"] == "900.0000"

    assert len(data["top_products"]) == 1
    prod = data["top_products"][0]
    assert prod["product_name"] == "Widget"
    assert prod["revenue"] == "1000.0000"
    assert prod["cogs"] == "100.0000"
    assert prod["profit"] == "900.0000"
    assert prod["margin_pct"] == "900.0000"


# ---------------------------------------------------------------------------
# Empty range → all zero, margin_pct null
# ---------------------------------------------------------------------------

def test_dashboard_empty_range(db):
    """No sales in range → totals all 0.0000, margin_pct null."""
    user = _make_user(8811)
    c = _client(user)

    response = c.get("/api/v1/financials/dashboard", {"from": "2020-01-01", "to": "2020-12-31"})
    assert response.status_code == 200
    data = response.json()

    totals = data["totals"]
    assert Decimal(totals["revenue"]) == Decimal("0")
    assert Decimal(totals["cogs"]) == Decimal("0")
    assert Decimal(totals["profit"]) == Decimal("0")
    assert totals["margin_pct"] is None
    assert data["top_products"] == []


# ---------------------------------------------------------------------------
# Validation: from > to → 400
# ---------------------------------------------------------------------------

def test_dashboard_from_gt_to_is_400(db):
    """from > to returns 400 ValidationError."""
    user = _make_user(8812)
    c = _client(user)

    response = c.get("/api/v1/financials/dashboard", {"from": "2026-05-10", "to": "2026-05-01"})
    assert response.status_code == 400
    assert response.json()["error"] == "ValidationError"


# ---------------------------------------------------------------------------
# Validation: range > 1 year → 400
# ---------------------------------------------------------------------------

def test_dashboard_range_exceeds_1_year_is_400(db):
    """Date range > 365 days returns 400 ValidationError."""
    user = _make_user(8813)
    c = _client(user)

    response = c.get("/api/v1/financials/dashboard", {"from": "2025-01-01", "to": "2026-06-01"})
    assert response.status_code == 400
    assert response.json()["error"] == "ValidationError"


# ---------------------------------------------------------------------------
# Voided SO excluded
# ---------------------------------------------------------------------------

def test_dashboard_voided_so_excluded(db):
    """Committing then voiding an SO removes it from the dashboard."""
    user = _make_user(8814)
    c = _client(user)

    product_id = _seed_product(user.id)
    batch_id = _seed_batch(user.id, product_id, quantity="50.0000", unit_cost="2.0000")
    so_id = _seed_committed_so(
        user.id, product_id, batch_id,
        quantity="50.0000", sell_price="5.0000", unit_cost="2.0000",
    )
    _void_so(so_id)

    response = c.get("/api/v1/financials/dashboard", {"from": _FROM, "to": _TO})
    assert response.status_code == 200
    data = response.json()
    # Owner 8814 has only one SO and it's voided — totals should be zero
    assert Decimal(data["totals"]["revenue"]) == Decimal("0")


# ---------------------------------------------------------------------------
# Unauthenticated → 401
# ---------------------------------------------------------------------------

def test_dashboard_unauthenticated_is_401(db):
    """Unauthenticated request returns 401."""
    c = APIClient()
    response = c.get("/api/v1/financials/dashboard")
    assert response.status_code == 401
