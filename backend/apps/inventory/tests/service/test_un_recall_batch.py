"""Service tests for un_recall_batch."""

from __future__ import annotations

import uuid
from decimal import Decimal

import os

import psycopg
import pytest

from apps.inventory.errors import BatchNotFound
from apps.inventory.services import create_manual_batch, recall_batch, un_recall_batch

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

pytestmark = pytest.mark.django_db


def _seed_user(uid: int) -> None:
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        email = f"inv_urb_{uid}@test.invalid"
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
            (product_id, owner_id, f"URB-{product_id[:8]}", f"Prod {product_id[:8]}"),
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

def test_un_recall_clears_flag_and_writes_recall_unblock_movement():
    """un_recall_batch clears is_recalled, clears recall_reason/recalled_at, writes recall_unblock."""
    owner_id = 7701
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _make_batch(owner_id, product_id, "URB-001")

    recall_batch(owner_id=owner_id, batch_id=batch_id, reason="precaution")
    result = un_recall_batch(owner_id=owner_id, batch_id=batch_id)

    assert result["is_recalled"] is False
    assert result["recall_reason"] is None
    assert result["recalled_at"] is None

    with psycopg.connect(_DB_URL) as conn:
        m = conn.execute(
            "SELECT kind FROM stock_movements WHERE batch_id = %s AND kind = 'recall_unblock'",
            (batch_id,),
        ).fetchone()
    assert m is not None


# ---------------------------------------------------------------------------
# Idempotent when not recalled
# ---------------------------------------------------------------------------

def test_un_recall_idempotent_when_not_recalled():
    """un_recall_batch on a non-recalled batch is a no-op (returns current state, no movement)."""
    owner_id = 7702
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _make_batch(owner_id, product_id, "URB-IDMP")

    result = un_recall_batch(owner_id=owner_id, batch_id=batch_id)

    assert result["is_recalled"] is False

    with psycopg.connect(_DB_URL) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM stock_movements WHERE batch_id = %s AND kind = 'recall_unblock'",
            (batch_id,),
        ).fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# Cross-owner
# ---------------------------------------------------------------------------

def test_un_recall_cross_owner_raises_batch_not_found():
    """un_recall_batch with wrong owner_id raises BatchNotFound (D4)."""
    owner_a = 7703
    owner_b = 7704
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_id = _seed_product(owner_a)
    batch_id = _make_batch(owner_a, product_id, "URB-CROSS")

    with pytest.raises(BatchNotFound):
        un_recall_batch(owner_id=owner_b, batch_id=batch_id)
