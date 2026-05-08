"""Seed helpers for sales service tests.

Provides _make_received_batch: seeds (owner → product → batch with N units
of receipt movement). All tests that need committed inventory start here.
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import psycopg

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


def seed_user(uid: int) -> None:
    email = f"svc_{uid}@test.invalid"
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


def seed_product(owner_id: int, sku: str | None = None) -> str:
    product_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO products (id, owner_id, sku, name, description, base_unit)
            VALUES (%s, %s, %s, %s, '', 'unit')
            """,
            (product_id, owner_id, sku or f"SVC-{product_id[:8]}", f"Prod {product_id[:8]}"),
        )
    return product_id


def seed_batch(
    owner_id: int,
    product_id: str,
    quantity: str,
    unit_cost: str = "1.0000",
    batch_code: str | None = None,
    expiration_date: str | None = None,
) -> str:
    """Seed a batch + receipt movement. Returns batch_id."""
    batch_id = str(uuid.uuid4())
    code = batch_code or f"B-{batch_id[:8]}"
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost, expiration_date)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (batch_id, owner_id, product_id, code, Decimal(unit_cost), expiration_date),
        )
        conn.execute(
            """
            INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity)
            VALUES (%s, %s, 'receipt', %s)
            """,
            (owner_id, batch_id, Decimal(quantity)),
        )
    return batch_id
