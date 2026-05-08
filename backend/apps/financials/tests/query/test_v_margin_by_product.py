"""Query tests for v_margin_by_product view (step 1 of ILEX-008).

Behavioral: tests assert on observable DB state (view rows), not on
internal helpers. Seed state is set directly via psycopg.
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import psycopg
import pytest

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


# ---------------------------------------------------------------------------
# Seed helpers (local to this module — not exported)
# ---------------------------------------------------------------------------

def _seed_user(uid: int) -> None:
    email = f"fin_{uid}@test.invalid"
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
            (product_id, owner_id, f"W-{product_id[:8]}", name),
        )
    return product_id


def _seed_batch(owner_id: int, product_id: str, quantity: str, unit_cost: str = "1.0000") -> str:
    """Seed a batch + receipt movement. Returns batch_id."""
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
    """Seed a committed SO + line + allocation. Returns sales_order_id."""
    so_id = str(uuid.uuid4())
    sol_id = str(uuid.uuid4())
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
            (sol_id, owner_id, so_id, product_id, Decimal(quantity), Decimal(sell_price)),
        )
        conn.execute(
            """
            INSERT INTO sale_allocations
                   (owner_id, sales_order_line_id, batch_id, allocated_quantity, unit_cost)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (owner_id, sol_id, batch_id, Decimal(quantity), Decimal(unit_cost)),
        )
    return so_id


def _void_so(so_id: str) -> None:
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "UPDATE sales_orders SET voided_at = NOW() WHERE id = %s",
            (so_id,),
        )


def _query_view(owner_id: int, sales_order_id: str) -> list[dict]:
    with psycopg.connect(_DB_URL) as conn:
        rows = conn.execute(
            """
            SELECT owner_id, product_id, product_name, sales_order_id,
                   units_sold, revenue, cogs
            FROM v_margin_by_product
            WHERE owner_id = %s AND sales_order_id = %s
            """,
            (owner_id, sales_order_id),
        ).fetchall()
    return [
        {
            "owner_id": r[0],
            "product_id": str(r[1]),
            "product_name": r[2],
            "sales_order_id": str(r[3]),
            "units_sold": Decimal(str(r[4])),
            "revenue": Decimal(str(r[5])),
            "cogs": Decimal(str(r[6])),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Test: brief anchor example — 100 units @ $1 received, 100 sold @ $10
# ---------------------------------------------------------------------------

def test_brief_example_view_row():
    """View yields revenue=1000, cogs=100, units_sold=100 for brief anchor."""
    owner_id = 8801
    _seed_user(owner_id)
    product_id = _seed_product(owner_id, name="Widget")
    batch_id = _seed_batch(owner_id, product_id, quantity="100.0000", unit_cost="1.0000")
    so_id = _seed_committed_so(
        owner_id, product_id, batch_id,
        quantity="100.0000", sell_price="10.0000", unit_cost="1.0000",
    )

    rows = _query_view(owner_id, so_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["product_name"] == "Widget"
    assert row["units_sold"] == Decimal("100.0000")
    assert row["revenue"] == Decimal("1000.0000")
    assert row["cogs"] == Decimal("100.0000")


# ---------------------------------------------------------------------------
# Test: voided SO disappears from view
# ---------------------------------------------------------------------------

def test_voided_so_not_in_view():
    """After voiding a committed SO, it disappears from v_margin_by_product."""
    owner_id = 8802
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id, quantity="50.0000", unit_cost="2.0000")
    so_id = _seed_committed_so(
        owner_id, product_id, batch_id,
        quantity="50.0000", sell_price="5.0000", unit_cost="2.0000",
    )

    # Before void: row is present
    rows_before = _query_view(owner_id, so_id)
    assert len(rows_before) == 1

    # Void the SO
    _void_so(so_id)

    # After void: row is gone
    rows_after = _query_view(owner_id, so_id)
    assert len(rows_after) == 0


# ---------------------------------------------------------------------------
# Test: cross-owner isolation — owner A's sales never appear for owner B
# ---------------------------------------------------------------------------

def test_cross_owner_isolation():
    """Owner A's sales are never visible when querying for owner B."""
    owner_a = 8803
    owner_b = 8804
    _seed_user(owner_a)
    _seed_user(owner_b)

    product_a = _seed_product(owner_a, name="Product A")
    batch_a = _seed_batch(owner_a, product_a, quantity="100.0000", unit_cost="1.0000")
    so_a = _seed_committed_so(
        owner_a, product_a, batch_a,
        quantity="100.0000", sell_price="10.0000", unit_cost="1.0000",
    )

    # Query view for owner_b — should see no rows for owner_a's SO
    with psycopg.connect(_DB_URL) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM v_margin_by_product WHERE owner_id = %s AND sales_order_id = %s",
            (owner_b, so_a),
        ).fetchone()
    assert rows[0] == 0
