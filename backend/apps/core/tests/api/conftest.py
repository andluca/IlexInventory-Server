"""Test fixtures for API tests that need the Ilex SQL schema.

Applies 0001_init.sql via migrate_sql once per session so the idempotency_keys
table exists when test_idempotency.py runs.
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


@pytest.fixture(scope="session", autouse=True)
def _apply_init_schema_api(db):
    """Run migrate_sql once per session to apply 0001_init.sql."""
    db_url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test"
    )
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["DJANGO_SECRET_KEY"] = env.get("DJANGO_SECRET_KEY", "test-secret")
    env["DJANGO_SETTINGS_MODULE"] = "settings.dev"
    env["PYTHONPATH"] = _PYTHONPATH

    result = subprocess.run(
        [sys.executable, str(_MANAGE), "migrate_sql"],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"migrate_sql failed in api test setup:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
