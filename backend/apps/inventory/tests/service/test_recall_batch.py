"""Service tests for recall_batch."""

from __future__ import annotations

import uuid
from decimal import Decimal

import os

import psycopg
import pytest

from apps.inventory.errors import BatchNotFound, RecallReasonRequired
from apps.inventory.services import create_manual_batch, recall_batch

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

pytestmark = pytest.mark.django_db


def _seed_user(uid: int) -> None:
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        email = f"inv_rb_{uid}@test.invalid"
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
            (product_id, owner_id, f"RCL-{product_id[:8]}", f"Prod {product_id[:8]}"),
        )
    return product_id


def _make_batch(owner_id: int, product_id: str, code: str) -> str:
    result = create_manual_batch(
        owner_id=owner_id,
        product_id=product_id,
        batch_code=code,
        expiration_date=None,
        unit_cost=Decimal("1.0000"),
        initial_quantity=Decimal("10.0000"),
    )
    return str(result["id"])


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_recall_sets_flag_and_writes_recall_block_movement():
    """recall_batch sets is_recalled=True, populated recalled_at, writes recall_block movement."""
    owner_id = 7601
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _make_batch(owner_id, product_id, "RCALL-001")

    result = recall_batch(owner_id=owner_id, batch_id=batch_id, reason="contamination detected")

    assert result["is_recalled"] is True
    assert result["recall_reason"] == "contamination detected"
    assert result["recalled_at"] is not None

    with psycopg.connect(_DB_URL) as conn:
        b = conn.execute(
            "SELECT is_recalled, recalled_at FROM batches WHERE id = %s", (batch_id,)
        ).fetchone()
    assert b[0] is True
    assert b[1] is not None

    with psycopg.connect(_DB_URL) as conn:
        m = conn.execute(
            "SELECT kind, signed_quantity, notes FROM stock_movements WHERE batch_id = %s AND kind = 'recall_block'",
            (batch_id,),
        ).fetchone()
    assert m is not None
    assert Decimal(str(m[1])) == Decimal("0")
    assert m[2] == "contamination detected"


# ---------------------------------------------------------------------------
# Idempotent on already-recalled
# ---------------------------------------------------------------------------

def test_recall_idempotent_on_already_recalled_no_writes():
    """recall_batch called twice: second call is a no-op, movement count stays at 1."""
    owner_id = 7602
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _make_batch(owner_id, product_id, "RCALL-IDMP")

    recall_batch(owner_id=owner_id, batch_id=batch_id, reason="defect")
    result2 = recall_batch(owner_id=owner_id, batch_id=batch_id, reason="defect")

    # State unchanged
    assert result2["is_recalled"] is True

    with psycopg.connect(_DB_URL) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM stock_movements WHERE batch_id = %s AND kind = 'recall_block'",
            (batch_id,),
        ).fetchone()[0]
    assert count == 1  # only one recall_block movement


# ---------------------------------------------------------------------------
# Blank reason → RecallReasonRequired
# ---------------------------------------------------------------------------

def test_recall_with_blank_reason_raises_validation_error():
    """recall_batch with blank reason raises RecallReasonRequired."""
    owner_id = 7603
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _make_batch(owner_id, product_id, "RCALL-BLANK")

    with pytest.raises(RecallReasonRequired):
        recall_batch(owner_id=owner_id, batch_id=batch_id, reason="  ")


# ---------------------------------------------------------------------------
# Cross-owner
# ---------------------------------------------------------------------------

def test_recall_cross_owner_raises_batch_not_found():
    """recall_batch with wrong owner_id raises BatchNotFound (D4)."""
    owner_a = 7604
    owner_b = 7605
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_id = _seed_product(owner_a)
    batch_id = _make_batch(owner_a, product_id, "RCALL-CROSS")

    with pytest.raises(BatchNotFound):
        recall_batch(owner_id=owner_b, batch_id=batch_id, reason="contamination")
