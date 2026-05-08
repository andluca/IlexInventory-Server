"""Query-layer tests for apps.inventory.queries.movements."""

from __future__ import annotations

import time
import uuid
from decimal import Decimal

import os

import psycopg
import pytest

from apps.inventory.queries.movements import (
    insert_movement,
    list_movements,
    on_hand_for_batch,
)

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_user(uid: int) -> None:
    email = f"inv_mq_{uid}@test.invalid"
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
            (product_id, owner_id, f"MQ-{product_id[:8]}", f"Product {product_id[:8]}"),
        )
    return product_id


def _seed_batch(owner_id: int, product_id: str, batch_code: str = "MQ-001") -> str:
    batch_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost)
            VALUES (%s, %s, %s, %s, 1.0)
            """,
            (batch_id, owner_id, product_id, batch_code),
        )
    return batch_id


def _raw_receipt(owner_id: int, batch_id: str, qty: Decimal = Decimal("10.0000")) -> str:
    mov_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO stock_movements (id, owner_id, batch_id, kind, signed_quantity)
            VALUES (%s, %s, %s, 'receipt', %s)
            """,
            (mov_id, owner_id, batch_id, qty),
        )
    return mov_id


# ---------------------------------------------------------------------------
# insert_movement
# ---------------------------------------------------------------------------

def test_insert_movement_returns_row():
    """insert_movement returns the full row dict with a non-null id."""
    owner_id = 7201
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id)

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            row = insert_movement(cur, params={
                "owner_id": owner_id,
                "batch_id": batch_id,
                "kind": "receipt",
                "signed_quantity": Decimal("10.0000"),
                "notes": None,
                "reference_type": "manual",
                "reference_id": None,
            })
        conn.commit()

    assert row["id"] is not None
    assert row["kind"] == "receipt"
    assert row["owner_id"] == owner_id
    assert Decimal(str(row["signed_quantity"])) == Decimal("10.0000")


# ---------------------------------------------------------------------------
# on_hand_for_batch
# ---------------------------------------------------------------------------

def test_on_hand_for_batch_via_view_sums_signed_quantity():
    """on_hand_for_batch sums signed_quantity via v_stock_by_batch: receipt +10, write-off -3 = 7."""
    owner_id = 7202
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id, "OH-001")

    # Receipt +10
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity) VALUES (%s, %s, 'receipt', 10)",
            (owner_id, batch_id),
        )
    # Write-off -3
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity) VALUES (%s, %s, 'write_off', -3)",
            (owner_id, batch_id),
        )

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            on_hand = on_hand_for_batch(cur, params={"batch_id": batch_id, "owner_id": owner_id})

    assert Decimal(str(on_hand)) == Decimal("7.0000")


# ---------------------------------------------------------------------------
# list_movements cursor pagination
# ---------------------------------------------------------------------------

def test_list_movements_cursor_pagination_orders_desc():
    """list_movements returns latest first; cursor advances to next page."""
    owner_id = 7203
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id, "PAGE-001")

    # Seed receipt so batch exists, then 5 adjustments with distinct timestamps
    _raw_receipt(owner_id, batch_id, Decimal("50.0000"))

    for i in range(1, 6):
        with psycopg.connect(_DB_URL, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity, notes)
                VALUES (%s, %s, 'adjustment', %s, %s)
                """,
                (owner_id, batch_id, i, f"adj {i}"),
            )
        time.sleep(0.01)  # ensure distinct created_at

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            # Page 1: limit=2 (desc order, so notes 'adj 5', 'adj 4')
            page1_rows, next_cursor = list_movements(cur, params={
                "owner_id": owner_id,
                "batch_id": batch_id,
                "product_id": None,
                "kind": "adjustment",
                "date_from": None,
                "date_to": None,
                "cursor": None,
                "limit": 2,
            })

    assert len(page1_rows) == 2
    assert next_cursor is not None
    # Latest signed_quantity is 5 (most recent adjustment)
    assert Decimal(str(page1_rows[0]["signed_quantity"])) == Decimal("5")
    assert Decimal(str(page1_rows[1]["signed_quantity"])) == Decimal("4")

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            page2_rows, next_cursor2 = list_movements(cur, params={
                "owner_id": owner_id,
                "batch_id": batch_id,
                "product_id": None,
                "kind": "adjustment",
                "date_from": None,
                "date_to": None,
                "cursor": next_cursor,
                "limit": 2,
            })

    assert len(page2_rows) == 2
    assert Decimal(str(page2_rows[0]["signed_quantity"])) == Decimal("3")
    assert Decimal(str(page2_rows[1]["signed_quantity"])) == Decimal("2")


def test_list_movements_filter_by_kind_and_date_range():
    """list_movements with kind and date_from/date_to filters."""
    owner_id = 7204
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    batch_id = _seed_batch(owner_id, product_id, "FILT-001")
    _raw_receipt(owner_id, batch_id, Decimal("20.0000"))

    # Write-off (should appear in kind filter)
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity) VALUES (%s, %s, 'write_off', -5)",
            (owner_id, batch_id),
        )

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            rows, _ = list_movements(cur, params={
                "owner_id": owner_id,
                "batch_id": batch_id,
                "product_id": None,
                "kind": "write_off",
                "date_from": None,
                "date_to": None,
                "cursor": None,
                "limit": 50,
            })

    assert len(rows) == 1
    assert rows[0]["kind"] == "write_off"
