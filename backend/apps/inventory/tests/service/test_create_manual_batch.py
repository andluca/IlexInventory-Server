"""Service tests for create_manual_batch."""

from __future__ import annotations

import uuid
from decimal import Decimal

import os

import psycopg
import pytest

from apps.inventory.errors import BatchExists, ProductNotFound
from apps.inventory.errors import ValidationError as InventoryValidationError
from apps.inventory.services import create_manual_batch

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

pytestmark = pytest.mark.django_db


def _owner_row(user_id: int) -> dict:
    return {
        "id": user_id,
        "password": "hashed",
        "last_login": None,
        "is_superuser": False,
        "username": f"inv_cmb_{user_id}",
        "first_name": "",
        "last_name": "",
        "email": f"inv_cmb_{user_id}@test.invalid",
        "is_staff": False,
        "is_active": True,
        "date_joined": "2026-01-01T00:00:00+00:00",
    }


def _seed_user(uid: int) -> None:
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        email = f"inv_cmb_{uid}@test.invalid"
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


def _seed_product(owner_id: int, sku: str = None) -> str:
    product_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO products (id, owner_id, sku, name, description, base_unit)
            VALUES (%s, %s, %s, %s, '', 'unit')
            """,
            (product_id, owner_id, sku or f"CMB-{product_id[:8]}", f"Prod {product_id[:8]}"),
        )
    return product_id


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_creates_batch_and_receipt_movement(db):
    """create_manual_batch inserts a batch + 1 receipt movement with reference_type='manual'."""
    owner_id = 7301
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)

    result = create_manual_batch(
        owner_id=owner_id,
        product_id=product_id,
        batch_code="MNL-001",
        expiration_date=None,
        unit_cost=Decimal("3.5000"),
        initial_quantity=Decimal("20.0000"),
    )

    assert result["batch_code"] == "MNL-001"
    assert Decimal(str(result["unit_cost"])) == Decimal("3.5000")

    batch_id = str(result["id"])
    # Verify batch row
    with psycopg.connect(_DB_URL) as conn:
        b = conn.execute(
            "SELECT batch_code, purchase_order_line_id FROM batches WHERE id = %s",
            (batch_id,),
        ).fetchone()
    assert b[0] == "MNL-001"
    assert b[1] is None  # manual batch

    # Verify receipt movement
    with psycopg.connect(_DB_URL) as conn:
        m = conn.execute(
            "SELECT kind, reference_type FROM stock_movements WHERE batch_id = %s",
            (batch_id,),
        ).fetchone()
    assert m[0] == "receipt"
    assert m[1] == "manual"
    db.rollback()


# ---------------------------------------------------------------------------
# Duplicate batch_code → BatchExists
# ---------------------------------------------------------------------------

def test_duplicate_batch_code_raises_batch_exists():
    """Inserting the same (owner_id, product_id, batch_code) twice raises BatchExists."""
    owner_id = 7302
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)

    create_manual_batch(
        owner_id=owner_id,
        product_id=product_id,
        batch_code="DUP-001",
        expiration_date=None,
        unit_cost=Decimal("1.0000"),
        initial_quantity=Decimal("10.0000"),
    )

    with pytest.raises(BatchExists):
        create_manual_batch(
            owner_id=owner_id,
            product_id=product_id,
            batch_code="DUP-001",
            expiration_date=None,
            unit_cost=Decimal("1.0000"),
            initial_quantity=Decimal("10.0000"),
        )


# ---------------------------------------------------------------------------
# Cross-owner product → ProductNotFound (D4)
# ---------------------------------------------------------------------------

def test_cross_owner_product_raises_product_not_found():
    """create_manual_batch with a product_id that belongs to another owner raises ProductNotFound."""
    owner_a = 7303
    owner_b = 7304
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_a = _seed_product(owner_a)

    with pytest.raises(ProductNotFound):
        create_manual_batch(
            owner_id=owner_b,
            product_id=product_a,
            batch_code="CROSS-001",
            expiration_date=None,
            unit_cost=Decimal("1.0000"),
            initial_quantity=Decimal("5.0000"),
        )


# ---------------------------------------------------------------------------
# Non-positive initial_quantity → ValidationError
# ---------------------------------------------------------------------------

def test_initial_quantity_must_be_positive_raises_validation_error():
    """initial_quantity <= 0 raises InventoryValidationError."""
    owner_id = 7305
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)

    with pytest.raises(InventoryValidationError):
        create_manual_batch(
            owner_id=owner_id,
            product_id=product_id,
            batch_code="ZERO-001",
            expiration_date=None,
            unit_cost=Decimal("1.0000"),
            initial_quantity=Decimal("0"),
        )
