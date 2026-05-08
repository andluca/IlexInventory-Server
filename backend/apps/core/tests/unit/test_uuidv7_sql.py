"""Integration tests for the SQL uuidv7() function and idempotency_keys table.

These tests require the database to have 0001_init.sql applied.
The migrate_sql command is applied in the session-scoped conftest for this dir.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest


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
    """(owner_id, key, endpoint) composite PK rejects duplicate inserts."""
    owner_id = str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO idempotency_keys (owner_id, key, endpoint, response_status, response_body)
            VALUES (%s, 'key-1', 'test.endpoint', 200, '{}')
            """,
            (owner_id,),
        )
    db.commit()

    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO idempotency_keys (owner_id, key, endpoint, response_status, response_body)
                VALUES (%s, 'key-1', 'test.endpoint', 200, '{}')
                """,
                (owner_id,),
            )
        db.commit()

    # Clean up after the failed transaction
    db.rollback()

    # Remove the successfully inserted row
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM idempotency_keys WHERE owner_id = %s",
            (owner_id,),
        )
    db.commit()
