"""Schema-level constraint tests for sales_orders, sales_order_lines, sale_allocations.

Behavioral: each test exercises one DB integrity rule.
No service or query function imports — raw psycopg only, so these tests
remain green across any future service refactor.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import os

import psycopg
import psycopg.errors
import pytest

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Seed helpers (raw SQL — tests at this layer own their own state)
# ---------------------------------------------------------------------------

def _seed_user(uid: int) -> None:
    email = f"sales_schema_{uid}@test.invalid"
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


def _seed_product(owner_id: int) -> str:
    product_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO products (id, owner_id, sku, name, description, base_unit)
            VALUES (%s, %s, %s, %s, '', 'unit')
            """,
            (product_id, owner_id, f"SL-{product_id[:8]}", f"Product {product_id[:8]}"),
        )
    return product_id


def _seed_batch(owner_id: int, product_id: str, unit_cost: str = "1.0000") -> str:
    batch_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (batch_id, owner_id, product_id, f"B-{batch_id[:8]}", Decimal(unit_cost)),
        )
    return batch_id


def _seed_sales_order(owner_id: int, customer_name: str = "Acme Corp") -> str:
    so_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO sales_orders (id, owner_id, customer_name, status)
            VALUES (%s, %s, %s, 'draft')
            """,
            (so_id, owner_id, customer_name),
        )
    return so_id


def _seed_sales_order_line(owner_id: int, so_id: str, product_id: str,
                            quantity: str = "10.0000", sell_price: str = "5.0000") -> str:
    line_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO sales_order_lines
                   (id, owner_id, sales_order_id, product_id, quantity, sell_price)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (line_id, owner_id, so_id, product_id, Decimal(quantity), Decimal(sell_price)),
        )
    return line_id


def _seed_receipt_movement(owner_id: int, batch_id: str, qty: str = "100.0000") -> None:
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity)
            VALUES (%s, %s, 'receipt', %s)
            """,
            (owner_id, batch_id, Decimal(qty)),
        )


# ---------------------------------------------------------------------------
# sales_orders CHECK constraints
# ---------------------------------------------------------------------------

def test_so_status_check_rejects_unknown_status():
    """INSERT sales_order with invalid status violates so_status_chk."""
    owner_id = 8001
    _seed_user(owner_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO sales_orders (owner_id, customer_name, status)
                VALUES (%s, 'Test Corp', 'invalid_status')
                """,
                (owner_id,),
            )


def test_so_committed_consistency_rejects_committed_without_timestamp():
    """INSERT committed SO without committed_at violates so_committed_consistency_chk."""
    owner_id = 8002
    _seed_user(owner_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO sales_orders (owner_id, customer_name, status, committed_at)
                VALUES (%s, 'Test Corp', 'committed', NULL)
                """,
                (owner_id,),
            )


def test_so_voided_requires_committed():
    """voided_at on a draft SO violates so_voided_requires_committed_chk."""
    owner_id = 8003
    _seed_user(owner_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO sales_orders (owner_id, customer_name, status, voided_at)
                VALUES (%s, 'Test Corp', 'draft', NOW())
                """,
                (owner_id,),
            )


def test_so_customer_name_not_blank():
    """INSERT SO with blank customer_name violates so_customer_name_not_blank."""
    owner_id = 8004
    _seed_user(owner_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO sales_orders (owner_id, customer_name, status)
                VALUES (%s, '   ', 'draft')
                """,
                (owner_id,),
            )


# ---------------------------------------------------------------------------
# sales_order_lines CHECK constraints
# ---------------------------------------------------------------------------

def test_sol_quantity_must_be_positive():
    """INSERT line with quantity <= 0 violates sol_quantity_positive."""
    owner_id = 8005
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    so_id = _seed_sales_order(owner_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO sales_order_lines
                       (owner_id, sales_order_id, product_id, quantity, sell_price)
                VALUES (%s, %s, %s, 0, 5.0000)
                """,
                (owner_id, so_id, product_id),
            )


def test_sol_sell_price_must_be_nonneg():
    """INSERT line with sell_price < 0 violates sol_sell_price_nonneg."""
    owner_id = 8006
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    so_id = _seed_sales_order(owner_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO sales_order_lines
                       (owner_id, sales_order_id, product_id, quantity, sell_price)
                VALUES (%s, %s, %s, 10.0000, -1.0000)
                """,
                (owner_id, so_id, product_id),
            )


def test_sol_cross_owner_so_fk_rejected():
    """INSERT line with (so_id, owner_id) mismatching violates sol_so_owner_fkey."""
    owner_a = 8007
    owner_b = 8008
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_b = _seed_product(owner_b)
    so_a = _seed_sales_order(owner_a)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO sales_order_lines
                       (owner_id, sales_order_id, product_id, quantity, sell_price)
                VALUES (%s, %s, %s, 10.0000, 5.0000)
                """,
                (owner_b, so_a, product_b),
            )


def test_sol_cross_owner_product_fk_rejected():
    """INSERT line with (product_id, owner_id) from another owner violates sol_product_owner_fkey."""
    owner_a = 8009
    owner_b = 8010
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_a = _seed_product(owner_a)
    so_b = _seed_sales_order(owner_b)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO sales_order_lines
                       (owner_id, sales_order_id, product_id, quantity, sell_price)
                VALUES (%s, %s, %s, 10.0000, 5.0000)
                """,
                (owner_b, so_b, product_a),
            )


# ---------------------------------------------------------------------------
# sale_allocations CHECK constraints
# ---------------------------------------------------------------------------

def test_sa_allocated_quantity_must_be_positive():
    """INSERT allocation with allocated_quantity <= 0 violates sa_allocated_quantity_positive."""
    owner_id = 8011
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id)
    so_id = _seed_sales_order(owner_id)
    line_id = _seed_sales_order_line(owner_id, so_id, product_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO sale_allocations
                       (owner_id, sales_order_line_id, batch_id, allocated_quantity, unit_cost)
                VALUES (%s, %s, %s, 0, 1.0000)
                """,
                (owner_id, line_id, batch_id),
            )


def test_sa_cross_owner_line_fk_rejected():
    """INSERT allocation with (line_id, owner_id) mismatching violates sa_sol_owner_fkey."""
    owner_a = 8012
    owner_b = 8013
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_a = _seed_product(owner_a)
    product_b = _seed_product(owner_b)
    batch_b = _seed_batch(owner_b, product_b)
    so_a = _seed_sales_order(owner_a)
    line_a = _seed_sales_order_line(owner_a, so_a, product_a)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO sale_allocations
                       (owner_id, sales_order_line_id, batch_id, allocated_quantity, unit_cost)
                VALUES (%s, %s, %s, 10.0000, 1.0000)
                """,
                (owner_b, line_a, batch_b),
            )


# ---------------------------------------------------------------------------
# v_recall_report shape and filtering
# ---------------------------------------------------------------------------

def test_v_recall_report_returns_committed_so_rows():
    """v_recall_report includes rows for committed, non-voided SOs."""
    owner_id = 8014
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id, unit_cost="1.0000")
    _seed_receipt_movement(owner_id, batch_id, qty="100.0000")

    # Seed a committed SO
    so_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO sales_orders (id, owner_id, customer_name, status, committed_at)
            VALUES (%s, %s, 'Beta LLC', 'committed', NOW())
            """,
            (so_id, owner_id),
        )
        line_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO sales_order_lines
                   (id, owner_id, sales_order_id, product_id, quantity, sell_price)
            VALUES (%s, %s, %s, %s, 60.0000, 10.0000)
            """,
            (line_id, owner_id, so_id, product_id),
        )
        conn.execute(
            """
            INSERT INTO sale_allocations
                   (owner_id, sales_order_line_id, batch_id, allocated_quantity, unit_cost)
            VALUES (%s, %s, %s, 60.0000, 1.0000)
            """,
            (owner_id, line_id, batch_id),
        )

    with psycopg.connect(_DB_URL) as conn:
        row = conn.execute(
            """
            SELECT sale_order_id, customer_name, quantity_received
              FROM v_recall_report
             WHERE batch_id = %s AND owner_id = %s
            """,
            (batch_id, owner_id),
        ).fetchone()

    assert row is not None
    assert str(row[0]) == so_id
    assert row[1] == "Beta LLC"
    assert Decimal(str(row[2])) == Decimal("60.0000")


def test_v_recall_report_excludes_voided_so():
    """v_recall_report omits rows for voided SOs (D8: void removes from report)."""
    owner_id = 8015
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id, unit_cost="1.0000")
    _seed_receipt_movement(owner_id, batch_id, qty="100.0000")

    # Seed a committed + voided SO
    so_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO sales_orders (id, owner_id, customer_name, status, committed_at, voided_at)
            VALUES (%s, %s, 'Gamma Corp', 'committed', NOW() - INTERVAL '1 hour', NOW())
            """,
            (so_id, owner_id),
        )
        line_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO sales_order_lines
                   (id, owner_id, sales_order_id, product_id, quantity, sell_price)
            VALUES (%s, %s, %s, %s, 30.0000, 10.0000)
            """,
            (line_id, owner_id, so_id, product_id),
        )
        conn.execute(
            """
            INSERT INTO sale_allocations
                   (owner_id, sales_order_line_id, batch_id, allocated_quantity, unit_cost)
            VALUES (%s, %s, %s, 30.0000, 1.0000)
            """,
            (owner_id, line_id, batch_id),
        )

    with psycopg.connect(_DB_URL) as conn:
        rows = conn.execute(
            "SELECT sale_order_id FROM v_recall_report WHERE batch_id = %s AND owner_id = %s",
            (batch_id, owner_id),
        ).fetchall()

    assert rows == []


def test_v_recall_report_excludes_draft_so():
    """v_recall_report omits rows for draft SOs (draft SOs have no allocations anyway)."""
    owner_id = 8016
    _seed_user(owner_id)

    with psycopg.connect(_DB_URL) as conn:
        rows = conn.execute(
            "SELECT 1 FROM v_recall_report WHERE owner_id = %s AND sale_order_id IS NULL",
            (owner_id,),
        ).fetchall()

    assert rows == []
