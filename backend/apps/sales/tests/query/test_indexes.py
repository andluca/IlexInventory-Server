"""EXPLAIN-based index tests for so_owner_status_created_idx (0009_indexes.sql).

Confirms the new (owner_id, status, created_at DESC) index is reachable for
status-filtered cursor pagination queries on sales_orders.
"""

from __future__ import annotations

import json
import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


def _seed_user(uid: int) -> None:
    email = f"so_idx_{uid}@test.invalid"
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


def _explain_json(conn, sql: str, params: tuple) -> list:
    with conn.cursor() as cur:
        cur.execute(f"EXPLAIN (FORMAT JSON) {sql}", params)
        return cur.fetchone()[0]


def _plan_text(plan_node) -> str:
    return json.dumps(plan_node)


# ---------------------------------------------------------------------------
# Test — so_owner_status_created_idx is reachable
# ---------------------------------------------------------------------------

def test_status_filtered_so_list_uses_new_index(db):
    """EXPLAIN on status+cursor SO query shows so_owner_status_created_idx."""
    owner_id = 9101
    _seed_user(owner_id)

    # Seed a draft SO so there is at least one row
    so_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO sales_orders (id, owner_id, customer_name, status)
            VALUES (%s, %s, 'Test Customer', 'draft')
            """,
            (so_id, owner_id),
        )

    with psycopg.connect(_DB_URL) as conn:
        conn.execute("SET LOCAL enable_seqscan = OFF")
        plan = _explain_json(
            conn,
            """
            SELECT id, created_at FROM sales_orders
             WHERE owner_id = %s AND status = %s
             ORDER BY created_at DESC
             LIMIT 50
            """,
            (owner_id, "draft"),
        )

    plan_str = _plan_text(plan)
    assert "so_owner_status_created_idx" in plan_str, (
        f"Expected so_owner_status_created_idx in EXPLAIN plan, got:\n{plan_str}"
    )
