"""Test fixtures for apps.catalog tests.

Applies Django ORM migrations + migrate_sql once per session against the
session-scoped `db` fixture. Mirrors the pattern in apps.core.tests.*
but is self-contained (pytest_plugins in non-top-level conftest is forbidden
in pytest >= 7).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[3]   # backend/
_REPO_ROOT = _BACKEND_DIR.parent                      # repo root (manage.py lives here)
_MANAGE = _REPO_ROOT / "manage.py"
_PYTHONPATH = str(_BACKEND_DIR)


def _run_manage(args: list[str], db_url: str) -> None:
    """Run a manage.py command; raise RuntimeError on non-zero exit."""
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
def _apply_catalog_schema(db):
    """Run ORM migrations + migrate_sql once per session (idempotent)."""
    db_url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test"
    )

    for app in ("contenttypes", "auth", "sessions"):
        _run_manage(["migrate", app], db_url)

    _run_manage(["migrate_sql"], db_url)
