"""Service tests for create_receipt_batches."""

from __future__ import annotations

import uuid
from decimal import Decimal

import os

import psycopg
import psycopg.errors
import pytest

from apps.inventory.services import create_receipt_batches

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

pytestmark = pytest.mark.django_db


def _seed_user(uid: int) -> None:
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        email = f"inv_crb_{uid}@test.invalid"
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
            (product_id, owner_id, f"CRB-{product_id[:8]}", f"Prod {product_id[:8]}"),
        )
    return product_id


def _seed_po_line(owner_id: int, product_id: str, qty: Decimal, unit_cost: Decimal) -> tuple[str, str]:
    """Insert a PO + line, return (po_id, line_id)."""
    po_id = str(uuid.uuid4())
    line_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO purchase_orders (id, owner_id, supplier_name, status, received_at)
            VALUES (%s, %s, 'Supplier', 'received', NOW())
            """,
            (po_id, owner_id),
        )
        conn.execute(
            """
            INSERT INTO purchase_order_lines (id, purchase_order_id, owner_id, product_id, quantity, unit_cost)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (line_id, po_id, owner_id, product_id, qty, unit_cost),
        )
    return po_id, line_id


# ---------------------------------------------------------------------------
# Creates batch per line with purchase_order_line_id set
# ---------------------------------------------------------------------------

def test_creates_batch_per_line_with_purchase_order_line_id_set():
    """create_receipt_batches creates 1 batch per line with purchase_order_line_id populated."""
    owner_id = 7801
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    _, line_id = _seed_po_line(owner_id, product_id, Decimal("10.0000"), Decimal("2.0000"))

    result = create_receipt_batches(
        owner_id=owner_id,
        lines=[{
            "line_id": line_id,
            "batch_code": "RCV-001",
            "expiration_date": None,
            "product_id": product_id,
            "quantity": Decimal("10.0000"),
            "unit_cost": Decimal("2.0000"),
            "purchase_order_line_id": line_id,
        }],
    )

    assert len(result) == 1
    assert str(result[0]["purchase_order_line_id"]) == line_id

    with psycopg.connect(_DB_URL) as conn:
        b = conn.execute(
            "SELECT purchase_order_line_id FROM batches WHERE id = %s",
            (str(result[0]["id"]),),
        ).fetchone()
    assert str(b[0]) == line_id


# ---------------------------------------------------------------------------
# Creates receipt movement per batch
# ---------------------------------------------------------------------------

def test_creates_receipt_movement_per_batch():
    """create_receipt_batches inserts a receipt movement per batch with correct reference."""
    owner_id = 7802
    _seed_user(owner_id)
    product_id1 = _seed_product(owner_id)
    product_id2 = _seed_product(owner_id)
    _, line_id1 = _seed_po_line(owner_id, product_id1, Decimal("5.0000"), Decimal("1.0000"))
    _, line_id2 = _seed_po_line(owner_id, product_id2, Decimal("8.0000"), Decimal("3.0000"))

    result = create_receipt_batches(
        owner_id=owner_id,
        lines=[
            {
                "line_id": line_id1,
                "batch_code": "RCV-M1",
                "expiration_date": None,
                "product_id": product_id1,
                "quantity": Decimal("5.0000"),
                "unit_cost": Decimal("1.0000"),
                "purchase_order_line_id": line_id1,
            },
            {
                "line_id": line_id2,
                "batch_code": "RCV-M2",
                "expiration_date": None,
                "product_id": product_id2,
                "quantity": Decimal("8.0000"),
                "unit_cost": Decimal("3.0000"),
                "purchase_order_line_id": line_id2,
            },
        ],
    )

    assert len(result) == 2

    for batch, line_id, qty in [
        (result[0], line_id1, Decimal("5.0000")),
        (result[1], line_id2, Decimal("8.0000")),
    ]:
        with psycopg.connect(_DB_URL) as conn:
            m = conn.execute(
                """
                SELECT kind, signed_quantity, reference_type, reference_id
                  FROM stock_movements
                 WHERE batch_id = %s
                """,
                (str(batch["id"]),),
            ).fetchone()
        assert m[0] == "receipt"
        assert Decimal(str(m[1])) == qty
        assert m[2] == "purchase_order_line"
        assert str(m[3]) == line_id


# ---------------------------------------------------------------------------
# Zero lines → empty list, no writes
# ---------------------------------------------------------------------------

def test_zero_lines_returns_empty_list_no_writes():
    """create_receipt_batches with empty lines returns [] without writing anything."""
    owner_id = 7803
    _seed_user(owner_id)

    result = create_receipt_batches(owner_id=owner_id, lines=[])

    assert result == []


# ---------------------------------------------------------------------------
# unit_cost carried from line
# ---------------------------------------------------------------------------

def test_unit_cost_carried_from_line():
    """Batch unit_cost matches the line's unit_cost passed in."""
    owner_id = 7804
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    _, line_id = _seed_po_line(owner_id, product_id, Decimal("10.0000"), Decimal("5.5000"))

    result = create_receipt_batches(
        owner_id=owner_id,
        lines=[{
            "line_id": line_id,
            "batch_code": "COST-001",
            "expiration_date": None,
            "product_id": product_id,
            "quantity": Decimal("10.0000"),
            "unit_cost": Decimal("5.5000"),
            "purchase_order_line_id": line_id,
        }],
    )

    assert Decimal(str(result[0]["unit_cost"])) == Decimal("5.5000")


# ---------------------------------------------------------------------------
# Cross-owner pol_id → ForeignKeyViolation
# ---------------------------------------------------------------------------

def test_cross_owner_pol_id_raises_or_product_fkey():
    """Passing a purchase_order_line_id from another owner raises ForeignKeyViolation."""
    owner_a = 7805
    owner_b = 7806
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_b = _seed_product(owner_b)
    # line belongs to owner_b
    _, line_id_b = _seed_po_line(owner_b, product_b, Decimal("5.0000"), Decimal("1.0000"))

    product_a = _seed_product(owner_a)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        create_receipt_batches(
            owner_id=owner_a,
            lines=[{
                "line_id": line_id_b,
                "batch_code": "CROSS-RCV",
                "expiration_date": None,
                "product_id": product_a,
                "quantity": Decimal("5.0000"),
                "unit_cost": Decimal("1.0000"),
                "purchase_order_line_id": line_id_b,  # belongs to owner_b
            }],
        )
