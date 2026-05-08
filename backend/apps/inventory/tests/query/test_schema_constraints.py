"""Schema-level constraint tests for batches + stock_movements.

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
    email = f"inv_schema_{uid}@test.invalid"
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
            (product_id, owner_id, f"SC-{product_id[:8]}", f"Product {product_id[:8]}"),
        )
    return product_id


def _seed_batch(owner_id: int, product_id: str, batch_code: str = "B-001") -> str:
    batch_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (batch_id, owner_id, product_id, batch_code, Decimal("1.0000")),
        )
    return batch_id


def _seed_receipt_movement(owner_id: int, batch_id: str) -> str:
    mov_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO stock_movements (id, owner_id, batch_id, kind, signed_quantity)
            VALUES (%s, %s, %s, 'receipt', %s)
            """,
            (mov_id, owner_id, batch_id, Decimal("10.0000")),
        )
    return mov_id


# ---------------------------------------------------------------------------
# Append-only trigger tests
# ---------------------------------------------------------------------------

def test_stock_movements_update_rejected_by_trigger():
    """UPDATE on stock_movements raises trigger exception (append-only, D3)."""
    owner_id = 7001
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id)
    mov_id = _seed_receipt_movement(owner_id, batch_id)

    with pytest.raises(psycopg.errors.RaiseException):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                "UPDATE stock_movements SET notes = 'tampered' WHERE id = %s",
                (mov_id,),
            )


def test_stock_movements_delete_rejected_by_trigger():
    """DELETE on stock_movements raises trigger exception (append-only, D3)."""
    owner_id = 7002
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id)
    mov_id = _seed_receipt_movement(owner_id, batch_id)

    with pytest.raises(psycopg.errors.RaiseException):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                "DELETE FROM stock_movements WHERE id = %s",
                (mov_id,),
            )


# ---------------------------------------------------------------------------
# Kind + sign CHECK constraints
# ---------------------------------------------------------------------------

def test_kind_sign_check_constraint_receipt_negative():
    """INSERT receipt with signed_quantity < 0 violates sm_sign_chk."""
    owner_id = 7003
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity)
                VALUES (%s, %s, 'receipt', -1)
                """,
                (owner_id, batch_id),
            )


def test_kind_sign_check_constraint_recall_block_nonzero():
    """INSERT recall_block with signed_quantity != 0 violates sm_sign_chk."""
    owner_id = 7004
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity)
                VALUES (%s, %s, 'recall_block', 5)
                """,
                (owner_id, batch_id),
            )


def test_kind_sign_check_constraint_adjustment_zero():
    """INSERT adjustment with signed_quantity = 0 violates sm_sign_chk."""
    owner_id = 7005
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity, notes)
                VALUES (%s, %s, 'adjustment', 0, 'reason')
                """,
                (owner_id, batch_id),
            )


# ---------------------------------------------------------------------------
# Adjustment notes required (D7)
# ---------------------------------------------------------------------------

def test_adjustment_notes_required():
    """INSERT adjustment with notes IS NULL violates sm_adjustment_notes_chk (D7)."""
    owner_id = 7006
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity, notes)
                VALUES (%s, %s, 'adjustment', 5, NULL)
                """,
                (owner_id, batch_id),
            )


# ---------------------------------------------------------------------------
# Recall consistency CHECK on batches
# ---------------------------------------------------------------------------

def test_recall_consistency_check():
    """INSERT batch with is_recalled=TRUE but recalled_at NULL violates batches_recall_consistency."""
    owner_id = 7007
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO batches (owner_id, product_id, batch_code, unit_cost,
                                     is_recalled, recall_reason, recalled_at)
                VALUES (%s, %s, 'BAD-RECALL', 1.0, TRUE, 'defect', NULL)
                """,
                (owner_id, product_id),
            )


# ---------------------------------------------------------------------------
# Unique constraint on (owner_id, product_id, batch_code)
# ---------------------------------------------------------------------------

def test_batches_owner_product_code_unique():
    """Duplicate (owner_id, product_id, batch_code) violates batches_owner_product_code_unique."""
    owner_id = 7008
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    _seed_batch(owner_id, product_id, batch_code="DUP-001")

    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO batches (owner_id, product_id, batch_code, unit_cost)
                VALUES (%s, %s, 'DUP-001', 1.0)
                """,
                (owner_id, product_id),
            )


# ---------------------------------------------------------------------------
# D4 composite FK: cross-owner product reference rejected
# ---------------------------------------------------------------------------

def test_batches_cross_owner_product_fk_rejected():
    """INSERT batch with (product_id, owner_id) that mismatches products row violates FK."""
    owner_a = 7009
    owner_b = 7010
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_a = _seed_product(owner_a)

    # owner_b tries to reference owner_a's product — FK (product_id, owner_id) must reject this.
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO batches (owner_id, product_id, batch_code, unit_cost)
                VALUES (%s, %s, 'CROSS-001', 1.0)
                """,
                (owner_b, product_a),
            )
