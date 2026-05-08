"""Service tests for record_movement."""

from __future__ import annotations

import uuid
from decimal import Decimal

import os

import psycopg
import pytest

from apps.inventory.errors import BatchNotFound, InvalidMovementKind, WriteOffExceedsOnHand
from apps.inventory.errors import ValidationError as InventoryValidationError
from apps.inventory.services import create_manual_batch, record_movement

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

pytestmark = pytest.mark.django_db


def _seed_user(uid: int) -> None:
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        email = f"inv_rm_{uid}@test.invalid"
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
            (product_id, owner_id, f"RM-{product_id[:8]}", f"Prod {product_id[:8]}"),
        )
    return product_id


def _make_batch(owner_id: int, product_id: str, batch_code: str, qty: Decimal) -> str:
    result = create_manual_batch(
        owner_id=owner_id,
        product_id=product_id,
        batch_code=batch_code,
        expiration_date=None,
        unit_cost=Decimal("1.0000"),
        initial_quantity=qty,
    )
    return str(result["id"])


# ---------------------------------------------------------------------------
# Adjustment
# ---------------------------------------------------------------------------

def test_adjustment_writes_movement_and_changes_on_hand(db):
    """Adjustment movement is inserted; on_hand changes accordingly."""
    owner_id = 7401
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _make_batch(owner_id, product_id, "ADJ-001", Decimal("10.0000"))

    result = record_movement(
        owner_id=owner_id,
        batch_id=batch_id,
        kind="adjustment",
        signed_quantity=Decimal("-2.0000"),
        notes="shrinkage correction",
    )

    assert result["kind"] == "adjustment"
    assert Decimal(str(result["signed_quantity"])) == Decimal("-2.0000")

    with psycopg.connect(_DB_URL) as conn:
        rows = conn.execute(
            "SELECT kind, signed_quantity, notes FROM stock_movements WHERE batch_id = %s ORDER BY created_at",
            (batch_id,),
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "receipt"
    assert rows[1][0] == "adjustment"
    assert Decimal(str(rows[1][1])) == Decimal("-2.0000")
    assert rows[1][2] == "shrinkage correction"
    db.rollback()


def test_adjustment_with_blank_notes_raises_validation_error():
    """Adjustment with empty notes raises InventoryValidationError (D7)."""
    owner_id = 7402
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _make_batch(owner_id, product_id, "ADJ-BLANK", Decimal("10.0000"))

    with pytest.raises(InventoryValidationError):
        record_movement(
            owner_id=owner_id,
            batch_id=batch_id,
            kind="adjustment",
            signed_quantity=Decimal("1.0000"),
            notes="   ",
        )


# ---------------------------------------------------------------------------
# Write-off
# ---------------------------------------------------------------------------

def test_write_off_within_on_hand_succeeds(db):
    """Write-off within available on_hand succeeds and records movement."""
    owner_id = 7403
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _make_batch(owner_id, product_id, "WO-OK", Decimal("15.0000"))

    result = record_movement(
        owner_id=owner_id,
        batch_id=batch_id,
        kind="write_off",
        signed_quantity=Decimal("-5.0000"),
        notes=None,
    )

    assert result["kind"] == "write_off"
    assert Decimal(str(result["signed_quantity"])) == Decimal("-5.0000")

    with psycopg.connect(_DB_URL) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM stock_movements WHERE batch_id = %s AND kind = 'write_off'",
            (batch_id,),
        ).fetchone()[0]
    assert count == 1
    db.rollback()


def test_write_off_into_negative_raises_write_off_exceeds_on_hand():
    """Write-off exceeding on_hand raises WriteOffExceedsOnHand (422)."""
    owner_id = 7404
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _make_batch(owner_id, product_id, "WO-NEG", Decimal("5.0000"))

    with pytest.raises(WriteOffExceedsOnHand):
        record_movement(
            owner_id=owner_id,
            batch_id=batch_id,
            kind="write_off",
            signed_quantity=Decimal("-10.0000"),
            notes=None,
        )


# ---------------------------------------------------------------------------
# Invalid kind
# ---------------------------------------------------------------------------

def test_kind_outside_allowlist_raises_invalid_movement_kind():
    """kind='sale' via record_movement raises InvalidMovementKind."""
    owner_id = 7405
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _make_batch(owner_id, product_id, "IK-001", Decimal("5.0000"))

    with pytest.raises(InvalidMovementKind):
        record_movement(
            owner_id=owner_id,
            batch_id=batch_id,
            kind="sale",
            signed_quantity=Decimal("-1.0000"),
            notes=None,
        )


# ---------------------------------------------------------------------------
# Cross-owner
# ---------------------------------------------------------------------------

def test_cross_owner_batch_raises_batch_not_found():
    """record_movement with wrong owner_id raises BatchNotFound (D4)."""
    owner_a = 7406
    owner_b = 7407
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_id = _seed_product(owner_a)
    batch_id = _make_batch(owner_a, product_id, "CROSS-RM", Decimal("10.0000"))

    with pytest.raises(BatchNotFound):
        record_movement(
            owner_id=owner_b,
            batch_id=batch_id,
            kind="write_off",
            signed_quantity=Decimal("-1.0000"),
            notes=None,
        )
