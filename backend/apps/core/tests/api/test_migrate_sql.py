"""Integration test for the migrate_sql management command.

Runs `python manage.py migrate_sql` via subprocess against the session-scoped
`db` fixture (a real Postgres test database), then queries `_sql_migrations`
to verify idempotent re-runs.
"""

from __future__ import annotations

import os
import subprocess
import sys


SETTINGS = "settings.dev"
# backend/ is 5 levels up from this file (tests/api/ → tests/ → core/ → apps/ → backend/)
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
# manage.py lives one level above backend/ (at the repo root)
PYTHONPATH = os.path.join(_BACKEND_DIR, "backend")
MANAGE = os.path.join(_BACKEND_DIR, "manage.py")


def _run_migrate(db_url: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["DJANGO_SECRET_KEY"] = os.environ.get("DJANGO_SECRET_KEY", "test-secret")
    env["DJANGO_SETTINGS_MODULE"] = SETTINGS
    env["PYTHONPATH"] = PYTHONPATH
    return subprocess.run(
        [sys.executable, MANAGE, "migrate_sql"],
        capture_output=True,
        text=True,
        env=env,
    )


def _count_migrations(db) -> int:
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM _sql_migrations")
        return cur.fetchone()[0]


_EXPECTED_MIGRATIONS = 2  # 0001_init.sql + 0002_auth_fk.sql


def test_migrate_sql_applies_and_is_idempotent(db):
    """First run applies all pending SQL migrations; second run is a no-op."""
    import psycopg

    db_url = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

    # First run — may output "applied: …" or "up to date" depending on whether
    # another conftest fixture already applied migrations in this session.
    result = _run_migrate(db_url)
    assert result.returncode == 0, (
        f"migrate_sql failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "applied" in result.stdout or "up to date" in result.stdout, (
        f"Unexpected output: {result.stdout!r}"
    )

    # Reconnect to check _sql_migrations (the subprocess used its own connection)
    conn = psycopg.connect(db_url, autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM _sql_migrations")
            count_after_first = cur.fetchone()[0]
        conn.rollback()
    finally:
        conn.close()

    assert count_after_first == _EXPECTED_MIGRATIONS, (
        f"Expected {_EXPECTED_MIGRATIONS} migration rows, got {count_after_first}"
    )

    # Second run — must be idempotent
    result2 = _run_migrate(db_url)
    assert result2.returncode == 0, (
        f"Second migrate_sql run failed:\nstdout: {result2.stdout}\nstderr: {result2.stderr}"
    )
    assert "up to date" in result2.stdout, (
        f"Expected 'up to date' on re-run, got: {result2.stdout!r}"
    )

    conn2 = psycopg.connect(db_url, autocommit=False)
    try:
        with conn2.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM _sql_migrations")
            count_after_second = cur.fetchone()[0]
        conn2.rollback()
    finally:
        conn2.close()

    assert count_after_second == _EXPECTED_MIGRATIONS, (
        f"Expected row count to stay at {_EXPECTED_MIGRATIONS}, got {count_after_second}"
    )
