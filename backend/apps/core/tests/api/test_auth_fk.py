"""Integration test: idempotency_keys.owner_id FK to auth_user(id).

Verifies that 0002_auth_fk.sql correctly:
- Changed owner_id from UUID to INT
- Added FK from idempotency_keys.owner_id → auth_user(id) ON DELETE CASCADE

All DB interaction uses raw psycopg — no ORM.
"""

from __future__ import annotations

import os

import psycopg
import psycopg.errors
import pytest


def _db_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test"
    )


def _insert_auth_user(conn: psycopg.Connection, uid: int, email: str) -> None:
    conn.execute(
        """
        INSERT INTO auth_user
            (id, username, email, password,
             is_superuser, is_staff, is_active,
             first_name, last_name, date_joined)
        VALUES (%s, %s, %s, 'unusable!', false, false, true, '', '', NOW())
        """,
        (uid, email, email),
    )


def _insert_idempotency_key(
    conn: psycopg.Connection, owner_id: int, key: str
) -> None:
    conn.execute(
        """
        INSERT INTO idempotency_keys
            (owner_id, key, endpoint, response_status, response_body)
        VALUES (%s, %s, 'test.endpoint', 200, '{}')
        """,
        (owner_id, key),
    )


@pytest.fixture(autouse=True)
def _clean(db):
    """Truncate between tests for isolation."""
    with psycopg.connect(_db_url(), autocommit=True) as conn:
        conn.execute("TRUNCATE idempotency_keys")
        conn.execute(
            "DELETE FROM auth_user WHERE id >= 8000 AND id < 9000"
        )
    yield
    with psycopg.connect(_db_url(), autocommit=True) as conn:
        conn.execute("TRUNCATE idempotency_keys")
        conn.execute(
            "DELETE FROM auth_user WHERE id >= 8000 AND id < 9000"
        )


def test_fk_violation_when_owner_not_in_auth_user():
    """Inserting an owner_id not in auth_user raises ForeignKeyViolation."""
    with psycopg.connect(_db_url()) as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            _insert_idempotency_key(conn, owner_id=8001, key="fk-bad")
            conn.commit()


def test_insert_succeeds_with_real_auth_user():
    """Inserting owner_id that matches an auth_user row succeeds."""
    uid = 8002
    with psycopg.connect(_db_url(), autocommit=True) as conn:
        _insert_auth_user(conn, uid, f"fk_test_{uid}@test.invalid")
        _insert_idempotency_key(conn, owner_id=uid, key="fk-good")

    # Verify the row is present.
    with psycopg.connect(_db_url(), autocommit=True) as conn:
        cur = conn.execute(
            "SELECT owner_id FROM idempotency_keys WHERE key = 'fk-good'"
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == uid


def test_owner_id_column_is_int():
    """owner_id column type is INT (not UUID) after 0002_auth_fk.sql."""
    with psycopg.connect(_db_url(), autocommit=True) as conn:
        cur = conn.execute(
            """
            SELECT data_type
              FROM information_schema.columns
             WHERE table_name = 'idempotency_keys'
               AND column_name = 'owner_id'
            """
        )
        row = cur.fetchone()

    assert row is not None
    # PostgreSQL reports INT as 'integer'
    assert row[0] == "integer", f"Expected 'integer', got {row[0]!r}"
