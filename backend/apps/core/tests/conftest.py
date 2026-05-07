"""
Test schema for db_test's own tests.

Three small isolated tables (`tt_*`) that don't depend on the Ilex business
schema. Each test gets a clean state: tables are created once per session
and TRUNCATE'd between tests.

The FK on `tt_items.user_id` is `DEFERRABLE INITIALLY IMMEDIATE` so that
`SET CONSTRAINTS ALL DEFERRED` (used inside `pre_db`) can defer it,
allowing inserts in any order.
"""

from __future__ import annotations

import pytest


SCHEMA_DDL = """
    CREATE TABLE IF NOT EXISTS tt_users (
        id   SERIAL PRIMARY KEY,
        name TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tt_items (
        id      SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES tt_users(id)
                DEFERRABLE INITIALLY IMMEDIATE,
        value   INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tt_decimals (
        id     SERIAL PRIMARY KEY,
        amount NUMERIC(14, 4) NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tt_events (
        id          SERIAL PRIMARY KEY,
        occurred_at TIMESTAMPTZ NOT NULL
    );
"""

TABLES = ("tt_users", "tt_items", "tt_decimals", "tt_events")


@pytest.fixture(scope="session", autouse=True)
def _create_schema(db):
    with db.cursor() as cur:
        cur.execute(SCHEMA_DDL)
    db.commit()


@pytest.fixture(autouse=True)
def _reset_schema(db):
    """Truncate all tt_* tables between tests so each function starts clean."""
    yield
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE"
        )
    db.commit()
