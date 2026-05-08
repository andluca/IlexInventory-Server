"""EXPLAIN-based index tests for 0009_indexes.sql (ILEX-009, step 1).

These tests confirm that the new composite indexes are reachable by the
query planner for the access patterns they were built for.  `enable_seqscan`
is disabled inside each test transaction so the planner is forced to use an
index if one is suitable — the intent is "index is reachable", not "planner
picks it on 5 rows in production".
"""

from __future__ import annotations

import json
import os
import uuid
from decimal import Decimal

import psycopg
import pytest

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_user(uid: int) -> None:
    email = f"idx_{uid}@test.invalid"
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
    pid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO products (id, owner_id, sku, name, description, base_unit) VALUES (%s,%s,%s,%s,'','unit')",
            (pid, owner_id, f"IDX-{pid[:8]}", f"Idx Prod {pid[:8]}"),
        )
    return pid


def _seed_batch(owner_id: int, product_id: str) -> str:
    bid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost) VALUES (%s,%s,%s,%s,%s)",
            (bid, owner_id, product_id, f"IB-{bid[:8]}", Decimal("1.0000")),
        )
        # Add a receipt so v_stock_by_batch has a row (guards related FEFO test)
        conn.execute(
            "INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity) VALUES (%s,%s,'receipt',%s)",
            (owner_id, bid, Decimal("100.0000")),
        )
    return bid


def _explain_json(conn, sql: str, params: tuple) -> list:
    """Run EXPLAIN (FORMAT JSON) and return the parsed plan list."""
    with conn.cursor() as cur:
        cur.execute(f"EXPLAIN (FORMAT JSON) {sql}", params)
        return cur.fetchone()[0]


def _plan_text(plan_node: dict) -> str:
    """Recursively flatten the plan to a single string for assertion."""
    return json.dumps(plan_node)


# ---------------------------------------------------------------------------
# Test 1 — sm_owner_batch_created_idx is reachable
# ---------------------------------------------------------------------------

def test_movements_batch_filter_uses_new_index(db):
    """EXPLAIN on batch-scoped movements query shows sm_owner_batch_created_idx."""
    owner_id = 9001
    _seed_user(owner_id)
    pid = _seed_product(owner_id)
    bid = _seed_batch(owner_id, pid)

    with psycopg.connect(_DB_URL) as conn:
        conn.execute("SET LOCAL enable_seqscan = OFF")
        plan = _explain_json(
            conn,
            """
            SELECT * FROM stock_movements
             WHERE owner_id = %s AND batch_id = %s
             ORDER BY created_at DESC
             LIMIT 50
            """,
            (owner_id, bid),
        )

    plan_str = _plan_text(plan)
    assert "sm_owner_batch_created_idx" in plan_str, (
        f"Expected sm_owner_batch_created_idx in EXPLAIN plan, got:\n{plan_str}"
    )


# ---------------------------------------------------------------------------
# Test 2 — batches_owner_product_expiry_idx regression guard
# ---------------------------------------------------------------------------

def test_fefo_walk_uses_batches_expiry_index(db):
    """EXPLAIN on FEFO-style batches query shows batches_owner_product_expiry_idx."""
    owner_id = 9002
    _seed_user(owner_id)
    pid = _seed_product(owner_id)
    _seed_batch(owner_id, pid)

    with psycopg.connect(_DB_URL) as conn:
        conn.execute("SET LOCAL enable_seqscan = OFF")
        plan = _explain_json(
            conn,
            """
            SELECT id FROM batches
             WHERE owner_id = %s AND product_id = %s
             ORDER BY expiration_date NULLS LAST, created_at
             LIMIT 10
            """,
            (owner_id, pid),
        )

    plan_str = _plan_text(plan)
    assert "batches_owner_product_expiry_idx" in plan_str, (
        f"Expected batches_owner_product_expiry_idx in EXPLAIN plan, got:\n{plan_str}"
    )
