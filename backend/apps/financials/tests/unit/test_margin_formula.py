"""Unit tests for the margin formula via the dashboard_for_owner selector.

Behavioral tests: assert on observable return values, not on private helpers.
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from apps.financials.selectors import dashboard_for_owner

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


def _seed_user(uid: int) -> None:
    email = f"mf_{uid}@test.invalid"
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


def _seed_product(owner_id: int, name: str = "Widget") -> str:
    product_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO products (id, owner_id, sku, name, description, base_unit)
            VALUES (%s, %s, %s, %s, '', 'unit')
            """,
            (product_id, owner_id, f"MF-{product_id[:8]}", name),
        )
    return product_id


def _seed_batch_and_committed_so(
    owner_id: int,
    product_id: str,
    quantity: str,
    unit_cost: str,
    sell_price: str,
) -> None:
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
            VALUES (%s, %s, 'Formula Test', 'committed', NOW())
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


# ---------------------------------------------------------------------------
# Brief anchor: revenue=1000, cogs=100 → margin_pct=900.0000%
# ---------------------------------------------------------------------------

def test_margin_pct_brief_example():
    """Anchor: receive 100 @ $1, sell 100 @ $10 → margin_pct=900.0000."""
    owner_id = 8901
    _seed_user(owner_id)
    product_id = _seed_product(owner_id, name="Widget")
    _seed_batch_and_committed_so(
        owner_id, product_id,
        quantity="100.0000", unit_cost="1.0000", sell_price="10.0000",
    )

    result = dashboard_for_owner(
        owner_id=owner_id,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
        top_n=5,
    )

    totals = result["totals"]
    assert totals["revenue"] == Decimal("1000.0000")
    assert totals["cogs"] == Decimal("100.0000")
    assert totals["profit"] == Decimal("900.0000")
    assert totals["margin_pct"] == Decimal("900.0000")


# ---------------------------------------------------------------------------
# Zero COGS → margin_pct is None (not 0, not Infinity)
# ---------------------------------------------------------------------------

def test_margin_pct_zero_cogs_returns_none():
    """When cogs=0, margin_pct must be None (avoid ZeroDivisionError)."""
    owner_id = 8902
    _seed_user(owner_id)
    product_id = _seed_product(owner_id, name="Free Item")
    _seed_batch_and_committed_so(
        owner_id, product_id,
        quantity="10.0000", unit_cost="0.0000", sell_price="5.0000",
    )

    result = dashboard_for_owner(
        owner_id=owner_id,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
        top_n=5,
    )

    totals = result["totals"]
    assert totals["cogs"] == Decimal("0.0000")
    assert totals["margin_pct"] is None


# ---------------------------------------------------------------------------
# Empty date range → revenue=0, cogs=0, profit=0, margin_pct=None
# ---------------------------------------------------------------------------

def test_empty_range_returns_zero_totals_and_null_margin():
    """Empty date range yields all-zero totals and margin_pct=None."""
    owner_id = 8903
    _seed_user(owner_id)

    result = dashboard_for_owner(
        owner_id=owner_id,
        date_from=date(1999, 1, 1),
        date_to=date(1999, 1, 31),
        top_n=5,
    )

    totals = result["totals"]
    assert totals["revenue"] == Decimal("0")
    assert totals["cogs"] == Decimal("0")
    assert totals["profit"] == Decimal("0")
    assert totals["margin_pct"] is None
    assert result["top_products"] == []
