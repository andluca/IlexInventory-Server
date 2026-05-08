"""Query-layer tests for apps.inventory.queries.batches."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import psycopg
import psycopg.errors
import pytest

from apps.catalog.queries.products import count_batches_for_product
from apps.inventory.queries.batches import (
    insert_batch,
    list_batches,
    list_eligible_for_fefo,
    select_batch_by_id,
)

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_user(uid: int) -> None:
    email = f"inv_bq_{uid}@test.invalid"
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


def _seed_product(owner_id: int, sku_suffix: str = "") -> str:
    product_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO products (id, owner_id, sku, name, description, base_unit)
            VALUES (%s, %s, %s, %s, '', 'unit')
            """,
            (product_id, owner_id, f"BQ-{sku_suffix or product_id[:8]}", f"Product {product_id[:8]}"),
        )
    return product_id


def _raw_insert_batch(
    owner_id: int,
    product_id: str,
    batch_code: str,
    *,
    expiration_date=None,
    is_recalled: bool = False,
    unit_cost=Decimal("1.0000"),
) -> str:
    batch_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        if is_recalled:
            conn.execute(
                """
                INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost,
                                     expiration_date, is_recalled, recall_reason, recalled_at)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, 'test recall', NOW())
                """,
                (batch_id, owner_id, product_id, batch_code, unit_cost, expiration_date),
            )
        else:
            conn.execute(
                """
                INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost, expiration_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (batch_id, owner_id, product_id, batch_code, unit_cost, expiration_date),
            )
    return batch_id


def _seed_receipt(owner_id: int, batch_id: str, qty: Decimal = Decimal("10.0000")) -> None:
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity)
            VALUES (%s, %s, 'receipt', %s)
            """,
            (owner_id, batch_id, qty),
        )


# ---------------------------------------------------------------------------
# insert_batch
# ---------------------------------------------------------------------------

def test_insert_batch_returns_row_with_uuidv7_id():
    """insert_batch returns a dict with a non-null UUID id."""
    owner_id = 7101
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            row = insert_batch(cur, params={
                "owner_id": owner_id,
                "product_id": product_id,
                "purchase_order_line_id": None,
                "batch_code": "INS-001",
                "expiration_date": None,
                "unit_cost": Decimal("5.0000"),
            })
        conn.commit()

    assert row["id"] is not None
    # Should be a valid UUID
    uuid.UUID(str(row["id"]))
    assert row["batch_code"] == "INS-001"
    assert row["owner_id"] == owner_id


# ---------------------------------------------------------------------------
# select_batch_by_id
# ---------------------------------------------------------------------------

def test_select_batch_by_id_cross_owner_returns_none():
    """select_batch_by_id with wrong owner_id returns None (D4)."""
    owner_a = 7102
    owner_b = 7103
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_id = _seed_product(owner_a)
    batch_id = _raw_insert_batch(owner_a, product_id, "CROSS-001")

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            result = select_batch_by_id(cur, params={"id": batch_id, "owner_id": owner_b})

    assert result is None


# ---------------------------------------------------------------------------
# list_eligible_for_fefo
# ---------------------------------------------------------------------------

def test_list_eligible_for_fefo_orders_by_expiry_then_created_at():
    """FEFO orders: earlier expiry first, NULL last; recalled and expired excluded."""
    owner_id = 7104
    _seed_user(owner_id)
    product_id = _seed_product(owner_id, "FEFO")

    # Batch A: expiry 2027-06-01 (earlier)
    batch_a = _raw_insert_batch(owner_id, product_id, "FEFO-A", expiration_date="2027-06-01")
    _seed_receipt(owner_id, batch_a, Decimal("5.0000"))

    # Batch B: no expiry (NULL → should come last)
    batch_b = _raw_insert_batch(owner_id, product_id, "FEFO-B", expiration_date=None)
    _seed_receipt(owner_id, batch_b, Decimal("5.0000"))

    # Batch C: expiry 2027-12-01 (later)
    batch_c = _raw_insert_batch(owner_id, product_id, "FEFO-C", expiration_date="2027-12-01")
    _seed_receipt(owner_id, batch_c, Decimal("5.0000"))

    # Batch D: recalled — must be excluded (D11)
    batch_d = _raw_insert_batch(owner_id, product_id, "FEFO-D", is_recalled=True)
    _seed_receipt(owner_id, batch_d, Decimal("5.0000"))

    # Batch E: expired (yesterday) — must be excluded (D11)
    batch_e = _raw_insert_batch(owner_id, product_id, "FEFO-E", expiration_date="2020-01-01")
    _seed_receipt(owner_id, batch_e, Decimal("5.0000"))

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            rows = list_eligible_for_fefo(cur, params={"owner_id": owner_id, "product_id": product_id})

    ids = [str(r["id"]) for r in rows]
    # A (2027-06), C (2027-12), B (NULL) — D and E excluded
    assert str(batch_a) in ids
    assert str(batch_c) in ids
    assert str(batch_b) in ids
    assert str(batch_d) not in ids  # recalled
    assert str(batch_e) not in ids  # expired

    # Order: A before C, both before B (NULL last)
    assert ids.index(str(batch_a)) < ids.index(str(batch_c))
    assert ids.index(str(batch_c)) < ids.index(str(batch_b))


def test_list_eligible_for_fefo_zero_on_hand_excluded():
    """FEFO excludes batches with zero on-hand (no movements or movements sum to 0)."""
    owner_id = 7105
    _seed_user(owner_id)
    product_id = _seed_product(owner_id, "FEFO-ZERO")

    # Batch with zero on-hand (no receipt movement)
    _raw_insert_batch(owner_id, product_id, "FEFO-ZERO-1")

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            rows = list_eligible_for_fefo(cur, params={"owner_id": owner_id, "product_id": product_id})

    assert rows == []


def test_list_eligible_for_fefo_takes_for_update_lock():
    """FOR UPDATE lock blocks concurrent SELECT FOR UPDATE NOWAIT on same rows."""
    owner_id = 7106
    _seed_user(owner_id)
    product_id = _seed_product(owner_id, "FEFO-LOCK")
    batch_id = _raw_insert_batch(owner_id, product_id, "LOCK-001", expiration_date="2027-06-01")
    _seed_receipt(owner_id, batch_id)

    conn1 = psycopg.connect(_DB_URL)
    conn2 = psycopg.connect(_DB_URL)
    try:
        cur1 = conn1.cursor()
        # conn1 acquires FOR UPDATE
        list_eligible_for_fefo(cur1, params={"owner_id": owner_id, "product_id": product_id})

        cur2 = conn2.cursor()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            cur2.execute(
                """
                SELECT * FROM batches
                 WHERE owner_id = %s AND product_id = %s
                 FOR UPDATE NOWAIT
                """,
                (owner_id, product_id),
            )
            conn2.rollback()
    finally:
        conn1.rollback()
        conn1.close()
        conn2.close()


# ---------------------------------------------------------------------------
# list_batches filters
# ---------------------------------------------------------------------------

def test_list_batches_filter_expiring_within_30_days():
    """list_batches with expiring_within=30 returns only batches expiring ≤ 30 days out."""
    owner_id = 7107
    _seed_user(owner_id)
    product_id = _seed_product(owner_id, "EXP")

    # Batch expiring in 10 days from now (should match)
    _raw_insert_batch(owner_id, product_id, "EXP-SOON", expiration_date="2026-05-18")

    # Batch expiring in 60 days (should not match)
    _raw_insert_batch(owner_id, product_id, "EXP-LATER", expiration_date="2026-07-08")

    # Batch with no expiration (should not match)
    _raw_insert_batch(owner_id, product_id, "EXP-NULL")

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            rows, total = list_batches(cur, params={
                "owner_id": owner_id,
                "product_id": product_id,
                "is_recalled": None,
                "expiring_within": 30,
                "limit": 50,
                "offset": 0,
            })

    codes = [r["batch_code"] for r in rows]
    assert "EXP-SOON" in codes
    assert "EXP-LATER" not in codes
    assert "EXP-NULL" not in codes


def test_list_batches_filter_is_recalled():
    """list_batches with is_recalled=True returns only recalled batches."""
    owner_id = 7108
    _seed_user(owner_id)
    product_id = _seed_product(owner_id, "RCALL")

    _raw_insert_batch(owner_id, product_id, "RCL-ACTIVE")
    _raw_insert_batch(owner_id, product_id, "RCL-RECALLED", is_recalled=True)

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            rows, total = list_batches(cur, params={
                "owner_id": owner_id,
                "product_id": product_id,
                "is_recalled": True,
                "expiring_within": None,
                "limit": 50,
                "offset": 0,
            })

    codes = [r["batch_code"] for r in rows]
    assert "RCL-RECALLED" in codes
    assert "RCL-ACTIVE" not in codes


# ---------------------------------------------------------------------------
# count_batches_for_product (catalog query — now real)
# ---------------------------------------------------------------------------

def test_count_batches_for_product_returns_real_count():
    """count_batches_for_product returns actual batch count from batches table."""
    owner_id = 7109
    _seed_user(owner_id)
    product_id = _seed_product(owner_id, "COUNT")

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            count0 = count_batches_for_product(cur, params={"owner_id": owner_id, "product_id": product_id})

    assert count0 == 0

    # Seed 2 batches
    _raw_insert_batch(owner_id, product_id, "CNT-001")
    _raw_insert_batch(owner_id, product_id, "CNT-002")

    with psycopg.connect(_DB_URL) as conn:
        with conn.cursor() as cur:
            count2 = count_batches_for_product(cur, params={"owner_id": owner_id, "product_id": product_id})

    assert count2 == 2
