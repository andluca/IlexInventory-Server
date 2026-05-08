"""Integration tests for the SQL uuidv7() function and idempotency_keys table.

These tests require the database to have 0001_init.sql and 0002_auth_fk.sql
applied (handled by the session-scoped conftest for this dir).

Note: idempotency_keys.owner_id is INT (post-0002) with a FK to auth_user(id).
Tests that insert into idempotency_keys must first create an auth_user row.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

# A stable INT id for the auth_user fixture row used in these tests.
_TEST_OWNER_ID = 7001


def test_sql_uuidv7_returns_uuid(db):
    """SELECT uuidv7() returns a well-formed UUID."""
    with db.cursor() as cur:
        cur.execute("SELECT uuidv7()")
        row = cur.fetchone()
    db.rollback()
    assert row is not None
    result = row[0]
    assert isinstance(result, uuid.UUID)


def test_sql_uuidv7_round_trips(db):
    """SELECT (uuidv7()::text)::uuid round-trips without error."""
    with db.cursor() as cur:
        cur.execute("SELECT (uuidv7()::text)::uuid")
        row = cur.fetchone()
    db.rollback()
    assert row is not None
    assert isinstance(row[0], uuid.UUID)


def test_sql_uuidv7_version_nibble(db):
    """The 13th hex character (version nibble) must be '7'."""
    with db.cursor() as cur:
        cur.execute("SELECT replace(uuidv7()::text, '-', '')")
        row = cur.fetchone()
    db.rollback()
    assert row is not None
    hex_str = row[0]
    assert hex_str[12] == "7", f"Expected version nibble '7', got '{hex_str[12]}'"


def test_idempotency_keys_pk_rejects_duplicate(db):
    """(owner_id, key, endpoint) composite PK rejects duplicate inserts.

    owner_id is INT (post-0002_auth_fk) with a FK to auth_user(id).
    We insert a minimal auth_user row first to satisfy the constraint.
    """
    owner_id = _TEST_OWNER_ID

    # Ensure the auth_user row exists (idempotent on conflict).
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO auth_user
                (id, username, email, password,
                 is_superuser, is_staff, is_active,
                 first_name, last_name, date_joined)
            VALUES (%s, %s, %s, 'unusable!', false, false, true, '', '', NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            (owner_id, f"uuidv7test_{owner_id}", f"uuidv7test_{owner_id}@test.invalid"),
        )
    db.commit()

    # First insert — should succeed.
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO idempotency_keys (owner_id, key, endpoint, response_status, response_body)
            VALUES (%s, 'key-pk-dup', 'test.pk_dup', 200, '{}')
            """,
            (owner_id,),
        )
    db.commit()

    # Second insert with same (owner_id, key, endpoint) — must raise UniqueViolation.
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO idempotency_keys (owner_id, key, endpoint, response_status, response_body)
                VALUES (%s, 'key-pk-dup', 'test.pk_dup', 200, '{}')
                """,
                (owner_id,),
            )
        db.commit()

    # Clean up after the failed transaction.
    db.rollback()

    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM idempotency_keys WHERE owner_id = %s",
            (owner_id,),
        )
    db.commit()
