"""
Session-scoped Postgres connection fixture.

Drops + recreates the test database once per session, opens a psycopg
connection, yields it, closes on teardown.

Tests that touch the DB use the `db` fixture; sibling conftest files
manage their schema setup (see backend/apps/core/tests/conftest.py).

pytest-django integration:
  When tests use @pytest.mark.django_db, pytest-django needs access to the
  same ilex_test database that the custom `db` fixture manages.  We override
  `django_db_setup` with a no-op so pytest-django does NOT create/drop its
  own test database — our custom `db` fixture owns the lifecycle.
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


@pytest.fixture(scope="session")
def django_db_setup() -> None:  # type: ignore[override]
    """No-op: the custom `db` fixture manages database lifecycle.

    pytest-django calls this to create/migrate its test database.
    We skip that entirely — `db` already drops and recreates ilex_test,
    and the api/unit conftest fixtures apply Django + SQL migrations via
    manage.py subprocesses.
    """


# Tables that survive between tests. Everything else gets TRUNCATEd before
# each test that uses the `db` fixture. Order matters only for clarity —
# CASCADE handles FK chains regardless.
_PRESERVED_TABLES = frozenset({
    "_sql_migrations",
    "django_migrations",
    "django_content_type",
    "auth_permission",
    "auth_group",
    "auth_group_permissions",
    "auth_user_groups",
    "auth_user_user_permissions",
    "django_session",
    "django_admin_log",
})


@pytest.fixture(autouse=True)
def _wipe_data_tables_between_tests(request):
    """Reset data tables before every DB-touching test.

    Opens a fresh autocommit psycopg connection (independent of the shared
    session `db` fixture, which may be in a [BAD] state from a previous test).
    Runs one TRUNCATE … RESTART IDENTITY CASCADE on every public-schema table
    except migration trackers and Django auth metadata.

    Skipped for tests that don't request `db` (pure unit tests).
    """
    if "db" not in request.fixturenames:
        yield
        return

    test_url = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    try:
        with psycopg.connect(test_url, autocommit=True) as wipe_conn:
            with wipe_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT tablename
                      FROM pg_tables
                     WHERE schemaname = 'public'
                       AND tablename NOT LIKE 'pg_%'
                    """
                )
                all_tables = [row[0] for row in cur.fetchall()]
                targets = [t for t in all_tables if t not in _PRESERVED_TABLES]
                if targets:
                    quoted = ", ".join(f'"{t}"' for t in targets)
                    cur.execute(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE")
    except psycopg.Error:
        # First few tests may run before the schema is ready (per-app session
        # autouse fixtures haven't applied migrate_sql yet). Let the test
        # itself fail if it depends on those tables.
        pass

    # If the shared `db` fixture is in an aborted-tx state from a prior test,
    # roll it back so this test starts with a clean session connection.
    db = request.getfixturevalue("db")
    try:
        db.rollback()
    except psycopg.Error:
        pass

    yield
