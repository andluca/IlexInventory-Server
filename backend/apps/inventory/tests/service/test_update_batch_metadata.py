"""Service tests for update_batch_metadata."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import os

import psycopg
import pytest

from apps.inventory.errors import BatchNotFound
from apps.inventory.services import create_manual_batch, update_batch_metadata

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

pytestmark = pytest.mark.django_db


def _seed_user(uid: int) -> None:
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        email = f"inv_ubm_{uid}@test.invalid"
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
            (product_id, owner_id, f"UBM-{product_id[:8]}", f"Prod {product_id[:8]}"),
        )
    return product_id


def _make_batch(owner_id: int, product_id: str, batch_code: str) -> str:
    result = create_manual_batch(
        owner_id=owner_id,
        product_id=product_id,
        batch_code=batch_code,
        expiration_date=None,
        unit_cost=Decimal("1.0000"),
        initial_quantity=Decimal("10.0000"),
    )
    return str(result["id"])


# ---------------------------------------------------------------------------
# Changing batch_code writes metadata_correction movement
# ---------------------------------------------------------------------------

def test_changing_batch_code_writes_metadata_correction_movement(db):
    """update_batch_metadata writes metadata_correction movement (qty=0, notes=diff)."""
    owner_id = 7501
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _make_batch(owner_id, product_id, "OLD-CODE")

    result = update_batch_metadata(
        owner_id=owner_id,
        batch_id=batch_id,
        batch_code="NEW-CODE",
        expiration_date=None,
    )

    assert result["batch_code"] == "NEW-CODE"

    # Verify batch state
    with psycopg.connect(_DB_URL) as conn:
        row = conn.execute(
            "SELECT batch_code FROM batches WHERE id = %s", (batch_id,)
        ).fetchone()
    assert row[0] == "NEW-CODE"

    # Verify movements for this batch: receipt + metadata_correction
    with psycopg.connect(_DB_URL) as conn:
        rows = conn.execute(
            "SELECT kind, signed_quantity FROM stock_movements WHERE batch_id = %s ORDER BY created_at",
            (batch_id,),
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "receipt"
    assert rows[1][0] == "metadata_correction"
    assert Decimal(str(rows[1][1])) == Decimal("0")
    db.rollback()


# ---------------------------------------------------------------------------
# No change is idempotent — no movement written
# ---------------------------------------------------------------------------

def test_unchanged_value_is_idempotent_no_movement_written(db):
    """update_batch_metadata with same values returns current batch without writing movement."""
    owner_id = 7502
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _make_batch(owner_id, product_id, "SAME-CODE")

    update_batch_metadata(
        owner_id=owner_id,
        batch_id=batch_id,
        batch_code="SAME-CODE",     # same as current
        expiration_date=None,       # same as current (None)
    )

    # Only the original receipt movement should exist for this batch
    with psycopg.connect(_DB_URL) as conn:
        rows = conn.execute(
            "SELECT kind FROM stock_movements WHERE batch_id = %s",
            (batch_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "receipt"
    db.rollback()


# ---------------------------------------------------------------------------
# Changing expiration_date to None (clear_expiration=True)
# ---------------------------------------------------------------------------

def test_changing_expiration_date_to_null_works(db):
    """Setting clear_expiration=True sets expiration_date to NULL and writes audit movement."""
    owner_id = 7503
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)

    batch = create_manual_batch(
        owner_id=owner_id,
        product_id=product_id,
        batch_code="EXP-CLEAR",
        expiration_date=date(2027, 6, 1),
        unit_cost=Decimal("1.0000"),
        initial_quantity=Decimal("10.0000"),
    )
    batch_id = str(batch["id"])

    result = update_batch_metadata(
        owner_id=owner_id,
        batch_id=batch_id,
        batch_code=None,
        expiration_date=None,
        clear_expiration=True,
    )

    assert result["expiration_date"] is None

    with psycopg.connect(_DB_URL) as conn:
        rows = conn.execute(
            "SELECT kind FROM stock_movements WHERE batch_id = %s ORDER BY created_at",
            (batch_id,),
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "receipt"
    assert rows[1][0] == "metadata_correction"
    db.rollback()


# ---------------------------------------------------------------------------
# Cross-owner raises BatchNotFound
# ---------------------------------------------------------------------------

def test_cross_owner_raises_batch_not_found():
    """update_batch_metadata with wrong owner_id raises BatchNotFound (D4)."""
    owner_a = 7504
    owner_b = 7505
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_id = _seed_product(owner_a)
    batch_id = _make_batch(owner_a, product_id, "CROSS-UBM")

    with pytest.raises(BatchNotFound):
        update_batch_metadata(
            owner_id=owner_b,
            batch_id=batch_id,
            batch_code="NEW",
            expiration_date=None,
        )
