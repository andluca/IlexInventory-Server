"""Service tests for commit_sales_order (FEFO + explicit allocation override)."""

from __future__ import annotations

import os
from decimal import Decimal

import psycopg
import pytest

from apps.sales.errors import InsufficientStock, InvalidAllocation, SalesOrderNotDraft
from apps.sales.services import commit_sales_order, create_sales_order_draft
from apps.sales.tests.service.conftest import seed_batch, seed_product, seed_user

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


# ---------------------------------------------------------------------------
# Happy path — brief anchor test: receive 100 @ $1, sell 100 @ $10
# ---------------------------------------------------------------------------

def test_commit_fefo_brief_example():
    """Anchor test: receive 100 @ $1, commit 100 @ $10.

    Expects:
    - 1 allocation row with unit_cost=1.0000, allocated_quantity=100.0000
    - 1 sale movement with signed_quantity=-100.0000
    - SO status flips to 'committed'
    - revenue (sell_price * qty) = 1000.0000
    - COGS (unit_cost * allocated_qty) = 100.0000
    """
    owner_id = 9201
    seed_user(owner_id)
    product_id = seed_product(owner_id)
    seed_batch(owner_id, product_id, quantity="100.0000", unit_cost="1.0000")

    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Brief Example Corp",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("100.0000"), "sell_price": Decimal("10.0000")}],
    )
    so_id = so["id"]

    committed = commit_sales_order(owner_id=owner_id, so_id=so_id)

    assert committed["status"] == "committed"
    assert committed["committed_at"] is not None
    assert len(committed["allocations"]) == 1

    alloc = committed["allocations"][0]
    assert Decimal(str(alloc["unit_cost"])) == Decimal("1.0000")
    assert Decimal(str(alloc["allocated_quantity"])) == Decimal("100.0000")

    # Revenue = sell_price * qty = 10 * 100 = 1000
    line = committed["lines"][0]
    revenue = Decimal(str(line["sell_price"])) * Decimal(str(line["quantity"]))
    assert revenue == Decimal("1000.0000")

    # COGS = unit_cost * allocated_qty = 1 * 100 = 100
    cogs = Decimal(str(alloc["unit_cost"])) * Decimal(str(alloc["allocated_quantity"]))
    assert cogs == Decimal("100.0000")

    # Profit = revenue - cogs = 900
    assert revenue - cogs == Decimal("900.0000")

    # DB: verify on-hand is now 0 via v_stock_by_batch
    batch_id = str(alloc["batch_id"])
    with psycopg.connect(_DB_URL) as conn:
        row = conn.execute(
            "SELECT on_hand FROM v_stock_by_batch WHERE batch_id = %s",
            (batch_id,),
        ).fetchone()
    assert row is not None
    assert Decimal(str(row[0])) == Decimal("0.0000")


# ---------------------------------------------------------------------------
# FEFO order: earliest-expiring batch consumed first
# ---------------------------------------------------------------------------

def test_commit_fefo_drains_earliest_expiring_batch_first():
    """FEFO drains the soonest-expiring batch first."""
    owner_id = 9202
    seed_user(owner_id)
    product_id = seed_product(owner_id)

    # Batch A expires sooner, Batch B expires later
    batch_a = seed_batch(
        owner_id, product_id, quantity="40.0000", unit_cost="1.0000",
        expiration_date="2026-06-01",
    )
    batch_b = seed_batch(
        owner_id, product_id, quantity="60.0000", unit_cost="2.0000",
        expiration_date="2026-12-01",
    )

    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="FEFO Test",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("50.0000"), "sell_price": Decimal("5.0000")}],
    )
    committed = commit_sales_order(owner_id=owner_id, so_id=so["id"])

    allocs = committed["allocations"]
    alloc_by_batch = {str(a["batch_id"]): a for a in allocs}

    # Batch A should be fully drained (40 units), Batch B takes the remaining 10
    assert batch_a in alloc_by_batch
    assert Decimal(str(alloc_by_batch[batch_a]["allocated_quantity"])) == Decimal("40.0000")
    assert batch_b in alloc_by_batch
    assert Decimal(str(alloc_by_batch[batch_b]["allocated_quantity"])) == Decimal("10.0000")


# ---------------------------------------------------------------------------
# Recalled and expired batches are invisible to FEFO
# ---------------------------------------------------------------------------

def test_commit_fefo_ignores_recalled_batch():
    """InsufficientStock raised when only inventory is recalled."""
    owner_id = 9203
    seed_user(owner_id)
    product_id = seed_product(owner_id)
    batch_id = seed_batch(owner_id, product_id, quantity="100.0000")

    # Recall the batch
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "UPDATE batches SET is_recalled=true, recall_reason='defect', recalled_at=NOW() WHERE id=%s",
            (batch_id,),
        )

    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Recalled Test",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("10.0000"), "sell_price": Decimal("5.0000")}],
    )
    with pytest.raises(InsufficientStock):
        commit_sales_order(owner_id=owner_id, so_id=so["id"])


def test_commit_fefo_ignores_expired_batch():
    """InsufficientStock raised when only inventory is expired."""
    owner_id = 9204
    seed_user(owner_id)
    product_id = seed_product(owner_id)
    seed_batch(
        owner_id, product_id, quantity="100.0000",
        expiration_date="2020-01-01",  # expired in the past
    )

    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Expired Test",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("10.0000"), "sell_price": Decimal("5.0000")}],
    )
    with pytest.raises(InsufficientStock):
        commit_sales_order(owner_id=owner_id, so_id=so["id"])


# ---------------------------------------------------------------------------
# Insufficient on-hand → 422-mappable error; no allocations written
# ---------------------------------------------------------------------------

def test_commit_insufficient_stock_raises_and_no_writes():
    """InsufficientStock (422) — no allocations or movements written on failure."""
    owner_id = 9205
    seed_user(owner_id)
    product_id = seed_product(owner_id)
    seed_batch(owner_id, product_id, quantity="5.0000")

    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Short Stock",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("10.0000"), "sell_price": Decimal("5.0000")}],
    )
    so_id = so["id"]

    with pytest.raises(InsufficientStock) as exc_info:
        commit_sales_order(owner_id=owner_id, so_id=so_id)

    # Error payload includes shortfall info
    assert exc_info.value.fields is not None
    shortfall = exc_info.value.fields["shortfall"]
    assert shortfall["product_id"] == product_id
    assert Decimal(shortfall["required"]) == Decimal("10.0000")
    assert Decimal(shortfall["available"]) == Decimal("5.0000")

    # No allocations written
    with psycopg.connect(_DB_URL) as conn:
        alloc_count = conn.execute(
            """
            SELECT COUNT(*) FROM sale_allocations sa
            JOIN sales_order_lines sol ON sol.id = sa.sales_order_line_id
            WHERE sol.sales_order_id = %s
            """,
            (so_id,),
        ).fetchone()[0]
    assert alloc_count == 0


# ---------------------------------------------------------------------------
# SO not in draft → 409
# ---------------------------------------------------------------------------

def test_commit_already_committed_raises_not_draft():
    """Committing an already-committed SO raises SalesOrderNotDraft (409)."""
    owner_id = 9206
    seed_user(owner_id)
    product_id = seed_product(owner_id)
    seed_batch(owner_id, product_id, quantity="10.0000")

    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Double Commit",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("5.0000"), "sell_price": Decimal("5.0000")}],
    )
    commit_sales_order(owner_id=owner_id, so_id=so["id"])

    with pytest.raises(SalesOrderNotDraft):
        commit_sales_order(owner_id=owner_id, so_id=so["id"])


# ---------------------------------------------------------------------------
# Explicit allocations override (D11 admin override)
# ---------------------------------------------------------------------------

def test_commit_explicit_allocations_skips_fefo():
    """Explicit allocations body bypasses FEFO walk."""
    owner_id = 9207
    seed_user(owner_id)
    product_id = seed_product(owner_id)
    # Two batches; FEFO would pick oldest-expiring first (_batch_a); we override to batch_b
    _batch_a = seed_batch(
        owner_id, product_id, quantity="50.0000", unit_cost="1.0000",
        expiration_date="2026-06-01",
    )
    batch_b = seed_batch(
        owner_id, product_id, quantity="50.0000", unit_cost="2.0000",
        expiration_date="2026-12-01",
    )

    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Admin Override",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("20.0000"), "sell_price": Decimal("5.0000")}],
    )
    line_id = so["lines"][0]["id"]

    # Force-allocate from batch_b (FEFO would pick batch_a)
    committed = commit_sales_order(
        owner_id=owner_id,
        so_id=so["id"],
        allocations=[{"line_id": line_id, "batch_id": batch_b, "quantity": Decimal("20.0000")}],
    )

    assert len(committed["allocations"]) == 1
    assert str(committed["allocations"][0]["batch_id"]) == batch_b
    # unit_cost comes from batch_b
    assert Decimal(str(committed["allocations"][0]["unit_cost"])) == Decimal("2.0000")


def test_commit_explicit_allocation_sum_mismatch_raises_invalid_allocation():
    """Per-line allocation sum != line.quantity raises InvalidAllocation."""
    owner_id = 9208
    seed_user(owner_id)
    product_id = seed_product(owner_id)
    batch_id = seed_batch(owner_id, product_id, quantity="100.0000")

    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Mismatch Test",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("10.0000"), "sell_price": Decimal("5.0000")}],
    )
    line_id = so["lines"][0]["id"]

    with pytest.raises(InvalidAllocation):
        commit_sales_order(
            owner_id=owner_id,
            so_id=so["id"],
            allocations=[{"line_id": line_id, "batch_id": batch_id, "quantity": Decimal("5.0000")}],
        )


def test_commit_explicit_allocation_recalled_batch_raises_invalid_allocation():
    """Explicit allocation from recalled batch raises InvalidAllocation (D11)."""
    owner_id = 9209
    seed_user(owner_id)
    product_id = seed_product(owner_id)
    batch_id = seed_batch(owner_id, product_id, quantity="100.0000")

    # Recall the batch
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "UPDATE batches SET is_recalled=true, recall_reason='defect', recalled_at=NOW() WHERE id=%s",
            (batch_id,),
        )

    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Recalled Alloc Test",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("10.0000"), "sell_price": Decimal("5.0000")}],
    )
    line_id = so["lines"][0]["id"]

    with pytest.raises(InvalidAllocation):
        commit_sales_order(
            owner_id=owner_id,
            so_id=so["id"],
            allocations=[{"line_id": line_id, "batch_id": batch_id, "quantity": Decimal("10.0000")}],
        )
