"""Test fixtures for unit tests that need the Ilex SQL schema.

Applies Django ORM migrations (auth, contenttypes, sessions) first so
auth_user exists, then runs migrate_sql (0001 + 0002) so the idempotency_keys
table exists with the INT FK owner_id column.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[4]
_REPO_ROOT = _BACKEND_DIR.parent
_MANAGE = _REPO_ROOT / "manage.py"
_PYTHONPATH = str(_BACKEND_DIR)


def _run_manage(args: list[str], db_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["DJANGO_SECRET_KEY"] = env.get("DJANGO_SECRET_KEY", "test-secret")
    env["DJANGO_SETTINGS_MODULE"] = "settings.dev"
    env["PYTHONPATH"] = _PYTHONPATH

    result = subprocess.run(
        [sys.executable, str(_MANAGE)] + args,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        cmd = " ".join(args)
        raise RuntimeError(
            f"manage.py {cmd} failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


@pytest.fixture(scope="session", autouse=True)
def _apply_init_schema(db):
    """Run ORM migrations then migrate_sql once per session."""
    db_url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test"
    )

    # Step 1: Django built-in migrations so auth_user exists.
    for app in ("contenttypes", "auth", "sessions"):
        _run_manage(["migrate", app], db_url)

    # Step 2: SQL migrations (0001 + 0002 in lex order).
    _run_manage(["migrate_sql"], db_url)
