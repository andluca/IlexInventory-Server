"""
Session-scoped Postgres connection fixture.

Drops + recreates the test database once per session, opens a psycopg
connection, yields it, closes on teardown.

Tests that touch the DB use the `db` fixture; sibling conftest files
manage their schema setup (see backend/apps/core/tests/conftest.py).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/ilex_test"


def _admin_url(test_url: str) -> str:
    """Postgres URL pointing at the maintenance DB (`postgres`).
    DROP/CREATE DATABASE can't run from inside the DB being targeted."""
    parts = urlparse(test_url)
    return urlunparse(parts._replace(path="/postgres"))


def _db_name(test_url: str) -> str:
    return urlparse(test_url).path.lstrip("/")


@pytest.fixture(scope="session")
def db():
    test_url = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    name = _db_name(test_url)

    with psycopg.connect(_admin_url(test_url), autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{name}"')

    conn = psycopg.connect(test_url, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()
