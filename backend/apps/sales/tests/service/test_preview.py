"""Service tests for preview_so_allocations."""

from __future__ import annotations

import os
from decimal import Decimal

import psycopg
import pytest

from apps.sales.errors import InsufficientStock
from apps.sales.services import create_sales_order_draft, preview_so_allocations
from apps.sales.tests.service.conftest import seed_batch, seed_product, seed_user

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


def test_preview_returns_proposed_allocations_without_persisting():
    """preview_so_allocations returns proposed allocs; no stock movements or allocations written."""
    owner_id = 9301
    seed_user(owner_id)
    product_id = seed_product(owner_id)
    batch_id = seed_batch(owner_id, product_id, quantity="100.0000", unit_cost="1.0000")

    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Preview Corp",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("60.0000"), "sell_price": Decimal("10.0000")}],
    )
    so_id = so["id"]

    proposed = preview_so_allocations(owner_id=owner_id, so_id=so_id)

    assert len(proposed) == 1
    assert str(proposed[0]["batch_id"]) == batch_id
    assert Decimal(str(proposed[0]["quantity"])) == Decimal("60.0000")
    assert Decimal(str(proposed[0]["unit_cost"])) == Decimal("1.0000")

    # Verify nothing was persisted
    with psycopg.connect(_DB_URL) as conn:
        # On-hand should still be 100
        row = conn.execute(
            "SELECT on_hand FROM v_stock_by_batch WHERE batch_id = %s",
            (batch_id,),
        ).fetchone()
    assert Decimal(str(row[0])) == Decimal("100.0000")

    # No allocations written
    with psycopg.connect(_DB_URL) as conn:
        count = conn.execute(
            """
            SELECT COUNT(*) FROM sale_allocations sa
            JOIN sales_order_lines sol ON sol.id = sa.sales_order_line_id
            WHERE sol.sales_order_id = %s
            """,
            (so_id,),
        ).fetchone()[0]
    assert count == 0


def test_preview_insufficient_stock_raises():
    """preview_so_allocations raises InsufficientStock when stock is insufficient."""
    owner_id = 9302
    seed_user(owner_id)
    product_id = seed_product(owner_id)
    seed_batch(owner_id, product_id, quantity="5.0000")

    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Preview Short",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("10.0000"), "sell_price": Decimal("5.0000")}],
    )
    with pytest.raises(InsufficientStock):
        preview_so_allocations(owner_id=owner_id, so_id=so["id"])
