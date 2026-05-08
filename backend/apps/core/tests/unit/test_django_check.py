"""Smoke test: `python manage.py check` exits 0.

Uses a subprocess so it verifies the real entry point, not just settings import.
Requires DJANGO_SECRET_KEY and DATABASE_URL in the environment.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]  # .../IlexInventory-Server


def test_manage_check_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "manage.py", "check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "settings.dev",
            "DJANGO_SECRET_KEY": os.environ.get(
                "DJANGO_SECRET_KEY", "dev-secret-do-not-use-in-prod"
            ),
            "DATABASE_URL": os.environ.get(
                "DATABASE_URL",
                "postgresql://postgres:postgres@localhost:5432/ilex_test",
            ),
            "PYTHONPATH": str(REPO_ROOT / "backend"),
        },
    )
    assert result.returncode == 0, (
        f"manage.py check failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
